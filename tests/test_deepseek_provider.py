from foxstar_bot.llm_client import _normalize_deepseek_reasoning_effort, _resolve_provider


def test_resolve_provider_routes_deepseek_models():
    assert _resolve_provider("auto", "deepseek-v4-pro") == "deepseek"
    assert _resolve_provider("deepseek", "deepseek-v4-flash") == "deepseek"


def test_deepseek_reasoning_effort_mapping():
    assert _normalize_deepseek_reasoning_effort("low") == "high"
    assert _normalize_deepseek_reasoning_effort("medium") == "high"
    assert _normalize_deepseek_reasoning_effort("high") == "high"
    assert _normalize_deepseek_reasoning_effort("max") == "max"
    assert _normalize_deepseek_reasoning_effort("none") == ""
