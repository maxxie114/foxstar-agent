# -*- coding: utf-8 -*-
"""Tool-call leak regression table (redesign_plan/TOOLCALL_LEAK.md step 4).

Discipline: every new provider dialect that ever leaks gets added here
BEFORE the fix ships; every false-positive class gets an anti-case.
"""
from foxstar_bot.router import _extract_leaked_reject_reason, _looks_like_tool_leak

# --- real incident samples ---

def test_glm_incident_truncated_form():
    # The actual 2026-07 leak: opening <tool_call> missing entirely.
    text = (
        "_drop_reply_internal<arg_key>reason</arg_key>"
        "<arg_value>离尘在聊自己的实习计划，络合在问问题，没有直接对猫猫说话，不需要插嘴。</arg_value>"
        "</tool_call>"
    )
    assert _looks_like_tool_leak(text) is True
    assert _extract_leaked_reject_reason(text) == (
        "离尘在聊自己的实习计划，络合在问问题，没有直接对猫猫说话，不需要插嘴。"
    )


def test_glm_full_form():
    text = (
        "<tool_call>_drop_reply_internal<arg_key>reason</arg_key>"
        "<arg_value>纯闲聊</arg_value></tool_call>"
    )
    assert _looks_like_tool_leak(text) is True
    assert _extract_leaked_reject_reason(text) == "纯闲聊"


def test_glm_mixed_with_normal_text():
    # Leak appended after a normal sentence: whole reply is contaminated.
    text = "这题答案是B喵。<tool_call>web_research<arg_key>query</arg_key><arg_value>x</arg_value></tool_call>"
    assert _looks_like_tool_leak(text) is True


# --- historical dialects must stay caught ---

def test_json_blob_form():
    assert _looks_like_tool_leak('{"name":"reject_response","arguments":{"reason":"x"}}') is True

def test_function_call_form():
    assert _looks_like_tool_leak("_drop_reply_internal(不需要回复)") is True

def test_fenced_form():
    assert _looks_like_tool_leak("```json\n{\"name\":\"update_memory\",\"arguments\":{}}\n```") is True


# --- false-positive discipline: legit chat must never be killed ---

def test_prose_mentioning_tool_names():
    assert _looks_like_tool_leak("你那个 web_research 工具是不是坏了，fetch_url 也打不开") is False

def test_tech_discussion_of_functions():
    assert _looks_like_tool_leak("这里应该写一个 parse_config() 函数，然后调用 load_skill") is False

def test_normal_reply():
    assert _looks_like_tool_leak("喵，今天行情一般般") is False
