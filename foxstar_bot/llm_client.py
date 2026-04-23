from __future__ import annotations

from pathlib import Path

import base64

import json

import logging

import mimetypes

import re

import time

from datetime import datetime, timedelta, timezone

from queue import Empty, Queue

from threading import Thread

from typing import Any

from urllib.parse import quote

from zoneinfo import ZoneInfo

from .config import ModelConfig

REQUEST_TIMEOUT = 60.0

REPLY_GATE_TIMEOUT = 6.0

RESPONSES_TIMEOUT = 45.0

OPENROUTER_TIMEOUT = 55.0

LOG = logging.getLogger(__name__)

TERMINAL_REJECT_TOOL_NAME = "_drop_reply_internal"

TOOL_NAME_ALIASES = {
    "reject_response": TERMINAL_REJECT_TOOL_NAME,
    TERMINAL_REJECT_TOOL_NAME: TERMINAL_REJECT_TOOL_NAME,
    "update_memory": "update_memory",
    "web_research": "web_research",
    "fetch_url": "fetch_url",
    "analyze_recent_image": "analyze_recent_image",
    "run_python_code": "run_python_code",
}

INTERPRETABLE_PLAINTEXT_TOOLS = {TERMINAL_REJECT_TOOL_NAME}

class LLMClient:
    def __init__(
        self,
        api_key: str,
        model_config: ModelConfig,
        gemini_api_key: str = "",
        openrouter_api_key: str = "",
        sambanova_api_key: str = "",
        fireworks_api_key: str = "",
    ) -> None:
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY 未配置")
        try:
            from openai import OpenAI
            import httpx
        except Exception as exc:
            raise RuntimeError("需要安装 openai Python SDK") from exc
        timeout = httpx.Timeout(REQUEST_TIMEOUT, connect=10.0, read=55.0, write=20.0, pool=10.0)
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
        self.sambanova_client = (
            OpenAI(
                api_key=sambanova_api_key,
                base_url="https://api.sambanova.ai/v1",
                timeout=timeout,
                max_retries=0,
            )
            if sambanova_api_key
            else None
        )
        self.fireworks_client = (
            OpenAI(
                api_key=fireworks_api_key,
                base_url="https://api.fireworks.ai/inference/v1",
                timeout=timeout,
                max_retries=0,
            )
            if fireworks_api_key
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
        model_name = _canonicalize_model_name(model or self.config.name)
        resolved_provider = _resolve_provider(provider or self.config.provider, model_name)
        if resolved_provider == "openrouter":
            return self._openrouter_chat(
                messages,
                model_name,
                max_tokens=max_completion_tokens or self.config.max_output_tokens,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
                timeout=timeout,
            )
        if resolved_provider == "fireworks":
            return self._fireworks_chat(
                messages,
                model_name,
                max_tokens=max_completion_tokens or self.config.max_output_tokens,
                temperature=temperature,
                timeout=timeout,
            )
        if resolved_provider == "sambanova":
            return self._sambanova_chat(
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
        openai_effort = _normalize_reasoning_effort(reasoning_effort)
        if openai_effort:
            kwargs["reasoning_effort"] = openai_effort
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
        model_name = _canonicalize_model_name(model or self.config.name)
        resolved_provider = _resolve_provider(provider or self.config.provider, model_name)
        if resolved_provider == "openrouter":
            return self.chat(
                messages,
                max_completion_tokens=max_output_tokens,
                model=model_name,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
                timeout=timeout,
                provider="openrouter",
            )
        if resolved_provider == "fireworks":
            return self.chat(
                messages,
                max_completion_tokens=max_output_tokens,
                model=model_name,
                temperature=temperature,
                timeout=timeout,
                provider="fireworks",
            )
        if resolved_provider == "sambanova":
            return self.chat(
                messages,
                max_completion_tokens=max_output_tokens,
                model=model_name,
                temperature=temperature,
                timeout=timeout,
                provider="sambanova",
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
        openai_effort = _normalize_reasoning_effort(reasoning_effort)
        if openai_effort:
            kwargs["reasoning"] = {"effort": openai_effort}
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

    def web_search(
        self,
        query: str,
        *,
        model: str = "gpt-5",
        reasoning_effort: str = "low",
        max_output_tokens: int = 6000,
        timeout: float = 55.0,
    ) -> str:
        search_query = " ".join((query or "").split()).strip()
        if not search_query:
            raise ValueError("web search query is empty")
        instructions = (
            "You are a fast web search subagent for a WeChat group assistant. "
            f"Current realtime context: {_california_time_context()}. "
            "Use web_search to investigate the query, open/read relevant pages when needed, "
            "then return a compact Chinese research brief with source names and URLs. "
            "Do not run deep research; finish within a small number of searches/pages. "
            "For time-sensitive queries, prioritize sources from today, the last 7 days, and the current year before older background. "
            "If the user names a specific source, publication, paywalled outlet, or report, explicitly search for that source first. "
            "Do not silently replace a named source with weaker reprints; if the original source is unavailable, say so and label reprints as secondary. "
            "Separate verified facts from rumors, uncertainty, and source conflicts. "
            "Include the most important URLs inline, but keep the final brief concise enough to be passed to another model."
        )
        kwargs: dict[str, Any] = {
            "model": model,
            "instructions": instructions,
            "input": search_query,
            "tools": [{"type": "web_search"}],
            "max_output_tokens": max(1200, min(int(max_output_tokens or 6000), 10000)),
            "timeout": timeout,
        }
        effort = (reasoning_effort or "").strip().lower()
        if effort and effort not in {"none", "off", "false", "0"}:
            kwargs["reasoning"] = {"effort": effort}
        LOG.info(
            "openai_web_search request model=%s reasoning=%s max_output_tokens=%s query=%r",
            model,
            effort or "default",
            kwargs["max_output_tokens"],
            search_query,
        )
        response = _openai_call_with_retry("responses.web_search", timeout + 5.0, self.client.responses.create, **kwargs)
        if _response_incomplete_reason(response) == "max_output_tokens" and kwargs["max_output_tokens"] < 10000:
            LOG.warning(
                "openai_web_search incomplete retry model=%s response_id=%s old_max_output_tokens=%s",
                model,
                getattr(response, "id", ""),
                kwargs["max_output_tokens"],
            )
            retry_kwargs = dict(kwargs)
            retry_kwargs["max_output_tokens"] = 10000
            retry_kwargs["input"] = (
                f"{search_query}\n\n"
                "The previous web_search report was cut off. Search again if needed, but produce a complete compact brief. "
                "Prioritize the original/named source, newest information, and at most 8 high-quality sources. "
                "Do not write a long background article."
            )
            try:
                response = _openai_call_with_retry(
                    "responses.web_search.retry",
                    timeout + 25.0,
                    self.client.responses.create,
                    **retry_kwargs,
                )
            except Exception as retry_exc:
                LOG.warning(
                    "openai_web_search retry failed; keeping first response model=%s response_id=%s reason=%s",
                    model,
                    getattr(response, "id", ""),
                    retry_exc,
                )
        output_items = list(getattr(response, "output", None) or [])
        LOG.info(
            "openai_web_search response model=%s response_id=%s status=%s incomplete=%s output_items=%s chars=%s",
            model,
            getattr(response, "id", ""),
            getattr(response, "status", ""),
            getattr(response, "incomplete_details", None),
            len(output_items),
            len(getattr(response, "output_text", "") or ""),
        )
        _log_prompt_cache_usage("responses.web_search", model, getattr(response, "usage", None))
        for item in output_items:
            item_type = getattr(item, "type", "")
            if item_type == "web_search_call":
                action = getattr(item, "action", None)
                LOG.info(
                    "openai_web_search tool_call id=%s status=%s action=%s",
                    getattr(item, "id", ""),
                    getattr(item, "status", ""),
                    _compact_json(action),
                )
        citations = _response_url_citations(output_items)
        if citations:
            LOG.info("openai_web_search citations count=%s urls=%s", len(citations), [item.get("url", "") for item in citations[:8]])
        else:
            LOG.warning("openai_web_search citations missing response_id=%s", getattr(response, "id", ""))
        text = (getattr(response, "output_text", "") or "").strip()
        if not text:
            raise RuntimeError("OpenAI web_search returned empty text")
        return text

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
        model_name = _canonicalize_model_name(model or self.config.name)
        resolved_provider = _resolve_provider(provider or self.config.provider, model_name)
        if resolved_provider == "openrouter":
            return self._openrouter_chat_with_tools(
                messages,
                tools,
                tool_handlers,
                model_name,
                max_tokens=max_output_tokens or self.config.max_output_tokens,
                reasoning_effort=reasoning_effort,
                max_tool_rounds=max_tool_rounds,
            )
        if resolved_provider == "fireworks":
            return self._fireworks_chat_with_tools(
                messages,
                tools,
                tool_handlers,
                model_name,
                max_tokens=max_output_tokens or self.config.max_output_tokens,
                max_tool_rounds=max_tool_rounds,
            )
        if resolved_provider == "sambanova":
            return self._sambanova_chat_with_tools(
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
                reasoning_effort=reasoning_effort,
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
                effort = _normalize_reasoning_effort(reasoning_effort or self.config.reasoning_effort)
                if effort:
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
                        LOG.warning("responses tool outputs suppressed from chat fallback: %s", rendered)
                        return ""
            return self.chat(
                messages,
                model=model_name,
                temperature=self.config.temperature if _model_supports_temperature(model_name) else None,
                reasoning_effort=reasoning_effort,
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
        effort = _normalize_reasoning_effort(reasoning_effort or self.config.reasoning_effort)
        if effort:
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
        reasoning_effort: str | None = None,
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
        extra_body = _openrouter_reasoning_extra_body(model_name, reasoning_effort or self.config.reasoning_effort)
        if extra_body:
            kwargs["extra_body"] = extra_body
            LOG.info(
                "reasoning_adapter api=openrouter model=%s requested=%s payload=%s",
                model_name,
                reasoning_effort or self.config.reasoning_effort,
                _compact_json(extra_body),
            )
        response = _call_openrouter_chat_completion(
            "openrouter.chat.completions",
            api_timeout + 2.0,
            self.openrouter_client.chat.completions.create,
            kwargs,
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

    def _fireworks_chat(
        self,
        messages: list[dict[str, Any]],
        model_name: str,
        *,
        max_tokens: int,
        temperature: float | None = None,
        timeout: float | None = None,
    ) -> str:
        if self.fireworks_client is None:
            raise RuntimeError("FIREWORKS_API_KEY is not configured")
        api_timeout = float(timeout or OPENROUTER_TIMEOUT)
        kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "max_tokens": max_tokens,
            "timeout": api_timeout,
            "extra_body": {"thinking": {"type": "enabled", "budget_tokens": 2048}},
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        response = _call_with_hard_timeout(
            "fireworks.chat.completions",
            api_timeout + 2.0,
            self.fireworks_client.chat.completions.create,
            **kwargs,
        )
        _log_prompt_cache_usage("fireworks.chat.completions", model_name, getattr(response, "usage", None))
        choice = response.choices[0]
        content = (choice.message.content or "").strip()
        if not content:
            LOG.warning(
                "fireworks chat returned empty content model=%s finish_reason=%s usage=%s",
                model_name,
                getattr(choice, "finish_reason", None),
                getattr(response, "usage", None),
            )
        return content

    def _sambanova_chat(
        self,
        messages: list[dict[str, Any]],
        model_name: str,
        *,
        max_tokens: int,
        temperature: float | None = None,
        timeout: float | None = None,
    ) -> str:
        if self.sambanova_client is None:
            raise RuntimeError("SAMBA_NOVA_KEY is not configured")
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
            "sambanova.chat.completions",
            api_timeout + 2.0,
            self.sambanova_client.chat.completions.create,
            **kwargs,
        )
        _log_prompt_cache_usage("sambanova.chat.completions", model_name, getattr(response, "usage", None))
        choice = response.choices[0]
        content = (choice.message.content or "").strip()
        if not content:
            LOG.warning(
                "sambanova chat returned empty content model=%s finish_reason=%s usage=%s",
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
        reasoning_effort: str | None = None,
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
            extra_body = _openrouter_reasoning_extra_body(model_name, reasoning_effort or self.config.reasoning_effort)
            if extra_body:
                kwargs["extra_body"] = extra_body
                LOG.info(
                    "reasoning_adapter api=openrouter model=%s requested=%s payload=%s",
                    model_name,
                    reasoning_effort or self.config.reasoning_effort,
                    _compact_json(extra_body),
                )
            LOG.info(
                "llm_tool_request api=openrouter model=%s round=%s/%s messages=%s tools=%s max_tokens=%s",
                model_name,
                round_index + 1,
                tool_rounds,
                len(chat_messages),
                [tool.get("function", {}).get("name", "") for tool in chat_tools],
                max_tokens,
            )
            response = _call_openrouter_chat_completion(
                "openrouter.chat.completions",
                OPENROUTER_TIMEOUT + 5.0,
                self.openrouter_client.chat.completions.create,
                kwargs,
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
                content = (message.content or "").strip()
                pseudo_result = _handle_plaintext_tool_call(content, tool_handlers)
                if pseudo_result is not None:
                    LOG.warning(
                        "llm_plaintext_tool_call api=openrouter model=%s round=%s result=%s",
                        model_name,
                        round_index + 1,
                        _compact_json(pseudo_result),
                    )
                    if isinstance(pseudo_result, dict) and pseudo_result.get("__terminal_response__"):
                        return str(pseudo_result.get("text", "")).strip()
                    return ""
                return content
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
        return self._openrouter_chat(
            chat_messages,
            model_name,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
        )

    def _fireworks_chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_handlers: dict[str, Any],
        model_name: str,
        *,
        max_tokens: int,
        max_tool_rounds: int = 4,
    ) -> str:
        if self.fireworks_client is None:
            raise RuntimeError("FIREWORKS_API_KEY is not configured")
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
                "extra_body": {"thinking": {"type": "enabled", "budget_tokens": 2048}},
            }
            if _model_supports_temperature(model_name):
                kwargs["temperature"] = self.config.temperature
            LOG.info(
                "llm_tool_request api=fireworks model=%s round=%s/%s messages=%s tools=%s max_tokens=%s",
                model_name,
                round_index + 1,
                tool_rounds,
                len(chat_messages),
                [tool.get("function", {}).get("name", "") for tool in chat_tools],
                max_tokens,
            )
            response = _call_with_hard_timeout(
                "fireworks.chat.completions",
                OPENROUTER_TIMEOUT + 5.0,
                self.fireworks_client.chat.completions.create,
                **kwargs,
            )
            LOG.info(
                "llm_tool_response api=fireworks model=%s round=%s finish_reason=%s",
                model_name,
                round_index + 1,
                getattr(response.choices[0], "finish_reason", None) if getattr(response, "choices", None) else None,
            )
            _log_prompt_cache_usage("fireworks.chat.completions", model_name, getattr(response, "usage", None))
            message = response.choices[0].message
            tool_calls = list(getattr(message, "tool_calls", None) or [])
            if not tool_calls:
                content = (message.content or "").strip()
                pseudo_result = _handle_plaintext_tool_call(content, tool_handlers)
                if pseudo_result is not None:
                    LOG.warning(
                        "llm_plaintext_tool_call api=fireworks model=%s round=%s result=%s",
                        model_name,
                        round_index + 1,
                        _compact_json(pseudo_result),
                    )
                    if isinstance(pseudo_result, dict) and pseudo_result.get("__terminal_response__"):
                        return str(pseudo_result.get("text", "")).strip()
                    return ""
                return content
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
                    "llm_tool_call api=fireworks model=%s round=%s name=%s call_id=%s args=%s",
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
                    "llm_tool_result api=fireworks model=%s round=%s name=%s call_id=%s result=%s",
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
        LOG.warning("llm_tool_budget_exhausted api=fireworks model=%s rounds=%s", model_name, tool_rounds)
        return self._fireworks_chat(chat_messages, model_name, max_tokens=max_tokens)

    def _sambanova_chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_handlers: dict[str, Any],
        model_name: str,
        *,
        max_tokens: int,
        max_tool_rounds: int = 4,
    ) -> str:
        if self.sambanova_client is None:
            raise RuntimeError("SAMBA_NOVA_KEY is not configured")
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
                "llm_tool_request api=sambanova model=%s round=%s/%s messages=%s tools=%s max_tokens=%s",
                model_name,
                round_index + 1,
                tool_rounds,
                len(chat_messages),
                [tool.get("function", {}).get("name", "") for tool in chat_tools],
                max_tokens,
            )
            response = _call_with_hard_timeout(
                "sambanova.chat.completions",
                OPENROUTER_TIMEOUT + 5.0,
                self.sambanova_client.chat.completions.create,
                **kwargs,
            )
            LOG.info(
                "llm_tool_response api=sambanova model=%s round=%s finish_reason=%s",
                model_name,
                round_index + 1,
                getattr(response.choices[0], "finish_reason", None) if getattr(response, "choices", None) else None,
            )
            _log_prompt_cache_usage("sambanova.chat.completions", model_name, getattr(response, "usage", None))
            message = response.choices[0].message
            tool_calls = list(getattr(message, "tool_calls", None) or [])
            if not tool_calls:
                content = (message.content or "").strip()
                pseudo_result = _handle_plaintext_tool_call(content, tool_handlers)
                if pseudo_result is not None:
                    LOG.warning(
                        "llm_plaintext_tool_call api=sambanova model=%s round=%s result=%s",
                        model_name,
                        round_index + 1,
                        _compact_json(pseudo_result),
                    )
                    if isinstance(pseudo_result, dict) and pseudo_result.get("__terminal_response__"):
                        return str(pseudo_result.get("text", "")).strip()
                    return ""
                return content
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
                    "llm_tool_call api=sambanova model=%s round=%s name=%s call_id=%s args=%s",
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
                    "llm_tool_result api=sambanova model=%s round=%s name=%s call_id=%s result=%s",
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
        LOG.warning("llm_tool_budget_exhausted api=sambanova model=%s rounds=%s", model_name, tool_rounds)
        return self._sambanova_chat(chat_messages, model_name, max_tokens=max_tokens)

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

def _call_openrouter_chat_completion(label: str, hard_timeout: float, func: Any, kwargs: dict[str, Any]) -> Any:
    try:
        return _call_with_hard_timeout(label, hard_timeout, func, **kwargs)
    except Exception as exc:
        if kwargs.get("extra_body") and _is_unsupported_reasoning_error(exc):
            retry_kwargs = dict(kwargs)
            removed = retry_kwargs.pop("extra_body", None)
            LOG.warning(
                "openrouter reasoning payload rejected; retrying without reasoning model=%s payload=%s reason=%s",
                kwargs.get("model", ""),
                _compact_json(removed),
                exc,
            )
            return _call_with_hard_timeout(label, hard_timeout, func, **retry_kwargs)
        raise

def _is_retryable_openai_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int) and (status_code == 408 or status_code == 409 or status_code == 429 or status_code >= 500):
        return True
    name = exc.__class__.__name__.lower()
    return "timeout" in name or "apierror" in name or "server" in name

def _is_unsupported_reasoning_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int) and status_code not in {400, 422}:
        return False
    text = str(exc).lower()
    if "reasoning" in text or "thinking" in text:
        return any(marker in text for marker in ("unsupported", "unknown", "unrecognized", "invalid", "not support", "does not support"))
    return "extra_body" in text and any(marker in text for marker in ("unsupported", "unknown", "unrecognized", "invalid"))

def _response_incomplete_reason(response: Any) -> str:
    if getattr(response, "status", "") != "incomplete":
        return ""
    details = getattr(response, "incomplete_details", None)
    return str(getattr(details, "reason", "") or "")

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

def _render_tool_outputs(input_items: list[Any], limit: int = 3500) -> str:
    outputs: list[str] = []
    for item in input_items:
        if isinstance(item, dict) and item.get("type") == "function_call_output":
            output = str(item.get("output") or "").strip()
            if output:
                outputs.append(output)
    if not outputs:
        return ""
    text = "\n".join(outputs)
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[:limit].rstrip() + "..."
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
    if value in {"openai", "openrouter", "fireworks", "sambanova"}:
        return value
    model_name = (model or "").strip().lower()
    if model_name.startswith("accounts/fireworks/"):
        return "fireworks"
    if "/" in model_name:
        return "openrouter"
    if model_name.startswith(("gpt-", "o1", "o3", "o4")):
        return "openai"
    return "openrouter"

def _normalize_reasoning_effort(value: str | None, *, preserve_max: bool = False) -> str:
    effort = (value or "").strip().lower()
    if not effort or effort in {"none", "off", "false", "0", "clear", "default"}:
        return ""
    aliases = {
        "minimal": "minimal",
        "min": "minimal",
        "low": "low",
        "medium": "medium",
        "med": "medium",
        "high": "high",
        "xhigh": "max" if preserve_max else "high",
        "max": "max" if preserve_max else "high",
    }
    return aliases.get(effort, effort)

def _openrouter_reasoning_extra_body(model: str, effort: str | None) -> dict[str, Any]:
    normalized = _normalize_reasoning_effort(effort, preserve_max=True)
    if not normalized:
        return {}
    model_name = (model or "").strip().lower()
    if normalized == "minimal":
        normalized = "low"
    payload: dict[str, Any] = {"effort": normalized, "exclude": True}
    if _openrouter_prefers_reasoning_budget(model_name):
        payload = {"max_tokens": _reasoning_budget_for_effort(normalized), "exclude": True}
    return {"reasoning": payload}

def _reply_gate_json_schema() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "reply_gate_decision",
            "schema": {
                "type": "object",
                "properties": {
                    "decision": {"type": "string", "enum": ["REPLY", "PASS"]},
                    "confidence": {"type": "number"},
                    "reason": {"type": "string"},
                    "relevant_signals": {"type": "array", "items": {"type": "string"}},
                    "risk": {"type": "string"},
                },
                "required": ["decision", "confidence", "reason", "relevant_signals", "risk"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    }

def _openrouter_prefers_reasoning_budget(model: str) -> bool:


    if not model.startswith("anthropic/"):
        return False
    if "4.7" in model or "4-7" in model or "4.6" in model or "4-6" in model:
        return False
    return "claude-3.7" in model or "claude-3-7" in model or "claude-sonnet-4.5" in model or "claude-4.5" in model

def _reasoning_budget_for_effort(effort: str) -> int:
    if effort == "low":
        return 1024
    if effort == "medium":
        return 4096
    if effort == "max":
        return 12288
    return 8192

def _responses_tool_to_chat_tool(tool: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.get("name", ""),
            "description": tool.get("description", ""),
            "parameters": tool.get("parameters", {"type": "object", "properties": {}}),
        },
    }

def _handle_plaintext_tool_call(content: str, tool_handlers: dict[str, Any]) -> dict[str, Any] | None:
    text = (content or "").strip()
    if not text:
        return None
    parsed = _parse_plaintext_tool_call(text)
    if parsed is None:
        return None
    name, args = parsed
    if name not in INTERPRETABLE_PLAINTEXT_TOOLS:
        LOG.warning("plaintext pseudo-tool blocked name=%s content=%r", name, text[:300])
        return {"ok": False, "__blocked_plaintext_tool__": True, "name": name}
    handler = tool_handlers.get(name)
    if handler is None:
        return {"ok": False, "error": f"unknown plaintext tool: {name}"}
    try:
        return handler(**args)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

def _parse_plaintext_tool_call(text: str) -> tuple[str, dict[str, Any]] | None:
    value = text.strip()
    fence = re.fullmatch(r"```(?:json|tool_code|python)?\s*([\s\S]*?)\s*```", value, re.IGNORECASE)
    if fence:
        value = fence.group(1).strip()
    for payload in _candidate_json_payloads(value):
        parsed = _parse_tool_call_json(payload)
        if parsed is not None:
            return parsed
    match = re.fullmatch(r"([a-zA-Z_][a-zA-Z0-9_]*)\s*\(([\s\S]*)\)\s*;?", value)
    if not match:
        return None
    name = _canonical_tool_name(match.group(1))
    raw_args = match.group(2).strip()
    if not name:
        return None
    if raw_args.startswith("{") and raw_args.endswith("}"):
        try:
            args = json.loads(raw_args)
        except Exception:
            args = {}
    elif name == TERMINAL_REJECT_TOOL_NAME:
        args = {"reason": raw_args.strip(" \t\r\n'\"")}
    else:
        args = {}
    return name, args if isinstance(args, dict) else {}

def _candidate_json_payloads(text: str) -> list[str]:
    payloads = [text]
    match = re.search(r"(\{[\s\S]*\})", text)
    if match and match.group(1) != text:
        payloads.append(match.group(1))
    return payloads

def _parse_tool_call_json(payload: str) -> tuple[str, dict[str, Any]] | None:
    try:
        data = json.loads(payload)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    name = _canonical_tool_name(str(data.get("name") or data.get("tool") or data.get("function") or "").strip())
    args = data.get("arguments") or data.get("args") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            args = {}
    if not name:
        return None
    return name, args if isinstance(args, dict) else {}

def _canonical_tool_name(name: str) -> str:
    return TOOL_NAME_ALIASES.get((name or "").strip(), "")

def _canonicalize_model_name(model: str) -> str:
    value = (model or "").strip()
    lowered = value.lower()
    if lowered.startswith(("gpt-", "o1", "o3", "o4")):
        return lowered
    return value

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
