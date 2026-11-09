# -*- coding: utf-8 -*-
"""OpenAI Decisions API client (gpt-6-luna) - typed fast decisions.

Used as (a) the gate's last-resort when Jev itself errors, and (b) a
shadow evaluator running in parallel with Jev for A/B data collection.
Docs: developers.openai.com/api/docs/guides/decisions ($0.10/M input).
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

import requests

LOG = logging.getLogger(__name__)

def _api_key() -> str:
    return os.environ.get("OPENAI_API_KEY", "").strip()


_URL = "https://api.openai.com/v1/decisions"
_MODEL = "gpt-6-luna"
_TIMEOUT = 8.0

GATE_BINARY_QUESTION = {
    "type": "choice",
    "name": "reply_gate",
    "instructions": (
        "Should this WeChat group bot reply to the current message? "
        "Be conservative, default to silence. REPLY only when the message is "
        "clearly about the bot, asks for help/analysis, continues an active "
        "exchange with the bot, or the sender is owner/whitelist clearly "
        "addressing the bot."
    ),
    "choices": [
        {"value": "REPLY", "description": "The bot should respond"},
        {"value": "PASS", "description": "The bot should stay silent"},
    ],
}

GATE_PREDICATES = {
    "addressing_bot": "Is the sender directly talking to the bot (explicit @-mention or bot name FoxStar, or a reply aimed at what the bot just said)?",
    "asks_help_analysis": "Is the message asking for help, analysis, explanation, calculation, or a factual answer where a bot reply is useful?",
    "continues_exchange": "Does this message continue an active exchange in which the bot recently participated?",
    "about_bot": "Is the message about the bot itself (behavior, identity, decisions, something it said)?",
    "social_hook": "Is this a greeting/welcome/celebration/funny moment where a short playful reply fits the vibe?",
}


def decisions_available() -> bool:
    return bool(_api_key())


def decisions_gate(
    state: Any,
    questions: list[dict[str, Any]] | None = None,
    timeout: float = _TIMEOUT,
) -> dict[str, Any]:
    """One Decisions call. Returns {answers, latency_ms}; raises on error."""
    if not _api_key():
        raise RuntimeError("OPENAI_API_KEY not configured")
    body = {
        "model": _MODEL,
        "input": state if isinstance(state, str) else str(state),
        "questions": questions or [GATE_BINARY_QUESTION],
    }
    started = time.perf_counter()
    resp = requests.post(
        _URL,
        headers={"Authorization": f"Bearer {_api_key()}", "Content-Type": "application/json"},
        json=body,
        timeout=timeout,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    resp.raise_for_status()
    data = resp.json()
    return {"answers": data.get("answers", []), "latency_ms": elapsed_ms}


def decisions_gate_binary(state: Any) -> dict[str, Any]:
    """Binary gate decision via the Decisions API.

    Returns {choice, probabilities, confidence, latency_ms}."""
    out = decisions_gate(state, [GATE_BINARY_QUESTION])
    ans = (out.get("answers") or [{}])[0]
    return {
        "choice": ans.get("choice", "PASS"),
        "probabilities": ans.get("probabilities", {}),
        "confidence": ans.get("confidence", 0.0),
        "latency_ms": out.get("latency_ms", 0.0),
    }
