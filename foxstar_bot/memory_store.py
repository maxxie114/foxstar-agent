from __future__ import annotations

from .persistence import Database, utc_now


class MemoryStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def upsert(
        self,
        scope: str,
        scope_id: str,
        key: str,
        value: str,
        priority: int = 50,
        source_user_id: str = "",
    ) -> bool:
        now = utc_now()
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT priority FROM memories WHERE scope = ? AND scope_id = ? AND key = ?",
                (scope, scope_id, key),
            ).fetchone()
            if row is not None and int(row["priority"]) > priority:
                return False
            conn.execute(
                """
                INSERT INTO memories(scope, scope_id, key, value, created_at, updated_at, priority, source_user_id)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(scope, scope_id, key)
                DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at,
                    priority = excluded.priority,
                    source_user_id = excluded.source_user_id
                """,
                (scope, scope_id, key, value.strip(), now, now, priority, source_user_id),
            )
        return True

    def delete(self, scope: str, scope_id: str, key: str) -> int:
        with self.db.connect() as conn:
            cur = conn.execute(
                "DELETE FROM memories WHERE scope = ? AND scope_id = ? AND key = ?",
                (scope, scope_id, key),
            )
            return cur.rowcount

    def list_scope(self, scope: str, scope_id: str, limit: int = 20) -> list[dict[str, str]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT key, value, priority, source_user_id, updated_at FROM memories WHERE scope = ? AND scope_id = ? "
                "ORDER BY priority DESC, updated_at DESC LIMIT ?",
                (scope, scope_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def clear_scope(self, scope: str, scope_id: str) -> int:
        with self.db.connect() as conn:
            cur = conn.execute("DELETE FROM memories WHERE scope = ? AND scope_id = ?", (scope, scope_id))
            return cur.rowcount

    def render_for_prompt(self, chat_id: str, user_id: str) -> str:
        memories = self.list_scope("chat", chat_id, 20)
        if not memories:
            return ""
        master = [item for item in memories if int(item["priority"]) >= 100]
        user = [item for item in memories if int(item["priority"]) < 100]
        sections = [
            (
                "Memory priority rules: follow Master Memory first. "
                "Use User Memory only when it does not conflict with Master Memory. "
                "If they conflict, Master Memory wins."
            )
        ]
        if master:
            sections.append("Master Memory:\n" + "\n".join(_render_memory_item(item) for item in master))
        if user:
            sections.append("User Memory:\n" + "\n".join(_render_memory_item(item) for item in user))
        return "\n\n".join(sections)


def _render_memory_item(item: dict[str, object]) -> str:
    return f"- {item['key']}: {item['value']}"
