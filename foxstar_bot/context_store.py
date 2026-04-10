from __future__ import annotations

from .persistence import Database, utc_now


class ContextStore:
    def __init__(self, db: Database, max_turns: int = 12) -> None:
        self.db = db
        self.max_turns = max_turns

    def add_message(self, chat_id: str, user_id: str, role: str, content: str, kind: str = "text") -> None:
        content = self._trim(content)
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
