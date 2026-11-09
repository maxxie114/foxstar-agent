from collections import deque
from types import SimpleNamespace

from foxstar_bot.config import ModelConfig
from foxstar_bot.llm_client import LLMClient
from foxstar_bot.router import MessageRouter
from foxstar_bot.wcf_adapter import IncomingMessage


def test_native_zai_request_keeps_multimodal_content_parts(tmp_path):
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        message = SimpleNamespace(content="native result", tool_calls=[])
        return SimpleNamespace(
            id="request-1",
            choices=[SimpleNamespace(message=message, finish_reason="stop")],
            usage=None,
        )

    image_path = tmp_path / "shot.png"
    image_path.write_bytes(b"image")
    llm = LLMClient("openai-test", ModelConfig(max_output_tokens=900))
    llm.zai_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )

    result = llm.analyze_image_native(
        image_path,
        "图里是什么？",
        model="glm-5.3-flash",
        provider="zai",
        reasoning_effort="medium",
    )

    assert result == "native result"
    assert calls[0]["model"] == "glm-5.3-flash"
    assert calls[0]["extra_body"] == {"thinking": {"type": "enabled"}}
    content = calls[0]["messages"][0]["content"]
    assert content[0]["type"] == "image_url"
    assert content[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert content[1] == {"type": "text", "text": "图里是什么？"}


def test_recent_image_handler_passes_native_reply_route(tmp_path):
    class FakeAdapter:
        def download_image(self, image):
            path = tmp_path / "shot.png"
            path.write_bytes(b"image")
            return path

    class FakeVision:
        def __init__(self):
            self.kwargs = None

        def analyze_local_image(self, path, chat_id, user_id, prompt, **kwargs):
            self.kwargs = kwargs
            return "native analysis"

    image = IncomingMessage(7, "wxid_user", "room", "room", "[图片]", 3, True, False)
    router = MessageRouter.__new__(MessageRouter)
    router.recent_images = {"room": deque([image])}
    router.vision = FakeVision()
    handler = router._tool_handlers(
        FakeAdapter(),
        "room",
        "wxid_user",
        is_admin=False,
        image_analysis_mode="native",
        image_model="glm-5.3-flash",
        image_provider="zai",
        image_reasoning_effort="medium",
    )["analyze_recent_image"]

    result = handler("latest", "图里是什么？")

    assert result["ok"] is True
    assert result["analysis_mode"] == "native"
    assert result["analysis"] == "native analysis"
    assert router.vision.kwargs == {
        "analysis_mode": "native",
        "model": "glm-5.3-flash",
        "provider": "zai",
        "reasoning_effort": "medium",
    }
