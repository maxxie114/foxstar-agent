from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except Exception:
        return
    load_dotenv()


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        import yaml
    except Exception as exc:
        raise RuntimeError("PyYAML is required to read config.yaml") from exc
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data or {}


def _get(data: dict[str, Any], path: str, default: Any) -> Any:
    cur: Any = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def _normalize_image_analysis_mode(value: Any) -> str:
    mode = str(value or "tool").strip().lower()
    return mode if mode in {"tool", "native"} else "tool"


def update_whitelist_user_ids(config_path: str | Path, user_ids: list[str]) -> None:
    path = Path(config_path)
    data = _load_yaml(path)
    data["whitelist_user_ids"] = user_ids
    _write_yaml(path, data)


def update_reply_timing(
    config_path: str | Path,
    min_delay_seconds: float,
    max_delay_seconds: float,
    between_messages_seconds: float,
) -> None:
    path = Path(config_path)
    data = _load_yaml(path)
    data["reply_timing"] = {
        "min_delay_seconds": min_delay_seconds,
        "max_delay_seconds": max_delay_seconds,
        "between_messages_seconds": between_messages_seconds,
    }
    _write_yaml(path, data)


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    try:
        import yaml
    except Exception as exc:
        raise RuntimeError("PyYAML is required to write config.yaml") from exc
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


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


@dataclass
class ClanConfig:
    api_base: str = ""
    api_key: str = ""
    enabled_groups: list[str] = field(default_factory=list)
    attendance_api_base: str = ""
    import_groups: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AppConfig:
    bot_name: str = "FoxStar"
    trigger_prefix: str = "!"
    owner_user_id: str = ""
    whitelist_user_ids: list[str] = field(default_factory=list)
    whitelist_room_ids: list[str] = field(default_factory=list)
    manual_debug: bool = False
    wcf_mode: str = "local"
    wcf_host: str | None = None
    wcf_port: int = 10086
    openai_api_key: str = ""
    gemini_api_key: str = ""
    tavily_api_key: str = ""
    exa_api_key: str = ""
    daytona_api_key: str = ""
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
    clan: ClanConfig = field(default_factory=ClanConfig)


def load_config(config_path: str = "config.yaml") -> AppConfig:
    _load_dotenv()
    data = _load_yaml(Path(config_path))

    sqlite_path = Path(os.getenv("SQLITE_PATH") or _get(data, "storage.sqlite_path", "data/foxstar.sqlite3"))
    files_dir = Path(_get(data, "storage.files_dir", "data/files"))
    images_dir = Path(_get(data, "storage.images_dir", "data/images"))

    configured_wcf_mode = str(os.getenv("WCF_MODE") or _get(data, "wcf.mode", "")).strip().lower()
    if configured_wcf_mode not in {"local", "remote"}:
        configured_wcf_mode = "local" if os.name == "nt" else "remote"
    configured_wcf_host = (os.getenv("WCF_HOST") or _get(data, "wcf.host", None) or None)
    wcf_host = configured_wcf_host if configured_wcf_mode == "remote" else None

    return AppConfig(
        bot_name=str(_get(data, "bot_name", "FoxStar")),
        trigger_prefix=str(_get(data, "trigger_prefix", "!")),
        owner_user_id=str(_get(data, "owner_user_id", "")).strip(),
        whitelist_user_ids=list(_get(data, "whitelist_user_ids", [])),
        whitelist_room_ids=list(_get(data, "whitelist_room_ids", [])),
        manual_debug=bool(_get(data, "manual_debug", False)),
        wcf_mode=configured_wcf_mode,
        wcf_host=wcf_host,
        wcf_port=int(os.getenv("WCF_PORT") or _get(data, "wcf.port", 10086)),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        tavily_api_key=os.getenv("TAVILY_API_KEY", ""),
        exa_api_key=os.getenv("EXA_API_KEY", ""),
        daytona_api_key=os.getenv("DAYTONA_API_KEY", ""),
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY", ""),
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        together_api_key=os.getenv("TOGETHER_API_KEY", ""),
        lightning_api_key=os.getenv("LIGHTNING_API_KEY", ""),
        minimax_api_key=os.getenv("MINIMAX_TOKEN_KEY") or os.getenv("MINIMAX_API_KEY", ""),
        bedrock_api_key=os.getenv("BEDROCK_API_KEY") or os.getenv("BEDROCK_KEY_1", ""),
        sambanova_api_key=os.getenv("SAMBA_NOVA_KEY", ""),
            cerebras_api_key=os.getenv("CEREBRAS_API_KEY", ""),
        fireworks_api_key=os.getenv("FIREWORKS_API_KEY", ""),
        zai_api_key=os.getenv("ZAI_API_KEY") or os.getenv("Z_AI_API_KEY", ""),
        zai_base_url=(os.getenv("ZAI_BASE_URL") or "https://api.z.ai/api/paas/v4/").strip(),
        telnyx_api_key=os.getenv("TELNYX_API_KEY", ""),
        telnyx_base_url=(os.getenv("TELNYX_BASE_URL") or "https://api.telnyx.com/v2/ai/openai").strip(),
        kimi_api_key=os.getenv("KIMI_API_KEY") or os.getenv("MOONSHOT_API_KEY", ""),
        kimi_base_url=(os.getenv("KIMI_BASE_URL") or os.getenv("MOONSHOT_BASE_URL") or "https://api.moonshot.ai/v1").strip(),
        log_level=os.getenv("LOG_LEVEL") or str(_get(data, "log_level", "INFO")),
        rate_limits=RateLimitConfig(
            user_cooldown_seconds=int(_get(data, "rate_limits.user_cooldown_seconds", 15)),
            group_cooldown_seconds=int(_get(data, "rate_limits.group_cooldown_seconds", 8)),
            user_daily_limit=int(_get(data, "rate_limits.user_daily_limit", 0)),
            group_daily_limit=int(_get(data, "rate_limits.group_daily_limit", 0)),
        ),
        tools=ToolConfig(
            web_search_enabled=bool(_get(data, "tools.web_search_enabled", True)),
            docs_enabled=bool(_get(data, "tools.docs_enabled", True)),
            vision_enabled=bool(_get(data, "tools.vision_enabled", True)),
            auto_memory_enabled=bool(_get(data, "tools.auto_memory_enabled", True)),
            web_research_provider=str(_get(data, "tools.web_research_provider", "openai")).strip().lower(),
            openai_web_search_model=str(_get(data, "tools.openai_web_search_model", "gpt-5")),
            openai_web_search_reasoning_effort=str(_get(data, "tools.openai_web_search_reasoning_effort", "low")).strip().lower(),
            openai_web_search_max_output_tokens=int(_get(data, "tools.openai_web_search_max_output_tokens", 6000)),
            openrouter_web_search_model=str(_get(data, "tools.openrouter_web_search_model", "perplexity/sonar-pro-search")),
            openrouter_web_search_max_output_tokens=int(_get(data, "tools.openrouter_web_search_max_output_tokens", 3000)),
            preferred_search_provider=str(_get(data, "tools.preferred_search_provider", "exa")),
            exa_search_type=str(_get(data, "tools.exa_search_type", "auto")).strip().lower(),
            code_execution_enabled=bool(_get(data, "tools.code_execution_enabled", False)),
        ),
        clan=ClanConfig(
            api_base=str(_get(data, "clan.api_base", "")).strip().rstrip("/"),
            api_key=str(os.getenv("CLAN_JIELONG_API_KEY", "") or _get(data, "clan.api_key", "")).strip(),
            enabled_groups=[str(g).strip() for g in (_get(data, "clan.enabled_groups", []) or []) if str(g).strip()],
            attendance_api_base=str(_get(data, "clan.attendance_api_base", "")).strip().rstrip("/"),
            import_groups=[str(g).strip() for g in (_get(data, "clan.import_groups", []) or []) if str(g).strip()],
        ),
        model=ModelConfig(
            name=str(_get(data, "model.name", "gpt-4.1-mini")),
            provider=str(_get(data, "model.provider", "auto")).strip().lower(),
            reply_gate_model=str(_get(data, "model.reply_gate_model", "gpt-5-nano")),
            reply_gate_middle_model=str(_get(data, "model.reply_gate_middle_model", "qwen-3.8-27b")),
            reply_gate_middle_provider=str(_get(data, "model.reply_gate_middle_provider", "cerebras")).strip().lower(),
            reply_gate_fallback_model=str(_get(data, "model.reply_gate_fallback_model", "z-ai/glm-5.3-flash")),
            context_compression_provider=str(_get(data, "model.context_compression_provider", "")).strip().lower(),
            context_compression_model=str(_get(data, "model.context_compression_model", "")).strip(),
            context_compression_fallback_provider=str(_get(data, "model.context_compression_fallback_provider", "")).strip().lower(),
            context_compression_fallback_model=str(_get(data, "model.context_compression_fallback_model", "")).strip(),
            financial_model=str(_get(data, "model.financial_model", "deepseek-ai/DeepSeek-V4-Pro")),
            financial_provider=str(_get(data, "model.financial_provider", "together")).strip().lower(),
            financial_reasoning_effort=str(_get(data, "model.financial_reasoning_effort", "medium")).strip().lower(),
            financial_verbosity=str(_get(data, "model.financial_verbosity", "medium")).strip().lower(),
            image_analysis_mode=_normalize_image_analysis_mode(
                _get(data, "model.image_analysis_mode", "tool")
            ),
            vision_model=str(_get(data, "model.vision_model", "gpt-4.1-mini")),
            vision_provider=str(_get(data, "model.vision_provider", "openai")).strip().lower(),
            gemini_vision_model=str(_get(data, "model.gemini_vision_model", "gemini-3.1-flash-image-preview")),
            reasoning_effort=str(_get(data, "model.reasoning_effort", "medium")).strip().lower(),
            verbosity=str(_get(data, "model.verbosity", "medium")).strip().lower(),
            temperature=float(_get(data, "model.temperature", 0.4)),
            max_output_tokens=int(_get(data, "model.max_output_tokens", 700)),
        ),
        model_router=ModelRouterConfig(
            enabled=bool(_get(data, "model_router.enabled", False)),
            low=ModelRouterTierConfig(
                provider=str(_get(data, "model_router.low.provider", "sambanova")).strip().lower(),
                model=str(_get(data, "model_router.low.model", "MiniMax-M2.7")).strip(),
                reasoning_effort=str(_get(data, "model_router.low.reasoning_effort", "low")).strip().lower(),
                verbosity=str(_get(data, "model_router.low.verbosity", "low")).strip().lower(),
            ),
            medium=ModelRouterTierConfig(
                provider=str(_get(data, "model_router.medium.provider", "openrouter")).strip().lower(),
                model=str(_get(data, "model_router.medium.model", "z-ai/glm-5-turbo")).strip(),
                reasoning_effort=str(_get(data, "model_router.medium.reasoning_effort", "medium")).strip().lower(),
                verbosity=str(_get(data, "model_router.medium.verbosity", "medium")).strip().lower(),
            ),
            high=ModelRouterTierConfig(
                provider=str(_get(data, "model_router.high.provider", "openai")).strip().lower(),
                model=str(_get(data, "model_router.high.model", "gpt-5.4")).strip(),
                reasoning_effort=str(_get(data, "model_router.high.reasoning_effort", "high")).strip().lower(),
                verbosity=str(_get(data, "model_router.high.verbosity", "medium")).strip().lower(),
            ),
        ),
        storage=StorageConfig(sqlite_path=sqlite_path, files_dir=files_dir, images_dir=images_dir),
        reply_timing=ReplyTimingConfig(
            min_delay_seconds=float(_get(data, "reply_timing.min_delay_seconds", 3.0)),
            max_delay_seconds=float(_get(data, "reply_timing.max_delay_seconds", 5.0)),
            between_messages_seconds=float(_get(data, "reply_timing.between_messages_seconds", 1.0)),
        ),
    )
