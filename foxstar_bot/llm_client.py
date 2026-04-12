from __future__ import annotations

from pathlib import Path

import base64

import json

import logging

import mimetypes

from typing import Any

from urllib.parse import quote

from .config import ModelConfig

REQUEST_TIMEOUT = 25.0

REPLY_GATE_TIMEOUT = 6.0

RESPONSES_TIMEOUT = 18.0

LOG = logging.getLogger(__name__)

class LLMClient:
    def __init__(self, api_key: str, model_config: ModelConfig, gemini_api_key: str = "") -> None:
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
        self.gemini_api_key = gemini_api_key

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        max_completion_tokens: int | None = None,
        model: str | None = None,
        timeout: float | None = None,
    ) -> str:
        response = self.client.chat.completions.create(
            model=model or self.config.name,
            messages=messages,
            temperature=self.config.temperature,
            max_completion_tokens=max_completion_tokens or self.config.max_output_tokens,
            timeout=timeout,
        )
        return (response.choices[0].message.content or "").strip()

    def analyze_image(self, image_path: Path, prompt: str) -> str:
        if self.config.vision_provider == "gemini":
            try:
                return self._analyze_image_gemini(image_path, prompt)
            except Exception as exc:
                LOG.warning("gemini vision failed, falling back to openai vision: %s", exc)
        return self._analyze_image_openai(image_path, prompt)

    def _analyze_image_openai(self, image_path: Path, prompt: str) -> str:
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

    def _analyze_image_gemini(self, image_path: Path, prompt: str) -> str:
        if not self.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        try:
            import httpx
        except Exception as exc:
            raise RuntimeError("httpx is required for Gemini vision") from exc

        mime = mimetypes.guess_type(image_path.name)[0] or "image/jpeg"
        data = base64.b64encode(image_path.read_bytes()).decode("ascii")
        model = self.config.gemini_vision_model.removeprefix("models/")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{quote(model, safe='-_.')}:generateContent"
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": prompt},
                        {"inline_data": {"mime_type": mime, "data": data}},
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 8192,
            },
        }
        timeout = httpx.Timeout(90.0, connect=10.0, read=75.0, write=30.0, pool=5.0)
        with httpx.Client(timeout=timeout) as client:
            response = client.post(url, headers={"x-goog-api-key": self.gemini_api_key}, json=payload)
            response.raise_for_status()
        body = response.json()
        parts = body.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        text = "\n".join(part.get("text", "") for part in parts if part.get("text"))
        if not text.strip():
            raise RuntimeError("Gemini returned no text")
        text = text.strip()
        LOG.info("gemini vision raw response image=%s chars=%s text=%r", image_path, len(text), text[:1000])
        return text
