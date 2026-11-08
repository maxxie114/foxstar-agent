from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date

from .config import RateLimitConfig
from .persistence import Database


@dataclass(frozen=True)
class LimitResult:
    allowed: bool
    reason: str = ""


class RateLimiter:
    def __init__(self, db: Database, config: RateLimitConfig) -> None:
        self.db = db
        self.config = config

    def check_and_record(
        self,
        user_id: str,
        chat_id: str,
        is_group: bool,
        bypass: bool = False,
        user_daily_limit_override: int | None = None,
        group_daily_limit_override: int | None = None,
        ignore_cooldown: bool = False,
    ) -> LimitResult:
        if bypass:
            return LimitResult(True)
        today = date.today().isoformat()
        now = time.time()
        user_daily_limit = self.config.user_daily_limit if user_daily_limit_override is None else max(0, int(user_daily_limit_override))
        group_daily_limit = self.config.group_daily_limit if group_daily_limit_override is None else max(0, int(group_daily_limit_override))
        checks = [
            (f"user:{chat_id}:{user_id}", self.config.user_cooldown_seconds, user_daily_limit),
        ]
        if is_group:
            checks.append((f"group:{chat_id}", self.config.group_cooldown_seconds, group_daily_limit))

        with self.db.connect() as conn:
            for key, cooldown, daily_limit in checks:
                row = conn.execute(
                    "SELECT count, last_at FROM rate_events WHERE key = ? AND bucket_date = ?",
                    (key, today),
                ).fetchone()
                count = int(row["count"]) if row else 0
                last_at = float(row["last_at"]) if row else 0
                if daily_limit > 0 and count >= daily_limit:
                    return LimitResult(False, "daily_limit")
                if not ignore_cooldown and now - last_at < cooldown:
                    return LimitResult(False, "cooldown")

            for key, _cooldown, _daily_limit in checks:
                conn.execute(
                    """
                    INSERT INTO rate_events(key, bucket_date, count, last_at)
                    VALUES(?, ?, 1, ?)
                    ON CONFLICT(key, bucket_date)
                    DO UPDATE SET count = count + 1, last_at = excluded.last_at
                    """,
                    (key, today, now),
                )
        return LimitResult(True)
