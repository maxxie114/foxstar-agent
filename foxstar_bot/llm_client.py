from __future__ import annotations

from pathlib import Path

import json

import logging

from typing import Any

from .config import ModelConfig

REQUEST_TIMEOUT = 25.0

REPLY_GATE_TIMEOUT = 6.0

RESPONSES_TIMEOUT = 18.0

LOG = logging.getLogger(__name__)

class LLMClient:
    def __init__(self, api_key: str, model_config: ModelConfig) -> None:
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY 未配置")
        try:
            from openai import OpenAI
            import httpx
        except Exception as exc:
            raise RuntimeError("需要安装 openai Python SDK") from exc
        timeout = httpx.Timeout(REQUEST_TIMEOUT, connect=10.0, read=20.0, write=10.0, pool=5.0)
        self.client = OpenAI(api_key=api_key, timeout=timeout, max_retries=0)
        self.config = model_config

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        max_completion_tokens: int | None = None,
        timeout: float | None = None,
    ) -> str:
        response = self.client.chat.completions.create(
            model=self.config.name,
            messages=messages,
            temperature=self.config.temperature,
            max_completion_tokens=max_completion_tokens or self.config.max_output_tokens,
            timeout=timeout,
        )
        return (response.choices[0].message.content or "").strip()

    def analyze_image(self, image_path: Path, prompt: str) -> str:
        from .tool_vision import image_to_data_url

        response = self.client.chat.completions.create(
            model=self.config.vision_model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_to_data_url(image_path)}},
                    ],
                }
            ],
            temperature=0.2,
            max_completion_tokens=min(self.config.max_output_tokens, 600),
        )
        return (response.choices[0].message.content or "").strip()
