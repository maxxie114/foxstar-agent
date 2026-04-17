from __future__ import annotations

from pathlib import Path

import base64

import json

import logging

import mimetypes

import time

from datetime import datetime, timedelta, timezone

from queue import Empty, Queue

from threading import Thread

from typing import Any

from urllib.parse import quote

from zoneinfo import ZoneInfo

from .config import ModelConfig

REQUEST_TIMEOUT = 25.0

REPLY_GATE_TIMEOUT = 6.0

RESPONSES_TIMEOUT = 18.0

OPENROUTER_TIMEOUT = 55.0

LOG = logging.getLogger(__name__)

class LLMClient:
    def __init__(
        self,
        api_key: str,
        model_config: ModelConfig,
        gemini_api_key: str = "",
        openrouter_api_key: str = "",
    ) -> None:
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY 未配置")
        try:
            from openai import OpenAI
            import httpx
        except Exception as exc:
            raise RuntimeError("需要安装 openai Python SDK") from exc
        timeout = httpx.Timeout(REQUEST_TIMEOUT, connect=10.0, read=20.0, write=10.0, pool=5.0)
        self.client = OpenAI(api_key=api_key, timeout=timeout, max_retries=0)
        self.openrouter_client = (
            OpenAI(
                api_key=openrouter_api_key,
                base_url="https://openrouter.ai/api/v1",
                timeout=timeout,
                max_retries=0,
                default_headers={

                    "X-Title": "FoxStar WeChat Bot",
                },
            )
            if openrouter_api_key
            else None
        )
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
        provider: str | None = None,
    ) -> str:
        model_name = model or self.config.name
        resolved_provider = _resolve_provider(provider or self.config.provider, model_name)
        if resolved_provider == "openrouter":
            return self._openrouter_chat(
                messages,
                model_name,
                max_tokens=max_completion_tokens or self.config.max_output_tokens,
                temperature=temperature,
                timeout=timeout,
            )
        api_timeout = float(timeout or OPENROUTER_TIMEOUT)
        kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "max_completion_tokens": max_completion_tokens or self.config.max_output_tokens,
            "timeout": api_timeout,
        }
        if temperature is not None and _model_supports_temperature(model_name):
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
        provider: str | None = None,
    ) -> str:
        model_name = model or self.config.name
        resolved_provider = _resolve_provider(provider or self.config.provider, model_name)
        if resolved_provider == "openrouter":
            return self.chat(
                messages,
                max_completion_tokens=max_output_tokens,
                model=model_name,
                temperature=temperature,
                timeout=timeout,
                provider="openrouter",
            )
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
        if temperature is not None and _model_supports_temperature(model_name):
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
        if getattr(response, "status", "") == "incomplete":
            LOG.warning(
                "responses incomplete model=%s details=%s usage=%s",
                model_name,
                getattr(response, "incomplete_details", None),
                getattr(response, "usage", None),
            )
        content = (response.output_text or "").strip()
        if not content:
            LOG.warning(
                "responses returned empty text model=%s usage=%s",
                kwargs["model"],
                getattr(response, "usage", None),
            )
        return content

    def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_handlers: dict[str, Any],
        max_output_tokens: int | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
        verbosity: str | None = None,
        prompt_cache_key: str | None = None,
        prompt_cache_retention: str | None = None,
        provider: str | None = None,
        max_tool_rounds: int = 4,
    ) -> str:
        model_name = model or self.config.name
        resolved_provider = _resolve_provider(provider or self.config.provider, model_name)
        if resolved_provider == "openrouter":
            return self._openrouter_chat_with_tools(
                messages,
                tools,
                tool_handlers,
                model_name,
                max_tokens=max_output_tokens or self.config.max_output_tokens,
                max_tool_rounds=max_tool_rounds,
            )
        if not tools:
            return self.chat(
                messages,
                max_completion_tokens=max_output_tokens,
                model=model_name,
                temperature=self.config.temperature if _model_supports_temperature(model_name) else None,
                prompt_cache_key=prompt_cache_key,
                prompt_cache_retention=prompt_cache_retention,
                provider=resolved_provider,
            )

        instructions = "\n\n".join(str(item["content"]) for item in messages if item.get("role") == "system")
        input_items: list[Any] = [
            {"role": item["role"], "content": item["content"]}
            for item in messages
            if item.get("role") in {"user", "assistant"}
        ]

        try:
            retention = prompt_cache_retention or _default_prompt_cache_retention(model_name)
            tool_rounds = max(1, min(max_tool_rounds, 12))
            for round_index in range(tool_rounds):
                kwargs: dict[str, Any] = {
                    "model": model_name,
                    "instructions": instructions,
                    "input": input_items,
                    "tools": tools,
                    "tool_choice": "auto",
                    "parallel_tool_calls": False,
                    "max_output_tokens": max_output_tokens or self.config.max_output_tokens,
                    "timeout": RESPONSES_TIMEOUT,
                }
                if _model_supports_temperature(model_name):
                    kwargs["temperature"] = self.config.temperature
                effort = (reasoning_effort or self.config.reasoning_effort or "").strip().lower()
                if effort and effort not in {"none", "off", "false", "0"}:
                    kwargs["reasoning"] = {"effort": effort}
                text_verbosity = (verbosity or self.config.verbosity or "").strip().lower()
                if text_verbosity:
                    kwargs["text"] = {"verbosity": text_verbosity}
                if prompt_cache_key:
                    kwargs["prompt_cache_key"] = prompt_cache_key
                if retention:
                    kwargs["prompt_cache_retention"] = retention
                LOG.info(
                    "llm_tool_request api=responses model=%s round=%s/%s input_items=%s tools=%s max_output_tokens=%s",
                    model_name,
                    round_index + 1,
                    tool_rounds,
                    len(input_items),
                    [tool.get("name", "") for tool in tools],
                    kwargs["max_output_tokens"],
                )
                response = _openai_call_with_retry(
                    "responses.create",
                    RESPONSES_TIMEOUT + 2.0,
                    self.client.responses.create,
                    **kwargs,
                )
                LOG.info(
                    "llm_tool_response api=responses model=%s round=%s response_id=%s status=%s output_items=%s",
                    model_name,
                    round_index + 1,
                    getattr(response, "id", ""),
                    getattr(response, "status", ""),
                    len(list(response.output or [])),
                )
                _log_prompt_cache_usage("responses.create", model_name, getattr(response, "usage", None))
                output = list(response.output or [])
                input_items.extend(output)
                tool_calls = [item for item in output if getattr(item, "type", "") == "function_call"]
                if not tool_calls:
                    return (response.output_text or "").strip()

                for call in tool_calls:
                    LOG.info(
                        "llm_tool_call api=responses model=%s round=%s name=%s call_id=%s args=%s",
                        model_name,
                        round_index + 1,
                        call.name,
                        call.call_id,
                        _compact_json(call.arguments),
                    )
                    handler = tool_handlers.get(call.name)
                    if handler is None:
                        result = {"ok": False, "error": f"unknown tool: {call.name}"}
                    else:
                        try:
                            args = json.loads(call.arguments or "{}")
                            result = handler(**args)
                        except Exception as exc:
                            result = {"ok": False, "error": str(exc)}
                    LOG.info(
                        "llm_tool_result api=responses model=%s round=%s name=%s call_id=%s result=%s",
                        model_name,
                        round_index + 1,
                        call.name,
                        call.call_id,
                        _compact_json(result),
                    )
                    if isinstance(result, dict) and result.get("__terminal_response__"):
                        return str(result.get("text", "")).strip()
                    input_items.append(
                        {
                            "type": "function_call_output",
                            "call_id": call.call_id,
                            "output": json.dumps(result, ensure_ascii=False),
                        }
                    )
            LOG.warning("llm_tool_budget_exhausted api=responses model=%s rounds=%s forcing_final_answer", model_name, tool_rounds)
            return self._responses_final_from_items(
                model_name,
                instructions,
                input_items,
                max_output_tokens=max_output_tokens or self.config.max_output_tokens,
                reasoning_effort=reasoning_effort,
                verbosity=verbosity,
                prompt_cache_key=prompt_cache_key,
                prompt_cache_retention=prompt_cache_retention,
            )
        except Exception as exc:
            LOG.warning("responses tool call failed, falling back to chat completions: %s", exc)
            if len(input_items) > len([item for item in messages if item.get("role") in {"user", "assistant"}]):
                try:
                    return self._responses_final_from_items(
                        model_name,
                        instructions,
                        input_items,
                        max_output_tokens=max_output_tokens or self.config.max_output_tokens,
                        reasoning_effort=reasoning_effort,
                        verbosity=verbosity,
                        prompt_cache_key=prompt_cache_key,
                        prompt_cache_retention=prompt_cache_retention,
                    )
                except Exception as final_exc:
                    LOG.warning("responses forced final failed after tool error: %s", final_exc)
                    rendered = _render_tool_outputs(input_items)
                    if rendered:
                        return rendered
            return self.chat(
                messages,
                model=model_name,
                temperature=self.config.temperature if _model_supports_temperature(model_name) else None,
                prompt_cache_key=prompt_cache_key,
                prompt_cache_retention=prompt_cache_retention,
                provider=resolved_provider,
            )

    def _responses_final_from_items(
        self,
        model_name: str,
        instructions: str,
        input_items: list[Any],
        *,
        max_output_tokens: int,
        reasoning_effort: str | None = None,
        verbosity: str | None = None,
        prompt_cache_key: str | None = None,
        prompt_cache_retention: str | None = None,
    ) -> str:
        final_input = list(input_items)
        final_input.append(
            {
                "role": "user",
                "content": (
                    "Tool budget is exhausted. Produce the final answer now using the tool results already available. "
                    "Do not call any more tools. If evidence is incomplete, say what is incomplete and give the best concise conclusion."
                ),
            }
        )
        kwargs: dict[str, Any] = {
            "model": model_name,
            "instructions": instructions,
            "input": final_input,
            "max_output_tokens": max_output_tokens,
            "timeout": RESPONSES_TIMEOUT,
        }
        effort = (reasoning_effort or self.config.reasoning_effort or "").strip().lower()
        if effort and effort not in {"none", "off", "false", "0"}:
            kwargs["reasoning"] = {"effort": effort}
        text_verbosity = (verbosity or self.config.verbosity or "").strip().lower()
        if text_verbosity:
            kwargs["text"] = {"verbosity": text_verbosity}
        if prompt_cache_key:
            kwargs["prompt_cache_key"] = prompt_cache_key
        retention = prompt_cache_retention or _default_prompt_cache_retention(model_name)
        if retention:
            kwargs["prompt_cache_retention"] = retention
        LOG.info("llm_tool_forced_final api=responses model=%s input_items=%s max_output_tokens=%s", model_name, len(final_input), max_output_tokens)
        response = _openai_call_with_retry("responses.final", RESPONSES_TIMEOUT + 2.0, self.client.responses.create, **kwargs)
        _log_prompt_cache_usage("responses.final", model_name, getattr(response, "usage", None))
        return (response.output_text or "").strip()

    def _openrouter_chat(
        self,
        messages: list[dict[str, Any]],
        model_name: str,
        *,
        max_tokens: int,
        temperature: float | None = None,
        timeout: float | None = None,
    ) -> str:
        if self.openrouter_client is None:
            raise RuntimeError("OPENROUTER_API_KEY is not configured")
        api_timeout = float(timeout or OPENROUTER_TIMEOUT)
        kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "max_tokens": max_tokens,
            "timeout": api_timeout,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        response = _call_with_hard_timeout(
            "openrouter.chat.completions",
            api_timeout + 2.0,
            self.openrouter_client.chat.completions.create,
            **kwargs,
        )
        _log_prompt_cache_usage("openrouter.chat.completions", model_name, getattr(response, "usage", None))
        choice = response.choices[0]
        content = (choice.message.content or "").strip()
        if not content:
            LOG.warning(
                "openrouter chat returned empty content model=%s finish_reason=%s usage=%s",
                model_name,
                getattr(choice, "finish_reason", None),
                getattr(response, "usage", None),
            )
        return content

    def _openrouter_chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_handlers: dict[str, Any],
        model_name: str,
        *,
        max_tokens: int,
        max_tool_rounds: int = 4,
    ) -> str:
        if self.openrouter_client is None:
            raise RuntimeError("OPENROUTER_API_KEY is not configured")
        chat_messages: list[dict[str, Any]] = [{"role": item["role"], "content": item["content"]} for item in messages]
        chat_tools = [_responses_tool_to_chat_tool(tool) for tool in tools]
        tool_rounds = max(1, min(max_tool_rounds, 12))
        for round_index in range(tool_rounds):
            kwargs: dict[str, Any] = {
                "model": model_name,
                "messages": chat_messages,
                "tools": chat_tools,
                "tool_choice": "auto",
                "parallel_tool_calls": False,
                "max_tokens": max_tokens,
                "timeout": OPENROUTER_TIMEOUT,
            }
            if _model_supports_temperature(model_name):
                kwargs["temperature"] = self.config.temperature
            LOG.info(
                "llm_tool_request api=openrouter model=%s round=%s/%s messages=%s tools=%s max_tokens=%s",
                model_name,
                round_index + 1,
                tool_rounds,
                len(chat_messages),
                [tool.get("function", {}).get("name", "") for tool in chat_tools],
                max_tokens,
            )
            response = _call_with_hard_timeout(
                "openrouter.chat.completions",
                OPENROUTER_TIMEOUT + 5.0,
                self.openrouter_client.chat.completions.create,
                **kwargs,
            )
            LOG.info(
                "llm_tool_response api=openrouter model=%s round=%s finish_reason=%s",
                model_name,
                round_index + 1,
                getattr(response.choices[0], "finish_reason", None) if getattr(response, "choices", None) else None,
            )
            _log_prompt_cache_usage("openrouter.chat.completions", model_name, getattr(response, "usage", None))
            message = response.choices[0].message
            tool_calls = list(getattr(message, "tool_calls", None) or [])
            if not tool_calls:
                return (message.content or "").strip()
            chat_messages.append(
                {
                    "role": "assistant",
                    "content": message.content or "",
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.function.name,
                                "arguments": call.function.arguments or "{}",
                            },
                        }
                        for call in tool_calls
                    ],
                }
            )
            for call in tool_calls:
                LOG.info(
                    "llm_tool_call api=openrouter model=%s round=%s name=%s call_id=%s args=%s",
                    model_name,
                    round_index + 1,
                    call.function.name,
                    call.id,
                    _compact_json(call.function.arguments),
                )
                handler = tool_handlers.get(call.function.name)
                if handler is None:
                    result = {"ok": False, "error": f"unknown tool: {call.function.name}"}
                else:
                    try:
                        args = json.loads(call.function.arguments or "{}")
                        result = handler(**args)
                    except Exception as exc:
                        result = {"ok": False, "error": str(exc)}
                LOG.info(
                    "llm_tool_result api=openrouter model=%s round=%s name=%s call_id=%s result=%s",
                    model_name,
                    round_index + 1,
                    call.function.name,
                    call.id,
                    _compact_json(result),
                )
                if isinstance(result, dict) and result.get("__terminal_response__"):
                    return str(result.get("text", "")).strip()
                chat_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
        LOG.warning("llm_tool_budget_exhausted api=openrouter model=%s rounds=%s forcing_final_answer", model_name, tool_rounds)
        chat_messages.append(
            {
                "role": "user",
                "content": (
                    "Tool budget is exhausted. Produce the final answer now using the tool results already available. "
                    "Do not call any more tools."
                ),
            }
        )
        return self._openrouter_chat(chat_messages, model_name, max_tokens=max_tokens)

    def analyze_image(self, image_path: Path, prompt: str) -> str:
        if self.config.vision_provider == "gemini":
            try:
                return self._analyze_image_gemini(image_path, prompt)
            except Exception as exc:
                LOG.warning("gemini vision failed, falling back to openai vision: %s", exc)
        return self._analyze_image_openai(image_path, prompt)

    def _analyze_image_openai(self, image_path: Path, prompt: str) -> str:
        from .tool_vision import image_to_data_url

        kwargs: dict[str, Any] = {
            "model": self.config.vision_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_to_data_url(image_path)}},
                    ],
                }
            ],
            "max_completion_tokens": min(self.config.max_output_tokens, 600),
        }
        if _model_supports_temperature(self.config.vision_model):
            kwargs["temperature"] = 0.2
        response = self.client.chat.completions.create(**kwargs)
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

def _california_time_context() -> str:
    now = datetime.now(_california_tz())
    return f"California time is {now.strftime('%Y-%m-%d %H:%M:%S %Z')} (ISO: {now.isoformat()})"

def _california_tz() -> timezone:
    try:
        return ZoneInfo("America/Los_Angeles")
    except Exception:
        return timezone(timedelta(hours=-7), "America/Los_Angeles")

def _compact_json(value: Any, limit: int = 900) -> str:
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            text = str(value)
    text = " ".join(text.split())
    if len(text) > limit:
        return text[:limit].rstrip() + "..."
    return text

def _response_url_citations(output_items: list[Any]) -> list[dict[str, str]]:
    citations: list[dict[str, str]] = []
    for item in output_items:
        if getattr(item, "type", "") != "message":
            continue
        for content in list(getattr(item, "content", None) or []):
            for annotation in list(getattr(content, "annotations", None) or []):
                if getattr(annotation, "type", "") != "url_citation":
                    continue
                citations.append(
                    {
                        "url": str(getattr(annotation, "url", "") or ""),
                        "title": str(getattr(annotation, "title", "") or ""),
                    }
                )
    return citations

def _resolve_provider(provider: str | None, model: str) -> str:
    value = (provider or "auto").strip().lower()
    if value in {"openai", "openrouter"}:
        return value
    model_name = (model or "").strip().lower()
    if "/" in model_name:
        return "openrouter"
    if model_name.startswith(("gpt-", "o1", "o3", "o4")):
        return "openai"
    return "openrouter"

def _responses_tool_to_chat_tool(tool: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.get("name", ""),
            "description": tool.get("description", ""),
            "parameters": tool.get("parameters", {"type": "object", "properties": {}}),
        },
    }

def _model_supports_temperature(model: str) -> bool:
    model_name = (model or "").lower()
    if model_name.startswith("gpt-5") or model_name.startswith("o1") or model_name.startswith("o3") or model_name.startswith("o4"):
        return False
    return True

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
