from __future__ import annotations

from pathlib import Path

import base64

import json

import logging

import mimetypes

import time

from queue import Empty, Queue

from threading import Thread

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
        temperature: float | None = None,
        reasoning_effort: str | None = None,
        verbosity: str | None = None,
        timeout: float | None = None,
        prompt_cache_key: str | None = None,
        prompt_cache_retention: str | None = None,
    ) -> str:
        model_name = model or self.config.name
        api_timeout = float(timeout or REQUEST_TIMEOUT)
        kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "max_completion_tokens": max_completion_tokens or self.config.max_output_tokens,
            "timeout": api_timeout,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        if reasoning_effort is not None:
            kwargs["reasoning_effort"] = reasoning_effort
        if verbosity is not None:
            kwargs["verbosity"] = verbosity
        if prompt_cache_key:
            kwargs["prompt_cache_key"] = prompt_cache_key
        retention = prompt_cache_retention or _default_prompt_cache_retention(model_name)
        if retention:
            kwargs["prompt_cache_retention"] = retention
        response = _call_with_hard_timeout(
            "chat.completions",
            api_timeout + 2.0,
            self.client.chat.completions.create,
            **kwargs,
        )
        _log_prompt_cache_usage("chat.completions", model_name, getattr(response, "usage", None))
        choice = response.choices[0]
        content = (choice.message.content or "").strip()
        if not content:
            LOG.warning(
                "chat completion returned empty content model=%s finish_reason=%s usage=%s",
                kwargs["model"],
                getattr(choice, "finish_reason", None),
                getattr(response, "usage", None),
            )
        return content

    def responses_text(
        self,
        messages: list[dict[str, Any]],
        *,
        max_output_tokens: int | None = None,
        model: str | None = None,
        temperature: float | None = None,
        reasoning_effort: str | None = None,
        verbosity: str | None = None,
        timeout: float | None = None,
        prompt_cache_key: str | None = None,
        prompt_cache_retention: str | None = None,
    ) -> str:
        model_name = model or self.config.name
        api_timeout = float(timeout or REQUEST_TIMEOUT)
        instructions = "\n\n".join(str(item["content"]) for item in messages if item.get("role") == "system")
        input_items = [
            {"role": item["role"], "content": item["content"]}
            for item in messages
            if item.get("role") in {"user", "assistant"}
        ]
        kwargs: dict[str, Any] = {
            "model": model_name,
            "instructions": instructions,
            "input": input_items,
            "max_output_tokens": max_output_tokens or self.config.max_output_tokens,
            "timeout": api_timeout,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        if reasoning_effort is not None:
            kwargs["reasoning"] = {"effort": reasoning_effort}
        if verbosity is not None:
            kwargs["text"] = {"verbosity": verbosity}
        if prompt_cache_key:
            kwargs["prompt_cache_key"] = prompt_cache_key
        retention = prompt_cache_retention or _default_prompt_cache_retention(model_name)
        if retention:
            kwargs["prompt_cache_retention"] = retention
        response = _openai_call_with_retry("responses.create", api_timeout + 2.0, self.client.responses.create, **kwargs)
        _log_prompt_cache_usage("responses.create", model_name, getattr(response, "usage", None))
        content = (response.output_text or "").strip()
        if not content:
            LOG.warning(
                "responses returned empty text model=%s usage=%s",
                kwargs["model"],
                getattr(response, "usage", None),
            )
        return content

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

def _call_with_hard_timeout(label: str, hard_timeout: float, func: Any, *args: Any, **kwargs: Any) -> Any:
    result: Queue[tuple[bool, Any]] = Queue(maxsize=1)

    def run() -> None:
        try:
            result.put((True, func(*args, **kwargs)))
        except Exception as exc:
            result.put((False, exc))

    Thread(target=run, name=f"OpenAI-{label}", daemon=True).start()
    try:
        ok, value = result.get(timeout=hard_timeout)
    except Empty as exc:
        raise TimeoutError(f"{label} hard timeout after {hard_timeout:.1f}s") from exc
    if ok:
        return value
    raise value

def _openai_call_with_retry(label: str, hard_timeout: float, func: Any, **kwargs: Any) -> Any:
    for attempt in range(2):
        try:
            return _call_with_hard_timeout(label, hard_timeout, func, **kwargs)
        except Exception as exc:
            if attempt == 0 and _is_retryable_openai_error(exc):
                LOG.warning("%s retrying after transient OpenAI error: %s", label, exc)
                time.sleep(0.4)
                continue
            raise
    raise RuntimeError("unreachable OpenAI retry state")

def _is_retryable_openai_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int) and (status_code == 408 or status_code == 409 or status_code == 429 or status_code >= 500):
        return True
    name = exc.__class__.__name__.lower()
    return "timeout" in name or "apierror" in name or "server" in name

def _default_prompt_cache_retention(model: str) -> str:
    model_name = (model or "").lower()
    if (
        model_name.startswith("gpt-5.4")
        or model_name.startswith("gpt-5.2")
        or model_name.startswith("gpt-5.1")
        or model_name.startswith("gpt-5-codex")
        or model_name == "gpt-5"
        or model_name.startswith("gpt-4.1")
        or model_name.startswith("gp5-5.1-codex-max")
    ):
        return "24h"
    return ""

def _log_prompt_cache_usage(api: str, model: str, usage: Any) -> None:
    if usage is None:
        return
    total = _usage_value(usage, "prompt_tokens")
    cached = _usage_nested_value(usage, "prompt_tokens_details", "cached_tokens")
    if total is None:
        total = _usage_value(usage, "input_tokens")
    if cached is None:
        cached = _usage_nested_value(usage, "input_tokens_details", "cached_tokens")
    if total is None and cached is None:
        return
    LOG.debug("prompt_cache api=%s model=%s cached_tokens=%s input_tokens=%s", api, model, cached or 0, total or 0)

def _usage_nested_value(usage: Any, parent: str, child: str) -> int | None:
    parent_value = _usage_value(usage, parent)
    if parent_value is None:
        return None
    if isinstance(parent_value, dict):
        value = parent_value.get(child)
    else:
        value = getattr(parent_value, child, None)
    return value if isinstance(value, int) else None

def _usage_value(usage: Any, key: str) -> Any:
    if isinstance(usage, dict):
        return usage.get(key)
    return getattr(usage, key, None)
