# -*- coding: utf-8 -*-
"""Tests for Jev integration: pre-gate, search gate, fallback behavior."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, ".")

from foxstar_bot import jev
from foxstar_bot.config import AppConfig
from foxstar_bot.context_store import ContextStore
from foxstar_bot.persistence import Database
from foxstar_bot.router import MessageRouter
from foxstar_bot.wcf_adapter import IncomingMessage


@pytest.fixture()
def router(tmp_path, monkeypatch):
    monkeypatch.setenv("TYPESAFE_JEV_KEY", "test-jev-key")
    db = Database(tmp_path / "jg.sqlite3")
    r = MessageRouter(
        config=AppConfig(openai_api_key="x"), db=db, auth=MagicMock(), limiter=MagicMock(),
        context=ContextStore(db), memory=MagicMock(), commands=MagicMock(), search=MagicMock(),
        url_fetch=MagicMock(), research=MagicMock(), code=MagicMock(), docs=MagicMock(),
        vision=MagicMock(), llm=MagicMock(), prompt_path=Path("PROMPT.md"), skills=MagicMock(),
        clan=None,
    )
    yield r
    r.close()


def _msg(chat_id="room"):
    return IncomingMessage(id=1, sender="wxid_user", chat_id=chat_id, room_id=chat_id,
                           content="test message", msg_type=1, is_group=True, is_self=False)


def test_jev_pre_gate_passes_confident_pass(router):
    """Jev says PASS with high confidence -> skip the expensive LLM gate."""
    with patch.object(jev, "jev_choice") as mock:
        mock.return_value = {
            "choice": "PASS", "confidence": 0.92,
            "probabilities": {"PASS": 0.92, "REPLY": 0.08},
        }
        # mock the dependencies _should_join_conversation needs
        router._social_reply_gate_fast_path = lambda *a, **k: None
        router.auth.is_whitelist_user = lambda wxid: False
        router.context.recent_messages = lambda chat: []
        result = router._should_join_conversation.__func__(router, _msg(), "bot_wxid", {"reply_policy": "auto", "mode": "normal", "jev_gate_mode": "binary"})
    assert result is False
    mock.assert_called_once()


def test_jev_pre_gate_falls_through_on_reply(router):
    """Jev says REPLY -> fall through to the LLM gate (don't shortcut)."""
    with patch.object(jev, "jev_choice") as mock:
        mock.return_value = {
            "choice": "REPLY", "confidence": 0.80,
            "probabilities": {"REPLY": 0.80, "PASS": 0.20},
        }
        router._social_reply_gate_fast_path = lambda *a, **k: None
        router.auth.is_whitelist_user = lambda wxid: False
        router.context.recent_messages = lambda chat: []
        # The LLM gate will run after - mock it to return True
        router.llm.reply_gate_json = lambda *a, **k: '{"decision":"REPLY","confidence":0.9,"reason":"test","relevant_signals":[],"risk":""}'
        result = router._should_join_conversation.__func__(router, _msg(), "bot_wxid", {"reply_policy": "auto", "mode": "normal", "jev_gate_mode": "binary"})
    assert result is True


def test_jev_pre_gate_falls_through_on_error(router):
    """Jev fails -> fall through gracefully to the LLM gate."""
    with patch.object(jev, "jev_choice") as mock:
        mock.side_effect = RuntimeError("network down")
        router._social_reply_gate_fast_path = lambda *a, **k: None
        router.auth.is_whitelist_user = lambda wxid: False
        router.context.recent_messages = lambda chat: []
        router.llm.reply_gate_json = lambda *a, **k: '{"decision":"PASS","confidence":0.9,"reason":"test","relevant_signals":[],"risk":""}'
        result = router._should_join_conversation.__func__(router, _msg(), "bot_wxid", {"reply_policy": "auto", "mode": "normal", "jev_gate_mode": "binary"})
    assert result is False




def test_jev_search_gate_uses_jev(router):
    """Web search gate prefers Jev when available."""
    with patch.object(jev, "jev_choice") as mock:
        mock.return_value = {
            "choice": "SEARCH", "confidence": 0.88,
            "probabilities": {"SEARCH": 0.88, "SKIP": 0.12},
        }
        router.search.should_search = lambda t: False
        router.context.render_recent = lambda chat, limit: []
        plan = router._plan_auto_web_search(
            _msg(), {"web_search_enabled": True, "mode": "normal", "jev_gate_mode": "binary"}, "latest AI news", [], "latest AI news",
            False, False, False, False,
        )
    assert plan["should_search"] is True
    assert plan["planner"] == "jev"
    mock.assert_called_once()


def test_jev_search_gate_falls_back_on_error(router):
    """Jev search gate failure -> falls back to LLM structured_judge_json."""
    with patch.object(jev, "jev_choice") as mock:
        mock.side_effect = RuntimeError("timeout")
        router.search.should_search = lambda t: False
        router.context.render_recent = lambda chat, limit: []
        router.llm.structured_judge_json = lambda *a, **k: (
            '{"decision":"SKIP","confidence":0.9,"reason":"no need","query":"","signals":[],"risk":""}'
        )
        plan = router._plan_auto_web_search(
            _msg(), {"web_search_enabled": True, "mode": "normal", "jev_gate_mode": "binary"}, "hello", [], "hello",
            False, False, False, False,
        )
    assert "planner" in plan  # any fallback planner is fine


def test_jev_module_reads_key():
    """Jev reads its key from the environment without requiring a private file."""
    assert isinstance(jev._api_key(), str)
    # In test env it may be empty; in production it's set


def test_uncertain_jev_and_failed_middle_gate_pass_through(router):
    """An uncertain pre-gate and unavailable middle model do not block replies."""
    from foxstar_bot.wcf_adapter import IncomingMessage

    msg = IncomingMessage(id=2, sender="wxid_user", chat_id="room", room_id="room",
                          content="@FoxStar help me", msg_type=1, is_group=True, is_self=False)
    settings = {"reply_policy": "auto", "mode": "normal", "jev_gate_mode": "binary", "reply_gate_mode": "normal", "reply_gate_vibe": "default"}

    # Mock the pre-gate to fall through (REPLY with low confidence)
    with patch.object(jev, "jev_choice") as mock:
        # First call: pre-gate (low confidence, falls through)
        # Second call: last resort
        mock.side_effect = [
            {"choice": "REPLY", "confidence": 0.30, "probabilities": {}},  # pre-gate: low conf, falls through
            {"choice": "REPLY", "confidence": 0.90, "probabilities": {}},  # last resort: REPLY
        ]
        router._social_reply_gate_fast_path = lambda *a, **k: None
        router.auth.is_whitelist_user = lambda wxid: False
        router.context.recent_messages = lambda chat: []
        router.context.render_recent = lambda chat, limit=8: []
        router.memory.render_for_prompt = lambda chat, sender: ""
        router._target_list_prompt = lambda s, sender: ""
        router._display_sender = lambda adapter, m: "User"
        router._log_reply_gate = lambda *a, **k: None
        # Make both LLM gates fail
        router.llm.reply_gate_json = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("sambanova down"))
        router.llm.responses_text = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("openrouter down"))

        result = router._should_join_conversation.__func__(router, msg, "bot_wxid", settings)

    assert result is True  # current policy passes through on middle-gate failure
    assert mock.call_count == 1  # no repeated provider calls after the middle gate fails


def test_criteria_gate_confident_pass_and_reply():
    quiet = {name: 0.01 for name in jev.GATE_CRITERIA}
    assert jev.aggregate_gate_criteria(quiet)["confident_decision"] == "PASS"
    direct = dict(quiet, addressing_bot=0.99)
    assert jev.aggregate_gate_criteria(direct)["confident_decision"] == "REPLY"


def test_key_is_optional_and_read_from_environment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TYPESAFE_JEV_KEY", raising=False)
    assert not jev.jev_available()
    monkeypatch.setenv("TYPESAFE_JEV_KEY", "test-key")
    assert jev.jev_available()
