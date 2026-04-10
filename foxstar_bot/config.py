from __future__ import annotations

import os

from dataclasses import dataclass, field

from pathlib import Path

from typing import Any

@dataclass(frozen=True)
class RateLimitConfig:
    user_cooldown_seconds: int = 15
    group_cooldown_seconds: int = 8
    user_daily_limit: int = 50
    group_daily_limit: int = 300

@dataclass(frozen=True)
class ToolConfig:
    web_search_enabled: bool = True

    docs_enabled: bool = True

    vision_enabled: bool = True

@dataclass(frozen=True)
class ModelConfig:
    name: str = "gpt-4.1-mini"
    vision_model: str = "gpt-4.1-mini"
    temperature: float = 0.4
    max_output_tokens: int = 700

@dataclass(frozen=True)
class StorageConfig:
    sqlite_path: Path = Path("data/foxstar.sqlite3")
    files_dir: Path = Path("data/files")
    images_dir: Path = Path("data/images")

@dataclass(frozen=True)
class AppConfig:
    owner_user_id: str = ""
    bot_name: str = "FoxStar"
    trigger_prefix: str = "!"
    whitelist_user_ids: list[str] = field(default_factory=list)
    whitelist_room_ids: list[str] = field(default_factory=list)
    manual_debug: bool = False
    openai_api_key: str = ""
    tavily_api_key: str = ""
    exa_api_key: str = ""
    log_level: str = "INFO"
    rate_limits: RateLimitConfig = field(default_factory=RateLimitConfig)
    tools: ToolConfig = field(default_factory=ToolConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
