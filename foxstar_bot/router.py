from __future__ import annotations

import json

import re

from .llm_client import TERMINAL_REJECT_TOOL_NAME

from .reply_style import split_reply_messages

from .style_profiles import parse_stored_style

import logging

from concurrent.futures import ThreadPoolExecutor

from threading import Lock

from .context_store import CONTEXT_COMPRESSION_MESSAGES, ContextStore, normalize_context_messages

from .persistence import utc_now

from .privacy import redact_private_ids

LOG = logging.getLogger(__name__)

from typing import Any

def delivery_parts_for_style(reply: str, style_value: object, line_chars: int | None = None) -> list[str]:
    text = (reply or "").strip()
    if not text:
        return []
    style = parse_stored_style(str(style_value or "strict"))
    if style.format_style == "free":
        return [text]
    if style.format_style == "human":
        return split_reply_messages(
            text,
            max_messages=0,
            max_single_chars=140,
            max_line_chars=line_chars or 70,
            split_on_sentences=True,
        )
    return split_reply_messages(
        text,
        max_messages=0,
        max_line_chars=line_chars or 45,
        split_on_sentences=True,
    )

def _parse_reply_decision(decision: str) -> bool:
    first = (decision or "").strip().split()
    if not first:
        return False
    return first[0].strip(" .,:;!?\n\t").upper() == "REPLY"

def _parse_reply_gate_decision(output: str) -> dict[str, object]:
    text = (output or "").strip()
    data: dict[str, object] | None = None
    if text:
        try:
            loaded = json.loads(text)
            if isinstance(loaded, dict):
                data = loaded
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", text)
            if match:
                try:
                    loaded = json.loads(match.group(0))
                    if isinstance(loaded, dict):
                        data = loaded
                except json.JSONDecodeError:
                    data = None
    if data is None:
        decision = "REPLY" if _parse_reply_decision(text) else "PASS"
        return {
            "decision": decision,
            "confidence": 0.0,
            "reason": "fallback parser used; model did not return valid JSON",
            "relevant_signals": [],
            "risk": "invalid_json",
        }
    decision = str(data.get("decision") or "").strip().upper()
    if decision not in {"REPLY", "PASS"}:
        decision = "REPLY" if _parse_reply_decision(text) else "PASS"
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(confidence, 1.0))
    signals = data.get("relevant_signals", [])
    if not isinstance(signals, list):
        signals = [str(signals)]
    return {
        "decision": decision,
        "confidence": confidence,
        "reason": str(data.get("reason") or "")[:500],
        "relevant_signals": [str(item)[:200] for item in signals[:8]],
        "risk": str(data.get("risk") or "")[:300],
    }

def _looks_like_tool_leak(text: str) -> bool:
    value = (text or "").strip()
    if not value:
        return False
    compact = " ".join(value.split())
    tool_names = (
        "reject_response",
        TERMINAL_REJECT_TOOL_NAME,
        "update_memory",
        "web_research",
        "fetch_url",
        "analyze_recent_image",
        "run_python_code",
    )
    if any(
        re.fullmatch(rf"(?:```(?:json|tool_code|python)?\s*)?{re.escape(name)}\s*\([\s\S]*\)\s*(?:```)?", value, re.IGNORECASE)
        for name in tool_names
    ):
        return True
    if re.fullmatch(r"(?:```(?:json)?\s*)?\{[\s\S]*\}\s*(?:```)?", value, re.IGNORECASE):
        lowered = compact.lower()
        if any(
            token in lowered
            for token in (
                '"name":"reject_response"',
                f'"name":"{TERMINAL_REJECT_TOOL_NAME.lower()}"',
                '"tool":"reject_response"',
                f'"tool":"{TERMINAL_REJECT_TOOL_NAME.lower()}"',
                '"function":"reject_response"',
                f'"function":"{TERMINAL_REJECT_TOOL_NAME.lower()}"',
                '"name":"update_memory"',
                '"tool":"update_memory"',
            )
        ):
            return True
    return False

def _is_timeout_error(exc: Exception) -> bool:
    current: BaseException | None = exc
    while current is not None:
        name = current.__class__.__name__.lower()
        if "timeout" in name:
            return True
        current = current.__cause__
    return False
