from foxstar_bot.llm_client import (
    _chat_messages_for_provider,
    _normalize_deepseek_reasoning_effort,
    _resolve_provider,
    _should_fallback_together_error,
    _blocked_repeated_failed_tool_call,
    _remember_failed_tool_signature,
    _together_openrouter_fallback_model,
)


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


def test_together_dynamic_rate_limit_is_fallback_eligible():
    error = Exception("Error code: 429 - {'error': {'type': 'dynamic_rate_limit', 'message': 'Too Many Requests'}}")
    assert _should_fallback_together_error(error, "deepseek/deepseek-v4-pro", object())


def test_together_internal_server_error_is_fallback_eligible():
    error = Exception("Error code: 500 - {'error': {'type': 'server_error', 'message': 'Internal server error'}}")
    assert _should_fallback_together_error(error, "deepseek/deepseek-v4-pro", object())


def test_provider_message_conversion_preserves_tool_fields():
    rendered = _chat_messages_for_provider(
        [
            {
                "role": "tool",
                "tool_call_id": "call_123",
                "content": '{"ok": false}',
            },
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "call_123", "type": "function", "function": {"name": "run_python_code", "arguments": "{}"}}],
                "reasoning_content": "thinking",
            },
        ]
    )

    assert rendered[0]["tool_call_id"] == "call_123"
    assert rendered[1]["tool_calls"][0]["id"] == "call_123"
    assert rendered[1]["reasoning_content"] == "thinking"


def test_repeated_failed_tool_call_is_blocked():
    failures: dict[tuple[str, str], int] = {}
    args = {"code": "print('hello')"}
    result = {"ok": False, "error": "ModuleNotFoundError: No module named yfinance"}

    _remember_failed_tool_signature(failures, "run_python_code", args, result)
    blocked = _blocked_repeated_failed_tool_call(failures, "run_python_code", args)

    assert blocked is not None
    assert blocked["__guardrail_blocked__"] is True
