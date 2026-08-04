import time
from threading import Event

from foxstar_bot.auth import AuthService
from foxstar_bot.config import AppConfig
from foxstar_bot.context_store import ContextStore, DEFAULT_CONTEXT_MESSAGES, MAX_CONTEXT_MESSAGES
from foxstar_bot.memory_store import MemoryStore
from foxstar_bot.persistence import Database
from foxstar_bot.privacy import public_participant_label


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
        {"user_id": "wxid_test_de81", "role": "user", "content": "决定继续使用方案 A", "kind": "text"},
        {"user_id": "wxid_test_de81", "role": "user", "content": "决定继续使用方案 A", "kind": "text"},
        {"user_id": "wxid_test_4c90", "role": "user", "content": "部署密码应该放在哪里？", "kind": "text"},
    ]

    source = ContextStore.render_compression_source(items)

    assert source.count("决定继续使用方案 A") == 1
    assert public_participant_label("wxid_test_de81") in source
    assert public_participant_label("wxid_test_4c90") in source
    assert "wxid_test_de81" not in source


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
