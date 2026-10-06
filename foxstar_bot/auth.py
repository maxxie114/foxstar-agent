from __future__ import annotations

import logging
from typing import Any

from .config import AppConfig
from .persistence import Database

LOG = logging.getLogger(__name__)

DB_KEY_WHITELIST_USERS = "whitelist_user_ids"
DB_KEY_WHITELIST_ROOMS = "whitelist_room_ids"


class AuthService:

    def __init__(self, config: AppConfig, db: Database | None = None, config_path: str | None = None) -> None:
        self.db = db
        if db is not None:
            if db.get_setting(DB_KEY_WHITELIST_USERS, None) is None:
                db.set_setting(DB_KEY_WHITELIST_USERS, sorted(set(config.whitelist_user_ids)))
            if db.get_setting(DB_KEY_WHITELIST_ROOMS, None) is None:
                db.set_setting(DB_KEY_WHITELIST_ROOMS, sorted(set(config.whitelist_room_ids)))
        self.whitelist_user_ids = self._load(DB_KEY_WHITELIST_USERS, config.whitelist_user_ids)
        self.whitelist_room_ids = self._load(DB_KEY_WHITELIST_ROOMS, config.whitelist_room_ids)
        LOG.info("auth whitelist users=%s rooms=%s (source=%s)",
                 len(self.whitelist_user_ids), len(self.whitelist_room_ids), "db" if db else "config")

    def _load(self, key: str, fallback: list[str]) -> set[str]:
        if self.db is not None:
            value = self.db.get_setting(key, None)
            if isinstance(value, list):
                return {str(item).strip() for item in value if str(item).strip()}
        return {str(item).strip() for item in fallback if str(item).strip()}

    def set_whitelist_users(self, users: list[str]) -> None:
        clean = sorted({str(u).strip() for u in users if str(u).strip()})
        if self.db is not None:
            self.db.set_setting(DB_KEY_WHITELIST_USERS, clean)
        self.whitelist_user_ids = set(clean)
        LOG.info("auth whitelist updated users=%s", len(clean))

    def is_whitelist_user(self, user_id: str) -> bool:
        return user_id in self.whitelist_user_ids

    def is_whitelist_room(self, room_id: str) -> bool:
        return room_id in self.whitelist_room_ids
