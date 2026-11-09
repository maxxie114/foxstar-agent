from pathlib import Path

from foxstar_bot.config import ModelConfig
from foxstar_bot.llm_client import (
    LLMClient,
    _model_supports_temperature,
    _normalize_reasoning_effort,
    _openrouter_reasoning_extra_body,
    _resolve_provider,
    _responses_tool_to_chat_tool,
)
from foxstar_bot.persistence import Database
from foxstar_bot.tool_vision import VisionTool


def test_model_config_defaults_main_reasoning():
    config = ModelConfig()

    assert config.reasoning_effort == "medium"
    assert config.verbosity == "medium"


def test_gpt5_models_omit_custom_temperature():
    assert not _model_supports_temperature("gpt-5.4")
    assert not _model_supports_temperature("gpt-5-nano")
    assert _model_supports_temperature("gpt-4.1-mini")


def test_openrouter_provider_routing_and_tool_schema():
    assert _resolve_provider("auto", "anthropic/claude-sonnet-4.5") == "openrouter"
    assert _resolve_provider("auto", "gpt-5.4") == "openai"
    assert _resolve_provider("openrouter", "gpt-5.4") == "openrouter"

    tool = _responses_tool_to_chat_tool(
        {
            "type": "function",
            "name": "fetch_url",
            "description": "Fetch a URL.",
            "parameters": {"type": "object", "properties": {"url": {"type": "string"}}},
        }
    )

    assert tool["type"] == "function"
    assert tool["function"]["name"] == "fetch_url"
    assert tool["function"]["parameters"]["properties"]["url"]["type"] == "string"


def test_reasoning_adapter_normalizes_openrouter_payloads():
    assert _normalize_reasoning_effort("none") == ""
    assert _normalize_reasoning_effort("med") == "medium"
    assert _normalize_reasoning_effort("max") == "high"
    assert _normalize_reasoning_effort("max", preserve_max=True) == "max"

    assert _openrouter_reasoning_extra_body("google/gemini-3-pro", "medium") == {
        "reasoning": {"effort": "medium", "exclude": True}
    }
    assert _openrouter_reasoning_extra_body("anthropic/claude-opus-4.7", "max") == {
        "reasoning": {"effort": "max", "exclude": True}
    }
    assert _openrouter_reasoning_extra_body("anthropic/claude-opus-4.7", "high") == {
        "reasoning": {"effort": "high", "exclude": True}
    }
    assert _openrouter_reasoning_extra_body("anthropic/claude-sonnet-4.5", "low") == {
        "reasoning": {"max_tokens": 1024, "exclude": True}
    }
    assert _openrouter_reasoning_extra_body("z-ai/glm-4.6", "none") == {}


def test_gemini_vision_client_posts_inline_image(monkeypatch, tmp_path):
    image_path = tmp_path / "shot.png"
    image_path.write_bytes(b"fake image bytes")
    calls = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "OCR text"}]}}]}

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, headers, json):
            calls["url"] = url
            calls["headers"] = headers
            calls["json"] = json
            return FakeResponse()

    import httpx

    monkeypatch.setattr(httpx, "Client", FakeClient)
    llm = LLMClient.__new__(LLMClient)
    llm.config = ModelConfig(vision_provider="gemini", gemini_vision_model="models/gemini-test")
    llm.gemini_api_key = "gemini-key"

    result = llm._analyze_image_gemini(Path(image_path), "read this")

    assert result == "OCR text"
    assert calls["url"].endswith("/models/gemini-test:generateContent")
    assert calls["headers"]["x-goog-api-key"] == "gemini-key"
    parts = calls["json"]["contents"][0]["parts"]
    assert parts[0]["text"] == "read this"
    assert parts[1]["inline_data"]["mime_type"] == "image/png"
    assert parts[1]["inline_data"]["data"]


def test_native_image_analysis_uses_selected_reply_model(tmp_path):
    image_path = tmp_path / "shot.png"
    image_path.write_bytes(b"fake image bytes")
    calls = {}
    llm = LLMClient.__new__(LLMClient)
    llm.config = ModelConfig(max_output_tokens=900)

    def fake_chat(messages, **kwargs):
        calls["messages"] = messages
        calls["kwargs"] = kwargs
        return "native result"

    llm.chat = fake_chat

    result = llm.analyze_image_native(
        image_path,
        "read this",
        model="glm-5.3-flash",
        provider="zai",
        reasoning_effort="medium",
        usage_context={"chat_id": "room", "feature": "native_image_analysis"},
    )

    assert result == "native result"
    assert calls["kwargs"]["model"] == "glm-5.3-flash"
    assert calls["kwargs"]["provider"] == "zai"
    assert calls["kwargs"]["reasoning_effort"] == "medium"
    parts = calls["messages"][0]["content"]
    assert parts[0]["type"] == "image_url"
    assert parts[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert parts[1] == {"type": "text", "text": "read this"}


def test_vision_tool_routes_native_mode_to_current_model(tmp_path):
    image_path = tmp_path / "shot.png"
    image_path.write_bytes(b"fake image bytes")
    calls = {}

    class FakeLLM:
        def analyze_image_native(self, path, prompt, **kwargs):
            calls["path"] = path
            calls["prompt"] = prompt
            calls["kwargs"] = kwargs
            return "seen natively"

        def analyze_image(self, path, prompt):
            raise AssertionError("dedicated image tool should not run in native mode")

    vision = VisionTool(Database(tmp_path / "bot.sqlite3"), tmp_path / "images", FakeLLM())

    result = vision.analyze_local_image(
        image_path,
        "room",
        "user",
        "what is this?",
        analysis_mode="native",
        model="glm-5.3-flash",
        provider="zai",
        reasoning_effort="low",
    )

    assert result == "seen natively"
    assert calls["prompt"] == "what is this?"
    assert calls["kwargs"]["model"] == "glm-5.3-flash"
    assert calls["kwargs"]["provider"] == "zai"


def test_vision_tool_keeps_dedicated_tool_mode_as_default(tmp_path):
    image_path = tmp_path / "shot.png"
    image_path.write_bytes(b"fake image bytes")

    class FakeLLM:
        def analyze_image(self, path, prompt):
            return "dedicated result"

        def analyze_image_native(self, path, prompt, **kwargs):
            raise AssertionError("native model should not run in tool mode")

    vision = VisionTool(Database(tmp_path / "bot.sqlite3"), tmp_path / "images", FakeLLM())

    result = vision.analyze_local_image(image_path, "room", "user", "read this")

    assert result == "dedicated result"
