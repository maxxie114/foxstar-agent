import time
from threading import Event

from foxstar_bot.auth import AuthService
from foxstar_bot.commands import CommandProcessor
from foxstar_bot.config import ModelConfig, AppConfig
from foxstar_bot.context_store import ContextStore, DEFAULT_CONTEXT_MESSAGES, MAX_CONTEXT_MESSAGES
from foxstar_bot.memory_store import MemoryStore
from foxstar_bot.persistence import Database
from foxstar_bot.privacy import public_participant_label
from foxstar_bot.router import MessageRouter
from foxstar_bot.wcf_adapter import IncomingMessage


def test_context_compression_window_accepts_per_group_recent_limit(tmp_path):
    db = Database(tmp_path / "bot.sqlite3")
    context = ContextStore(db)
    for index in range(70):
        context.add_message("room", f"wxid_{index}", "user", f"message {index}")

    older, recent, signature = context.compression_window("room", max_turns=45)

    assert len(older) == 25
    assert len(recent) == 45
    assert recent[0]["content"] == "message 25"
    assert recent[-1]["content"] == "message 69"
    assert older[-1]["content"] == "message 24"
    assert signature


def test_context_compression_source_is_capped_at_500_messages(tmp_path):
    db = Database(tmp_path / "bot.sqlite3")
    context = ContextStore(db)
    for index in range(700):
        context.add_message("room", f"user-{index % 5}", "user", f"message {index}")

    older, recent, _ = context.compression_window("room", max_turns=20)

    assert len(older) == 500
    assert len(recent) == 20
    assert older[0]["content"] == "message 180"
    assert older[-1]["content"] == "message 679"
    assert recent[0]["content"] == "message 680"
    with db.connect() as conn:
        indexes = {row["name"] for row in conn.execute("PRAGMA index_list(messages)").fetchall()}
    assert "idx_messages_chat_id_id" in indexes


def test_context_compression_source_redacts_ids_and_deduplicates():
    items = [
        {"user_id": "wxid_example025", "role": "user", "content": "决定继续使用方案 A", "kind": "text"},
        {"user_id": "wxid_example025", "role": "user", "content": "决定继续使用方案 A", "kind": "text"},
        {"user_id": "wxid_example024", "role": "user", "content": "部署密码应该放在哪里？", "kind": "text"},
    ]

    source = ContextStore.render_compression_source(items)

    assert source.count("决定继续使用方案 A") == 1
    assert public_participant_label("wxid_example025") in source
    assert public_participant_label("wxid_example024") in source
    assert "wxid_example025" not in source


def test_rolling_window_catches_up_oldest_first_and_bridges_latest(tmp_path):
    db = Database(tmp_path / "bot.sqlite3")
    context = ContextStore(db)
    for index in range(700):
        context.add_message("room", "user", "user", f"message {index}")
    with db.connect() as conn:
        checkpoint_id = conn.execute(
            "SELECT id FROM messages WHERE chat_id = ? AND content = ?",
            ("room", "message 99"),
        ).fetchone()["id"]

    source, bridge, recent = context.rolling_window(
        "room",
        max_turns=20,
        summarized_through_id=checkpoint_id,
    )

    assert len(source) == 500
    assert source[0]["content"] == "message 100"
    assert source[-1]["content"] == "message 599"
    assert len(bridge) == 40
    assert bridge[0]["content"] == "message 640"
    assert bridge[-1]["content"] == "message 679"
    assert recent[0]["content"] == "message 680"

    next_source, _, _ = context.rolling_window(
        "room",
        max_turns=20,
        summarized_through_id=int(source[-1]["id"]),
    )
    assert next_source[0]["content"] == "message 600"
    assert next_source[-1]["content"] == "message 679"


def test_context_window_normalizes_invalid_or_oversized_runtime_values(tmp_path):
    db = Database(tmp_path / "bot.sqlite3")
    context = ContextStore(db)
    for index in range(MAX_CONTEXT_MESSAGES + 10):
        context.add_message("room", "user", "user", f"message {index}")

    _, invalid_recent, _ = context.compression_window("room", max_turns="invalid")
    _, oversized_recent, _ = context.compression_window("room", max_turns=9999)

    assert len(invalid_recent) == DEFAULT_CONTEXT_MESSAGES
    assert len(oversized_recent) == MAX_CONTEXT_MESSAGES


def test_router_uses_stored_group_context_length(tmp_path):
    config = AppConfig(openai_api_key="x", model=ModelConfig(context_compression_provider="openai"))
    db = Database(tmp_path / "bot.sqlite3")
    memory = MemoryStore(db)
    context = ContextStore(db)
    prompt_path = tmp_path / "PROMPT.md"
    prompt_path.write_text("Test prompt", encoding="utf-8")
    router = MessageRouter(
        config=config,
        db=db,
        auth=AuthService(config),
        limiter=None,
        context=context,
        memory=memory,
        commands=CommandProcessor(config, db, memory),
        search=None,
        url_fetch=None,
        research=None,
        code=None,
        docs=None,
        vision=None,
        llm=None,
        prompt_path=prompt_path,
        clan=None,
    )
    for index in range(45):
        context.add_message("room", f"user-{index}", "user", f"message {index}")
    db.set_setting("group_context_messages:room", 40)

    settings = router._group_settings("room")
    messages = router._assemble_messages(
        IncomingMessage(1, "current-user", "room", "room", "current", 1, True, False),
        "current",
        [],
        settings,
        is_admin=False,
    )
    historical = [item["content"] for item in messages if item["role"] == "user" and "message " in item["content"]]

    assert len(historical) == 40
    assert historical[0].endswith("message 5")
    assert historical[-1].endswith("message 44")


def test_context_length_and_summary_are_isolated_per_group(tmp_path):
    config = AppConfig(openai_api_key="x", model=ModelConfig(context_compression_provider="openai"))
    db = Database(tmp_path / "bot.sqlite3")
    memory = MemoryStore(db)
    context = ContextStore(db)
    prompt_path = tmp_path / "PROMPT.md"
    prompt_path.write_text("Test prompt", encoding="utf-8")
    router = MessageRouter(
        config=config,
        db=db,
        auth=AuthService(config),
        limiter=None,
        context=context,
        memory=memory,
        commands=CommandProcessor(config, db, memory),
        search=None,
        url_fetch=None,
        research=None,
        code=None,
        docs=None,
        vision=None,
        llm=None,
        prompt_path=prompt_path,
        clan=None,
    )
    processor = router.commands
    for chat_id in ("room-a", "room-b"):
        for index in range(45):
            context.add_message(chat_id, "user", "user", f"{chat_id} message {index}")
    db.set_setting("group_context_summary:room-a", {"summary": "obsolete"})

    processor.handle("/context 40", "room-a", True, is_admin=True)

    assert router._group_settings("room-a")["context_messages"] == 40
    assert router._group_settings("room-b")["context_messages"] == DEFAULT_CONTEXT_MESSAGES
    assert db.get_setting("group_context_summary:room-a") == {}
    assert db.get_setting("group_context_summary:room-b") is None

    room_a = context.compression_window("room-a", max_turns=router._group_settings("room-a")["context_messages"])
    room_b = context.compression_window("room-b", max_turns=router._group_settings("room-b")["context_messages"])
    assert len(room_a[1]) == 40
    assert len(room_b[1]) == DEFAULT_CONTEXT_MESSAGES


def test_router_refreshes_context_summary_without_blocking_main_prompt(tmp_path):
    class SlowLLM:
        def __init__(self):
            self.started = Event()
            self.release = Event()
            self.calls = 0
            self.inputs = []

        def chat(self, messages, **kwargs):
            self.calls += 1
            self.inputs.append(messages)
            self.started.set()
            assert self.release.wait(timeout=15)
            return "决定：下周二发布。\n待确认：数据库回滚方案。"

    config = AppConfig(openai_api_key="x", model=ModelConfig(context_compression_provider="openai"))
    db = Database(tmp_path / "bot.sqlite3")
    memory = MemoryStore(db)
    context = ContextStore(db)
    llm = SlowLLM()
    prompt_path = tmp_path / "PROMPT.md"
    prompt_path.write_text("Test prompt", encoding="utf-8")
    router = MessageRouter(
        config=config,
        db=db,
        auth=AuthService(config),
        limiter=None,
        context=context,
        memory=memory,
        commands=CommandProcessor(config, db, memory),
        search=None,
        url_fetch=None,
        research=None,
        code=None,
        docs=None,
        vision=None,
        llm=llm,
        prompt_path=prompt_path,
        clan=None,
    )
    for index in range(45):
        context.add_message("room", f"user-{index % 3}", "user", f"message {index}")
    settings = router._group_settings("room")
    msg = IncomingMessage(1, "current-user", "room", "room", "current", 1, True, False)

    started_at = time.monotonic()
    first_messages = router._assemble_messages(msg, "current", [], settings, is_admin=False)
    elapsed = time.monotonic() - started_at

    assert not llm.release.is_set()
    assert llm.started.wait(timeout=1)
    assert not any("下周二发布" in item["content"] for item in first_messages)
    llm.release.set()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and not db.get_setting("group_context_summary:room", {}):
        time.sleep(0.02)

    second_messages = router._assemble_messages(msg, "current", [], settings, is_admin=False)
    assert any("下周二发布" in item["content"] for item in second_messages)
    assert llm.calls == 1

    llm.started.clear()
    llm.release.clear()
    for index in range(45, 64):
        context.add_message("room", f"user-{index % 3}", "user", f"message {index}")
    bridge_messages = router._assemble_messages(msg, "current", [], settings, is_admin=False)

    assert llm.calls == 1
    assert not llm.started.is_set()
    assert any("message 15" in item["content"] and "message 33" in item["content"] for item in bridge_messages)

    context.add_message("room", "user-1", "user", "message 64")
    refresh_started_at = time.monotonic()
    stale_messages = router._assemble_messages(msg, "current", [], settings, is_admin=False)
    refresh_elapsed = time.monotonic() - refresh_started_at

    assert not llm.release.is_set()
    assert llm.started.wait(timeout=1)
    assert any("下周二发布" in item["content"] for item in stale_messages)
    assert any("message 15" in item["content"] and "message 34" in item["content"] for item in stale_messages)
    incremental_prompt = llm.inputs[1][-1]["content"]
    assert "<untrusted_existing_summary>" in incremental_prompt
    assert 'count="20"' in incremental_prompt
    assert "message 15" in incremental_prompt
    assert "message 34" in incremental_prompt
    assert "message 0" not in incremental_prompt
    llm.release.set()
    deadline = time.monotonic() + 3
    refreshed = {}
    while time.monotonic() < deadline:
        refreshed = db.get_setting("group_context_summary:room", {})
        if refreshed.get("last_batch_count") == 20:
            break
        time.sleep(0.02)

    assert refreshed["source_count"] == 35
    assert refreshed["last_batch_count"] == 20
    llm.started.clear()
    settled_messages = router._assemble_messages(msg, "current", [], settings, is_admin=False)
    assert llm.calls == 2
    assert not llm.started.is_set()
    assert not any("not yet merged" in item["content"] for item in settled_messages)
    router.close()

    assert llm.calls == 2


def test_closed_router_does_not_schedule_context_compression(tmp_path):
    class RecordingLLM:
        def __init__(self):
            self.calls = 0

        def chat(self, messages, **kwargs):
            self.calls += 1
            return "summary"

    config = AppConfig(openai_api_key="x", model=ModelConfig(context_compression_provider="openai"))
    db = Database(tmp_path / "bot.sqlite3")
    memory = MemoryStore(db)
    context = ContextStore(db)
    llm = RecordingLLM()
    prompt_path = tmp_path / "PROMPT.md"
    prompt_path.write_text("Test prompt", encoding="utf-8")
    router = MessageRouter(
        config=config,
        db=db,
        auth=AuthService(config),
        limiter=None,
        context=context,
        memory=memory,
        commands=CommandProcessor(config, db, memory),
        search=None,
        url_fetch=None,
        research=None,
        code=None,
        docs=None,
        vision=None,
        llm=llm,
        prompt_path=prompt_path,
        clan=None,
    )
    for index in range(45):
        context.add_message("room", "user", "user", f"message {index}")
    router.close()

    router._assemble_messages(
        IncomingMessage(1, "user", "room", "room", "current", 1, True, False),
        "current",
        [],
        router._group_settings("room"),
        is_admin=False,
    )

    assert llm.calls == 0
