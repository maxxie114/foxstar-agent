# -*- coding: utf-8 -*-
"""Jev-1 client for fast structured decisions (reply gate, search gate)."""
from __future__ import annotations

import logging
import os
from typing import Any

import requests

LOG = logging.getLogger(__name__)

def _api_key() -> str:
    return os.environ.get("TYPESAFE_JEV_KEY", "").strip()


_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
_TIMEOUT = 8.0


def jev_available() -> bool:
    return bool(_api_key())


def jev_choice(state: dict[str, Any], instructions: str, options: dict[str, str]) -> dict[str, Any]:
    """Single Choice primitive call. Returns {choice, probabilities, confidence}."""
    if not _api_key():
        raise RuntimeError("TYPESAFE_JEV_KEY not configured")
    import time as _time
    started = _time.perf_counter()
    resp = requests.post(
        _ENDPOINT,
        headers={
            "Authorization": f"Bearer {_api_key()}",
            "Content-Type": "application/json",
        },
        json={
            "state": state,
            "model": "jev-latest",
            "questions": {
                "decision": {
                    "type": "choice",
                    "instructions": instructions,
                    "criteria": options,
                },
            },
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    elapsed = (_time.perf_counter() - started) * 1000
    data = resp.json()
    answer = data.get("answers", {}).get("decision", {})
    tokens = data.get("usage", {}).get("input_tokens", 0)
    LOG.info(
        "jev_choice choice=%s conf=%.2f tokens=%s latency=%.0fms",
        answer.get("choice", ""), answer.get("confidence", 0.0), tokens, elapsed,
    )
    return {
        "choice": answer.get("choice", ""),
        "probabilities": answer.get("probabilities", {}),
        "confidence": answer.get("confidence", 0.0),
        "input_tokens": tokens,
        "latency_ms": elapsed,
    }


def jev_noul(state: dict[str, Any], instructions: str,
             true_desc: str = "", false_desc: str = "") -> float:
    """Noul primitive: returns 0-1 probability for a yes/no question."""
    if not _api_key():
        raise RuntimeError("TYPESAFE_JEV_KEY not configured")
    question: dict[str, Any] = {"type": "noul", "instructions": instructions}
    if true_desc or false_desc:
        question["criteria"] = {"true": true_desc, "false": false_desc}
    import time as _time
    started = _time.perf_counter()
    resp = requests.post(
        _ENDPOINT,
        headers={
            "Authorization": f"Bearer {_api_key()}",
            "Content-Type": "application/json",
        },
        json={
            "state": state,
            "model": "jev-latest",
            "questions": {"q": question},
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    elapsed = (_time.perf_counter() - started) * 1000
    data = resp.json()
    answer = data.get("answers", {}).get("q", {})
    noul_value = float(answer.get("noul", 0.5))
    LOG.info(
        "jev_noul noul=%.2f latency=%.0fms",
        noul_value, elapsed,
    )
    return noul_value


# Intent-detection criteria for the reply gate: instead of one fuzzy
# "should it reply" question, judge crisp independent intents and let code
# aggregate them. Tunable per deployment; aggregation thresholds live in
# aggregate_gate_criteria().
GATE_CRITERIA = {
    "addressing_bot": (
        "Is the sender directly talking to the bot? True if the message "
        "explicitly @-mentions the bot or names it (FoxStar), or is clearly a "
        "reply aimed at what the bot just said. False for general group talk."
    ),
    "asks_help_analysis": (
        "Is the message asking for help, analysis, explanation, calculation, "
        "translation, or a factual/technical answer where a bot reply would "
        "be useful? False for rhetorical or self-answered questions."
    ),
    "continues_exchange": (
        "Does this message continue an active back-and-forth exchange in "
        "which the bot recently participated? False if the bot has been "
        "silent for a while or the thread moved on without it."
    ),
    "about_bot": (
        "Is the message about the bot itself - its behavior, identity, "
        "replies, decisions, or something it recently said? False for "
        "messages merely mentioning AI/robots in general."
    ),
    "social_hook": (
        "Is this a clear greeting, welcome, celebration, or genuinely funny "
        "moment where a short playful bot reply would improve the group "
        "vibe? False for ordinary chatter or private jokes between others."
    ),
}

# criterion -> minimum noul probability that alone justifies a reply.
# Re-tuned 2026-10-01 on 200 hand-relabeled production cases (the original
# 0.55-uniform was grid-searched against the old gate's own decisions and
# over-fit its over-replying bias; on fair labels it fired 50% false
# positives). Chain accuracy with these: 81.5% vs binary-chain 79.5%.
GATE_REPLY_THRESHOLDS = {
    "addressing_bot": 0.65,
    "asks_help_analysis": 0.85,
    "continues_exchange": 0.70,
    "about_bot": 0.55,
    "social_hook": 0.65,
}
# confident shortcut bounds for the pre-gate: every criterion this low ->
# confident PASS without consulting the LLM gate; any criterion this high ->
# confident REPLY.
GATE_CONFIDENT_PASS_MAX = 0.40
GATE_CONFIDENT_REPLY_MIN = 0.80


def jev_gate_criteria(
    state: dict[str, Any],
    *,
    criteria: dict[str, str] | None = None,
) -> dict[str, Any]:
    """One API call, one noul question per criterion.

    Returns {probabilities: {criterion: p}, aggregate: {decision, hit},
    input_tokens, latency_ms}. Aggregation is deterministic code - see
    aggregate_gate_criteria().
    """
    if not _api_key():
        raise RuntimeError("TYPESAFE_JEV_KEY is not configured")
    criteria = criteria or GATE_CRITERIA
    import time as _time
    started = _time.perf_counter()
    resp = requests.post(
        _ENDPOINT,
        headers={
            "Authorization": f"Bearer {_api_key()}",
            "Content-Type": "application/json",
        },
        json={
            "state": state,
            "model": "jev-latest",
            "questions": {
                name: {"type": "noul", "instructions": desc}
                for name, desc in criteria.items()
            },
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    elapsed = (_time.perf_counter() - started) * 1000
    data = resp.json()
    answers = data.get("answers", {})
    probabilities = {
        name: float((answers.get(name) or {}).get("noul", 0.0))
        for name in criteria
    }
    tokens = data.get("usage", {}).get("input_tokens", 0)
    LOG.info(
        "jev_gate_criteria %s tokens=%s latency=%.0fms",
        " ".join(f"{k}={v:.2f}" for k, v in probabilities.items()),
        tokens, elapsed,
    )
    return {
        "probabilities": probabilities,
        "input_tokens": tokens,
        "latency_ms": elapsed,
    }


def aggregate_gate_criteria(
    probabilities: dict[str, float],
    *,
    social_allowed: bool = True,
) -> dict[str, Any]:
    """Deterministic aggregation of criterion probabilities -> gate decision.

    Returns {decision: REPLY|PASS, hit: criterion|None, confident: bool,
    confident_decision: REPLY|PASS|None}.
    """
    thresholds = dict(GATE_REPLY_THRESHOLDS)
    if not social_allowed:
        thresholds.pop("social_hook", None)
    hit = None
    for name, threshold in thresholds.items():
        if probabilities.get(name, 0.0) >= threshold:
            hit = name
            break
    decision = "REPLY" if hit else "PASS"
    confident_decision = None
    if not hit and all(p <= GATE_CONFIDENT_PASS_MAX for p in probabilities.values()):
        confident_decision = "PASS"
    elif hit and probabilities.get(hit, 0.0) >= GATE_CONFIDENT_REPLY_MIN:
        confident_decision = "REPLY"
    return {
        "decision": decision,
        "hit": hit,
        "confident": confident_decision is not None,
        "confident_decision": confident_decision,
    }
