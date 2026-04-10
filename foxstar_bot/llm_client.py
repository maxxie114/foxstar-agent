from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import ModelConfig


class LLMClient:
    def __init__(self, api_key: str, model_config: ModelConfig) -> None:
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY 未配置")
        try:
            from openai import OpenAI
        except Exception as exc:
            raise RuntimeError("需要安装 openai Python SDK") from exc
        self.client = OpenAI(api_key=api_key)
        self.config = model_config

    def chat(self, messages: list[dict[str, Any]]) -> str:
        response = self.client.chat.completions.create(
            model=self.config.name,
            messages=messages,
            temperature=self.config.temperature,
            max_completion_tokens=self.config.max_output_tokens,
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
