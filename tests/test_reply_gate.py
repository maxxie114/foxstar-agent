from foxstar_bot.auth import AuthService
from foxstar_bot.commands import CommandProcessor
from foxstar_bot.config import AppConfig, ReplyTimingConfig
from foxstar_bot.context_store import ContextStore
from foxstar_bot.limiter import LimitResult
from foxstar_bot.llm_client import TERMINAL_REJECT_TOOL_NAME, _handle_plaintext_tool_call
from foxstar_bot.memory_store import MemoryStore
from foxstar_bot.persistence import Database
from foxstar_bot.privacy import public_display_name, redact_private_ids
from foxstar_bot.router import (
    MessageRouter,
    WECHAT_EMOJI_PROMPT,
    _parse_group_member_event,
    _parse_reply_decision,
)
from foxstar_bot.skills import SkillRegistry
from foxstar_bot.wcf_adapter import IncomingMessage


def _make_router(tmp_path, prompt_text: str = "DEFAULT PROMPT") -> tuple[MessageRouter, Database]:
    config = AppConfig(openai_api_key="x", sambanova_api_key="test-key", openrouter_api_key="test-key")
    db = Database(tmp_path / "bot.sqlite3")
    memory = MemoryStore(db)
    prompt_path = tmp_path / "PROMPT.md"
    prompt_path.write_text(prompt_text, encoding="utf-8")
    router = MessageRouter(
        config=config,
        db=db,
        auth=AuthService(config),
        limiter=None,
        context=ContextStore(db),
        memory=memory,
        commands=CommandProcessor(config, db, memory),
        search=None,
        url_fetch=None,
        docs=None,
        vision=None,
        llm=None,
        prompt_path=prompt_path,
        clan=None,
        code=None,
        research=None,
    )
    return router, db


def test_parse_reply_decision_accepts_only_reply_token():
    assert _parse_reply_decision("REPLY")
    assert _parse_reply_decision("reply\nbecause relevant")
    assert not _parse_reply_decision("PASS")
    assert not _parse_reply_decision("I would reply")


def test_wechat_emoji_prompt_lists_builtin_tokens():
    assert "[旺柴]" in WECHAT_EMOJI_PROMPT
    assert "[捂脸]" in WECHAT_EMOJI_PROMPT
    assert "[转圈]" in WECHAT_EMOJI_PROMPT
    assert "0-2" in WECHAT_EMOJI_PROMPT






def test_redact_private_ids_removes_wxid_example014():
    text = "@示例乙(wxid_example019) 这句不成立，微信号: example-handle，群 900000003@chatroom"

    redacted = redact_private_ids(text)

    assert "wxid_" not in redacted
    assert "example-handle" not in redacted
    assert "@chatroom" not in redacted
    assert redacted.startswith("@示例乙 ")


def test_public_display_name_never_returns_raw_id():
    assert public_display_name("示例甲", "wxid_example020") == "示例甲"
    assert public_display_name("example-handle", "example-handle").startswith("用户")


def test_direct_reply_policy_only_triggers_at_or_quoted_bot(tmp_path):
    class FakeAdapter:
        def is_at_me(self, msg, self_wxid):
            return "@FoxStar" in msg.content

        def is_file_message(self, msg):
            return False

        def is_image_message(self, msg):
            return False

    router, db = _make_router(tmp_path)
    db.set_setting("group_reply_policy:room", "direct")
    settings = router._group_settings("room")

    plain = IncomingMessage(1, "wxid_user", "room", "room", "hello", 1, True, False)
    tagged = IncomingMessage(2, "wxid_user", "room", "room", "@FoxStar hello", 1, True, False)
    quoted = IncomingMessage(
        3,
        "wxid_user",
        "room",
        "room",
        "[引用消息]\n当前回复: hi\n引用原文: FoxStar: old",
        49,
        True,
        False,
    )

    assert not router._is_triggered(FakeAdapter(), plain, "wxid_example011ot", settings, False)
    assert router._is_triggered(FakeAdapter(), tagged, "wxid_example011ot", settings, False)
    assert router._is_triggered(FakeAdapter(), quoted, "wxid_example011ot", settings, False)


def test_main_model_cooldown_blocks_non_admin_after_gate(tmp_path):
    router, db = _make_router(tmp_path)
    db.set_setting("group_api_cooldown_seconds:room", 10)
    settings = router._group_settings("room")
    msg = IncomingMessage(1, "wxid_user", "room", "room", "hello", 1, True, False)

    assert router._check_and_record_main_model_cooldown(msg, settings, bypass=False)
    assert not router._check_and_record_main_model_cooldown(msg, settings, bypass=False)
    assert router._check_and_record_main_model_cooldown(msg, settings, bypass=True)


def test_whitelist_bypasses_reply_delay(tmp_path, monkeypatch):
    router, db = _make_router(tmp_path)
    db.set_setting("group_reply_delay:room", {"min": 5.0, "max": 10.0, "between": 5.0})
    settings = router._group_settings("room")
    sleeps = []
    monkeypatch.setattr("foxstar_bot.router.time.sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr("foxstar_bot.router.random.uniform", lambda min_delay, max_delay: max_delay)

    router._sleep_before_reply(settings, is_admin=True)
    router._sleep_between_reply_parts(settings, is_admin=True)
    router._sleep_before_reply(settings, is_admin=False)
    router._sleep_between_reply_parts(settings, is_admin=False)

    assert sleeps == [10.0, 5.0]


def test_reply_gate_uses_configured_middle_model(tmp_path):
    class FakeLLM:
        def __init__(self):
            self.kwargs = None

        def reply_gate_json(self, instructions, payload, **kwargs):
            self.kwargs = kwargs
            return "PASS"

    router, db = _make_router(tmp_path)
    fake_llm = FakeLLM()
    router.llm = fake_llm
    msg = IncomingMessage(1, "wxid_user", "room", "room", "hello", 1, True, False)
    settings = router._group_settings("room")

    assert not router._should_join_conversation(msg, "wxid_example011ot", settings)
    assert fake_llm.kwargs["model"] == router.config.model.reply_gate_middle_model
    assert fake_llm.kwargs["provider"] == router.config.model.reply_gate_middle_provider
    assert fake_llm.kwargs["timeout"] == 4.0


def test_main_tools_include_terminal_reject_response(tmp_path):
    router, db = _make_router(tmp_path)
    settings = router._group_settings("room")

    specs = router._tool_specs(settings)
    handlers = router._tool_handlers(adapter=None, chat_id="room", sender_id="wxid_user", is_admin=False)
    result = handlers["reject_response"]("irrelevant side chatter")

    assert any(tool["name"] == TERMINAL_REJECT_TOOL_NAME for tool in specs)
    assert TERMINAL_REJECT_TOOL_NAME in handlers
    assert result["__terminal_response__"] is True
    assert result["text"] == ""
    assert result["reason"] == "irrelevant side chatter"


def test_plaintext_tool_interpreter_only_executes_terminal_reject(tmp_path):
    router, db = _make_router(tmp_path)
    handlers = router._tool_handlers(adapter=None, chat_id="room", sender_id="wxid_user", is_admin=False)

    terminal = _handle_plaintext_tool_call(f'{TERMINAL_REJECT_TOOL_NAME}("side chatter")', handlers)
    blocked = _handle_plaintext_tool_call('web_research({"query":"btc"})', handlers)

    assert terminal is not None
    assert terminal["__terminal_response__"] is True
    assert blocked is not None
    assert blocked["__blocked_plaintext_tool__"] is True
    assert blocked["name"] == "web_research"


def test_router_reads_group_model_and_reasoning_overrides(tmp_path):
    router, db = _make_router(tmp_path)
    db.set_setting("group_reply_model:room", "gpt-5.2")
    db.set_setting("group_reasoning_effort:room", "high")
    db.set_setting("group_verbosity:room", "low")

    settings = router._group_settings("room")

    assert router._reply_model(settings) == "gpt-5.2"
    assert router._reply_reasoning_effort(settings) == "high"
    assert router._reply_verbosity(settings) == "low"


def test_router_selects_low_medium_high_layers(tmp_path):
    from types import SimpleNamespace
    router, db = _make_router(tmp_path)
    router.llm = SimpleNamespace(sambanova_client=object(), openrouter_client=object())
    db.set_setting("group_model_router_enabled:room", True)
    db.set_setting("group_reply_model:room", "gpt-5.2")

    settings = router._group_settings("room")

    low = router._select_reply_route(settings, "哈哈好的", [])
    medium = router._select_reply_route(settings, "帮我分析一下这个观点为什么不成立", [])
    high = router._select_reply_route(settings, "1. 统计一下名单\n2. 列出没接龙的人\n3. 解释原因\n4. 给出完整分析", [])

    assert low["layer"] == "low"
    assert low["provider"] == router.config.model_router.low.provider
    assert medium["layer"] == "medium"
    assert medium["model"] == "gpt-5.2"
    assert high["layer"] == "high"
    assert high["model"] == router.config.model_router.high.model


def test_router_effective_user_daily_limit_prefers_specific_then_global(tmp_path):
    router, db = _make_router(tmp_path)
    db.set_setting("global_user_daily_limit", 25)
    db.set_setting("user_daily_limit:wxid_user", 7)

    assert router._effective_user_daily_limit("wxid_user") == 7
    assert router._effective_user_daily_limit("wxid_example024") == 25


def test_context_compression_window_keeps_recent_30_and_caps_older_at_500(tmp_path):
    db = Database(tmp_path / "bot.sqlite3")
    context = ContextStore(db)
    for index in range(85):
        context.add_message("room", f"wxid_{index}", "user", f"message {index}")

    older, recent, signature = context.compression_window("room")

    assert len(recent) == 30
    assert recent[0]["content"] == "message 55"
    assert recent[-1]["content"] == "message 84"
    assert len(older) == 55
    assert older[0]["content"] == "message 0"
    assert older[-1]["content"] == "message 54"
    assert signature


def test_admin_identity_uses_explicit_owner_not_whitelist_order(tmp_path):
    config = AppConfig(
        openai_api_key="x",
        owner_user_id="wxid_owner",
        whitelist_user_ids=["wxid_example024", "wxid_owner"],
    )
    db = Database(tmp_path / "bot.sqlite3")
    memory = MemoryStore(db)
    router = MessageRouter(
        config=config,
        db=db,
        auth=AuthService(config),
        limiter=None,
        context=ContextStore(db),
        memory=memory,
        commands=CommandProcessor(config, db, memory),
        search=None,
        url_fetch=None,
        docs=None,
        vision=None,
        llm=None,
        prompt_path=tmp_path / "PROMPT.md",
        clan=None,
        code=None,
        research=None,
    )

    prompt = router._admin_identity_prompt("wxid_owner", is_admin=True)

    assert "current sender role is owner" in prompt
    assert "wxid_owner" not in prompt
    assert "WeChat IDs are private" in prompt


def test_router_reads_group_blacklist(tmp_path):
    router, db = _make_router(tmp_path)
    db.set_setting("group_blacklist:room", ["wxid_example022"])

    settings = router._group_settings("room")

    assert "wxid_example022" in settings["blacklist"]


def test_router_uses_group_prompt_template(tmp_path):
    router, db = _make_router(tmp_path)
    db.set_setting("group_prompt_profile:room", "roast")

    prompt = router._system_prompt("room")

    assert "Roast Prompt" in prompt
    assert "DEFAULT PROMPT" not in prompt


def test_router_uses_default_prompt_template(tmp_path):
    router, db = _make_router(tmp_path)
    db.set_setting("group_prompt_profile:room", "default")

    prompt = router._system_prompt("room")

    assert "Default Prompt" in prompt
    assert "DEFAULT PROMPT" not in prompt


def test_router_uses_custom_group_prompt(tmp_path):
    router, db = _make_router(tmp_path)
    db.set_setting("group_prompt_profile:room", "custom")
    db.set_setting("group_prompt_custom:room", "CUSTOM SYSTEM PROMPT")

    prompt = router._system_prompt("room")

    assert "CUSTOM SYSTEM PROMPT" in prompt
    assert "Priority Compliance & Security Guardrail" in prompt


def test_router_falls_back_to_default_prompt(tmp_path):
    router, db = _make_router(tmp_path)
    db.set_setting("group_prompt_profile:room", "missing-template")

    assert "Default Prompt" in router._system_prompt("room")


def test_router_uses_prompt_md_when_group_prompt_is_cleared(tmp_path):
    router, db = _make_router(tmp_path)
    db.set_setting("group_prompt_profile:room", "main")

    prompt = router._system_prompt("room")

    assert "DEFAULT PROMPT" in prompt
    assert "Priority Compliance & Security Guardrail" in prompt


def test_router_includes_available_skill_catalog_in_system_messages(tmp_path):
    config = AppConfig(openai_api_key="x", sambanova_api_key="test-key", openrouter_api_key="test-key")
    db = Database(tmp_path / "bot.sqlite3")
    memory = MemoryStore(db)
    prompt_path = tmp_path / "PROMPT.md"
    prompt_path.write_text("DEFAULT PROMPT", encoding="utf-8")
    skill_dir = tmp_path / "skills" / "yfinance_quote"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "# Yahoo Finance Quote Lookup\n\nUse coding tools to fetch market quotes.\n",
        encoding="utf-8",
    )
    router = MessageRouter(
        config=config,
        db=db,
        auth=AuthService(config),
        limiter=None,
        context=ContextStore(db),
        memory=memory,
        commands=CommandProcessor(config, db, memory, skills=SkillRegistry(tmp_path / "skills")),
        search=None,
        url_fetch=None,
        docs=None,
        vision=None,
        llm=None,
        prompt_path=prompt_path,
        skills=SkillRegistry(tmp_path / "skills"),
        clan=None,
        code=None,
        research=None,
    )
    settings = router._group_settings("room")
    msg = IncomingMessage(1, "wxid_user", "room", "room", "查一下价格", 1, True, False)

    messages = router._assemble_messages(msg, msg.content, [], settings, is_admin=True)
    catalog = "\n".join(item["content"] for item in messages if item["role"] == "system")

    assert "Available local skills you can use right now" in catalog
    assert "yfinance_quote" in catalog
    assert "Use coding tools to fetch market quotes." in catalog


def test_router_does_not_send_fallback_on_error(tmp_path):
    class FailingRouter(MessageRouter):
        def _build_reply(self, adapter, msg, settings, is_admin):
            raise RuntimeError("boom")

    class FakeLimiter:
        def check_and_record(self, *args, **kwargs):
            return LimitResult(True)

    class FakeAdapter:
        sent: list[tuple[str, str]]

        def __init__(self):
            self.sent = []

        def send_text(self, receiver: str, text: str):
            self.sent.append((receiver, text))

        def is_file_message(self, msg):
            return False

        def is_image_message(self, msg):
            return False

    config = AppConfig(
        openai_api_key="x",
        manual_debug=True,
        reply_timing=ReplyTimingConfig(min_delay_seconds=0, max_delay_seconds=0, between_messages_seconds=0),
    )
    db = Database(tmp_path / "bot.sqlite3")
    memory = MemoryStore(db)
    router = FailingRouter(
        config=config,
        db=db,
        auth=AuthService(config),
        limiter=FakeLimiter(),
        context=ContextStore(db),
        memory=memory,
        commands=CommandProcessor(config, db, memory),
        search=None,
        url_fetch=None,
        docs=None,
        vision=None,
        llm=None,
        prompt_path=tmp_path / "PROMPT.md",
        clan=None,
        code=None,
        research=None,
    )
    adapter = FakeAdapter()
    msg = IncomingMessage(
        id=1,
        sender="wxid_user",
        chat_id="room",
        room_id="room",
        content="hello",
        msg_type=1,
        is_group=True,
        is_self=False,
    )

    router.handle(adapter, msg, "wxid_example011ot")

    assert adapter.sent == []


def test_global_bot_off_passively_logs_without_reply(tmp_path):
    class FakeLimiter:
        def check_and_record(self, *args, **kwargs):
            raise AssertionError("rate limiter should not run")

    class FakeAdapter:
        def __init__(self):
            self.sent = []

        def send_text(self, receiver: str, text: str):
            self.sent.append((receiver, text))

        def is_file_message(self, msg):
            return False

        def is_image_message(self, msg):
            return False

    config = AppConfig(openai_api_key="x", sambanova_api_key="test-key", openrouter_api_key="test-key")
    db = Database(tmp_path / "bot.sqlite3")
    db.set_setting("global_bot_enabled", False)
    memory = MemoryStore(db)
    router = MessageRouter(
        config=config,
        db=db,
        auth=AuthService(config),
        limiter=FakeLimiter(),
        context=ContextStore(db),
        memory=memory,
        commands=CommandProcessor(config, db, memory),
        search=None,
        url_fetch=None,
        docs=None,
        vision=None,
        llm=None,
        prompt_path=tmp_path / "PROMPT.md",
        clan=None,
        code=None,
        research=None,
    )
    adapter = FakeAdapter()
    msg = IncomingMessage(
        id=1,
        sender="wxid_user",
        chat_id="room",
        room_id="room",
        content="@FoxStar hello",
        msg_type=1,
        is_group=True,
        is_self=False,
    )

    router.handle(adapter, msg, "wxid_example011ot")

    assert adapter.sent == []
    assert router.context.recent_messages("room")[0]["content"] == "@FoxStar hello"


def test_global_bot_off_allows_group_with_explicit_override(tmp_path):
    class ReplyRouter(MessageRouter):
        def _build_reply(self, adapter, msg, settings, is_admin):
            return "pong"

    class FakeLimiter:
        def check_and_record(self, *args, **kwargs):
            return LimitResult(True)

    class FakeAdapter:
        def __init__(self):
            self.sent = []

        def is_image_message(self, msg):
            return False

        def is_at_me(self, msg, self_wxid):
            return "@FoxStar" in msg.content

        def send_text(self, receiver: str, text: str):
            self.sent.append((receiver, text))

        def is_file_message(self, msg):
            return False

    config = AppConfig(openai_api_key="x", whitelist_user_ids=["wxid_example009dmin"])
    db = Database(tmp_path / "bot.sqlite3")
    db.set_setting("global_bot_enabled", False)
    db.set_setting("group_global_override:room", True)
    memory = MemoryStore(db)
    router = ReplyRouter(
        config=config,
        db=db,
        auth=AuthService(config),
        limiter=FakeLimiter(),
        context=ContextStore(db),
        memory=memory,
        commands=CommandProcessor(config, db, memory),
        search=None,
        url_fetch=None,
        docs=None,
        vision=None,
        llm=None,
        prompt_path=tmp_path / "PROMPT.md",
        clan=None,
        code=None,
        research=None,
    )
    adapter = FakeAdapter()
    msg = IncomingMessage(
        id=1,
        sender="wxid_user",
        chat_id="room",
        room_id="room",
        content="@FoxStar hello",
        msg_type=1,
        is_group=True,
        is_self=False,
    )

    router.handle(adapter, msg, "wxid_example011ot")

    assert adapter.sent == [("room", "pong")]


def test_global_bot_off_does_not_block_private_whitelist_chat(tmp_path):
    class ReplyRouter(MessageRouter):
        def _build_reply(self, adapter, msg, settings, is_admin):
            return "private pong"

    class FakeLimiter:
        def check_and_record(self, *args, **kwargs):
            return LimitResult(True)

    class FakeAdapter:
        def __init__(self):
            self.sent = []

        def is_image_message(self, msg):
            return False

        def send_text(self, receiver: str, text: str):
            self.sent.append((receiver, text))

        def is_file_message(self, msg):
            return False

    config = AppConfig(openai_api_key="x", whitelist_user_ids=["wxid_example009dmin"])
    db = Database(tmp_path / "bot.sqlite3")
    db.set_setting("global_bot_enabled", False)
    memory = MemoryStore(db)
    router = ReplyRouter(
        config=config,
        db=db,
        auth=AuthService(config),
        limiter=FakeLimiter(),
        context=ContextStore(db),
        memory=memory,
        commands=CommandProcessor(config, db, memory),
        search=None,
        url_fetch=None,
        docs=None,
        vision=None,
        llm=None,
        prompt_path=tmp_path / "PROMPT.md",
        clan=None,
        code=None,
        research=None,
    )
    adapter = FakeAdapter()
    msg = IncomingMessage(
        id=1,
        sender="wxid_example009dmin",
        chat_id="wxid_example009dmin",
        room_id="",
        content="hello",
        msg_type=1,
        is_group=False,
        is_self=False,
    )

    router.handle(adapter, msg, "wxid_example011ot")

    assert adapter.sent == [("wxid_example009dmin", "private pong")]


def test_parse_group_member_event():
    assert _parse_group_member_event('"Alice" joined the group chat') == ("joined", "Alice")
    assert _parse_group_member_event('"Bob" left the group chat') == ("left", "Bob")
    assert _parse_group_member_event('"张三"加入了群聊') == ("joined", "张三")


def test_idlookup_reads_quoted_sender_from_xml(tmp_path):
    class Raw:
        content = """<?xml version="1.0"?>
<msg>
  <appmsg>
    <title>/idlookup</title>
    <type>57</type>
    <refermsg>
      <chatusr>wxid_example026</chatusr>
      <displayname>Quoted Name</displayname>
      <content>hello</content>
    </refermsg>
  </appmsg>
</msg>"""

    class FakeAdapter:
        def __init__(self):
            self.sent = []

        def send_text(self, receiver: str, text: str):
            self.sent.append((receiver, text))

        def display_name(self, wxid: str, room_id: str = "") -> str:
            return "Resolved Name"

        def is_at_me(self, msg, self_wxid):
            return False

        def is_file_message(self, msg):
            return False

        def is_image_message(self, msg):
            return False

    config = AppConfig(openai_api_key="x", whitelist_user_ids=["wxid_example009dmin"])
    db = Database(tmp_path / "bot.sqlite3")
    memory = MemoryStore(db)
    router = MessageRouter(
        config=config,
        db=db,
        auth=AuthService(config),
        limiter=None,
        context=ContextStore(db),
        memory=memory,
        commands=CommandProcessor(config, db, memory),
        search=None,
        url_fetch=None,
        docs=None,
        vision=None,
        llm=None,
        prompt_path=tmp_path / "PROMPT.md",
        clan=None,
        code=None,
        research=None,
    )
    adapter = FakeAdapter()
    msg = IncomingMessage(
        id=1,
        sender="wxid_example009dmin",
        chat_id="room",
        room_id="room",
        content="[引用消息]\n当前回复: /idlookup\n引用原文: Quoted Name: hello",
        msg_type=49,
        is_group=True,
        is_self=False,
        raw=Raw(),
    )

    router.handle(adapter, msg, "wxid_example011ot")

    assert adapter.sent
    assert "wxid: wxid_example026" in adapter.sent[0][1]
    assert "quoted_name: Quoted Name" in adapter.sent[0][1]
    assert "resolved_name: Resolved Name" in adapter.sent[0][1]


def test_router_does_not_send_fallback_on_timeout(tmp_path):
    class TimeoutRouter(MessageRouter):
        def _build_reply(self, adapter, msg, settings, is_admin):
            raise TimeoutError("slow")

    class FakeLimiter:
        def check_and_record(self, *args, **kwargs):
            return LimitResult(True)

    class FakeAdapter:
        def __init__(self):
            self.sent = []

        def send_text(self, receiver: str, text: str):
            self.sent.append((receiver, text))

        def is_file_message(self, msg):
            return False

        def is_image_message(self, msg):
            return False

    config = AppConfig(
        openai_api_key="x",
        manual_debug=True,
        reply_timing=ReplyTimingConfig(min_delay_seconds=0, max_delay_seconds=0, between_messages_seconds=0),
    )
    db = Database(tmp_path / "bot.sqlite3")
    memory = MemoryStore(db)
    router = TimeoutRouter(
        config=config,
        db=db,
        auth=AuthService(config),
        limiter=FakeLimiter(),
        context=ContextStore(db),
        memory=memory,
        commands=CommandProcessor(config, db, memory),
        search=None,
        url_fetch=None,
        docs=None,
        vision=None,
        llm=None,
        prompt_path=tmp_path / "PROMPT.md",
        clan=None,
        code=None,
        research=None,
    )
    adapter = FakeAdapter()
    msg = IncomingMessage(
        id=1,
        sender="wxid_user",
        chat_id="room",
        room_id="room",
        content="hello",
        msg_type=1,
        is_group=True,
        is_self=False,
    )

    router.handle(adapter, msg, "wxid_example011ot")

    assert adapter.sent == []


def test_router_skips_main_reply_when_same_chat_reply_is_in_flight(tmp_path):
    class FailingLimiter:
        def check_and_record(self, *args, **kwargs):
            raise AssertionError("main model path should not continue while chat reply is in flight")

    class FakeAdapter:
        def __init__(self):
            self.sent = []

        def is_image_message(self, msg):
            return False

        def send_text(self, receiver: str, text: str):
            self.sent.append((receiver, text))

        def is_file_message(self, msg):
            return False

    config = AppConfig(
        openai_api_key="x",
        manual_debug=True,
        reply_timing=ReplyTimingConfig(min_delay_seconds=0, max_delay_seconds=0, between_messages_seconds=0),
    )
    db = Database(tmp_path / "bot.sqlite3")
    memory = MemoryStore(db)
    router = MessageRouter(
        config=config,
        db=db,
        auth=AuthService(config),
        limiter=FailingLimiter(),
        context=ContextStore(db),
        memory=memory,
        commands=CommandProcessor(config, db, memory),
        search=None,
        url_fetch=None,
        docs=None,
        vision=None,
        llm=None,
        prompt_path=tmp_path / "PROMPT.md",
        clan=None,
        code=None,
        research=None,
    )
    adapter = FakeAdapter()
    msg = IncomingMessage(
        id=1,
        sender="wxid_user",
        chat_id="room",
        room_id="room",
        content="@FoxStar hello",
        msg_type=1,
        is_group=True,
        is_self=False,
    )
    lock = router._acquire_chat_reply_lock("room")
    assert lock is not None
    try:
        router.handle(adapter, msg, "wxid_example011ot")
    finally:
        lock.release()

    assert adapter.sent == []
    assert router.context.recent_messages("room")[0]["content"] == "@FoxStar hello"


def test_relevant_skill_prompt_forces_signup_skill(tmp_path):
    config = AppConfig(openai_api_key="x", sambanova_api_key="test-key", openrouter_api_key="test-key")
    db = Database(tmp_path / "bot.sqlite3")
    memory = MemoryStore(db)
    prompt_path = tmp_path / "PROMPT.md"
    prompt_path.write_text("DEFAULT PROMPT", encoding="utf-8")
    skill_dir = tmp_path / "skills" / "signup_roster_compare"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "# Signup Roster Compare\n\n"
        "Compare a guild roster against a signup list.\n",
        encoding="utf-8",
    )
    router = MessageRouter(
        config=config,
        db=db,
        auth=AuthService(config),
        limiter=None,
        context=ContextStore(db),
        memory=memory,
        commands=CommandProcessor(config, db, memory),
        search=None,
        url_fetch=None,
        docs=None,
        vision=None,
        llm=None,
        prompt_path=prompt_path,
        skills=SkillRegistry(tmp_path / "skills"),
        clan=None,
        code=None,
        research=None,
    )

    prompt = router._relevant_skill_prompt("根据帮众名单和接龙名单统计未接龙和请假", [])

    assert "signup_roster_compare" in prompt
    assert "must call load_skill" in prompt


def test_relevant_skill_prompt_forces_yfinance_skill(tmp_path):
    config = AppConfig(openai_api_key="x", sambanova_api_key="test-key", openrouter_api_key="test-key")
    db = Database(tmp_path / "bot.sqlite3")
    memory = MemoryStore(db)
    prompt_path = tmp_path / "PROMPT.md"
    prompt_path.write_text("DEFAULT PROMPT", encoding="utf-8")
    skill_dir = tmp_path / "skills" / "yfinance_quote"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "# Yahoo Finance Quote Lookup\n\n"
        "Use this skill for direct quote lookups.\n",
        encoding="utf-8",
    )
    router = MessageRouter(
        config=config,
        db=db,
        auth=AuthService(config),
        limiter=None,
        context=ContextStore(db),
        memory=memory,
        commands=CommandProcessor(config, db, memory),
        search=None,
        url_fetch=None,
        docs=None,
        vision=None,
        llm=None,
        prompt_path=prompt_path,
        skills=SkillRegistry(tmp_path / "skills"),
        clan=None,
        code=None,
        research=None,
    )

    prompt = router._relevant_skill_prompt("@FoxStar 用coding tool调yfinance查NVDA实时价格", [], is_admin=True)

    assert "yfinance_quote" in prompt
    assert "fetch_market_quote" in prompt
