from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator


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
                """
            )
            for statement in (
                "ALTER TABLE memories ADD COLUMN priority INTEGER NOT NULL DEFAULT 50",
                "ALTER TABLE memories ADD COLUMN source_user_id TEXT",
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
        now = utc_now()
        payload = json.dumps(value, ensure_ascii=False)
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, payload),
            )

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

    def recent_chat_events(self, chat_id: str, *, limit: int = 50, days: int | None = 1) -> list[dict[str, Any]]:
        params: list[Any] = [chat_id]
        where = "WHERE chat_id = ?"
        if days is not None:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=max(days, 0))).isoformat(timespec="seconds")
            where += " AND created_at >= ?"
            params.append(cutoff)
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT created_at, event_type, display_name, user_id, raw_content
                FROM chat_events
                {where}
                ORDER BY id DESC
                LIMIT ?
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
