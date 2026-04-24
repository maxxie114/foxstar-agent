def test_resolve_provider_routes_deepseek_models():
    assert _resolve_provider("auto", "deepseek-v4-pro") == "deepseek"
    assert _resolve_provider("deepseek", "deepseek-v4-flash") == "deepseek"

def test_deepseek_reasoning_effort_mapping():
    assert _normalize_deepseek_reasoning_effort("low") == "high"
    assert _normalize_deepseek_reasoning_effort("medium") == "high"
    assert _normalize_deepseek_reasoning_effort("high") == "high"
    assert _normalize_deepseek_reasoning_effort("max") == "max"
    assert _normalize_deepseek_reasoning_effort("none") == ""

def test_together_model_fallback_mapping():
    assert _together_openrouter_fallback_model("deepseek-ai/DeepSeek-V4-Pro") == "deepseek/deepseek-v4-pro"
    assert _together_openrouter_fallback_model("deepseek-ai/DeepSeek-V4-Flash") == "deepseek/deepseek-v4-flash"
