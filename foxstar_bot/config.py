from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RateLimitConfig:
    user_cooldown_seconds: int = 15
    group_cooldown_seconds: int = 8
    user_daily_limit: int = 0
    group_daily_limit: int = 0


@dataclass(frozen=True)
class ToolConfig:
    web_search_enabled: bool = True
    docs_enabled: bool = True
    vision_enabled: bool = True
    auto_memory_enabled: bool = True
    web_research_provider: str = "openai"
    openai_web_search_model: str = "gpt-5"
    openai_web_search_reasoning_effort: str = "low"
    openai_web_search_max_output_tokens: int = 6000
    openrouter_web_search_model: str = "perplexity/sonar-pro-search"
    openrouter_web_search_max_output_tokens: int = 3000
    preferred_search_provider: str = "exa"
    exa_search_type: str = "auto"
    exa_agent_effort: str = "minimal"
    code_execution_enabled: bool = False


@dataclass(frozen=True)
class ModelConfig:
    name: str = "gpt-4.1-mini"
    provider: str = "auto"
    reply_gate_model: str = "gpt-5-nano"
    reply_gate_middle_model: str = "qwen-3.8-27b"
    reply_gate_middle_provider: str = "cerebras"
    reply_gate_fallback_model: str = "z-ai/glm-5.3-flash"
    context_compression_provider: str = ""
    context_compression_model: str = ""
    context_compression_fallback_provider: str = ""
    context_compression_fallback_model: str = ""
    financial_model: str = "deepseek-ai/DeepSeek-V4-Pro"
    financial_provider: str = "together"
    financial_reasoning_effort: str = "medium"
    financial_verbosity: str = "medium"
    image_analysis_mode: str = "tool"
    vision_model: str = "gpt-4.1-mini"
    vision_provider: str = "openai"
    gemini_vision_model: str = "gemini-3.1-flash-image-preview"
    reasoning_effort: str = "medium"
    verbosity: str = "medium"
    temperature: float = 0.4
    max_output_tokens: int = 700


@dataclass(frozen=True)
class ModelRouterTierConfig:
    provider: str = "openai"
    model: str = "gpt-5.4"
    reasoning_effort: str = "medium"
    verbosity: str = "medium"


@dataclass(frozen=True)
class ModelRouterConfig:
    enabled: bool = False
    low: ModelRouterTierConfig = field(
        default_factory=lambda: ModelRouterTierConfig(
            provider="sambanova",
            model="MiniMax-M2.7",
            reasoning_effort="low",
            verbosity="low",
        )
    )
    medium: ModelRouterTierConfig = field(
        default_factory=lambda: ModelRouterTierConfig(
            provider="openrouter",
            model="z-ai/glm-5-turbo",
            reasoning_effort="medium",
            verbosity="medium",
        )
    )
    high: ModelRouterTierConfig = field(
        default_factory=lambda: ModelRouterTierConfig(
            provider="openai",
            model="gpt-5.4",
            reasoning_effort="high",
            verbosity="medium",
        )
    )


@dataclass(frozen=True)
class StorageConfig:
    sqlite_path: Path = Path("data/foxstar.sqlite3")
    files_dir: Path = Path("data/files")
    images_dir: Path = Path("data/images")


@dataclass
class ReplyTimingConfig:
    min_delay_seconds: float = 3.0
    max_delay_seconds: float = 5.0
    between_messages_seconds: float = 1.0


@dataclass(frozen=True)
class AppConfig:
    owner_user_id: str = ""
    bot_name: str = "FoxStar"
    trigger_prefix: str = "!"
    whitelist_user_ids: list[str] = field(default_factory=list)
    whitelist_room_ids: list[str] = field(default_factory=list)
    manual_debug: bool = False
    openai_api_key: str = ""
    gemini_api_key: str = ""
    tavily_api_key: str = ""
    exa_api_key: str = ""
    openrouter_api_key: str = ""
    deepseek_api_key: str = ""
    together_api_key: str = ""
    lightning_api_key: str = ""
    minimax_api_key: str = ""
    bedrock_api_key: str = ""
    sambanova_api_key: str = ""
    cerebras_api_key: str = ""
    fireworks_api_key: str = ""
    zai_api_key: str = ""
    zai_base_url: str = "https://api.z.ai/api/paas/v4/"
    telnyx_api_key: str = ""
    telnyx_base_url: str = "https://api.telnyx.com/v2/ai/openai"
    kimi_api_key: str = ""
    kimi_base_url: str = "https://api.moonshot.ai/v1"
    log_level: str = "INFO"
    rate_limits: RateLimitConfig = field(default_factory=RateLimitConfig)
    tools: ToolConfig = field(default_factory=ToolConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    model_router: ModelRouterConfig = field(default_factory=ModelRouterConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    reply_timing: ReplyTimingConfig = field(default_factory=ReplyTimingConfig)
