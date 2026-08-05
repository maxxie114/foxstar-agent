from types import SimpleNamespace

from foxstar_bot.config import ModelConfig
from foxstar_bot.llm_client import LLMClient, _provider_reasoning_kwargs, _resolve_provider


def _response(*, content: str = "ok", tool_calls: list[object] | None = None, reasoning: str = "") -> object:
    message = SimpleNamespace(content=content, tool_calls=tool_calls or [])
    if reasoning:
        message.reasoning_content = reasoning
    return SimpleNamespace(
        id="request-123",
        choices=[SimpleNamespace(message=message, finish_reason="tool_calls" if tool_calls else "stop")],
        usage=None,
    )


def _recording_client(responses: list[object]) -> tuple[object, list[dict[str, object]]]:
    calls: list[dict[str, object]] = []

    def create(**kwargs: object) -> object:
        calls.append(kwargs)
        return responses.pop(0)

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return client, calls


def test_provider_clients_use_documented_compatibility_endpoints():
    client = LLMClient(
        "openai-test",
        ModelConfig(),
        zai_api_key="zai-test",
        telnyx_api_key="telnyx-test",
        kimi_api_key="kimi-test",
    )

    assert str(client.zai_client.base_url) == "https://api.z.ai/api/paas/v4/"
    assert str(client.telnyx_client.base_url) == "https://api.telnyx.com/v2/ai/openai/"
    assert str(client.kimi_client.base_url) == "https://api.moonshot.ai/v1/"


def test_provider_resolution_supports_aliases_and_official_model_names():
    assert _resolve_provider("z.ai", "glm-5.2") == "zai"
    assert _resolve_provider("telnyx-inference", "moonshotai/Kimi-K3") == "telnyx"
    assert _resolve_provider("moonshot", "kimi-k3") == "kimi"
    assert _resolve_provider("auto", "glm-5.2") == "zai"
    assert _resolve_provider("auto", "kimi-k3") == "kimi"


def test_provider_reasoning_payloads_match_each_api():
    assert _provider_reasoning_kwargs("zai", "glm-5.2", "high") == {
        "extra_body": {"thinking": {"type": "enabled"}}
    }
    assert _provider_reasoning_kwargs("telnyx", "zai-org/GLM-5.2", "none") == {
        "extra_body": {"enable_thinking": False}
    }
    assert _provider_reasoning_kwargs("kimi", "kimi-k3", "medium") == {"reasoning_effort": "high"}
    assert _provider_reasoning_kwargs("kimi", "kimi-k3", "none") == {"reasoning_effort": "low"}
    assert _provider_reasoning_kwargs("kimi", "kimi-k2.6", "none") == {
        "extra_body": {"thinking": {"type": "disabled"}}
    }
    assert _provider_reasoning_kwargs("kimi", "kimi-k2.7-code", "none") == {
        "extra_body": {"thinking": {"type": "enabled"}}
    }


def test_chat_sends_provider_specific_reasoning_parameters():
    llm = LLMClient("openai-test", ModelConfig(temperature=0.4))
    telnyx, telnyx_calls = _recording_client([_response()])
    kimi, kimi_calls = _recording_client([_response()])
    llm.telnyx_client = telnyx
    llm.kimi_client = kimi

    assert llm.chat([{"role": "user", "content": "hi"}], model="zai-org/GLM-5.2", provider="telnyx", reasoning_effort="low") == "ok"
    assert llm.chat([{"role": "user", "content": "hi"}], model="kimi-k3", provider="kimi", reasoning_effort="medium") == "ok"

    assert telnyx_calls[0]["extra_body"] == {"enable_thinking": True}
    assert telnyx_calls[0]["max_tokens"] == ModelConfig().max_output_tokens
    assert kimi_calls[0]["reasoning_effort"] == "high"
    assert "temperature" not in kimi_calls[0]


def test_kimi_tool_loop_preserves_reasoning_content_and_avoids_unsupported_fields():
    llm = LLMClient("openai-test", ModelConfig(reasoning_effort="high"))
    tool_call = SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(name="lookup", arguments='{"value":"x"}'),
    )
    kimi, calls = _recording_client(
        [
            _response(content="", tool_calls=[tool_call], reasoning="need tool"),
            _response(content="final"),
        ]
    )
    llm.kimi_client = kimi
    tools = [
        {
            "type": "function",
            "name": "lookup",
            "description": "Lookup a value.",
            "parameters": {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
        }
    ]

    result = llm.chat_with_tools(
        [{"role": "user", "content": "use lookup"}],
        tools,
        {"lookup": lambda value: {"ok": True, "value": value}},
        model="kimi-k2.6",
        provider="kimi",
    )

    assert result == "final"
    assert calls[0]["extra_body"] == {"thinking": {"type": "enabled"}}
    assert "temperature" not in calls[0]
    assert "parallel_tool_calls" not in calls[0]
    assert calls[1]["messages"][1]["reasoning_content"] == "need tool"
    assert calls[1]["messages"][2]["role"] == "tool"


def test_tool_budget_fallback_keeps_kimi_reasoning_controls():
    llm = LLMClient("openai-test", ModelConfig(reasoning_effort="high", temperature=0.4))
    tool_call = SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(name="lookup", arguments='{"value":"x"}'),
    )
    kimi, calls = _recording_client(
        [
            _response(content="", tool_calls=[tool_call], reasoning="need tool"),
            _response(content="final"),
        ]
    )
    llm.kimi_client = kimi
    tools = [
        {
            "type": "function",
            "name": "lookup",
            "description": "Lookup a value.",
            "parameters": {"type": "object", "properties": {}},
        }
    ]

    result = llm.chat_with_tools(
        [{"role": "user", "content": "use lookup"}],
        tools,
        {"lookup": lambda value: {"ok": True}},
        model="kimi-k2.6",
        provider="kimi",
        max_tool_rounds=1,
    )

    assert result == "final"
    assert calls[1]["extra_body"] == {"thinking": {"type": "enabled"}}
    assert "temperature" not in calls[1]


def test_telnyx_uses_only_its_unified_thinking_switch_for_hosted_models():
    assert _provider_reasoning_kwargs("telnyx", "moonshotai/Kimi-K3", "max") == {
        "extra_body": {"enable_thinking": True}
    }
    assert _provider_reasoning_kwargs("telnyx", "zai-org/GLM-5.2", "none") == {
        "extra_body": {"enable_thinking": False}
    }
