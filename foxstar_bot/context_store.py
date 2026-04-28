from __future__ import annotations

from collections import defaultdict, deque

from .persistence import Database, utc_now

from .privacy import public_participant_label, redact_private_ids

class ContextStore:
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
