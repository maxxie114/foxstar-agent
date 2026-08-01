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

CONTEXT_COMPRESSION_REFRESH_MESSAGES = 20

CONTEXT_COMPRESSION_MAX_PENDING_CHATS = 8

def delivery_parts_for_style(reply: str, style_value: object, line_chars: int | None = None) -> list[str]:
    text = (reply or "").strip()
    if not text:
        return []
    style = parse_stored_style(str(style_value or "strict"))
    if style.format_style == "free":


        return _wechat_safe_sections(text)
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

WECHAT_MAX_PART_BYTES = 1500

def _wechat_safe_sections(text: str) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    if len(text.encode("utf-8")) <= WECHAT_MAX_PART_BYTES:
        return [text]


    sections = [s.strip() for s in re.split(r"\n\s*\n", text) if s.strip()]


    atoms: list[str] = []
    for section in sections:
        if len(section.encode("utf-8")) <= WECHAT_MAX_PART_BYTES:
            atoms.append(section)
            continue
        lines = [ln.strip() for ln in section.splitlines() if ln.strip()]
        for ln in lines:
            if len(ln.encode("utf-8")) <= WECHAT_MAX_PART_BYTES:
                atoms.append(ln)
            else:
                atoms.extend(_hard_wrap_utf8(ln, WECHAT_MAX_PART_BYTES))

    parts: list[str] = []
    chunk: list[str] = []
    chunk_bytes = 0
    for atom in atoms:
        join_overhead = (2 if chunk else 0)
        atom_bytes = len(atom.encode("utf-8"))
        if chunk and chunk_bytes + join_overhead + atom_bytes > WECHAT_MAX_PART_BYTES:
            parts.append("\n\n".join(chunk))
            chunk, chunk_bytes = [], 0
            join_overhead = 0
        chunk.append(atom)
        chunk_bytes += join_overhead + atom_bytes
    if chunk:
        parts.append("\n\n".join(chunk))
    return [p for p in parts if p.strip()]

def _hard_wrap_utf8(text: str, max_bytes: int) -> list[str]:
    out: list[str] = []
    buf: list[str] = []
    buf_bytes = 0
    for ch in text:
        ch_bytes = len(ch.encode("utf-8"))
        if buf and buf_bytes + ch_bytes > max_bytes:
            out.append("".join(buf))
            buf, buf_bytes = [], 0
        buf.append(ch)
        buf_bytes += ch_bytes
    if buf:
        out.append("".join(buf))
    return out

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

def _auto_web_search_plan_schema() -> dict[str, object]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "auto_web_search_plan",
            "schema": {
                "type": "object",
                "properties": {
                    "decision": {"type": "string", "enum": ["SEARCH", "SKIP"]},
                    "confidence": {"type": "number"},
                    "reason": {"type": "string"},
                    "query": {"type": "string"},
                    "signals": {"type": "array", "items": {"type": "string"}},
                    "risk": {"type": "string"},
                },
                "required": ["decision", "confidence", "reason", "query", "signals", "risk"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    }

def _parse_auto_web_search_plan(output: str, *, fallback_query: str) -> dict[str, object]:
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
        return {
            "should_search": False,
            "query": "",
            "reason": "invalid_json",
            "confidence": 0.0,
            "signals": [],
            "risk": "invalid_json",
        }
    decision = str(data.get("decision") or "").strip().upper()
    if decision not in {"SEARCH", "SKIP"}:
        decision = "SKIP"
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(confidence, 1.0))
    query = str(data.get("query") or "").strip()
    if decision == "SEARCH" and not query:
        query = fallback_query
    signals = data.get("signals", [])
    if not isinstance(signals, list):
        signals = [str(signals)]
    return {
        "should_search": decision == "SEARCH",
        "query": query,
        "reason": str(data.get("reason") or "")[:500],
        "confidence": confidence,
        "signals": [str(item)[:200] for item in signals[:8]],
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
        "search_knowledge_base",
        "discover_skills",
        "load_skill",
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

def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0

def _is_timeout_error(exc: Exception) -> bool:
    current: BaseException | None = exc
    while current is not None:
        name = current.__class__.__name__.lower()
        if "timeout" in name:
            return True
        current = current.__cause__
    return False

class ContextCompressor:
    def __init__(self, db, llm, config):
        self.db = db
        self.llm = llm
        self.config = config
        self.context = ContextStore(db)
        self._context_compression_executor = ThreadPoolExecutor(max_workers=2)
        self._context_compression_futures = {}
        self._context_compression_lock = Lock()
        self._context_compression_closed = False

    def refresh(self, chat_id, context_messages):
        context_messages = normalize_context_messages(context_messages)
        cached = self._context_summary_cache(chat_id, context_messages)
        limit = CONTEXT_COMPRESSION_MESSAGES
        if self.config.model.context_compression_provider == "sambanova":
            limit = max(4, min(12, (3000 - len(str(cached.get("summary") or ""))) // 200))
        source, _, _ = self.context.rolling_window(
            chat_id, max_turns=context_messages,
            summarized_through_id=_safe_int(cached.get("source_last_id", 0)),
            compression_limit=limit,
        )
        self._schedule_context_compression(chat_id, context_messages, source, cached)
        return cached

    def close(self):
        with self._context_compression_lock:
            self._context_compression_closed = True
        self._context_compression_executor.shutdown(wait=True)

    def _context_summary_cache(self, chat_id: str, context_messages: int) -> dict[str, object]:
        value = self.db.get_setting(f"group_context_summary:{chat_id}", {})
        if not isinstance(value, dict) or int(value.get("context_messages", 0) or 0) != context_messages:
            return {}
        return value
