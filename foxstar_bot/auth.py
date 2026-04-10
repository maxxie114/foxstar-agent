from __future__ import annotations

from .config import AppConfig


class AuthService:
    def __init__(self, config: AppConfig) -> None:
        self.whitelist_user_ids = set(config.whitelist_user_ids)
        self.whitelist_room_ids = set(config.whitelist_room_ids)

    def is_whitelist_user(self, user_id: str) -> bool:
        return user_id in self.whitelist_user_ids

    def is_whitelist_room(self, room_id: str) -> bool:
        return room_id in self.whitelist_room_ids
