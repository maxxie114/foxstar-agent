from __future__ import annotations

from .persistence import Database, utc_now

from .privacy import public_participant_label, redact_private_ids

class ContextStore:
    def add_message(self, chat_id: str, user_id: str, role: str, content: str, kind: str = "text") -> None:
        user_id = public_participant_label(user_id)
        content = self._trim(redact_private_ids(content))
        if not content:
            return
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO messages(chat_id, user_id, role, content, kind, created_at) VALUES(?, ?, ?, ?, ?, ?)",
                (chat_id, user_id, role, content, kind, utc_now()),
            )

    def recent_messages(self, chat_id: str) -> list[dict[str, str]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT user_id, role, content, kind FROM messages WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
                (chat_id, self.max_turns),
            ).fetchall()
        rows = list(reversed(rows))
        return [dict(row) for row in rows]

    @staticmethod
    def _trim(content: str, limit: int = 2000) -> str:
        content = (content or "").strip()
        if len(content) <= limit:
            return content
        return content[:limit] + "\n[内容已截断]"

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
