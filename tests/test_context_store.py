import time

from threading import Event

from foxstar_bot.auth import AuthService

from foxstar_bot.config import AppConfig

from foxstar_bot.context_store import ContextStore

from foxstar_bot.memory_store import MemoryStore

from foxstar_bot.persistence import Database

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
