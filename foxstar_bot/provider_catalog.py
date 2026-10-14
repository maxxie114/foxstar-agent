PROVIDER_MODEL_CATALOG: dict[str, tuple[str, str]] = {

    "glm-5.3-flashx": ("zai", "glm-5.3-flashx"),
    "glm-5.3-flash": ("zai", "glm-5.3-flash"),
    "glm-5.3": ("zai", "glm-5.3"),
    "glm-5.2": ("zai", "glm-5.2"),
    "glm-5.1": ("zai", "glm-5.1"),
    "glm-5-turbo": ("zai", "glm-5-turbo"),
    "glm-5": ("zai", "glm-5"),
    "glm-4.7": ("zai", "glm-4.7"),
    "glm-4.6": ("zai", "glm-4.6"),
    "glm-4.5-air": ("zai", "glm-4.5-air"),
    "glm-4.5": ("zai", "glm-4.5"),

    "moonshotai/kimi-k3": ("telnyx", "moonshotai/Kimi-K3"),
    "kimi-k3": ("telnyx", "moonshotai/Kimi-K3"),
    "moonshotai/kimi-k2.6": ("telnyx", "moonshotai/Kimi-K2.6"),
    "moonshotai/kimi-k2.5": ("telnyx", "moonshotai/Kimi-K2.5"),
    "minimax-m2.7": ("telnyx", "MiniMaxAI/MiniMax-M2.7"),
    "minimaxai/minimax-m2.7": ("telnyx", "MiniMaxAI/MiniMax-M2.7"),
    "minimax-m3": ("telnyx", "MiniMaxAI/MiniMax-M3-MXFP8"),
    "minimaxai/minimax-m3": ("telnyx", "MiniMaxAI/MiniMax-M3-MXFP8"),

    "qwen/qwen3-235b": ("telnyx", "Qwen/Qwen3-235B-A22B"),
    "deepseek-ai/deepseek-v4-flash": ("telnyx", "deepseek-ai/DeepSeek-V4-Flash-0731"),
}


def catalog_lookup(model: str) -> tuple[str, str] | None:
    value = (model or "").strip().lower()
    if not value:
        return None
    best_key = ""
    for key in PROVIDER_MODEL_CATALOG:
        if value.startswith(key) and len(key) > len(best_key):
            best_key = key
    if not best_key:
        return None
    provider, canonical = PROVIDER_MODEL_CATALOG[best_key]

    suffix = (model or "").strip()[len(best_key):]
    return provider, canonical + suffix
