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
