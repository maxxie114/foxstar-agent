from __future__ import annotations

from pathlib import Path

import base64

import json

import logging

import mimetypes

import os

import re

import time

from datetime import datetime, timedelta, timezone

from queue import Empty, Queue

from threading import Thread

from typing import Any

from urllib.parse import quote

from zoneinfo import ZoneInfo

import requests

from .config import ModelConfig

REQUEST_TIMEOUT = 300.0

REPLY_GATE_TIMEOUT = 6.0

RESPONSES_TIMEOUT = 300.0

OPENROUTER_TIMEOUT = 300.0

LOG = logging.getLogger(__name__)

TOOL_TRACE_LOG = logging.getLogger("foxstar_bot.tool_trace")

TESTING_MODE_LOG = logging.getLogger("foxstar_bot.testing_mode")

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
        deepseek_api_key: str = "",
        together_api_key: str = "",
        lightning_api_key: str = "",
        minimax_api_key: str = "",
        bedrock_api_key: str = "",
        sambanova_api_key: str = "",
        fireworks_api_key: str = "",
        zai_api_key: str = "",
        zai_base_url: str = "https://api.z.ai/api/paas/v4/",
        telnyx_api_key: str = "",
        telnyx_base_url: str = "https://api.telnyx.com/v2/ai/openai",
        kimi_api_key: str = "",
        kimi_base_url: str = "https://api.moonshot.ai/v1",
        usage_recorder: Any | None = None,
    ) -> None:
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY 未配置")
        try:
            from openai import OpenAI
            import httpx
        except Exception as exc:
            raise RuntimeError("需要安装 openai Python SDK") from exc
        timeout = httpx.Timeout(REQUEST_TIMEOUT, connect=10.0, read=295.0, write=30.0, pool=10.0)
        self._openai_class = OpenAI
        self._httpx_timeout = timeout
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
        self.deepseek_client = (
            OpenAI(
                api_key=deepseek_api_key,
                base_url="https://api.deepseek.com",
                timeout=timeout,
                max_retries=0,
            )
            if deepseek_api_key
            else None
        )
        self.together_client = (
            OpenAI(
                api_key=together_api_key,
                base_url="https://api.together.xyz/v1",
                timeout=timeout,
                max_retries=0,
            )
            if together_api_key
            else None
        )
        self.lightning_client = (
            OpenAI(
                api_key=lightning_api_key,
                base_url="https://lightning.ai/api/v1",
                timeout=timeout,
                max_retries=0,
            )
            if lightning_api_key
            else None
        )
        self.minimax_client = (
            OpenAI(
                api_key=minimax_api_key,
                base_url="https://api.minimax.io/v1",
                timeout=timeout,
                max_retries=0,
            )
            if minimax_api_key
            else None
        )
        self.bedrock_client = bedrock_api_key or None
        self._bedrock_clients: dict[tuple[str, str], Any] = {}
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
        self.zai_client = (
            OpenAI(api_key=zai_api_key, base_url=zai_base_url, timeout=timeout, max_retries=0)
            if zai_api_key
            else None
        )
        self.telnyx_client = (
            OpenAI(api_key=telnyx_api_key, base_url=telnyx_base_url, timeout=timeout, max_retries=0)
            if telnyx_api_key
            else None
        )
        self.kimi_client = (
            OpenAI(api_key=kimi_api_key, base_url=kimi_base_url, timeout=timeout, max_retries=0)
            if kimi_api_key
            else None
        )
        self.config = model_config
        self.gemini_api_key = gemini_api_key
        self.usage_recorder = usage_recorder

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
        usage_context: dict[str, Any] | None = None,
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
                usage_context=usage_context,
            )
        if resolved_provider == "deepseek":
            return self._deepseek_chat(
                messages,
                model_name,
                max_tokens=max_completion_tokens or self.config.max_output_tokens,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
                timeout=timeout,
                usage_context=usage_context,
            )
        if resolved_provider == "together":
            return self._together_chat(
                messages,
                model_name,
                max_tokens=max_completion_tokens or self.config.max_output_tokens,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
                timeout=timeout,
                usage_context=usage_context,
            )
        if resolved_provider == "lightning":
            return self._lightning_chat(
                messages,
                model_name,
                max_tokens=max_completion_tokens or self.config.max_output_tokens,
                temperature=temperature,
                timeout=timeout,
                usage_context=usage_context,
            )
        if resolved_provider == "minimax":
            return self._minimax_chat(
                messages,
                model_name,
                max_tokens=max_completion_tokens or self.config.max_output_tokens,
                temperature=temperature,
                timeout=timeout,
                usage_context=usage_context,
            )
        if resolved_provider == "bedrock":
            return self._bedrock_chat(
                messages,
                model_name,
                max_tokens=max_completion_tokens or self.config.max_output_tokens,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
                verbosity=verbosity,
                timeout=timeout,
                usage_context=usage_context,
            )
        if resolved_provider == "fireworks":
            return self._fireworks_chat(
                messages,
                model_name,
                max_tokens=max_completion_tokens or self.config.max_output_tokens,
                temperature=temperature,
                timeout=timeout,
                usage_context=usage_context,
            )
        if resolved_provider == "sambanova":
            return self._sambanova_chat(
                messages,
                model_name,
                max_tokens=max_completion_tokens or self.config.max_output_tokens,
                temperature=temperature,
                timeout=timeout,
                usage_context=usage_context,
            )
        if resolved_provider in {"zai", "telnyx", "kimi"}:
            return self._provider_compatible_chat(
                resolved_provider,
                messages,
                model_name,
                max_tokens=max_completion_tokens or self.config.max_output_tokens,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
                timeout=timeout,
                usage_context=usage_context,
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
        self._record_usage(usage_context, api="chat.completions", model=model_name, provider="openai", usage=getattr(response, "usage", None))
        choice = response.choices[0]
        _testing_trace_response(
            usage_context=usage_context,
            api="chat.completions",
            provider="openai",
            model=model_name,
            request_messages=messages,
            request_kwargs=kwargs,
            response=response,
            choice=choice,
        )
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
        usage_context: dict[str, Any] | None = None,
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
                usage_context=usage_context,
            )
        if resolved_provider == "deepseek":
            return self.chat(
                messages,
                max_completion_tokens=max_output_tokens,
                model=model_name,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
                timeout=timeout,
                provider="deepseek",
                usage_context=usage_context,
            )
        if resolved_provider == "together":
            return self.chat(
                messages,
                max_completion_tokens=max_output_tokens,
                model=model_name,
                temperature=temperature,
                timeout=timeout,
                provider="together",
                usage_context=usage_context,
            )
        if resolved_provider == "lightning":
            return self.chat(
                messages,
                max_completion_tokens=max_output_tokens,
                model=model_name,
                temperature=temperature,
                timeout=timeout,
                provider="lightning",
                usage_context=usage_context,
            )
        if resolved_provider == "minimax":
            return self.chat(
                messages,
                max_completion_tokens=max_output_tokens,
                model=model_name,
                temperature=temperature,
                timeout=timeout,
                provider="minimax",
                usage_context=usage_context,
            )
        if resolved_provider == "fireworks":
            return self.chat(
                messages,
                max_completion_tokens=max_output_tokens,
                model=model_name,
                temperature=temperature,
                timeout=timeout,
                provider="fireworks",
                usage_context=usage_context,
            )
        if resolved_provider in {"sambanova", "zai", "telnyx", "kimi"}:
            return self.chat(
                messages,
                max_completion_tokens=max_output_tokens,
                model=model_name,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
                timeout=timeout,
                provider=resolved_provider,
                usage_context=usage_context,
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
        self._record_usage(usage_context, api="responses.create", model=model_name, provider="openai", usage=getattr(response, "usage", None))
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

    def reply_gate_json(
        self,
        instructions: str,
        payload: dict[str, Any],
        *,
        model: str | None = None,
        timeout: float = REPLY_GATE_TIMEOUT,
        usage_context: dict[str, Any] | None = None,
    ) -> str:
        model = _canonicalize_model_name(model or self.config.reply_gate_model)
        return self._structured_json_call(
            "reply_gate",
            instructions,
            payload,
            response_format=_reply_gate_json_schema(),
            model=model,
            timeout=float(timeout or REPLY_GATE_TIMEOUT),
            max_tokens=2000,
            usage_context=usage_context,
        )

    def structured_judge_json(
        self,
        instructions: str,
        payload: dict[str, Any],
        *,
        schema: dict[str, Any],
        model: str | None = None,
        timeout: float = REPLY_GATE_TIMEOUT,
        max_tokens: int = 2000,
        usage_context: dict[str, Any] | None = None,
    ) -> str:
        model = _canonicalize_model_name(model or self.config.reply_gate_model)
        return self._structured_json_call(
            "structured_judge",
            instructions,
            payload,
            response_format=schema,
            model=model,
            timeout=float(timeout or REPLY_GATE_TIMEOUT),
            max_tokens=max_tokens,
            usage_context=usage_context,
        )

    def web_search(
        self,
        query: str,
        *,
        model: str = "gpt-5",
        reasoning_effort: str = "low",
        max_output_tokens: int = 6000,
        timeout: float = 55.0,
        usage_context: dict[str, Any] | None = None,
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
        self._record_usage(usage_context, api="responses.web_search", model=model, provider="openai", usage=getattr(response, "usage", None))
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
        max_tool_rounds: int = 5,
        usage_context: dict[str, Any] | None = None,
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
                usage_context=usage_context,
            )
        if resolved_provider == "deepseek":
            return self._deepseek_chat_with_tools(
                messages,
                tools,
                tool_handlers,
                model_name,
                max_tokens=max_output_tokens or self.config.max_output_tokens,
                temperature=self.config.temperature,
                reasoning_effort=reasoning_effort,
                max_tool_rounds=max_tool_rounds,
                usage_context=usage_context,
            )
        if resolved_provider == "together":
            return self._together_chat_with_tools(
                messages,
                tools,
                tool_handlers,
                model_name,
                max_tokens=max_output_tokens or self.config.max_output_tokens,
                reasoning_effort=reasoning_effort,
                max_tool_rounds=max_tool_rounds,
                usage_context=usage_context,
            )
        if resolved_provider == "lightning":
            return self._lightning_chat_with_tools(
                messages,
                tools,
                tool_handlers,
                model_name,
                max_tokens=max_output_tokens or self.config.max_output_tokens,
                max_tool_rounds=max_tool_rounds,
                usage_context=usage_context,
            )
        if resolved_provider == "minimax":
            return self._minimax_chat_with_tools(
                messages,
                tools,
                tool_handlers,
                model_name,
                max_tokens=max_output_tokens or self.config.max_output_tokens,
                max_tool_rounds=max_tool_rounds,
                usage_context=usage_context,
            )
        if resolved_provider == "bedrock":
            return self._bedrock_chat_with_tools(
                messages,
                tools,
                tool_handlers,
                model_name,
                max_output_tokens=max_output_tokens or self.config.max_output_tokens,
                reasoning_effort=reasoning_effort,
                verbosity=verbosity,
                max_tool_rounds=max_tool_rounds,
                usage_context=usage_context,
            )
        if resolved_provider == "fireworks":
            return self._fireworks_chat_with_tools(
                messages,
                tools,
                tool_handlers,
                model_name,
                max_tokens=max_output_tokens or self.config.max_output_tokens,
                max_tool_rounds=max_tool_rounds,
                usage_context=usage_context,
            )
        if resolved_provider == "sambanova":
            return self._sambanova_chat_with_tools(
                messages,
                tools,
                tool_handlers,
                model_name,
                max_tokens=max_output_tokens or self.config.max_output_tokens,
                max_tool_rounds=max_tool_rounds,
                usage_context=usage_context,
            )
        if resolved_provider in {"zai", "telnyx", "kimi"}:
            return self._provider_compatible_chat_with_tools(
                resolved_provider,
                messages,
                tools,
                tool_handlers,
                model_name,
                max_tokens=max_output_tokens or self.config.max_output_tokens,
                reasoning_effort=reasoning_effort,
                max_tool_rounds=max_tool_rounds,
                usage_context=usage_context,
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
                usage_context=usage_context,
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
            failed_tool_signatures: dict[tuple[str, str], int] = {}
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
                self._record_usage(usage_context, api="responses.create", model=model_name, provider="openai", usage=getattr(response, "usage", None))
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
                    _tool_trace(
                        phase="input",
                        api="responses",
                        model=model_name,
                        round_index=round_index + 1,
                        tool_name=call.name,
                        call_id=call.call_id,
                        payload=call.arguments,
                    )
                    handler = tool_handlers.get(call.name)
                    args: dict[str, Any] = {}
                    if handler is None:
                        result = {"ok": False, "error": f"unknown tool: {call.name}"}
                    else:
                        try:
                            args = json.loads(call.arguments or "{}")
                            blocked = _blocked_repeated_failed_tool_call(failed_tool_signatures, call.name, args)
                            if blocked is not None:
                                result = blocked
                            else:
                                result = handler(**args)
                        except Exception as exc:
                            result = {"ok": False, "error": str(exc)}
                    _remember_failed_tool_signature(failed_tool_signatures, call.name, args, result)
                    LOG.info(
                        "llm_tool_result api=responses model=%s round=%s name=%s call_id=%s result=%s",
                        model_name,
                        round_index + 1,
                        call.name,
                        call.call_id,
                        _compact_json(result),
                    )
                    _tool_trace(
                        phase="output",
                        api="responses",
                        model=model_name,
                        round_index=round_index + 1,
                        tool_name=call.name,
                        call_id=call.call_id,
                        payload=result,
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
                        usage_context=usage_context,
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
                usage_context=usage_context,
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
        usage_context: dict[str, Any] | None = None,
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
        self._record_usage(usage_context, api="responses.final", model=model_name, provider="openai", usage=getattr(response, "usage", None))
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
        usage_context: dict[str, Any] | None = None,
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
        self._record_usage(usage_context, api="openrouter.chat.completions", model=model_name, provider="openrouter", usage=getattr(response, "usage", None))
        choice = response.choices[0]
        _testing_trace_response(
            usage_context=usage_context,
            api="openrouter.chat.completions",
            provider="openrouter",
            model=model_name,
            request_messages=messages,
            request_kwargs=kwargs,
            response=response,
            choice=choice,
        )
        content = (choice.message.content or "").strip()
        if not content:
            LOG.warning(
                "openrouter chat returned empty content model=%s finish_reason=%s usage=%s",
                model_name,
                getattr(choice, "finish_reason", None),
                getattr(response, "usage", None),
            )
        return content

    def _deepseek_chat(
        self,
        messages: list[dict[str, Any]],
        model_name: str,
        *,
        max_tokens: int,
        temperature: float | None = None,
        reasoning_effort: str | None = None,
        timeout: float | None = None,
        usage_context: dict[str, Any] | None = None,
    ) -> str:
        if self.deepseek_client is None:
            raise RuntimeError("DEEPSEEK_API_KEY is not configured")
        api_timeout = float(timeout or OPENROUTER_TIMEOUT)
        kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "max_tokens": max_tokens,
            "timeout": api_timeout,
        }
        extra_body = _deepseek_extra_body(reasoning_effort)
        if extra_body:
            kwargs["extra_body"] = extra_body
        thinking_enabled = _deepseek_thinking_enabled(reasoning_effort)
        if temperature is not None and _model_supports_temperature(model_name) and not thinking_enabled:
            kwargs["temperature"] = temperature
        normalized_effort = _normalize_deepseek_reasoning_effort(reasoning_effort)
        if normalized_effort:
            kwargs["reasoning_effort"] = normalized_effort
        response = _call_with_hard_timeout(
            "deepseek.chat.completions",
            api_timeout + 2.0,
            self.deepseek_client.chat.completions.create,
            **kwargs,
        )
        _log_prompt_cache_usage("deepseek.chat.completions", model_name, getattr(response, "usage", None))
        self._record_usage(usage_context, api="deepseek.chat.completions", model=model_name, provider="deepseek", usage=getattr(response, "usage", None))
        choice = response.choices[0]
        _testing_trace_response(
            usage_context=usage_context,
            api="deepseek.chat.completions",
            provider="deepseek",
            model=model_name,
            request_messages=messages,
            request_kwargs=kwargs,
            response=response,
            choice=choice,
        )
        content = (choice.message.content or "").strip()
        if not content:
            LOG.warning(
                "deepseek chat returned empty content model=%s finish_reason=%s usage=%s",
                model_name,
                getattr(choice, "finish_reason", None),
                getattr(response, "usage", None),
            )
        return content

    def _together_chat(
        self,
        messages: list[dict[str, Any]],
        model_name: str,
        *,
        max_tokens: int,
        temperature: float | None = None,
        reasoning_effort: str | None = None,
        timeout: float | None = None,
        usage_context: dict[str, Any] | None = None,
    ) -> str:
        try:
            return self._compatible_chat(
                client=self.together_client,
                provider_name="together",
                messages=messages,
                model_name=model_name,
                max_tokens=max_tokens,
                temperature=temperature,
                extra_create_kwargs=_together_reasoning_kwargs(reasoning_effort or self.config.reasoning_effort),
                timeout=timeout,
                usage_context=usage_context,
            )
        except Exception as exc:
            fallback_model = _together_openrouter_fallback_model(model_name)
            if not _should_fallback_together_error(exc, fallback_model, self.openrouter_client):
                raise
            LOG.warning(
                "together provider error; falling back to openrouter model=%s fallback_model=%s reason=%s",
                model_name,
                fallback_model,
                str(exc),
            )
            return self._openrouter_chat(
                messages,
                fallback_model,
                max_tokens=max_tokens,
                temperature=temperature,
                reasoning_effort=self.config.reasoning_effort,
                timeout=timeout,
                usage_context=usage_context,
            )

    def _lightning_chat(
        self,
        messages: list[dict[str, Any]],
        model_name: str,
        *,
        max_tokens: int,
        temperature: float | None = None,
        timeout: float | None = None,
        usage_context: dict[str, Any] | None = None,
    ) -> str:
        return self._compatible_chat(
            client=self.lightning_client,
            provider_name="lightning",
            messages=messages,
            model_name=model_name,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
            use_content_parts=True,
            usage_context=usage_context,
        )

    def _minimax_chat(
        self,
        messages: list[dict[str, Any]],
        model_name: str,
        *,
        max_tokens: int,
        temperature: float | None = None,
        timeout: float | None = None,
        usage_context: dict[str, Any] | None = None,
    ) -> str:
        return self._compatible_chat(
            client=self.minimax_client,
            provider_name="minimax",
            messages=messages,
            model_name=model_name,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
            max_tokens_field="max_completion_tokens",
            extra_create_kwargs={"extra_body": {"reasoning_split": True}},
            usage_context=usage_context,
        )

    def _bedrock_chat(
        self,
        messages: list[dict[str, Any]],
        model_name: str,
        *,
        max_tokens: int,
        temperature: float | None = None,
        reasoning_effort: str | None = None,
        verbosity: str | None = None,
        timeout: float | None = None,
        usage_context: dict[str, Any] | None = None,
    ) -> str:
        family = _bedrock_model_family(model_name)
        if family == "openai":
            return self._bedrock_openai_chat(
                messages,
                model_name,
                max_output_tokens=max_tokens,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
                verbosity=verbosity,
                timeout=timeout,
                usage_context=usage_context,
            )
        if family == "anthropic":
            return self._bedrock_anthropic_chat(
                messages,
                model_name,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout,
                usage_context=usage_context,
            )
        extra_kwargs = {"extra_body": {"reasoning_split": True}} if model_name.lower().startswith("minimax.") else None
        return self._compatible_chat(
            client=self._bedrock_openai_client(model_name),
            provider_name="bedrock",
            messages=messages,
            model_name=model_name,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
            max_tokens_field="max_completion_tokens",
            extra_create_kwargs=extra_kwargs,
            usage_context=usage_context,
        )

    def _bedrock_chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_handlers: dict[str, Any],
        model_name: str,
        *,
        max_output_tokens: int,
        reasoning_effort: str | None = None,
        verbosity: str | None = None,
        max_tool_rounds: int = 5,
        usage_context: dict[str, Any] | None = None,
    ) -> str:
        family = _bedrock_model_family(model_name)
        if family == "openai":
            return self._bedrock_openai_chat_with_tools(
                messages,
                tools,
                tool_handlers,
                model_name,
                max_output_tokens=max_output_tokens,
                reasoning_effort=reasoning_effort,
                verbosity=verbosity,
                max_tool_rounds=max_tool_rounds,
                usage_context=usage_context,
            )
        if family == "anthropic":
            return self._bedrock_anthropic_chat_with_tools(
                messages,
                tools,
                tool_handlers,
                model_name,
                max_tokens=max_output_tokens,
                max_tool_rounds=max_tool_rounds,
                usage_context=usage_context,
            )
        extra_kwargs = {"extra_body": {"reasoning_split": True}} if model_name.lower().startswith("minimax.") else None
        return self._compatible_chat_with_tools(
            client=self._bedrock_openai_client(model_name),
            provider_name="bedrock",
            messages=messages,
            tools=tools,
            tool_handlers=tool_handlers,
            model_name=model_name,
            max_tokens=max_output_tokens,
            max_tool_rounds=max_tool_rounds,
            max_tokens_field="max_completion_tokens",
            extra_create_kwargs=extra_kwargs,
            usage_context=usage_context,
        )

    def _bedrock_openai_chat(
        self,
        messages: list[dict[str, Any]],
        model_name: str,
        *,
        max_output_tokens: int,
        temperature: float | None = None,
        reasoning_effort: str | None = None,
        verbosity: str | None = None,
        timeout: float | None = None,
        usage_context: dict[str, Any] | None = None,
    ) -> str:
        client = self._bedrock_openai_client(model_name)
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
            "max_output_tokens": max_output_tokens,
            "timeout": api_timeout,
        }
        if temperature is not None and _model_supports_temperature(model_name):
            kwargs["temperature"] = temperature
        effort = _normalize_reasoning_effort(reasoning_effort)
        if effort:
            kwargs["reasoning"] = {"effort": effort}
        text_verbosity = (verbosity or self.config.verbosity or "").strip().lower()
        if text_verbosity:
            kwargs["text"] = {"verbosity": text_verbosity}
        response = _openai_call_with_retry("bedrock.responses.create", api_timeout + 2.0, client.responses.create, **kwargs)
        _log_prompt_cache_usage("bedrock.responses.create", model_name, getattr(response, "usage", None))
        self._record_usage(usage_context, api="bedrock.responses.create", model=model_name, provider="bedrock", usage=getattr(response, "usage", None))
        trace_id = _response_trace_id(response)
        LOG.info(
            "llm_response api=bedrock.responses model=%s trace_id=%s status=%s usage=%s",
            model_name,
            trace_id,
            getattr(response, "status", ""),
            getattr(response, "usage", None),
        )
        content = (response.output_text or "").strip()
        if not content:
            LOG.warning("bedrock responses returned empty text model=%s trace_id=%s", model_name, trace_id)
        return content

    def _bedrock_openai_chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_handlers: dict[str, Any],
        model_name: str,
        *,
        max_output_tokens: int,
        reasoning_effort: str | None = None,
        verbosity: str | None = None,
        max_tool_rounds: int = 5,
        usage_context: dict[str, Any] | None = None,
    ) -> str:
        client = self._bedrock_openai_client(model_name)
        instructions = "\n\n".join(str(item["content"]) for item in messages if item.get("role") == "system")
        input_items: list[Any] = [
            {"role": item["role"], "content": item["content"]}
            for item in messages
            if item.get("role") in {"user", "assistant"}
        ]
        tool_rounds = max(1, min(max_tool_rounds, 12))
        failed_tool_signatures: dict[tuple[str, str], int] = {}
        for round_index in range(tool_rounds):
            kwargs: dict[str, Any] = {
                "model": model_name,
                "instructions": instructions,
                "input": input_items,
                "tools": tools,
                "tool_choice": "auto",
                "parallel_tool_calls": False,
                "max_output_tokens": max_output_tokens,
                "timeout": RESPONSES_TIMEOUT,
            }
            effort = _normalize_reasoning_effort(reasoning_effort or self.config.reasoning_effort)
            if effort:
                kwargs["reasoning"] = {"effort": effort}
            text_verbosity = (verbosity or self.config.verbosity or "").strip().lower()
            if text_verbosity:
                kwargs["text"] = {"verbosity": text_verbosity}
            LOG.info(
                "llm_tool_request api=bedrock.responses model=%s round=%s/%s input_items=%s tools=%s max_output_tokens=%s",
                model_name,
                round_index + 1,
                tool_rounds,
                len(input_items),
                [tool.get("name", "") for tool in tools],
                max_output_tokens,
            )
            response = _openai_call_with_retry("bedrock.responses.create", RESPONSES_TIMEOUT + 2.0, client.responses.create, **kwargs)
            trace_id = _response_trace_id(response)
            LOG.info(
                "llm_tool_response api=bedrock.responses model=%s round=%s trace_id=%s status=%s output_items=%s",
                model_name,
                round_index + 1,
                trace_id,
                getattr(response, "status", ""),
                len(list(response.output or [])),
            )
            _log_prompt_cache_usage("bedrock.responses.create", model_name, getattr(response, "usage", None))
            self._record_usage(usage_context, api="bedrock.responses.create", model=model_name, provider="bedrock", usage=getattr(response, "usage", None))
            output = list(response.output or [])
            input_items.extend(output)
            tool_calls = [item for item in output if getattr(item, "type", "") == "function_call"]
            if not tool_calls:
                return (response.output_text or "").strip()
            for call in tool_calls:
                LOG.info(
                    "llm_tool_call api=bedrock.responses model=%s round=%s trace_id=%s name=%s call_id=%s args=%s",
                    model_name,
                    round_index + 1,
                    trace_id,
                    call.name,
                    call.call_id,
                    _compact_json(call.arguments),
                )
                _tool_trace(
                    phase="input",
                    api="bedrock.responses",
                    model=model_name,
                    round_index=round_index + 1,
                    tool_name=call.name,
                    call_id=call.call_id,
                    payload=call.arguments,
                    trace_id=trace_id,
                )
                handler = tool_handlers.get(call.name)
                args: dict[str, Any] = {}
                if handler is None:
                    result = {"ok": False, "error": f"unknown tool: {call.name}"}
                else:
                    try:
                        args = json.loads(call.arguments or "{}")
                        blocked = _blocked_repeated_failed_tool_call(failed_tool_signatures, call.name, args)
                        if blocked is not None:
                            result = blocked
                        else:
                            result = handler(**args)
                    except Exception as exc:
                        result = {"ok": False, "error": str(exc)}
                _remember_failed_tool_signature(failed_tool_signatures, call.name, args, result)
                LOG.info(
                    "llm_tool_result api=bedrock.responses model=%s round=%s trace_id=%s name=%s call_id=%s result=%s",
                    model_name,
                    round_index + 1,
                    trace_id,
                    call.name,
                    call.call_id,
                    _compact_json(result),
                )
                _tool_trace(
                    phase="output",
                    api="bedrock.responses",
                    model=model_name,
                    round_index=round_index + 1,
                    tool_name=call.name,
                    call_id=call.call_id,
                    payload=result,
                    trace_id=trace_id,
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
        LOG.warning("llm_tool_budget_exhausted api=bedrock.responses model=%s rounds=%s", model_name, tool_rounds)
        return self._bedrock_openai_chat(
            messages,
            model_name,
            max_output_tokens=max_output_tokens,
            reasoning_effort=reasoning_effort,
            verbosity=verbosity,
            usage_context=usage_context,
        )

    def _bedrock_anthropic_chat(
        self,
        messages: list[dict[str, Any]],
        model_name: str,
        *,
        max_tokens: int,
        temperature: float | None = None,
        timeout: float | None = None,
        usage_context: dict[str, Any] | None = None,
    ) -> str:
        system_text, anthropic_messages = _bedrock_anthropic_prompt(messages)
        payload: dict[str, Any] = {
            "model": model_name,
            "max_tokens": max_tokens,
            "messages": anthropic_messages,
        }
        if system_text:
            payload["system"] = system_text
        if temperature is not None and _model_supports_temperature(model_name):
            payload["temperature"] = temperature
        body, trace_id = self._bedrock_anthropic_post(payload, timeout=timeout)
        text = _bedrock_anthropic_text(body)
        LOG.info(
            "llm_response api=bedrock.anthropic model=%s trace_id=%s stop_reason=%s usage=%s",
            model_name,
            trace_id,
            body.get("stop_reason"),
            _compact_json(body.get("usage")),
        )
        self._record_usage(usage_context, api="bedrock.anthropic.messages", model=model_name, provider="bedrock", usage=None)
        return text

    def _bedrock_anthropic_chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_handlers: dict[str, Any],
        model_name: str,
        *,
        max_tokens: int,
        max_tool_rounds: int = 5,
        usage_context: dict[str, Any] | None = None,
    ) -> str:
        system_text, convo = _bedrock_anthropic_prompt(messages)
        anthropic_tools = [_responses_tool_to_anthropic_tool(tool) for tool in tools]
        tool_rounds = max(1, min(max_tool_rounds, 12))
        failed_tool_signatures: dict[tuple[str, str], int] = {}
        for round_index in range(tool_rounds):
            payload: dict[str, Any] = {
                "model": model_name,
                "max_tokens": max_tokens,
                "messages": convo,
                "tools": anthropic_tools,
            }
            if system_text:
                payload["system"] = system_text
            body, trace_id = self._bedrock_anthropic_post(payload, timeout=OPENROUTER_TIMEOUT)
            items = list(body.get("content") or [])
            tool_uses = [item for item in items if item.get("type") == "tool_use"]
            text = _bedrock_anthropic_text(body)
            LOG.info(
                "llm_tool_response api=bedrock.anthropic model=%s round=%s trace_id=%s tool_calls=%s stop_reason=%s content_preview=%r",
                model_name,
                round_index + 1,
                trace_id,
                [item.get("name", "") for item in tool_uses],
                body.get("stop_reason"),
                text[:300],
            )
            self._record_usage(usage_context, api="bedrock.anthropic.messages", model=model_name, provider="bedrock", usage=None)
            if not tool_uses:
                return text
            convo.append({"role": "assistant", "content": items})
            tool_results: list[dict[str, Any]] = []
            for item in tool_uses:
                tool_name = str(item.get("name") or "")
                tool_id = str(item.get("id") or "")
                args = item.get("input") if isinstance(item.get("input"), dict) else {}
                LOG.info(
                    "llm_tool_call api=bedrock.anthropic model=%s round=%s trace_id=%s name=%s call_id=%s args=%s",
                    model_name,
                    round_index + 1,
                    trace_id,
                    tool_name,
                    tool_id,
                    _compact_json(args),
                )
                _tool_trace(
                    phase="input",
                    api="bedrock.anthropic",
                    model=model_name,
                    round_index=round_index + 1,
                    tool_name=tool_name,
                    call_id=tool_id,
                    payload=args,
                    trace_id=trace_id,
                )
                handler = tool_handlers.get(tool_name)
                if handler is None:
                    result = {"ok": False, "error": f"unknown tool: {tool_name}"}
                else:
                    try:
                        blocked = _blocked_repeated_failed_tool_call(failed_tool_signatures, tool_name, args)
                        if blocked is not None:
                            result = blocked
                        else:
                            result = handler(**args)
                    except Exception as exc:
                        result = {"ok": False, "error": str(exc)}
                _remember_failed_tool_signature(failed_tool_signatures, tool_name, args, result)
                LOG.info(
                    "llm_tool_result api=bedrock.anthropic model=%s round=%s trace_id=%s name=%s call_id=%s result=%s",
                    model_name,
                    round_index + 1,
                    trace_id,
                    tool_name,
                    tool_id,
                    _compact_json(result),
                )
                _tool_trace(
                    phase="output",
                    api="bedrock.anthropic",
                    model=model_name,
                    round_index=round_index + 1,
                    tool_name=tool_name,
                    call_id=tool_id,
                    payload=result,
                    trace_id=trace_id,
                )
                if isinstance(result, dict) and result.get("__terminal_response__"):
                    return str(result.get("text", "")).strip()
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
            convo.append({"role": "user", "content": tool_results})
        LOG.warning("llm_tool_budget_exhausted api=bedrock.anthropic model=%s rounds=%s", model_name, tool_rounds)
        return self._bedrock_anthropic_chat(
            messages,
            model_name,
            max_tokens=max_tokens,
            usage_context=usage_context,
        )

    def _bedrock_openai_client(self, model_name: str) -> Any:
        if not self.bedrock_client:
            raise RuntimeError("BEDROCK_API_KEY / BEDROCK_KEY_1 is not configured")
        family = _bedrock_model_family(model_name)
        region = _bedrock_region_for_model(model_name)
        cache_key = (family, region)
        client = self._bedrock_clients.get(cache_key)
        if client is not None:
            return client
        if family == "openai":
            base_url = f"https://bedrock-mantle.{region}.api.aws/openai/v1"
        else:
            base_url = f"https://bedrock-mantle.{region}.api.aws/v1"
        client = self._openai_class(
            api_key=self.bedrock_client,
            base_url=base_url,
            timeout=self._httpx_timeout,
            max_retries=0,
        )
        self._bedrock_clients[cache_key] = client
        return client

    def _bedrock_anthropic_post(self, payload: dict[str, Any], *, timeout: float | None = None) -> tuple[dict[str, Any], str]:
        if not self.bedrock_client:
            raise RuntimeError("BEDROCK_API_KEY / BEDROCK_KEY_1 is not configured")
        model_name = str(payload.get("model") or "")
        region = _bedrock_region_for_model(model_name)
        url = f"https://bedrock-mantle.{region}.api.aws/anthropic/v1/messages"
        response = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {self.bedrock_client}",
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
            },
            json=payload,
            timeout=float(timeout or OPENROUTER_TIMEOUT),
        )
        trace_id = (
            response.headers.get("x-request-id")
            or response.headers.get("x-amzn-requestid")
            or response.headers.get("x-amzn-request-id")
            or ""
        )
        body = response.json()
        if response.status_code >= 400:
            raise RuntimeError(f"Bedrock Anthropic error {response.status_code} trace_id={trace_id} body={_compact_json(body)}")
        if not trace_id:
            trace_id = str(body.get("id") or body.get("request_id") or "")
        return body, trace_id

    def _compatible_chat(
        self,
        *,
        client: Any,
        provider_name: str,
        messages: list[dict[str, Any]],
        model_name: str,
        max_tokens: int,
        temperature: float | None = None,
        timeout: float | None = None,
        use_content_parts: bool = False,
        max_tokens_field: str = "max_tokens",
        extra_create_kwargs: dict[str, Any] | None = None,
        usage_context: dict[str, Any] | None = None,
    ) -> str:
        if client is None:
            raise RuntimeError(f"{provider_name.upper()}_API_KEY is not configured")
        api_timeout = float(timeout or OPENROUTER_TIMEOUT)
        kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": _chat_messages_for_provider(
                messages,
                use_content_parts=use_content_parts,
                provider_name=provider_name,
            ),
            "timeout": api_timeout,
        }
        kwargs[max_tokens_field] = max_tokens
        if temperature is not None and _model_supports_temperature(model_name):
            kwargs["temperature"] = temperature
        if extra_create_kwargs:
            kwargs.update(extra_create_kwargs)
        response = _call_with_hard_timeout(
            f"{provider_name}.chat.completions",
            api_timeout + 2.0,
            client.chat.completions.create,
            **kwargs,
        )
        _log_prompt_cache_usage(f"{provider_name}.chat.completions", model_name, getattr(response, "usage", None))
        self._record_usage(usage_context, api=f"{provider_name}.chat.completions", model=model_name, provider=provider_name, usage=getattr(response, "usage", None))
        trace_id = _response_trace_id(response)
        choice = response.choices[0]
        LOG.info(
            "llm_response api=%s.chat.completions model=%s trace_id=%s finish_reason=%s usage=%s",
            provider_name,
            model_name,
            trace_id,
            getattr(choice, "finish_reason", None),
            getattr(response, "usage", None),
        )
        _testing_trace_response(
            usage_context=usage_context,
            api=f"{provider_name}.chat.completions",
            provider=provider_name,
            model=model_name,
            request_messages=messages,
            request_kwargs=kwargs,
            response=response,
            choice=choice,
        )
        content = _sanitize_provider_content(choice.message.content or "", provider_name=provider_name)
        if not content:
            LOG.warning(
                "%s chat returned empty content model=%s finish_reason=%s usage=%s",
                provider_name,
                model_name,
                getattr(choice, "finish_reason", None),
                getattr(response, "usage", None),
            )
        return content

    def _provider_compatible_chat(
        self,
        provider_name: str,
        messages: list[dict[str, Any]],
        model_name: str,
        *,
        max_tokens: int,
        temperature: float | None = None,
        reasoning_effort: str | None = None,
        timeout: float | None = None,
        usage_context: dict[str, Any] | None = None,
    ) -> str:
        return self._compatible_chat(
            client=self._provider_compatible_client(provider_name),
            provider_name=provider_name,
            messages=messages,
            model_name=model_name,
            max_tokens=max_tokens,
            temperature=None if provider_name == "kimi" else temperature,
            timeout=timeout,
            extra_create_kwargs=_provider_reasoning_kwargs(
                provider_name,
                model_name,
                reasoning_effort or self.config.reasoning_effort,
            ),
            usage_context=usage_context,
        )

    def _provider_compatible_client(self, provider_name: str) -> Any:
        return {
            "zai": self.zai_client,
            "telnyx": self.telnyx_client,
            "kimi": self.kimi_client,
        }.get(provider_name)

    def _fireworks_chat(
        self,
        messages: list[dict[str, Any]],
        model_name: str,
        *,
        max_tokens: int,
        temperature: float | None = None,
        timeout: float | None = None,
        usage_context: dict[str, Any] | None = None,
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
        self._record_usage(usage_context, api="fireworks.chat.completions", model=model_name, provider="fireworks", usage=getattr(response, "usage", None))
        choice = response.choices[0]
        _testing_trace_response(
            usage_context=usage_context,
            api="fireworks.chat.completions",
            provider="fireworks",
            model=model_name,
            request_messages=messages,
            request_kwargs=kwargs,
            response=response,
            choice=choice,
        )
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
        usage_context: dict[str, Any] | None = None,
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
        self._record_usage(usage_context, api="sambanova.chat.completions", model=model_name, provider="sambanova", usage=getattr(response, "usage", None))
        choice = response.choices[0]
        _testing_trace_response(
            usage_context=usage_context,
            api="sambanova.chat.completions",
            provider="sambanova",
            model=model_name,
            request_messages=messages,
            request_kwargs=kwargs,
            response=response,
            choice=choice,
        )
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
        max_tool_rounds: int = 5,
        usage_context: dict[str, Any] | None = None,
    ) -> str:
        if self.openrouter_client is None:
            raise RuntimeError("OPENROUTER_API_KEY is not configured")
        chat_messages: list[dict[str, Any]] = [{"role": item["role"], "content": item["content"]} for item in messages]
        chat_tools = [_responses_tool_to_chat_tool(tool) for tool in tools]
        tool_rounds = max(1, min(max_tool_rounds, 12))
        failed_tool_signatures: dict[tuple[str, str], int] = {}
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
            self._record_usage(usage_context, api="openrouter.chat.completions", model=model_name, provider="openrouter", usage=getattr(response, "usage", None))
            message = response.choices[0].message
            tool_calls = list(getattr(message, "tool_calls", None) or [])
            if not tool_calls:
                content = _sanitize_provider_content(message.content or "", provider_name="openrouter")
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
            chat_messages.append(_assistant_tool_message(message))
            for call in tool_calls:
                LOG.info(
                    "llm_tool_call api=openrouter model=%s round=%s name=%s call_id=%s args=%s",
                    model_name,
                    round_index + 1,
                    call.function.name,
                    call.id,
                    _compact_json(call.function.arguments),
                )
                _tool_trace(
                    phase="input",
                    api="openrouter",
                    model=model_name,
                    round_index=round_index + 1,
                    tool_name=call.function.name,
                    call_id=call.id,
                    payload=call.function.arguments,
                )
                handler = tool_handlers.get(call.function.name)
                args: dict[str, Any] = {}
                if handler is None:
                    result = {"ok": False, "error": f"unknown tool: {call.function.name}"}
                else:
                    try:
                        args = json.loads(call.function.arguments or "{}")
                        blocked = _blocked_repeated_failed_tool_call(failed_tool_signatures, call.function.name, args)
                        if blocked is not None:
                            result = blocked
                        else:
                            result = handler(**args)
                    except Exception as exc:
                        result = {"ok": False, "error": str(exc)}
                _remember_failed_tool_signature(failed_tool_signatures, call.function.name, args, result)
                LOG.info(
                    "llm_tool_result api=openrouter model=%s round=%s name=%s call_id=%s result=%s",
                    model_name,
                    round_index + 1,
                    call.function.name,
                    call.id,
                    _compact_json(result),
                )
                _tool_trace(
                    phase="output",
                    api="openrouter",
                    model=model_name,
                    round_index=round_index + 1,
                    tool_name=call.function.name,
                    call_id=call.id,
                    payload=result,
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
            usage_context=usage_context,
        )

    def _deepseek_chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_handlers: dict[str, Any],
        model_name: str,
        *,
        max_tokens: int,
        temperature: float | None = None,
        reasoning_effort: str | None = None,
        max_tool_rounds: int = 5,
        usage_context: dict[str, Any] | None = None,
    ) -> str:
        if self.deepseek_client is None:
            raise RuntimeError("DEEPSEEK_API_KEY is not configured")
        chat_messages: list[dict[str, Any]] = [{"role": item["role"], "content": item["content"]} for item in messages]
        chat_tools = [_responses_tool_to_chat_tool(tool) for tool in tools]
        tool_rounds = max(1, min(max_tool_rounds, 12))
        thinking_enabled = _deepseek_thinking_enabled(reasoning_effort)
        failed_tool_signatures: dict[tuple[str, str], int] = {}
        for round_index in range(tool_rounds):
            kwargs: dict[str, Any] = {
                "model": model_name,
                "messages": chat_messages,
                "tools": chat_tools,
                "tool_choice": "auto",
                "max_tokens": max_tokens,
                "timeout": OPENROUTER_TIMEOUT,
            }
            extra_body = _deepseek_extra_body(reasoning_effort)
            if extra_body:
                kwargs["extra_body"] = extra_body
            normalized_effort = _normalize_deepseek_reasoning_effort(reasoning_effort)
            if normalized_effort:
                kwargs["reasoning_effort"] = normalized_effort
            if temperature is not None and _model_supports_temperature(model_name) and not thinking_enabled:
                kwargs["temperature"] = temperature
            LOG.info(
                "llm_tool_request api=deepseek model=%s round=%s/%s messages=%s tools=%s max_tokens=%s thinking=%s",
                model_name,
                round_index + 1,
                tool_rounds,
                len(chat_messages),
                [tool.get("function", {}).get("name", "") for tool in chat_tools],
                max_tokens,
                thinking_enabled,
            )
            response = _call_with_hard_timeout(
                "deepseek.chat.completions",
                OPENROUTER_TIMEOUT + 5.0,
                self.deepseek_client.chat.completions.create,
                **kwargs,
            )
            LOG.info(
                "llm_tool_response api=deepseek model=%s round=%s finish_reason=%s",
                model_name,
                round_index + 1,
                getattr(response.choices[0], "finish_reason", None) if getattr(response, "choices", None) else None,
            )
            _log_prompt_cache_usage("deepseek.chat.completions", model_name, getattr(response, "usage", None))
            self._record_usage(usage_context, api="deepseek.chat.completions", model=model_name, provider="deepseek", usage=getattr(response, "usage", None))
            message = response.choices[0].message
            tool_calls = list(getattr(message, "tool_calls", None) or [])
            if not tool_calls:
                content = _sanitize_provider_content(message.content or "", provider_name="deepseek")
                pseudo_result = _handle_plaintext_tool_call(content, tool_handlers)
                if pseudo_result is not None:
                    LOG.warning(
                        "llm_plaintext_tool_call api=deepseek model=%s round=%s result=%s",
                        model_name,
                        round_index + 1,
                        _compact_json(pseudo_result),
                    )
                    if isinstance(pseudo_result, dict) and pseudo_result.get("__terminal_response__"):
                        return str(pseudo_result.get("text", "")).strip()
                    return ""
                return content
            chat_messages.append(_deepseek_assistant_message_dict(message))
            for call in tool_calls:
                LOG.info(
                    "llm_tool_call api=deepseek model=%s round=%s name=%s call_id=%s args=%s",
                    model_name,
                    round_index + 1,
                    call.function.name,
                    call.id,
                    _compact_json(call.function.arguments),
                )
                _tool_trace(
                    phase="input",
                    api="deepseek",
                    model=model_name,
                    round_index=round_index + 1,
                    tool_name=call.function.name,
                    call_id=call.id,
                    payload=call.function.arguments,
                )
                handler = tool_handlers.get(call.function.name)
                args: dict[str, Any] = {}
                if handler is None:
                    result = {"ok": False, "error": f"unknown tool: {call.function.name}"}
                else:
                    try:
                        args = json.loads(call.function.arguments or "{}")
                        blocked = _blocked_repeated_failed_tool_call(failed_tool_signatures, call.function.name, args)
                        if blocked is not None:
                            result = blocked
                        else:
                            result = handler(**args)
                    except Exception as exc:
                        result = {"ok": False, "error": str(exc)}
                _remember_failed_tool_signature(failed_tool_signatures, call.function.name, args, result)
                LOG.info(
                    "llm_tool_result api=deepseek model=%s round=%s name=%s call_id=%s result=%s",
                    model_name,
                    round_index + 1,
                    call.function.name,
                    call.id,
                    _compact_json(result),
                )
                _tool_trace(
                    phase="output",
                    api="deepseek",
                    model=model_name,
                    round_index=round_index + 1,
                    tool_name=call.function.name,
                    call_id=call.id,
                    payload=result,
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
        LOG.warning("llm_tool_budget_exhausted api=deepseek model=%s rounds=%s forcing_final_answer", model_name, tool_rounds)
        chat_messages.append(
            {
                "role": "user",
                "content": (
                    "Tool budget is exhausted. Produce the final answer now using the tool results already available. "
                    "Do not call any more tools."
                ),
            }
        )
        return self._deepseek_chat(
            chat_messages,
            model_name,
            max_tokens=max_tokens,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
            usage_context=usage_context,
        )

    def _together_chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_handlers: dict[str, Any],
        model_name: str,
        *,
        max_tokens: int,
        reasoning_effort: str | None = None,
        max_tool_rounds: int = 5,
        usage_context: dict[str, Any] | None = None,
    ) -> str:
        try:
            return self._compatible_chat_with_tools(
                client=self.together_client,
                provider_name="together",
                messages=messages,
                tools=tools,
                tool_handlers=tool_handlers,
                model_name=model_name,
                max_tokens=max_tokens,
                extra_create_kwargs=_together_reasoning_kwargs(reasoning_effort or self.config.reasoning_effort),
                max_tool_rounds=max_tool_rounds,
                usage_context=usage_context,
            )
        except Exception as exc:
            fallback_model = _together_openrouter_fallback_model(model_name)
            if not _should_fallback_together_error(exc, fallback_model, self.openrouter_client):
                raise
            LOG.warning(
                "together provider error during tool run; falling back to openrouter model=%s fallback_model=%s reason=%s",
                model_name,
                fallback_model,
                str(exc),
            )
            return self._openrouter_chat_with_tools(
                messages,
                tools,
                tool_handlers,
                fallback_model,
                max_tokens=max_tokens,
                reasoning_effort=self.config.reasoning_effort,
                max_tool_rounds=max_tool_rounds,
                usage_context=usage_context,
            )

    def _lightning_chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_handlers: dict[str, Any],
        model_name: str,
        *,
        max_tokens: int,
        max_tool_rounds: int = 5,
        usage_context: dict[str, Any] | None = None,
    ) -> str:
        return self._compatible_chat_with_tools(
            client=self.lightning_client,
            provider_name="lightning",
            messages=messages,
            tools=tools,
            tool_handlers=tool_handlers,
            model_name=model_name,
            max_tokens=max_tokens,
            max_tool_rounds=max_tool_rounds,
            use_content_parts=True,
            usage_context=usage_context,
        )

    def _minimax_chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_handlers: dict[str, Any],
        model_name: str,
        *,
        max_tokens: int,
        max_tool_rounds: int = 5,
        usage_context: dict[str, Any] | None = None,
    ) -> str:
        return self._compatible_chat_with_tools(
            client=self.minimax_client,
            provider_name="minimax",
            messages=messages,
            tools=tools,
            tool_handlers=tool_handlers,
            model_name=model_name,
            max_tokens=max_tokens,
            max_tool_rounds=max_tool_rounds,
            max_tokens_field="max_completion_tokens",
            extra_create_kwargs={"extra_body": {"reasoning_split": True}},
            usage_context=usage_context,
        )

    def _compatible_chat_with_tools(
        self,
        *,
        client: Any,
        provider_name: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_handlers: dict[str, Any],
        model_name: str,
        max_tokens: int,
        max_tool_rounds: int = 5,
        use_content_parts: bool = False,
        max_tokens_field: str = "max_tokens",
        extra_create_kwargs: dict[str, Any] | None = None,
        include_temperature: bool = True,
        include_parallel_tool_calls: bool = True,
        usage_context: dict[str, Any] | None = None,
    ) -> str:
        if client is None:
            raise RuntimeError(f"{provider_name.upper()}_API_KEY is not configured")
        chat_messages = _chat_messages_for_provider(
            messages,
            use_content_parts=use_content_parts,
            provider_name=provider_name,
        )
        chat_tools = [_responses_tool_to_chat_tool(tool) for tool in tools]
        tool_rounds = max(1, min(max_tool_rounds, 12))
        failed_tool_signatures: dict[tuple[str, str], int] = {}
        for round_index in range(tool_rounds):
            kwargs: dict[str, Any] = {
                "model": model_name,
                "messages": chat_messages,
                "tools": chat_tools,
                "tool_choice": "auto",
                "timeout": OPENROUTER_TIMEOUT,
            }
            if include_parallel_tool_calls:
                kwargs["parallel_tool_calls"] = False
            kwargs[max_tokens_field] = max_tokens
            if include_temperature and _model_supports_temperature(model_name):
                kwargs["temperature"] = self.config.temperature
            if extra_create_kwargs:
                kwargs.update(extra_create_kwargs)
            LOG.info(
                "llm_tool_request api=%s model=%s round=%s/%s messages=%s tools=%s max_tokens=%s",
                provider_name,
                model_name,
                round_index + 1,
                tool_rounds,
                len(chat_messages),
                [tool.get("function", {}).get("name", "") for tool in chat_tools],
                max_tokens,
            )
            response = _call_with_hard_timeout(
                f"{provider_name}.chat.completions",
                OPENROUTER_TIMEOUT + 5.0,
                client.chat.completions.create,
                **kwargs,
            )
            _log_prompt_cache_usage(f"{provider_name}.chat.completions", model_name, getattr(response, "usage", None))
            self._record_usage(usage_context, api=f"{provider_name}.chat.completions", model=model_name, provider=provider_name, usage=getattr(response, "usage", None))
            trace_id = _response_trace_id(response)
            choice = response.choices[0]
            message = choice.message
            tool_calls = list(getattr(message, "tool_calls", None) or [])
            content = _sanitize_provider_content(message.content or "", provider_name=provider_name)
            LOG.info(
                "llm_tool_response api=%s model=%s round=%s trace_id=%s finish_reason=%s tool_calls=%s has_reasoning=%s content_preview=%r usage=%s",
                provider_name,
                model_name,
                round_index + 1,
                trace_id,
                getattr(choice, "finish_reason", None),
                [call.function.name for call in tool_calls],
                bool(_message_reasoning_content(message)),
                content[:300],
                getattr(response, "usage", None),
            )
            if not tool_calls:
                interpreted = _handle_plaintext_tool_call(content, tool_handlers)
                if interpreted is not None:
                    LOG.warning(
                        "llm_tool_plaintext_interpreted api=%s model=%s round=%s content=%r result=%s",
                        provider_name,
                        model_name,
                        round_index + 1,
                        content[:300],
                        _compact_json(interpreted),
                    )
                    if isinstance(interpreted, dict) and interpreted.get("__terminal_response__"):
                        return str(interpreted.get("text", "")).strip()
                    return ""
                return content
            chat_messages.append(_assistant_tool_message(message, use_content_parts=use_content_parts))
            for call in tool_calls:
                LOG.info(
                    "llm_tool_call api=%s model=%s round=%s trace_id=%s name=%s call_id=%s arguments=%s",
                    provider_name,
                    model_name,
                    round_index + 1,
                    trace_id,
                    call.function.name,
                    call.id,
                    _compact_json(call.function.arguments),
                )
                _tool_trace(
                    phase="input",
                    api=provider_name,
                    model=model_name,
                    round_index=round_index + 1,
                    tool_name=call.function.name,
                    call_id=call.id,
                    payload=call.function.arguments,
                    trace_id=trace_id,
                )
                handler = tool_handlers.get(call.function.name)
                args: dict[str, Any] = {}
                if handler is None:
                    result = {"ok": False, "error": f"unknown tool: {call.function.name}"}
                else:
                    try:
                        args = json.loads(call.function.arguments or "{}")
                        blocked = _blocked_repeated_failed_tool_call(
                            failed_tool_signatures,
                            call.function.name,
                            args,
                        )
                        if blocked is not None:
                            result = blocked
                        else:
                            result = handler(**args)
                    except Exception as exc:
                        result = {"ok": False, "error": str(exc)}
                _remember_failed_tool_signature(failed_tool_signatures, call.function.name, args if 'args' in locals() else {}, result)
                LOG.info(
                    "llm_tool_result api=%s model=%s round=%s trace_id=%s name=%s call_id=%s result=%s",
                    provider_name,
                    model_name,
                    round_index + 1,
                    trace_id,
                    call.function.name,
                    call.id,
                    _compact_json(result),
                )
                _tool_trace(
                    phase="output",
                    api=provider_name,
                    model=model_name,
                    round_index=round_index + 1,
                    tool_name=call.function.name,
                    call_id=call.id,
                    payload=result,
                    trace_id=trace_id,
                )
                if isinstance(result, dict) and result.get("__terminal_response__"):
                    return str(result.get("text", "")).strip()
                chat_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": _provider_text_content(json.dumps(result, ensure_ascii=False), use_content_parts),
                    }
                )
        LOG.warning("llm_tool_budget_exhausted api=%s model=%s rounds=%s", provider_name, model_name, tool_rounds)
        return self._compatible_chat(
            client=client,
            provider_name=provider_name,
            messages=chat_messages,
            model_name=model_name,
            max_tokens=max_tokens,
            temperature=(
                self.config.temperature
                if include_temperature and _model_supports_temperature(model_name)
                else None
            ),
            use_content_parts=use_content_parts,
            max_tokens_field=max_tokens_field,
            extra_create_kwargs=extra_create_kwargs,
            usage_context=usage_context,
        )

    def _provider_compatible_chat_with_tools(
        self,
        provider_name: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_handlers: dict[str, Any],
        model_name: str,
        *,
        max_tokens: int,
        reasoning_effort: str | None = None,
        max_tool_rounds: int = 5,
        usage_context: dict[str, Any] | None = None,
    ) -> str:
        return self._compatible_chat_with_tools(
            client=self._provider_compatible_client(provider_name),
            provider_name=provider_name,
            messages=messages,
            tools=tools,
            tool_handlers=tool_handlers,
            model_name=model_name,
            max_tokens=max_tokens,
            max_tool_rounds=max_tool_rounds,
            extra_create_kwargs=_provider_reasoning_kwargs(
                provider_name,
                model_name,
                reasoning_effort or self.config.reasoning_effort,
            ),
            include_temperature=provider_name != "kimi",
            include_parallel_tool_calls=provider_name != "kimi",
            usage_context=usage_context,
        )

    def _fireworks_chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_handlers: dict[str, Any],
        model_name: str,
        *,
        max_tokens: int,
        max_tool_rounds: int = 5,
        usage_context: dict[str, Any] | None = None,
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
            self._record_usage(usage_context, api="fireworks.chat.completions", model=model_name, provider="fireworks", usage=getattr(response, "usage", None))
            message = response.choices[0].message
            tool_calls = list(getattr(message, "tool_calls", None) or [])
            if not tool_calls:
                content = _sanitize_provider_content(message.content or "", provider_name="fireworks")
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
                _tool_trace(
                    phase="input",
                    api="fireworks",
                    model=model_name,
                    round_index=round_index + 1,
                    tool_name=call.function.name,
                    call_id=call.id,
                    payload=call.function.arguments,
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
                _tool_trace(
                    phase="output",
                    api="fireworks",
                    model=model_name,
                    round_index=round_index + 1,
                    tool_name=call.function.name,
                    call_id=call.id,
                    payload=result,
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
        return self._fireworks_chat(chat_messages, model_name, max_tokens=max_tokens, usage_context=usage_context)

    def _sambanova_chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_handlers: dict[str, Any],
        model_name: str,
        *,
        max_tokens: int,
        max_tool_rounds: int = 5,
        usage_context: dict[str, Any] | None = None,
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
            self._record_usage(usage_context, api="sambanova.chat.completions", model=model_name, provider="sambanova", usage=getattr(response, "usage", None))
            message = response.choices[0].message
            tool_calls = list(getattr(message, "tool_calls", None) or [])
            if not tool_calls:
                content = _sanitize_provider_content(message.content or "", provider_name="sambanova")
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
                _tool_trace(
                    phase="input",
                    api="sambanova",
                    model=model_name,
                    round_index=round_index + 1,
                    tool_name=call.function.name,
                    call_id=call.id,
                    payload=call.function.arguments,
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
                _tool_trace(
                    phase="output",
                    api="sambanova",
                    model=model_name,
                    round_index=round_index + 1,
                    tool_name=call.function.name,
                    call_id=call.id,
                    payload=result,
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
        return self._sambanova_chat(chat_messages, model_name, max_tokens=max_tokens, usage_context=usage_context)

    def _record_usage(
        self,
        usage_context: dict[str, Any] | None,
        *,
        api: str,
        model: str,
        provider: str,
        usage: Any,
    ) -> None:
        if not usage_context or usage is None or self.usage_recorder is None:
            return
        chat_id = str(usage_context.get("chat_id") or "").strip()
        if not chat_id:
            return
        input_tokens, output_tokens, cached_tokens = _usage_totals(usage)
        if input_tokens <= 0 and output_tokens <= 0 and cached_tokens <= 0:
            return
        try:
            self.usage_recorder(
                {
                    "chat_id": chat_id,
                    "feature": str(usage_context.get("feature") or "unknown"),
                    "provider": provider,
                    "model": model,
                    "api": api,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cached_tokens": cached_tokens,
                }
            )
        except Exception:
            LOG.exception("token_usage_record_failed chat=%s feature=%s api=%s model=%s", chat_id, usage_context.get("feature"), api, model)

    def analyze_image(self, image_path: Path, prompt: str) -> str:
        if self.config.vision_provider == "gemini":
            try:
                return self._analyze_image_gemini(image_path, prompt)
            except Exception as exc:
                LOG.warning("gemini vision failed, falling back to openai vision: %s", exc)
        return self._analyze_image_openai(image_path, prompt)

    def analyze_image_native(
        self,
        image_path: Path,
        prompt: str,
        *,
        model: str | None = None,
        provider: str | None = None,
        reasoning_effort: str | None = None,
        usage_context: dict[str, Any] | None = None,
    ) -> str:
        from .tool_vision import image_to_data_url

        model_name = _canonicalize_model_name(model or self.config.name)
        resolved_provider = _resolve_provider(provider or self.config.provider, model_name)
        LOG.info(
            "native image analysis request provider=%s model=%s image=%s",
            resolved_provider,
            model_name,
            image_path,
        )
        return self.chat(
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": image_to_data_url(image_path)}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
            max_completion_tokens=max(600, min(self.config.max_output_tokens, 8192)),
            model=model_name,
            provider=resolved_provider,
            reasoning_effort=reasoning_effort,
            usage_context=usage_context,
        )

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
    if "reasoning_content" in text and "passed back" in text:
        return False
    if "must be passed back" in text:
        return False
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

def _tool_trace(
    *,
    phase: str,
    api: str,
    model: str,
    round_index: int,
    tool_name: str,
    call_id: str,
    payload: Any,
    trace_id: str = "",
) -> None:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "phase": phase,
        "api": api,
        "model": model,
        "round": round_index,
        "tool_name": tool_name,
        "call_id": call_id,
        "trace_id": trace_id,
        "payload": payload,
    }
    try:
        TOOL_TRACE_LOG.info(json.dumps(record, ensure_ascii=False, default=str))
    except Exception:
        TOOL_TRACE_LOG.info(str(record))

def _testing_trace_response(
    *,
    usage_context: dict[str, Any] | None,
    api: str,
    provider: str,
    model: str,
    request_messages: list[dict[str, Any]],
    request_kwargs: dict[str, Any],
    response: Any,
    choice: Any,
) -> None:
    if not _is_testing_usage_context(usage_context):
        return
    message = getattr(choice, "message", None)
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": "response",
        "feature": str((usage_context or {}).get("feature") or ""),
        "chat_id": str((usage_context or {}).get("chat_id") or ""),
        "sender": str((usage_context or {}).get("sender") or ""),
        "msg_type": (usage_context or {}).get("msg_type"),
        "provider": provider,
        "api": api,
        "model": model,
        "original_text": str((usage_context or {}).get("original_text") or ""),
        "sanitized_text": str((usage_context or {}).get("sanitized_text") or ""),
        "request_messages": request_messages,
        "request_kwargs": _testing_trace_sanitize_request_kwargs(request_kwargs),
        "response_id": getattr(response, "id", None),
        "finish_reason": getattr(choice, "finish_reason", None),
        "content": getattr(message, "content", "") if message is not None else "",
        "reasoning_content": _message_reasoning_content(message) if message is not None else None,
        "usage": _safe_model_dump(getattr(response, "usage", None)),
        "raw_message": _safe_model_dump(message),
    }
    try:
        TESTING_MODE_LOG.info(json.dumps(record, ensure_ascii=False, default=str))
    except Exception:
        TESTING_MODE_LOG.info(str(record))

def _is_testing_usage_context(usage_context: dict[str, Any] | None) -> bool:
    return str((usage_context or {}).get("feature") or "").strip().lower() == "main_reply_testing_mode"

def _testing_trace_sanitize_request_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in kwargs.items():
        if key == "messages":
            continue
        if key == "timeout":
            safe[key] = value
            continue
        safe[key] = _safe_model_dump(value)
    return safe

def _safe_model_dump(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _safe_model_dump(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_model_dump(v) for v in value]
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump()
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        try:
            return {str(k): _safe_model_dump(v) for k, v in vars(value).items() if not str(k).startswith("_")}
        except Exception:
            pass
    return str(value)

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

def _chat_messages_for_provider(
    messages: list[dict[str, Any]],
    *,
    use_content_parts: bool = False,
    provider_name: str = "",
) -> list[dict[str, Any]]:
    source_messages = _collapse_system_messages(messages)
    rendered: list[dict[str, Any]] = []
    for item in source_messages:
        payload: dict[str, Any] = {
            "role": item.get("role", "user"),
            "content": _provider_text_content(item.get("content", ""), use_content_parts),
        }
        if item.get("tool_call_id"):
            payload["tool_call_id"] = item["tool_call_id"]
        if item.get("tool_calls"):
            payload["tool_calls"] = item["tool_calls"]
        if item.get("reasoning_content"):
            payload["reasoning_content"] = item["reasoning_content"]
        rendered.append(payload)
    return rendered

def _collapse_system_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    system_parts: list[str] = []
    collapsed: list[dict[str, Any]] = []
    for item in messages:
        if item.get("role") == "system":
            content = str(item.get("content", "") or "").strip()
            if content:
                system_parts.append(content)
            continue
        collapsed.append(item)
    if not system_parts:
        return list(messages)
    return [{"role": "system", "content": "\n\n".join(system_parts)}] + collapsed

def _provider_text_content(content: Any, use_content_parts: bool) -> Any:
    if not use_content_parts:
        return content
    if isinstance(content, list):
        return content
    return [{"type": "text", "text": str(content or "")}]

def _assistant_tool_message(message: Any, *, use_content_parts: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "role": "assistant",
        "content": _provider_text_content(getattr(message, "content", "") or "", use_content_parts),
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments or "{}",
                },
            }
            for call in list(getattr(message, "tool_calls", None) or [])
        ],
    }
    reasoning_content = _message_reasoning_content(message)
    if reasoning_content:
        payload["reasoning_content"] = reasoning_content
    return payload

def _resolve_provider(provider: str | None, model: str) -> str:
    value = (provider or "auto").strip().lower()
    aliases = {"z.ai": "zai", "z-ai": "zai", "moonshot": "kimi", "telnyx-inference": "telnyx"}
    value = aliases.get(value, value)
    if value in {"openai", "openrouter", "deepseek", "together", "lightning", "minimax", "bedrock", "fireworks", "sambanova", "zai", "telnyx", "kimi"}:
        return value
    model_name = (model or "").strip().lower()
    if model_name.startswith("deepseek-"):
        return "deepseek"
    if model_name.startswith("minimax-"):
        return "minimax"
    if model_name.startswith("accounts/fireworks/"):
        return "fireworks"
    if model_name.startswith("glm-"):
        return "zai"
    if model_name.startswith(("kimi-", "moonshot-v1-")):
        return "kimi"
    if "/" in model_name:
        return "openrouter"
    if model_name.startswith(("gpt-", "o1", "o3", "o4")):
        return "openai"
    return "openrouter"

def _provider_reasoning_kwargs(provider: str, model: str, reasoning_effort: str | None) -> dict[str, Any]:
    effort = _normalize_reasoning_effort(reasoning_effort, preserve_max=True)
    enabled = bool(effort)
    if provider == "zai":
        return {"extra_body": {"thinking": {"type": "enabled" if enabled else "disabled"}}}
    if provider == "telnyx":
        return {"extra_body": {"enable_thinking": enabled}}
    if provider == "kimi":
        model_name = (model or "").strip().lower()
        if model_name.startswith("kimi-k3"):

            if effort in {"", "minimal", "low"}:
                return {"reasoning_effort": "low"}
            if effort in {"medium", "high"}:
                return {"reasoning_effort": "high"}
            return {"reasoning_effort": "max"}
        if model_name.startswith("kimi-k2.7-code"):

            return {"extra_body": {"thinking": {"type": "enabled"}}}
        return {"extra_body": {"thinking": {"type": "enabled" if enabled else "disabled"}}}
    return {}

def _bedrock_model_family(model: str) -> str:
    model_name = (model or "").strip().lower()
    if model_name.startswith("anthropic."):
        return "anthropic"
    if model_name.startswith("openai."):
        return "openai"
    return "compat"

def _bedrock_region_for_model(model: str) -> str:
    model_name = (model or "").strip().lower()
    global_region = (os.environ.get("BEDROCK_REGION") or "").strip()
    if model_name.startswith("openai."):
        return (os.environ.get("BEDROCK_OPENAI_REGION") or global_region or "us-east-2").strip()
    if model_name.startswith("anthropic."):
        return (os.environ.get("BEDROCK_ANTHROPIC_REGION") or global_region or "us-east-1").strip()
    return (os.environ.get("BEDROCK_COMPAT_REGION") or global_region or "us-east-1").strip()

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

def _normalize_deepseek_reasoning_effort(value: str | None) -> str:
    effort = _normalize_reasoning_effort(value, preserve_max=True)
    if effort in {"", "none"}:
        return ""
    if effort in {"minimal", "low", "medium", "high"}:
        return "high"
    if effort in {"xhigh", "max"}:
        return "max"
    return "high"

def _deepseek_thinking_enabled(value: str | None) -> bool:
    effort = (value or "").strip().lower()
    return effort not in {"", "none", "off", "false", "0", "clear", "default"}

def _deepseek_extra_body(reasoning_effort: str | None) -> dict[str, Any]:
    return {"thinking": {"type": "enabled" if _deepseek_thinking_enabled(reasoning_effort) else "disabled"}}

def _together_reasoning_kwargs(reasoning_effort: str | None) -> dict[str, Any]:
    effort = _normalize_reasoning_effort(reasoning_effort, preserve_max=True)
    if not effort or effort in {"none", "off", "false", "0"}:
        return {}
    return {
        "extra_body": {
            "reasoning_effort": effort,
            "reasoning": {"enabled": True},
        },
    }

def _deepseek_assistant_message_dict(message: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "role": "assistant",
        "content": getattr(message, "content", "") or "",
    }
    reasoning_content = _message_reasoning_content(message)
    if reasoning_content:
        payload["reasoning_content"] = reasoning_content
    tool_calls = list(getattr(message, "tool_calls", None) or [])
    if tool_calls:
        payload["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments or "{}",
                },
            }
            for call in tool_calls
        ]
    return payload

def _message_reasoning_content(message: Any) -> Any:
    direct = getattr(message, "reasoning_content", None)
    if direct:
        return direct
    direct_reasoning = getattr(message, "reasoning", None)
    if direct_reasoning:
        return direct_reasoning
    if isinstance(message, dict):
        return message.get("reasoning_content") or message.get("reasoning")
    model_extra = getattr(message, "model_extra", None)
    if isinstance(model_extra, dict):
        if model_extra.get("reasoning_content"):
            return model_extra.get("reasoning_content")
        if model_extra.get("reasoning"):
            return model_extra.get("reasoning")
    try:
        dumped = message.model_dump()
    except Exception:
        dumped = None
    if isinstance(dumped, dict):
        return dumped.get("reasoning_content") or dumped.get("reasoning")
    return None

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

def _response_trace_id(response: Any) -> str:
    trace_id = str(getattr(response, "id", "") or "")
    if trace_id:
        return trace_id
    headers = getattr(response, "headers", None)
    if headers:
        try:
            return str(
                headers.get("x-request-id")
                or headers.get("x-amzn-requestid")
                or headers.get("x-amzn-request-id")
                or ""
            )
        except Exception:
            return ""
    return ""

def _responses_tool_to_chat_tool(tool: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.get("name", ""),
            "description": tool.get("description", ""),
            "parameters": tool.get("parameters", {"type": "object", "properties": {}}),
        },
    }

def _responses_tool_to_anthropic_tool(tool: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": tool.get("name", ""),
        "description": tool.get("description", ""),
        "input_schema": tool.get("parameters", {"type": "object", "properties": {}}),
    }

def _bedrock_anthropic_prompt(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    collapsed = _collapse_system_messages(messages)
    system_text = ""
    prompt_messages: list[dict[str, Any]] = []
    for item in collapsed:
        role = str(item.get("role", "user"))
        if role == "system":
            system_text = str(item.get("content", "") or "")
            continue
        if role not in {"user", "assistant"}:
            continue
        prompt_messages.append({"role": role, "content": str(item.get("content", "") or "")})
    return system_text, prompt_messages

def _bedrock_anthropic_text(body: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in list(body.get("content") or []):
        if isinstance(item, dict) and item.get("type") == "text" and item.get("text"):
            parts.append(str(item.get("text")))
    return "".join(parts).strip()

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
    minimax_aliases = {
        "minimax-m2.7": "MiniMax-M2.7",
        "minimax-m3": "MiniMax-M3",
    }
    if lowered in minimax_aliases:
        return minimax_aliases[lowered]
    if lowered.startswith(("gpt-", "o1", "o3", "o4")):
        return lowered
    return value

def _together_openrouter_fallback_model(model: str) -> str:
    value = (model or "").strip()
    lowered = value.lower()
    mapping = {
        "deepseek-ai/deepseek-v4-pro": "deepseek/deepseek-v4-pro",
        "deepseek-ai/deepseek-v4-flash": "deepseek/deepseek-v4-flash",
        "deepseek-v4-pro": "deepseek/deepseek-v4-pro",
        "deepseek-v4-flash": "deepseek/deepseek-v4-flash",
    }
    return mapping.get(lowered, value)

def _should_fallback_together_error(exc: Exception, fallback_model: str, openrouter_client: Any) -> bool:
    if openrouter_client is None:
        return False
    text = str(exc).lower()
    retryable_429 = ("429" in text or "ratelimit" in text or "rate limit" in text) and (
        "dynamic_rate_limit" in text or "too many requests" in text
    )
    retryable_5xx = (
        "500" in text
        or "502" in text
        or "503" in text
        or "504" in text
        or "internal server error" in text
        or "server_error" in text
        or "bad gateway" in text
        or "service unavailable" in text
        or "gateway timeout" in text
    )
    if not retryable_429 and not retryable_5xx:
        return False
    return bool(fallback_model)

def _tool_failure_signature(name: str, args: dict[str, Any], result: Any) -> tuple[str, str] | None:
    if not isinstance(result, dict):
        return None
    if result.get("ok") is True:
        return None
    if result.get("__terminal_response__"):
        return None
    error = str(result.get("error", "") or result.get("reason", "")).strip().lower()
    args_sig = _compact_json(args)[:160]
    if error:
        error = re.sub(r"\s+", " ", error)[:160]
    else:
        error = "non_ok"
    return ((name or "").strip(), f"{args_sig}|{error}")

def _remember_failed_tool_signature(
    failed_tool_signatures: dict[tuple[str, str], int],
    name: str,
    args: dict[str, Any],
    result: Any,
) -> None:
    signature = _tool_failure_signature(name, args, result)
    if signature is None:
        return
    failed_tool_signatures[signature] = failed_tool_signatures.get(signature, 0) + 1

def _blocked_repeated_failed_tool_call(
    failed_tool_signatures: dict[tuple[str, str], int],
    name: str,
    args: dict[str, Any],
) -> dict[str, Any] | None:
    compact_args = _compact_json(args)[:160]
    for (tool_name, failure_key), count in failed_tool_signatures.items():
        if tool_name != (name or "").strip():
            continue
        if count < 1:
            continue
        if compact_args and failure_key.startswith(compact_args):
            return {
                "ok": False,
                "error": "Repeated failed tool method blocked. Switch to a different method instead of retrying the same failing approach.",
                "__guardrail_blocked__": True,
            }
    return None

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

def _usage_totals(usage: Any) -> tuple[int, int, int]:
    input_tokens = _usage_value(usage, "prompt_tokens")
    if input_tokens is None:
        input_tokens = _usage_value(usage, "input_tokens")
    output_tokens = _usage_value(usage, "completion_tokens")
    if output_tokens is None:
        output_tokens = _usage_value(usage, "output_tokens")
    cached_tokens = _usage_nested_value(usage, "prompt_tokens_details", "cached_tokens")
    if cached_tokens is None:
        cached_tokens = _usage_nested_value(usage, "input_tokens_details", "cached_tokens")
    return int(input_tokens or 0), int(output_tokens or 0), int(cached_tokens or 0)

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
