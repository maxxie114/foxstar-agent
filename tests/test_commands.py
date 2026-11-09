from foxstar_bot.auth import AuthService
from foxstar_bot.commands import CommandProcessor
from foxstar_bot.config import AppConfig
from foxstar_bot.memory_store import MemoryStore
from foxstar_bot.persistence import Database
from foxstar_bot.skills import SkillRegistry


class _FakeLLM:
    def chat(self, messages, **kwargs):
        return "analysis ok"


def test_non_admin_cannot_run_command(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db))

    result = processor.handle("/status", "room", True, is_admin=False)

    assert result.handled is True
    assert result.reply == ""


def test_admin_can_change_mode(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db))

    result = processor.handle("/mode verify", "room", True, is_admin=True)

    assert result.handled is True
    assert "verify" in result.reply


def test_version_reads_version_file(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    (tmp_path / "VERSION").write_text("0d6c3fa\n", encoding="utf-8")
    processor = CommandProcessor(config, db, MemoryStore(db), config_path=str(tmp_path / "config.yaml"))

    result = processor.handle("/version", "room", True, is_admin=True)

    assert result.handled is True
    assert result.reply == "0d6c3fa"


def test_admin_can_set_composite_style(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db))

    result = processor.handle("/style human intj leo", "room", True, is_admin=True)

    assert result.handled is True
    assert "human intj leo" in result.reply
    assert db.get_setting("group_style:room") == "human intj leo"


def test_admin_can_use_chinese_zodiac_style_alias(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db))

    result = processor.handle("/style enfp 双鱼座", "room", True, is_admin=True)

    assert result.handled is True
    assert db.get_setting("group_style:room") == "strict enfp pisces"


def test_admin_can_set_gender_and_tone_style(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db))

    result = processor.handle("/style human 女生 柔软 白羊座", "room", True, is_admin=True)

    assert result.handled is True
    assert db.get_setting("group_style:room") == "human feminine soft aries"


def test_admin_can_switch_group_prompt_template(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db))

    result = processor.handle("/prompt use roast", "room", True, is_admin=True)

    assert result.handled is True
    assert "roast" in result.reply
    assert db.get_setting("group_prompt_profile:room") == "roast"
    assert db.get_setting("group_prompt_custom:room") == ""


def test_admin_can_switch_group_prompt_default_template(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db))

    result = processor.handle("/prompt use default", "room", True, is_admin=True)

    assert result.handled is True
    assert "prompt_templates/default.md" in result.reply
    assert db.get_setting("group_prompt_profile:room") == "default"


def test_admin_can_switch_debate_prompt_template(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db))

    result = processor.handle("/prompt debate", "room", True, is_admin=True)

    assert result.handled is True
    assert db.get_setting("group_prompt_profile:room") == "debate"


def test_prompt_templates_include_logic_guardrail():
    from foxstar_bot.prompt_profiles import get_template

    template = get_template("roast")

    assert "Logic Guardrail" in template
    assert "Priority Compliance & Security Guardrail" in template
    assert "谁主张谁举证" in template
    assert "不泄露机制" in template
    assert "Status-frame trap" in template
    assert "如实承认AI身份" in template  # identity-disclosure compliance rule


def test_prompt_typo_alias_works(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db))

    result = processor.handle("/propmt use debate", "room", True, is_admin=True)

    assert result.handled is True
    assert db.get_setting("group_prompt_profile:room") == "debate"


def test_admin_can_set_and_clear_custom_group_prompt(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db))

    result = processor.handle("/prompt custom You are sharp and concise.", "room", True, is_admin=True)

    assert result.handled is True
    assert db.get_setting("group_prompt_profile:room") == "custom"
    assert db.get_setting("group_prompt_custom:room") == "You are sharp and concise."

    cleared = processor.handle("/prompt clear", "room", True, is_admin=True)

    assert cleared.handled is True
    assert db.get_setting("group_prompt_profile:room") == "main"
    assert db.get_setting("group_prompt_custom:room") == ""


def test_admin_can_manage_group_blacklist(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db))

    result = processor.handle("/blacklist add wxid_example022", "room", True, is_admin=True)

    assert result.handled is True
    assert "wxid_example022" in result.reply
    assert db.get_setting("group_blacklist:room") == ["wxid_example022"]

    listed = processor.handle("/blacklist list", "room", True, is_admin=True)

    assert "wxid_example022" in listed.reply

    removed = processor.handle("/blacklist remove wxid_example022", "room", True, is_admin=True)

    assert removed.handled is True
    assert db.get_setting("group_blacklist:room") == []


def test_admin_can_manage_group_target_list(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db))

    added = processor.handle("/target add wxid_example023", "room", True, is_admin=True)
    listed = processor.handle("/target list", "room", True, is_admin=True)

    assert added.handled is True
    assert db.get_setting("group_target_list:room") == ["wxid_example023"]
    assert "wxid_example023" in listed.reply

    removed = processor.handle("/target remove wxid_example023", "room", True, is_admin=True)
    assert removed.handled is True
    assert db.get_setting("group_target_list:room") == []


def test_admin_can_remember_chat_memory(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    memory = MemoryStore(db)
    processor = CommandProcessor(config, db, memory)

    result = processor.handle("/memory remember 群偏好: 回复更强势", "room", True, is_admin=True, sender_id="wxid_example009dmin")

    assert result.handled is True
    assert "群偏好" in result.reply
    assert memory.list_scope("chat", "room")[0]["value"] == "回复更强势"
    assert memory.list_scope("chat", "room")[0]["priority"] == 100


def test_non_admin_cannot_clear_memory(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    memory = MemoryStore(db)
    memory.upsert("chat", "room", "群偏好", "回复更强势")
    processor = CommandProcessor(config, db, memory)

    result = processor.handle("/memory clear", "room", True, is_admin=False)

    assert result.handled is True
    assert result.reply == ""
    assert memory.list_scope("chat", "room")


def test_non_admin_cannot_use_memory_command(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    memory = MemoryStore(db)
    processor = CommandProcessor(config, db, memory)

    result = processor.handle("/memory remember 群偏好: 普通人写入", "room", True, is_admin=False)

    assert result.handled is True
    assert result.reply == ""
    assert memory.list_scope("chat", "room") == []


def test_low_priority_memory_cannot_override_high_priority(tmp_path):
    db = Database(tmp_path / "bot.sqlite3")
    memory = MemoryStore(db)

    assert memory.upsert("chat", "room", "群偏好", "owner value", priority=100, source_user_id="wxid_example009dmin")
    assert not memory.upsert("chat", "room", "群偏好", "ordinary value", priority=50, source_user_id="wxid_user")

    item = memory.list_scope("chat", "room")[0]
    assert item["value"] == "owner value"
    assert item["priority"] == 100


def test_memory_prompt_splits_master_and_user_memory(tmp_path):
    db = Database(tmp_path / "bot.sqlite3")
    memory = MemoryStore(db)
    memory.upsert("chat", "room", "owner_rule", "follow this first", priority=100, source_user_id="wxid_example009dmin")
    memory.upsert("chat", "room", "user_note", "lower priority note", priority=50, source_user_id="wxid_user")

    rendered = memory.render_for_prompt("room", "wxid_user")

    assert "Master Memory" in rendered
    assert "User Memory" in rendered
    assert "owner_rule" in rendered
    assert "user_note" in rendered


def test_admin_can_manage_whitelist(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("whitelist_user_ids:\n  - wxid_example009dmin\n", encoding="utf-8")
    config = AppConfig(openai_api_key="x", whitelist_user_ids=["wxid_example009dmin"])
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db), config_path=str(config_path))

    result = processor.handle("/whitelist add wxid_example013", "room", True, is_admin=True)

    assert result.handled is True
    assert "wxid_example013" in result.reply
    assert "wxid_example013" in config.whitelist_user_ids
    assert "wxid_example013" in db.get_setting("whitelist_user_ids")
    assert "wxid_example013" not in config_path.read_text(encoding="utf-8")

    listed = processor.handle("/whitelist list", "room", True, is_admin=True)

    assert "wxid_example009dmin" in listed.reply
    assert "wxid_example013" in listed.reply

    removed = processor.handle("/whitelist remove wxid_example013", "room", True, is_admin=True)

    assert removed.handled is True
    assert "wxid_example013" not in config.whitelist_user_ids


def test_admin_can_hot_edit_reply_delay(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "reply_timing:\n  min_delay_seconds: 1.0\n  max_delay_seconds: 2.0\n  between_messages_seconds: 0.5\n",
        encoding="utf-8",
    )
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db), config_path=str(config_path))

    result = processor.handle("/delay 3 5 1", "room", True, is_admin=True)

    assert result.handled is True
    assert "3-5s" in result.reply
    # /delay is group-scoped now (stored in DB, not the global config file)
    delay = db.get_setting("group_reply_delay:room", {})
    assert delay.get("min") == 3.0
    assert delay.get("max") == 5.0
    assert delay.get("between") == 1.0


def test_admin_can_list_known_groups(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db))
    processor.handle("/status", "900000003@chatroom", True, is_admin=True)

    result = processor.handle("/groups", "wxid_example009dmin", False, is_admin=True)

    assert result.handled is True
    assert "900000003@chatroom" in result.reply


def test_admin_can_list_and_show_skills(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    skills_root = tmp_path / "skills" / "signup_roster_compare"
    skills_root.mkdir(parents=True)
    (skills_root / "SKILL.md").write_text(
        "# Signup Roster Compare\n\n"
        "Compare a guild roster against a signup list.\n",
        encoding="utf-8",
    )
    processor = CommandProcessor(config, db, MemoryStore(db), skills=SkillRegistry(tmp_path / "skills"))

    listed = processor.handle("/skills", "wxid_example009dmin", False, is_admin=True)
    shown = processor.handle("/skills show signup_roster_compare", "wxid_example009dmin", False, is_admin=True)

    assert listed.handled is True
    assert "signup_roster_compare" in listed.reply
    assert shown.handled is True
    assert "Signup Roster Compare" in shown.reply


def test_admin_can_name_known_groups(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db))

    named = processor.handle("/groups name 900000003@chatroom AI群", "wxid_example009dmin", False, is_admin=True)
    listed = processor.handle("/groups", "wxid_example009dmin", False, is_admin=True)
    cleared = processor.handle("/groups clear 900000003@chatroom", "wxid_example009dmin", False, is_admin=True)

    assert named.handled is True
    assert named.reply == "alias set: AI群 = 900000003@chatroom"
    assert cleared.handled is True
    assert "AI群 | 900000003@chatroom" in listed.reply
    assert "recent:" not in listed.reply


def test_admin_can_set_group_reply_policy_and_length(tmp_path):
    config = AppConfig(openai_api_key="x", bot_name="FoxStar")
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db))

    reply = processor.handle("/reply direct", "room", True, is_admin=True)
    length = processor.handle("/length 300", "room", True, is_admin=True)
    natural_reply = processor.handle("/set 这个群只在 @FoxStar 或引用它时回复", "room2", True, is_admin=True)
    natural_length = processor.handle("/set 最大长度 420 字符", "room2", True, is_admin=True)
    line_tokens = processor.handle("/set line_tokens 35", "room2", True, is_admin=True)

    assert reply.handled is True
    assert length.handled is True
    assert natural_reply.handled is True
    assert natural_length.handled is True
    assert line_tokens.handled is True
    assert db.get_setting("group_reply_policy:room") == "direct"
    assert db.get_setting("group_max_reply_tokens:room") == 300
    assert db.get_setting("group_reply_policy:room2") == "direct"
    assert db.get_setting("group_max_reply_tokens:room2") == 420
    assert db.get_setting("group_reply_line_tokens:room2") == 35


def test_admin_can_set_show_and_clear_group_context_length(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db))
    db.set_setting("group_context_summary:room", {"summary": "stale"})

    changed = processor.handle("/context 20", "room", True, is_admin=True)
    assert db.get_setting("group_context_summary:room") == {}
    db.set_setting("group_context_summary:room", {"summary": "stale again"})
    shown = processor.handle("/context", "room", True, is_admin=True)
    cleared = processor.handle("/context clear", "room", True, is_admin=True)

    assert changed.handled is True
    assert "20" in changed.reply
    assert "20" in shown.reply
    assert "30" in cleared.reply
    assert db.get_setting("group_context_messages:room") == 30
    assert db.get_setting("group_context_summary:room") == {}


def test_context_length_rejects_invalid_values(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db))

    non_numeric = processor.handle("/context many", "room", True, is_admin=True)
    too_small = processor.handle("/context 0", "room", True, is_admin=True)
    too_large = processor.handle("/context 201", "room", True, is_admin=True)

    assert "整数" in non_numeric.reply
    assert "1 到 200" in too_small.reply
    assert "1 到 200" in too_large.reply
    assert db.get_setting("group_context_messages:room") is None


def test_admin_can_view_group_token_usage(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    db.record_token_usage(
        chat_id="room",
        feature="main_reply",
        provider="openai",
        model="gpt-5.4",
        api="responses.create",
        input_tokens=120,
        output_tokens=45,
        cached_tokens=20,
    )
    db.record_token_usage(
        chat_id="room",
        feature="reply_gate",
        provider="sambanova",
        model="MiniMax-M2.5",
        api="sambanova.chat.completions",
        input_tokens=30,
        output_tokens=10,
        cached_tokens=0,
    )
    processor = CommandProcessor(config, db, MemoryStore(db))

    result = processor.handle("/tokens today", "room", True, is_admin=True)

    assert result.handled is True
    assert "token usage (today):" in result.reply
    assert "requests: 2" in result.reply
    assert "input_tokens: 150" in result.reply
    assert "output_tokens: 55" in result.reply
    assert "cached_tokens: 20" in result.reply
    assert "- main_reply:" in result.reply
    assert "- reply_gate:" in result.reply
    assert "- openai/gpt-5.4:" in result.reply
    assert "- sambanova/MiniMax-M2.5:" in result.reply


def test_admin_can_clear_group_token_usage(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    db.record_token_usage(
        chat_id="room",
        feature="main_reply",
        provider="openai",
        model="gpt-5.4",
        api="responses.create",
        input_tokens=10,
        output_tokens=5,
        cached_tokens=0,
    )
    processor = CommandProcessor(config, db, MemoryStore(db))

    cleared = processor.handle("/token clear", "room", True, is_admin=True)
    status = processor.handle("/tokens today", "room", True, is_admin=True)

    assert cleared.handled is True
    assert "cleared" in cleared.reply
    assert "requests: 0" in status.reply


def test_admin_can_set_reply_gate_mode(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db))

    direct = processor.handle("/replygate soft guild", "room", True, is_admin=True)
    strict = processor.handle("/replygate strict", "room2", True, is_admin=True)
    vibe = processor.handle("/replygate vibe tech", "room3", True, is_admin=True)

    assert direct.handled is True
    assert strict.handled is True
    assert vibe.handled is True
    assert db.get_setting("group_reply_gate_mode:room") == "soft"
    assert db.get_setting("group_reply_gate_vibe:room") == "guild"
    assert db.get_setting("group_reply_gate_mode:room2") == "strict"
    assert db.get_setting("group_reply_gate_vibe:room3") == "tech"


def test_admin_can_delegate_group_command_from_private_chat(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db))

    result = processor.handle("/gset target@chatroom /set line_tokens 28", "wxid_example009dmin", False, is_admin=True)

    assert result.handled is True
    assert "target@chatroom" in result.reply
    assert db.get_setting("group_reply_line_tokens:target@chatroom") == 28


def test_admin_can_delegate_memberlog_from_private_chat(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db))
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO chat_events(chat_id, event_type, user_id, display_name, raw_content, created_at)
            VALUES(?, 'joined', ?, ?, ?, ?)
            """,
            ("target@chatroom", "wxid_example009", "Alice", "Alice joined", "2026-04-26T00:00:00+00:00"),
        )

    result = processor.handle("/gset target@chatroom /memberlog all", "wxid_example009dmin", False, is_admin=True)

    assert result.handled is True
    assert "target: target@chatroom" in result.reply
    assert "member log (all):" in result.reply
    assert "joined: 1" in result.reply


def test_admin_can_delegate_chatlog_analyze_from_private_chat(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db), llm=_FakeLLM())
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO messages(chat_id, user_id, role, content, kind, created_at)
            VALUES(?, ?, ?, ?, ?, ?)
            """,
            ("target@chatroom", "wxid_example009", "user", "hello there", "text", "2026-04-26T00:00:00+00:00"),
        )

    result = processor.handle("/gset target@chatroom /chatlog analyze 50", "wxid_example009dmin", False, is_admin=True)

    assert result.handled is True
    assert "target: target@chatroom" in result.reply
    assert "analysis ok" in result.reply


def test_admin_can_create_list_and_remove_scheduled_tasks(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db))

    created = processor.handle("/schedule 0 8 * * * /chatlog analyze 120", "room", True, is_admin=True, sender_id="wxid_example009dmin")
    listed = processor.handle("/schedule list", "room", True, is_admin=True)
    removed = processor.handle("/schedule remove 1", "room", True, is_admin=True)

    assert created.handled is True
    assert "scheduled #1" in created.reply
    assert listed.handled is True
    assert "#1" in listed.reply
    assert "/chatlog analyze 120" in listed.reply
    assert removed.handled is True
    assert "removed schedule #1" in removed.reply


def test_admin_can_create_one_shot_scheduled_prompt(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db))

    created = processor.handle("/schedule in 2h 帮我查一下当前ETH的行情", "room", True, is_admin=True, sender_id="wxid_example009dmin")
    listed = processor.handle("/schedule list", "room", True, is_admin=True)

    assert created.handled is True
    assert "scheduled #1: once" in created.reply
    assert listed.handled is True
    assert "帮我查一下当前ETH的行情" in listed.reply


def test_admin_can_target_group_from_private_set_text(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db))

    result = processor.handle(
        "/set 900000003@chatroom群聊的delay改成25-30秒之间，每句话间隔10秒，cooldown设置成10秒",
        "wxid_example009dmin",
        False,
        is_admin=True,
    )

    assert result.handled is True
    assert db.get_setting("group_reply_delay:900000003@chatroom") == {"min": 25.0, "max": 30.0, "between": 10.0}
    assert db.get_setting("group_api_cooldown_seconds:900000003@chatroom") == 10.0


def test_private_set_can_delegate_group_slash_commands(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    memory = MemoryStore(db)
    processor = CommandProcessor(config, db, memory)

    prompt = processor.handle("/set 900000003@chatroom /prompt debate", "wxid_example009dmin", False, is_admin=True)
    memory_result = processor.handle(
        "/set 900000003@chatroom /memory remember nickname: Example User",
        "wxid_example009dmin",
        False,
        is_admin=True,
        sender_id="wxid_example009dmin",
    )

    assert prompt.handled is True
    assert memory_result.handled is True
    assert db.get_setting("group_prompt_profile:900000003@chatroom") == "debate"
    assert memory.list_scope("chat", "900000003@chatroom")[0]["key"] == "nickname"
    assert memory.list_scope("chat", "900000003@chatroom")[0]["priority"] == 100


def test_private_set_natural_language_covers_group_commands(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    memory = MemoryStore(db)
    processor = CommandProcessor(config, db, memory)
    room = "900000003@chatroom"

    target = processor.handle(f"/set {room} 把 wxid_example023 加入 target_list", "wxid_example009dmin", False, is_admin=True)
    style = processor.handle(f"/set {room} style human intj scorpio", "wxid_example009dmin", False, is_admin=True)
    prompt = processor.handle(f"/set {room} prompt debate", "wxid_example009dmin", False, is_admin=True)
    vision = processor.handle(f"/set {room} 关闭图片识别", "wxid_example009dmin", False, is_admin=True)
    prefix = processor.handle(f"/set {room} prefix !", "wxid_example009dmin", False, is_admin=True)
    memory_result = processor.handle(
        f"/set {room} 记住 昵称: Example User",
        "wxid_example009dmin",
        False,
        is_admin=True,
        sender_id="wxid_example009dmin",
    )

    assert target.handled is True
    assert style.handled is True
    assert prompt.handled is True
    assert vision.handled is True
    assert prefix.handled is True
    assert memory_result.handled is True
    assert db.get_setting(f"group_target_list:{room}") == ["wxid_example023"]
    assert db.get_setting(f"group_style:{room}") == "human intj scorpio"
    assert db.get_setting(f"group_prompt_profile:{room}") == "debate"
    assert processor._get_group(room)["vision_enabled"] == 0
    assert processor._get_group(room)["prefix"] == "!"
    assert memory.list_scope("chat", room)[0]["key"] == "昵称"


def test_admin_can_set_group_cooldown(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db))

    result = processor.handle("/cooldown 10", "room", True, is_admin=True)
    natural = processor.handle("/set cooldown 15", "room2", True, is_admin=True)

    assert result.handled is True
    assert natural.handled is True
    assert db.get_setting("group_api_cooldown_seconds:room") == 10.0
    assert db.get_setting("group_api_cooldown_seconds:room2") == 15.0


def test_admin_can_select_native_or_tool_image_analysis(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db))

    native = processor.handle("/vision mode native", "room", True, is_admin=True)
    status = processor.handle("/vision status", "room", True, is_admin=True)
    tool = processor.handle("/set image_mode tool", "room", True, is_admin=True)

    assert native.handled is True
    assert "native" in native.reply
    assert "mode=native" in status.reply
    assert tool.handled is True
    assert db.get_setting("group_image_analysis_mode:room") == "tool"
    assert processor._get_group("room")["vision_enabled"] == 1


def test_admin_can_set_group_model_and_reasoning(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db))
    room = "900000003@chatroom"

    model = processor.handle("/model gpt-5.4", "room", True, is_admin=True)
    reasoning = processor.handle("/reasoning high", "room", True, is_admin=True)
    private_model = processor.handle(f"/set {room} model gpt-5.2", "wxid_example009dmin", False, is_admin=True)
    private_reasoning = processor.handle(f"/set {room} reasoning medium", "wxid_example009dmin", False, is_admin=True)

    assert model.handled is True
    assert reasoning.handled is True
    assert private_model.handled is True
    assert private_reasoning.handled is True
    assert db.get_setting("group_reply_model:room") == "gpt-5.4"
    assert db.get_setting("group_reasoning_effort:room") == "high"
    assert db.get_setting(f"group_reply_model:{room}") == "gpt-5.2"
    assert db.get_setting(f"group_reasoning_effort:{room}") == "medium"


def test_admin_can_set_reasoning_max_alias(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db))

    result = processor.handle("/reasoning max", "room", True, is_admin=True)
    natural = processor.handle("/set reasoning xhigh", "room2", True, is_admin=True)

    assert result.handled is True
    assert natural.handled is True
    assert db.get_setting("group_reasoning_effort:room") == "max"
    assert db.get_setting("group_reasoning_effort:room2") == "max"


def test_admin_can_toggle_group_router(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db))

    direct = processor.handle("/router on", "room", True, is_admin=True)
    natural = processor.handle("/set router off", "room2", True, is_admin=True)

    assert direct.handled is True
    assert natural.handled is True
    assert db.get_setting("group_model_router_enabled:room") is True
    assert db.get_setting("group_model_router_enabled:room2") is False


def test_admin_can_set_global_and_user_limits(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db))

    global_limit = processor.handle("/limit global 30", "room", True, is_admin=True)
    user_limit = processor.handle("/limit wxid_user 12", "room", True, is_admin=True)
    clear_limit = processor.handle("/limit wxid_user clear", "room", True, is_admin=True)

    assert global_limit.handled is True
    assert user_limit.handled is True
    assert clear_limit.handled is True
    assert db.get_setting("global_user_daily_limit") == 30
    assert db.get_setting("user_daily_limit:wxid_user") == 0


def test_admin_can_set_openrouter_provider_and_model(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db))

    provider = processor.handle("/model provider openrouter", "room", True, is_admin=True)
    model = processor.handle("/model openrouter anthropic/claude-sonnet-4.5", "room", True, is_admin=True)
    set_provider = processor.handle("/set provider openai", "room2", True, is_admin=True)
    set_model = processor.handle("/set model google/gemini-2.5-pro", "room2", True, is_admin=True)

    assert provider.handled is True
    assert model.handled is True
    assert set_provider.handled is True
    assert set_model.handled is True
    assert db.get_setting("group_model_provider:room") == "openrouter"
    assert db.get_setting("group_reply_model:room") == "anthropic/claude-sonnet-4.5"
    assert db.get_setting("group_model_provider:room2") == "openai"
    assert db.get_setting("group_reply_model:room2") == "google/gemini-2.5-pro"


def test_admin_can_set_deepseek_provider_and_model(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db))

    provider = processor.handle("/model provider deepseek", "room", True, is_admin=True)
    model = processor.handle("/model deepseek-v4-pro", "room", True, is_admin=True)

    assert provider.handled is True
    assert model.handled is True
    assert db.get_setting("group_model_provider:room") == "deepseek"
    assert db.get_setting("group_reply_model:room") == "deepseek-v4-pro"


def test_admin_can_set_together_and_lightning_provider_and_model(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db))

    together = processor.handle("/model together deepseek-ai/DeepSeek-V4-Pro", "room", True, is_admin=True)
    lightning = processor.handle("/model lightning lightning-ai/deepseek-v4-pro", "room2", True, is_admin=True)

    assert together.handled is True
    assert lightning.handled is True
    assert db.get_setting("group_model_provider:room") == "together"
    assert db.get_setting("group_reply_model:room") == "deepseek-ai/DeepSeek-V4-Pro"
    assert db.get_setting("group_model_provider:room2") == "lightning"
    assert db.get_setting("group_reply_model:room2") == "lightning-ai/deepseek-v4-pro"


def test_admin_can_set_bedrock_provider_and_model(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db))

    provider = processor.handle("/model provider bedrock", "room", True, is_admin=True)
    model = processor.handle("/model bedrock openai.gpt-5.5", "room", True, is_admin=True)

    assert provider.handled is True
    assert model.handled is True
    assert db.get_setting("group_model_provider:room") == "bedrock"
    assert db.get_setting("group_reply_model:room") == "openai.gpt-5.5"


def test_admin_can_set_zai_telnyx_and_kimi_providers(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db))

    zai = processor.handle("/model z.ai glm-5.2", "zai-room", True, is_admin=True)
    telnyx = processor.handle("/model telnyx moonshotai/Kimi-K3", "telnyx-room", True, is_admin=True)
    kimi = processor.handle("/model moonshot kimi-k3", "kimi-room", True, is_admin=True)

    assert zai.handled is True
    assert telnyx.handled is True
    assert kimi.handled is True
    assert db.get_setting("group_model_provider:zai-room") == "zai"
    assert db.get_setting("group_reply_model:zai-room") == "glm-5.2"
    assert db.get_setting("group_model_provider:telnyx-room") == "telnyx"
    assert db.get_setting("group_reply_model:telnyx-room") == "moonshotai/Kimi-K3"
    assert db.get_setting("group_model_provider:kimi-room") == "kimi"
    assert db.get_setting("group_reply_model:kimi-room") == "kimi-k3"


def test_admin_can_toggle_global_bot_and_status_shows_events(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db))

    off = processor.handle("/bot global off", "room", True, is_admin=True)
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO chat_events(chat_id, event_type, user_id, display_name, raw_content, created_at)
            VALUES(?, ?, ?, ?, ?, ?)
            """,
            ("room", "joined", "wxid_example021", "New Person", "New Person joined", "2999-01-01T00:00:00+00:00"),
        )
    status = processor.handle("/status", "room", True, is_admin=True)
    on = processor.handle("/bot global on", "room", True, is_admin=True)

    assert off.handled is True
    assert on.handled is True
    assert db.get_setting("global_bot_enabled") is True
    assert "global_bot: off" in status.reply
    # member join/left events moved from /status to /memberlog
    memberlog = processor.handle("/memberlog all", "room", True, is_admin=True)
    assert "joined: 1" in memberlog.reply


def test_bot_on_under_global_off_enables_current_group_override(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db))

    processor.handle("/bot global off", "room", True, is_admin=True)
    on = processor.handle("/bot on", "room", True, is_admin=True)
    override_after_on = db.get_setting("group_global_override:room")
    status = processor.handle("/status", "room", True, is_admin=True)
    off = processor.handle("/bot off", "room", True, is_admin=True)

    assert on.handled is True
    assert db.get_setting("global_bot_enabled") is False
    assert override_after_on is True
    assert db.get_setting("group_global_override:room") is False
    assert "global_bot: off" in status.reply
    assert "global_override: on" in status.reply
    assert off.handled is True


def test_auth_reads_whitelist():
    config = AppConfig(openai_api_key="x", whitelist_user_ids=["wxid_example009dmin"])
    auth = AuthService(config)

    assert auth.is_whitelist_user("wxid_example009dmin")
    assert not auth.is_whitelist_user("wxid_example024")


def test_fortune_command_outputs_local_fortune(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db))

    all_result = processor.handle("/fortune", "room", True, is_admin=True)
    star_result = processor.handle("/fortune star aries", "room", True, is_admin=True)
    huangli_result = processor.handle("/fortune huangli", "room", True, is_admin=True)
    divination_result = processor.handle("/fortune divination", "room", True, is_admin=True)

    assert all_result.handled is True
    assert "离线运势" in all_result.reply
    assert "白羊" in star_result.reply
    assert "黄历" in huangli_result.reply
    assert "卦象" in divination_result.reply


def _seed_group(processor, chat_id, alias=""):
    processor._ensure_group(chat_id)
    with processor.db.connect() as conn:
        conn.execute(
            "INSERT INTO group_aliases(chat_id, alias, last_seen_at) VALUES(?, ?, datetime('now')) "
            "ON CONFLICT(chat_id) DO UPDATE SET alias = excluded.alias",
            (chat_id, alias),
        )


def test_gset_target_resolution_alias_and_code(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db))

    _seed_group(processor, "11111111111@chatroom", alias="示例帮会群")
    _seed_group(processor, "22222222222@chatroom", alias="猜谜群")

    assert processor._resolve_group_id("11111111111@chatroom") == "11111111111@chatroom"
    assert processor._resolve_group_id("示例帮会群") == "11111111111@chatroom"
    assert processor._resolve_group_id("示例") == "11111111111@chatroom"  # unique alias prefix
    assert processor._resolve_group_id("11111111111") == "11111111111@chatroom"  # id prefix
    assert processor._resolve_group_id("不存在") == ""

    processor._ensure_group_codes()
    code1 = db.get_setting("group_code:11111111111@chatroom")
    code2 = db.get_setting("group_code:22222222222@chatroom")
    assert code1 and code2 and code1 != code2
    assert processor._resolve_group_id(str(code1)) == "11111111111@chatroom"
    assert processor._resolve_group_id(str(code2)) == "22222222222@chatroom"
    # codes are stable across re-runs
    processor._ensure_group_codes()
    assert db.get_setting("group_code:11111111111@chatroom") == code1


def test_deployed_bug_fixes_auto_close(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db))
    with db.connect() as conn:
        conn.executemany(
            "INSERT INTO bug_reports(chat_id, created_by, description, status, created_at, updated_at) "
            "VALUES(?, ?, ?, 'open', datetime('now'), datetime('now'))",
            [
                ("room1", "u1", "json bug", ),
                ("room2", "u2", "robot bug", ),
                ("room3", "u3", "still open report", ),
            ],
        )
    # remap ids deterministically: rows are 1,2,3; close #1 and #2 via registry subset
    from foxstar_bot.commands import FIXED_BUG_REPORTS

    subset = {1: "fixed-a", 2: "fixed-b"}
    original = dict(FIXED_BUG_REPORTS)
    FIXED_BUG_REPORTS.clear()
    FIXED_BUG_REPORTS.update(subset)
    try:
        closed = processor.apply_deployed_bug_fixes()
        assert closed == [1, 2]
        # idempotent
        assert processor.apply_deployed_bug_fixes() == []
    finally:
        FIXED_BUG_REPORTS.clear()
        FIXED_BUG_REPORTS.update(original)
    with db.connect() as conn:
        states = {r["id"]: r["status"] for r in conn.execute("SELECT id, status FROM bug_reports")}
    assert states == {1: "closed", 2: "closed", 3: "open"}


def test_sqlite_wal_mode_enabled(tmp_path):
    db = Database(tmp_path / "bot.sqlite3")
    with db.connect() as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
