from __future__ import annotations

import json

import sqlite3

from contextlib import contextmanager

from datetime import datetime, timedelta, timezone

from pathlib import Path

from typing import Any, Iterator

MAX_ENABLED_SCHEDULED_TASKS_PER_CHAT = 25

class ScheduledTaskLimitError(RuntimeError):
    pass

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS groups (
                    group_id TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    mode TEXT NOT NULL DEFAULT 'normal',
                    prefix TEXT,
                    web_search_enabled INTEGER NOT NULL DEFAULT 1,
                    doc_enabled INTEGER NOT NULL DEFAULT 1,
                    vision_enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    nickname TEXT,
                    is_whitelist INTEGER NOT NULL DEFAULT 0,
                    daily_count INTEGER NOT NULL DEFAULT 0,
                    last_seen_at TEXT
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'text',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_messages_chat_time ON messages(chat_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_messages_chat_id_id ON messages(chat_id, id);

                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scope TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(scope, scope_id, key)
                );

                CREATE TABLE IF NOT EXISTS files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    extracted_text TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS images (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    image_path TEXT NOT NULL,
                    ocr_text TEXT,
                    vision_summary TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS rate_events (
                    key TEXT NOT NULL,
                    bucket_date TEXT NOT NULL,
                    count INTEGER NOT NULL DEFAULT 0,
                    last_at REAL NOT NULL DEFAULT 0,
                    PRIMARY KEY(key, bucket_date)
                );

                CREATE TABLE IF NOT EXISTS chat_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    user_id TEXT,
                    display_name TEXT,
                    raw_content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_chat_events_chat_time ON chat_events(chat_id, created_at);

                CREATE TABLE IF NOT EXISTS group_member_snapshots (
                    chat_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    display_name TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(chat_id, user_id)
                );
                CREATE INDEX IF NOT EXISTS idx_group_member_snapshots_chat ON group_member_snapshots(chat_id);

                CREATE TABLE IF NOT EXISTS group_aliases (
                    chat_id TEXT PRIMARY KEY,
                    alias TEXT,
                    last_sender TEXT,
                    last_message TEXT,
                    last_seen_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS token_usage_daily (
                    chat_id TEXT NOT NULL,
                    bucket_date TEXT NOT NULL,
                    feature TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    api TEXT NOT NULL,
                    requests INTEGER NOT NULL DEFAULT 0,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    cached_tokens INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(chat_id, bucket_date, feature, provider, model, api)
                );
                CREATE INDEX IF NOT EXISTS idx_token_usage_daily_chat_date ON token_usage_daily(chat_id, bucket_date);

                CREATE TABLE IF NOT EXISTS scheduled_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    schedule_type TEXT NOT NULL,
                    cron_expr TEXT,
                    timezone TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    next_run_at TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    run_count INTEGER NOT NULL DEFAULT 0,
                    last_run_at TEXT,
                    last_result TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_due ON scheduled_tasks(enabled, next_run_at);

                CREATE TABLE IF NOT EXISTS accounting_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    entry_type TEXT NOT NULL,
                    counterparty TEXT NOT NULL,
                    amount REAL NOT NULL,
                    currency TEXT NOT NULL DEFAULT 'CNY',
                    description TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    cleared_at TEXT,
                    cleared_by TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_accounting_entries_chat_time ON accounting_entries(chat_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_accounting_entries_chat_type_status ON accounting_entries(chat_id, entry_type, status);

                CREATE TABLE IF NOT EXISTS bug_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    closed_at TEXT,
                    closed_by TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_bug_reports_chat_status ON bug_reports(chat_id, status, id);
                CREATE INDEX IF NOT EXISTS idx_bug_reports_chat_time ON bug_reports(chat_id, created_at);

                CREATE TABLE IF NOT EXISTS finance_debug_outputs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL,
                    rendered_key TEXT NOT NULL,
                    rendered_text TEXT NOT NULL,
                    full_reply_text TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_finance_debug_chat_key_time
                    ON finance_debug_outputs(chat_id, rendered_key, created_at);

                CREATE TABLE IF NOT EXISTS finance_noteboard_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL,
                    source_message_id TEXT NOT NULL DEFAULT '',
                    sender_id TEXT NOT NULL,
                    sender_name TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL,
                    numeric_values_json TEXT NOT NULL DEFAULT '[]',
                    message_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_finance_noteboard_chat_time
                    ON finance_noteboard_entries(chat_id, message_at, id);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_finance_noteboard_source_message
                    ON finance_noteboard_entries(chat_id, source_message_id)
                    WHERE source_message_id != '';
                """
            )
            for statement in (
                "ALTER TABLE memories ADD COLUMN priority INTEGER NOT NULL DEFAULT 50",
                "ALTER TABLE memories ADD COLUMN source_user_id TEXT",
                "ALTER TABLE finance_noteboard_entries ADD COLUMN classified INTEGER NOT NULL DEFAULT 0",
            ):
                try:
                    conn.execute(statement)
                except sqlite3.OperationalError as exc:
                    if "duplicate column name" not in str(exc).lower():
                        raise

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return row["value"]

    def set_setting(self, key: str, value: Any) -> None:
        payload = json.dumps(value, ensure_ascii=False)
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, payload),
            )

    def delete_setting(self, key: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM settings WHERE key = ?", (key,))

    def add_finance_debug_output(
        self,
        *,
        chat_id: str,
        rendered_key: str,
        rendered_text: str,
        full_reply_text: str,
        mode: str,
        payload_json: str,
    ) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO finance_debug_outputs(
                    chat_id, rendered_key, rendered_text, full_reply_text, mode, payload_json, created_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (chat_id, rendered_key, rendered_text, full_reply_text, mode, payload_json, now),
            )

    def latest_finance_debug_output(self, *, chat_id: str, rendered_key: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT id, chat_id, rendered_key, rendered_text, full_reply_text, mode, payload_json, created_at
                FROM finance_debug_outputs
                WHERE chat_id = ? AND rendered_key = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (chat_id, rendered_key),
            ).fetchone()
        return dict(row) if row is not None else None

    def add_finance_noteboard_entry(
        self,
        *,
        chat_id: str,
        source_message_id: str,
        sender_id: str,
        sender_name: str,
        content: str,
        numeric_values: list[dict[str, Any]],
        message_at: str | None = None,
    ) -> int | None:
        now = utc_now()
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO finance_noteboard_entries(
                    chat_id, source_message_id, sender_id, sender_name, content,
                    numeric_values_json, message_at, created_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chat_id,
                    str(source_message_id or ""),
                    sender_id,
                    sender_name,
                    content,
                    json.dumps(numeric_values, ensure_ascii=False),
                    message_at or now,
                    now,
                ),
            )
            return int(cursor.lastrowid) if cursor.rowcount else None

    def list_finance_noteboard_entries(
        self,
        chat_id: str,
        *,
        days: int | None = 30,
        sender: str = "",
        query: str = "",
        limit: int = 100,
        include_chatter: bool = False,
    ) -> list[dict[str, Any]]:
        clauses = ["chat_id = ?"]
        params: list[Any] = [chat_id]
        if not include_chatter:


            clauses.append("classified != -1")
        if days is not None:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=max(0, int(days)))).isoformat(timespec="seconds")
            clauses.append("message_at >= ?")
            params.append(cutoff)
        if sender.strip():
            clauses.append("(sender_id = ? OR sender_name = ?)")
            params.extend([sender.strip(), sender.strip()])
        if query.strip():
            clauses.append("content LIKE ?")
            params.append(f"%{query.strip()}%")
        params.append(max(1, min(int(limit), 500)))
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, source_message_id, sender_id, sender_name, content,
                       numeric_values_json, message_at, created_at
                FROM finance_noteboard_entries
                WHERE {' AND '.join(clauses)}
                ORDER BY message_at DESC, id DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            try:
                item["numeric_values"] = json.loads(str(item.pop("numeric_values_json") or "[]"))
            except json.JSONDecodeError:
                item["numeric_values"] = []
                item.pop("numeric_values_json", None)
            result.append(item)
        return result

    def count_finance_noteboard_entries(self, chat_id: str) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM finance_noteboard_entries WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
        return int(row["count"] if row else 0)

    def earliest_live_notebook_entry_time(self, chat_id: str) -> str:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT MIN(message_at) AS m
                FROM finance_noteboard_entries
                WHERE chat_id = ? AND source_message_id != ''
                  AND source_message_id NOT LIKE 'context:%'
                """,
                (chat_id,),
            ).fetchone()
        return str(row["m"]) if row and row["m"] else ""

    def unclassified_finance_noteboard_entries(self, chat_id: str, *, limit: int = 30) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, sender_name, content
                FROM finance_noteboard_entries
                WHERE chat_id = ? AND classified = 0
                ORDER BY id DESC
                LIMIT ?
                """,
                (chat_id, max(1, min(int(limit), 100))),
            ).fetchall()
        return [dict(row) for row in rows]

    def set_finance_noteboard_verdicts(self, verdicts: dict[int, int]) -> int:
        if not verdicts:
            return 0
        with self.connect() as conn:
            before = conn.total_changes
            conn.executemany(
                "UPDATE finance_noteboard_entries SET classified = ? WHERE id = ?",
                [(int(verdict), int(entry_id)) for entry_id, verdict in verdicts.items()],
            )
            return int(conn.total_changes - before)

    def finance_noteboard_backfill_messages(self, chat_id: str, *, limit: int = 20000) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, user_id, content, created_at
                FROM messages
                WHERE chat_id = ? AND role = 'user'
                ORDER BY id ASC
                LIMIT ?
                """,
                (chat_id, max(1, min(int(limit), 20000))),
            ).fetchall()
        return [dict(row) for row in rows]

    def add_finance_noteboard_entries_bulk(self, entries: list[dict[str, Any]]) -> int:
        if not entries:
            return 0
        now = utc_now()
        rows = [
            (
                str(entry.get("chat_id") or ""),
                str(entry.get("source_message_id") or ""),
                str(entry.get("sender_id") or ""),
                str(entry.get("sender_name") or ""),
                str(entry.get("content") or ""),
                json.dumps(entry.get("numeric_values") or [], ensure_ascii=False),
                str(entry.get("message_at") or now),
                now,
            )
            for entry in entries
        ]
        with self.connect() as conn:
            before = conn.total_changes
            conn.executemany(
                """
                INSERT OR IGNORE INTO finance_noteboard_entries(
                    chat_id, source_message_id, sender_id, sender_name, content,
                    numeric_values_json, message_at, created_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            return int(conn.total_changes - before)

    def record_token_usage(
        self,
        *,
        chat_id: str,
        feature: str,
        provider: str,
        model: str,
        api: str,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int = 0,
    ) -> None:
        bucket_date = datetime.now(timezone.utc).date().isoformat()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO token_usage_daily(
                    chat_id, bucket_date, feature, provider, model, api,
                    requests, input_tokens, output_tokens, cached_tokens
                )
                VALUES(?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                ON CONFLICT(chat_id, bucket_date, feature, provider, model, api) DO UPDATE SET
                    requests = requests + 1,
                    input_tokens = input_tokens + excluded.input_tokens,
                    output_tokens = output_tokens + excluded.output_tokens,
                    cached_tokens = cached_tokens + excluded.cached_tokens
                """,
                (
                    chat_id,
                    bucket_date,
                    feature,
                    provider,
                    model,
                    api,
                    int(input_tokens or 0),
                    int(output_tokens or 0),
                    int(cached_tokens or 0),
                ),
            )

    def token_usage_summary(self, chat_id: str, *, days: int | None = 7) -> dict[str, Any]:
        params: list[Any] = [chat_id]
        where = "WHERE chat_id = ?"
        if days is not None:
            cutoff = datetime.now(timezone.utc).date().fromordinal(datetime.now(timezone.utc).date().toordinal() - max(days - 1, 0)).isoformat()
            where += " AND bucket_date >= ?"
            params.append(cutoff)
        with self.connect() as conn:
            total = conn.execute(
                f"""
                SELECT
                    COALESCE(SUM(requests), 0) AS requests,
                    COALESCE(SUM(input_tokens), 0) AS input_tokens,
                    COALESCE(SUM(output_tokens), 0) AS output_tokens,
                    COALESCE(SUM(cached_tokens), 0) AS cached_tokens
                FROM token_usage_daily
                {where}
                """,
                tuple(params),
            ).fetchone()
            by_feature = conn.execute(
                f"""
                SELECT
                    feature,
                    SUM(requests) AS requests,
                    SUM(input_tokens) AS input_tokens,
                    SUM(output_tokens) AS output_tokens,
                    SUM(cached_tokens) AS cached_tokens
                FROM token_usage_daily
                {where}
                GROUP BY feature
                ORDER BY SUM(input_tokens + output_tokens) DESC, feature ASC
                """,
                tuple(params),
            ).fetchall()
            by_model = conn.execute(
                f"""
                SELECT
                    provider,
                    model,
                    SUM(requests) AS requests,
                    SUM(input_tokens) AS input_tokens,
                    SUM(output_tokens) AS output_tokens,
                    SUM(cached_tokens) AS cached_tokens
                FROM token_usage_daily
                {where}
                GROUP BY provider, model
                ORDER BY SUM(input_tokens + output_tokens) DESC, provider ASC, model ASC
                """,
                tuple(params),
            ).fetchall()
        return {
            "requests": int(total["requests"] or 0),
            "input_tokens": int(total["input_tokens"] or 0),
            "output_tokens": int(total["output_tokens"] or 0),
            "cached_tokens": int(total["cached_tokens"] or 0),
            "by_feature": [dict(row) for row in by_feature],
            "by_model": [dict(row) for row in by_model],
        }

    def clear_token_usage(self, chat_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM token_usage_daily WHERE chat_id = ?", (chat_id,))

    def add_scheduled_task(
        self,
        *,
        chat_id: str,
        created_by: str,
        kind: str,
        schedule_type: str,
        cron_expr: str,
        timezone_name: str,
        payload: str,
        next_run_at: str,
    ) -> tuple[int, bool]:
        now = utc_now()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                """
                SELECT id FROM scheduled_tasks
                WHERE chat_id = ? AND schedule_type = ? AND COALESCE(cron_expr, '') = ?
                  AND timezone = ? AND payload = ? AND enabled = 1
                  AND (? = 'cron' OR next_run_at = ?)
                ORDER BY id ASC LIMIT 1
                """,
                (
                    chat_id,
                    schedule_type,
                    cron_expr or "",
                    timezone_name,
                    payload,
                    schedule_type,
                    next_run_at,
                ),
            ).fetchone()
            if existing is not None:
                return int(existing["id"]), False
            active_count = conn.execute(
                "SELECT COUNT(*) AS count FROM scheduled_tasks WHERE chat_id = ? AND enabled = 1",
                (chat_id,),
            ).fetchone()
            if int(active_count["count"] or 0) >= MAX_ENABLED_SCHEDULED_TASKS_PER_CHAT:
                raise ScheduledTaskLimitError(
                    f"active scheduled task limit reached ({MAX_ENABLED_SCHEDULED_TASKS_PER_CHAT})"
                )
            cursor = conn.execute(
                """
                INSERT INTO scheduled_tasks(
                    chat_id, created_by, kind, schedule_type, cron_expr, timezone, payload,
                    next_run_at, enabled, run_count, last_run_at, last_result, created_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, 1, 0, NULL, NULL, ?, ?)
                """,
                (
                    chat_id,
                    created_by,
                    kind,
                    schedule_type,
                    cron_expr,
                    timezone_name,
                    payload,
                    next_run_at,
                    now,
                    now,
                ),
            )
            return int(cursor.lastrowid), True

    def list_scheduled_tasks(self, chat_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, kind, schedule_type, cron_expr, timezone, payload, next_run_at,
                       enabled, run_count, last_run_at, last_result, created_by, created_at, updated_at
                FROM scheduled_tasks
                WHERE chat_id = ?
                ORDER BY enabled DESC, next_run_at ASC, id ASC
                """,
                (chat_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_scheduled_task(self, chat_id: str, task_id: int) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM scheduled_tasks WHERE chat_id = ? AND id = ?",
                (chat_id, int(task_id)),
            )
            return int(cursor.rowcount or 0)

    def clear_scheduled_tasks(self, chat_id: str) -> int:
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM scheduled_tasks WHERE chat_id = ?", (chat_id,))
            return int(cursor.rowcount or 0)

    def due_scheduled_tasks(self, *, now_iso: str, limit: int = 10) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM scheduled_tasks
                WHERE enabled = 1 AND next_run_at <= ?
                ORDER BY next_run_at ASC, id ASC
                LIMIT ?
                """,
                (now_iso, int(limit)),
            ).fetchall()
        return [dict(row) for row in rows]

    def complete_scheduled_task(
        self,
        task_id: int,
        *,
        next_run_at: str | None,
        last_result: str,
        enabled: bool,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE scheduled_tasks
                SET next_run_at = ?, enabled = ?, run_count = run_count + 1,
                    last_run_at = ?, last_result = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    next_run_at or "",
                    1 if enabled else 0,
                    utc_now(),
                    (last_result or "")[:2000],
                    utc_now(),
                    int(task_id),
                ),
            )

    def recent_chat_events(self, chat_id: str, *, limit: int | None = 50, days: int | None = 1) -> list[dict[str, Any]]:
        params: list[Any] = [chat_id]
        where = "WHERE chat_id = ?"
        if days is not None:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=max(days, 0))).isoformat(timespec="seconds")
            where += " AND created_at >= ?"
            params.append(cutoff)
        limit_sql = ""
        if limit is not None:
            params.append(int(limit))
            limit_sql = "LIMIT ?"
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT created_at, event_type, display_name, user_id, raw_content
                FROM chat_events
                {where}
                ORDER BY id DESC
                {limit_sql}
                """,
                tuple(params),
            ).fetchall()
        return [dict(row) for row in rows]

    def recent_messages(self, chat_id: str, *, limit: int = 120) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, user_id, role, content, kind, created_at
                FROM messages
                WHERE chat_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (chat_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def has_recent_chat_event(
        self,
        chat_id: str,
        event_type: str,
        *,
        user_id: str = "",
        display_name: str = "",
        within_seconds: int = 900,
    ) -> bool:
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=max(within_seconds, 0))).isoformat(timespec="seconds")
        clauses = ["chat_id = ?", "event_type = ?", "created_at >= ?"]
        params: list[Any] = [chat_id, event_type, cutoff]
        if user_id:
            clauses.append("user_id = ?")
            params.append(user_id)
        elif display_name:
            clauses.append("display_name = ?")
            params.append(display_name)
        with self.connect() as conn:
            row = conn.execute(
                f"SELECT 1 FROM chat_events WHERE {' AND '.join(clauses)} ORDER BY id DESC LIMIT 1",
                tuple(params),
            ).fetchone()
        return row is not None

    def add_accounting_entry(
        self,
        *,
        chat_id: str,
        created_by: str,
        entry_type: str,
        counterparty: str,
        amount: float,
        description: str,
        currency: str = "CNY",
        status: str = "open",
    ) -> int:
        now = utc_now()
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO accounting_entries(
                    chat_id, created_by, entry_type, counterparty, amount, currency,
                    description, status, cleared_at, cleared_by, created_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)
                """,
                (
                    chat_id,
                    created_by,
                    entry_type,
                    counterparty,
                    float(amount),
                    currency,
                    description,
                    status,
                    now,
                    now,
                ),
            )
            return int(cursor.lastrowid)

    def add_accounting_entries_bulk(
        self,
        *,
        chat_id: str,
        created_by: str,
        entry_type: str,
        counterparties: list[str],
        amount: float,
        description: str,
        currency: str = "CNY",
        status: str = "open",
    ) -> int:
        names = [str(name or "").strip() for name in counterparties]
        names = [name for name in names if name]
        if not names:
            return 0
        now = utc_now()
        rows = [
            (
                chat_id,
                created_by,
                entry_type,
                name,
                float(amount),
                currency,
                description,
                status,
                now,
                now,
            )
            for name in names
        ]
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO accounting_entries(
                    chat_id, created_by, entry_type, counterparty, amount, currency,
                    description, status, cleared_at, cleared_by, created_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)
                """,
                rows,
            )
        return len(rows)

    def clear_accounting_owe(
        self,
        *,
        chat_id: str,
        counterparty: str,
        amount: float,
        description: str,
        cleared_by: str,
    ) -> int:
        now = utc_now()
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT id
                FROM accounting_entries
                WHERE chat_id = ? AND entry_type = 'owe' AND status = 'open'
                  AND counterparty = ? AND amount = ? AND description = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (chat_id, counterparty, float(amount), description),
            ).fetchone()
            if row is None:
                return 0
            cursor = conn.execute(
                """
                UPDATE accounting_entries
                SET status = 'cleared', cleared_at = ?, cleared_by = ?, updated_at = ?
                WHERE id = ?
                """,
                (now, cleared_by, now, int(row["id"])),
            )
            return int(cursor.rowcount or 0)

    def delete_accounting_entry(
        self,
        *,
        chat_id: str,
        entry_id: int,
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT id, entry_type, counterparty, amount, currency, description, status,
                       cleared_at, cleared_by, created_by, created_at, updated_at
                FROM accounting_entries
                WHERE chat_id = ? AND id = ?
                """,
                (chat_id, int(entry_id)),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "DELETE FROM accounting_entries WHERE chat_id = ? AND id = ?",
                (chat_id, int(entry_id)),
            )
        return dict(row)

    def lookup_accounting(
        self,
        chat_id: str,
        *,
        entry_type: str | None = None,
        days: int | None = 30,
        status: str | None = None,
        counterparty: str = "",
        limit: int = 5000,
    ) -> list[dict[str, Any]]:
        clauses = ["chat_id = ?"]
        params: list[Any] = [chat_id]
        if entry_type and entry_type != "all":
            clauses.append("entry_type = ?")
            params.append(entry_type)
        if status and status != "all":
            clauses.append("status = ?")
            params.append(status)
        if counterparty.strip():
            clauses.append("counterparty = ?")
            params.append(counterparty.strip())
        if days is not None:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=max(days, 0))).isoformat(timespec="seconds")
            clauses.append("created_at >= ?")
            params.append(cutoff)
        params.append(int(limit))
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, entry_type, counterparty, amount, currency, description, status,
                       cleared_at, cleared_by, created_by, created_at, updated_at
                FROM accounting_entries
                WHERE {' AND '.join(clauses)}
                ORDER BY id DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [dict(row) for row in rows]

    def summarize_accounting(
        self,
        chat_id: str,
        *,
        entry_type: str | None = None,
        days: int | None = 30,
        status: str | None = None,
        counterparty: str = "",
    ) -> dict[str, Any]:
        rows = self.lookup_accounting(
            chat_id,
            entry_type=entry_type,
            days=days,
            status=status,
            counterparty=counterparty,
            limit=5000,
        )
        total_amount = sum(float(row.get("amount") or 0.0) for row in rows)
        by_counterparty: dict[str, float] = {}
        for row in rows:
            name = str(row.get("counterparty") or "").strip() or "(unknown)"
            by_counterparty[name] = by_counterparty.get(name, 0.0) + float(row.get("amount") or 0.0)
        return {
            "count": len(rows),
            "total_amount": total_amount,
            "by_counterparty": [
                {"counterparty": name, "amount": amount}
                for name, amount in sorted(by_counterparty.items(), key=lambda item: (-item[1], item[0]))
            ],
            "rows": rows,
        }

    def add_bug_report(
        self,
        *,
        chat_id: str,
        created_by: str,
        description: str,
    ) -> int:
        now = utc_now()
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO bug_reports(
                    chat_id, created_by, description, status,
                    closed_at, closed_by, created_at, updated_at
                )
                VALUES(?, ?, ?, 'open', NULL, NULL, ?, ?)
                """,
                (chat_id, created_by, description, now, now),
            )
            return int(cursor.lastrowid)

    def list_bug_reports(
        self,
        chat_id: str | None = None,
        *,
        status: str = "open",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []


        if chat_id:
            clauses.append("chat_id = ?")
            params.append(chat_id)
        if status and status != "all":
            clauses.append("status = ?")
            params.append(status)
        params.append(int(limit))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, chat_id, created_by, description, status,
                       closed_at, closed_by, created_at, updated_at
                FROM bug_reports
                {where}
                ORDER BY id DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [dict(row) for row in rows]

    def close_bug_reports_auto(self, bug_ids: list[int], *, actor: str = "auto-fix") -> list[int]:
        if not bug_ids:
            return []
        now = utc_now()
        closed: list[int] = []
        with self.connect() as conn:
            for bug_id in bug_ids:
                cursor = conn.execute(
                    "UPDATE bug_reports SET status = 'closed', closed_at = ?, closed_by = ?, updated_at = ? "
                    "WHERE id = ? AND status = 'open'",
                    (now, actor, now, int(bug_id)),
                )
                if cursor.rowcount:
                    closed.append(int(bug_id))
        return closed

    def update_bug_report_status(
        self,
        *,
        bug_id: int,
        status: str,
        actor: str,
        chat_id: str | None = None,
    ) -> dict[str, Any] | None:
        normalized = (status or "").strip().lower()
        if normalized not in {"open", "closed"}:
            raise ValueError("bug status must be open or closed")
        now = utc_now()
        closed_at = now if normalized == "closed" else None
        closed_by = actor if normalized == "closed" else None
        clauses = ["id = ?"]
        params: list[Any] = [int(bug_id)]
        if chat_id:
            clauses.append("chat_id = ?")
            params.append(chat_id)
        where = " AND ".join(clauses)
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT id, chat_id, created_by, description, status,
                       closed_at, closed_by, created_at, updated_at
                FROM bug_reports
                WHERE """
                + where,
                tuple(params),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                """
                UPDATE bug_reports
                SET status = ?, closed_at = ?, closed_by = ?, updated_at = ?
                WHERE """
                + where,
                tuple([normalized, closed_at, closed_by, now] + params),
            )
        updated = dict(row)
        updated["status"] = normalized
        updated["closed_at"] = closed_at
        updated["closed_by"] = closed_by
        updated["updated_at"] = now
        return updated
