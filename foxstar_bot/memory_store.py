from __future__ import annotations

from .persistence import Database, utc_now

class MemoryStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def delete(self, scope: str, scope_id: str, key: str) -> int:
        with self.db.connect() as conn:
            cur = conn.execute(
                "DELETE FROM memories WHERE scope = ? AND scope_id = ? AND key = ?",
                (scope, scope_id, key),
            )
            return cur.rowcount

    def clear_scope(self, scope: str, scope_id: str) -> int:
        with self.db.connect() as conn:
            cur = conn.execute("DELETE FROM memories WHERE scope = ? AND scope_id = ?", (scope, scope_id))
            return cur.rowcount
