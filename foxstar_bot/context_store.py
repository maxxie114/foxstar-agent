from __future__ import annotations

from collections import defaultdict, deque

from .persistence import Database, utc_now

from .privacy import public_participant_label, redact_private_ids

DEFAULT_CONTEXT_MESSAGES = 30

MAX_CONTEXT_MESSAGES = 200

CONTEXT_COMPRESSION_MESSAGES = 500

CONTEXT_BRIDGE_MESSAGES = 40

def normalize_context_messages(value: object, default: int = DEFAULT_CONTEXT_MESSAGES) -> int:
    try:
        message_count = int(value)
    except (TypeError, ValueError):
        message_count = default
    return max(1, min(message_count, MAX_CONTEXT_MESSAGES))

class ContextStore:
    def __init__(self, db: Database, max_turns: int = DEFAULT_CONTEXT_MESSAGES) -> None:
        self.db = db
        self.max_turns = normalize_context_messages(max_turns)
        self._suppressed_context_keys: dict[str, deque[tuple[str, str, str]]] = defaultdict(lambda: deque(maxlen=64))

    def suppress_message(self, chat_id: str, *, user_id: str, role: str, content: str) -> None:
        normalized = _normalized_for_dedupe(content)
        if not normalized:
            return
        self._suppressed_context_keys[chat_id].append((user_id, role, normalized))

    def recent_messages(self, chat_id: str) -> list[dict[str, str]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT user_id, role, content, kind FROM messages WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
                (chat_id, self.max_turns),
            ).fetchall()
        rows = list(reversed(rows))
        items = [dict(row) for row in rows]
        return [item for item in items if not self._is_suppressed(chat_id, item)]

    def render_recent(self, chat_id: str, limit: int = 8) -> list[str]:
        items = self.recent_messages(chat_id)
        if limit > 0:
            items = items[-limit:]
        rendered: list[str] = []
        for item in items:
            role = "bot" if item.get("role") == "assistant" else public_participant_label(str(item.get("user_id") or "user"))
            content = _compact_content(redact_private_ids(str(item.get("content") or "")), limit=180)
            if not content:
                continue
            rendered.append(f"{role}: {content}")
        return rendered

    def compression_window(
        self,
        chat_id: str,
        max_turns: int | None = None,
        compression_turns: int = CONTEXT_COMPRESSION_MESSAGES,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]], str]:
        recent_limit = self.max_turns if max_turns is None else normalize_context_messages(max_turns)
        compression_limit = max(0, min(int(compression_turns), CONTEXT_COMPRESSION_MESSAGES))
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT id, user_id, role, content, kind, created_at FROM messages WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
                (chat_id, recent_limit + compression_limit),
            ).fetchall()
        items = [dict(row) for row in reversed(rows)]
        items = [item for item in items if not self._is_suppressed(chat_id, item)]
        if len(items) <= recent_limit:
            return [], items, ""
        older = items[:-recent_limit]
        recent = items[-recent_limit:]
        signature = f"{older[0]['id']}:{older[-1]['id']}:{len(older)}"
        return older, recent, signature

    def rolling_window(
        self,
        chat_id: str,
        *,
        max_turns: int | None = None,
        summarized_through_id: int = 0,
        compression_limit: int = CONTEXT_COMPRESSION_MESSAGES,
        bridge_limit: int = CONTEXT_BRIDGE_MESSAGES,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
        recent_limit = self.max_turns if max_turns is None else normalize_context_messages(max_turns)
        compression_limit = max(1, min(int(compression_limit), CONTEXT_COMPRESSION_MESSAGES))
        bridge_limit = max(1, min(int(bridge_limit), CONTEXT_BRIDGE_MESSAGES))
        with self.db.connect() as conn:
            recent_rows = conn.execute(
                "SELECT id, user_id, role, content, kind, created_at FROM messages WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
                (chat_id, recent_limit),
            ).fetchall()
            recent = [dict(row) for row in reversed(recent_rows)]
            recent = [item for item in recent if not self._is_suppressed(chat_id, item)]
            if not recent:
                return [], [], []
            recent_first_id = int(recent[0]["id"])
            if summarized_through_id > 0:
                source_rows = conn.execute(
                    """
                    SELECT id, user_id, role, content, kind, created_at FROM messages
                    WHERE chat_id = ? AND id > ? AND id < ?
                    ORDER BY id ASC LIMIT ?
                    """,
                    (chat_id, summarized_through_id, recent_first_id, compression_limit),
                ).fetchall()
                bridge_rows = conn.execute(
                    """
                    SELECT id, user_id, role, content, kind, created_at FROM messages
                    WHERE chat_id = ? AND id > ? AND id < ?
                    ORDER BY id DESC LIMIT ?
                    """,
                    (chat_id, summarized_through_id, recent_first_id, bridge_limit),
                ).fetchall()
            else:
                source_rows = conn.execute(
                    """
                    SELECT id, user_id, role, content, kind, created_at FROM messages
                    WHERE chat_id = ? AND id < ?
                    ORDER BY id DESC LIMIT ?
                    """,
                    (chat_id, recent_first_id, compression_limit),
                ).fetchall()
                source_rows = list(reversed(source_rows))
                bridge_rows = conn.execute(
                    """
                    SELECT id, user_id, role, content, kind, created_at FROM messages
                    WHERE chat_id = ? AND id < ?
                    ORDER BY id DESC LIMIT ?
                    """,
                    (chat_id, recent_first_id, bridge_limit),
                ).fetchall()
            source = [dict(row) for row in source_rows]
            bridge = [dict(row) for row in reversed(bridge_rows)]
        source = [item for item in source if not self._is_suppressed(chat_id, item)]
        bridge = [item for item in bridge if not self._is_suppressed(chat_id, item)]
        return source, bridge, recent

    @staticmethod
    def render_compression_source(items: list[dict[str, object]], per_message_limit: int = 180) -> str:
        seen: set[tuple[str, str]] = set()
        lines: list[str] = []
        for item in items:
            if item.get("role") == "assistant":
                role = "bot"
            else:
                user_id = str(item.get("user_id") or "user")
                role = public_participant_label(user_id)
            content = _compact_content(redact_private_ids(str(item.get("content") or "")), limit=per_message_limit)
            key = (role, _normalized_for_dedupe(content).lower())
            if not content or key in seen:
                continue
            seen.add(key)
            created_at = str(item.get("created_at") or "")[:16]
            timestamp = f"[{created_at} UTC] " if created_at else ""
            lines.append(f"{timestamp}{role}: {content}")
        return "\n".join(lines)

    @staticmethod
    def _trim(content: str, limit: int = 2000) -> str:
        content = (content or "").strip()
        if len(content) <= limit:
            return content
        return content[:limit] + "\n[内容已截断]"

    def _is_suppressed(self, chat_id: str, item: dict[str, str]) -> bool:
        keys = self._suppressed_context_keys.get(chat_id)
        if not keys:
            return False
        probe = (
            str(item.get("user_id") or ""),
            str(item.get("role") or ""),
            _normalized_for_dedupe(str(item.get("content") or "")),
        )
        return probe in keys

def _compact_content(content: str, limit: int = 110) -> str:
    content = " ".join((content or "").split())
    if not content or _is_low_signal_content(content):
        return ""
    content = content.replace("[引用消息]", "").strip()
    content = content.replace("当前回复:", "reply:").replace("引用原文:", "quote:")
    if len(content) > limit:
        content = content[:limit].rstrip() + "..."
    return content

def _is_low_signal_content(content: str) -> bool:
    value = content.strip()
    if not value:
        return True
    if value.startswith("[图片") or value.startswith("[动画表情]"):
        return True
    if len(value) <= 8 and "[" in value and "]" in value:
        return True
    return False

def _normalized_for_dedupe(content: str) -> str:
    return " ".join((content or "").split())
