from unittest.mock import Mock

from foxstar_bot.config import AppConfig
from foxstar_bot.context_store import ContextStore
from foxstar_bot.persistence import Database
from foxstar_bot.router import ContextCompressor


def test_reply_job_can_be_recovered_and_completed(tmp_path):
    path = tmp_path / "example.sqlite3"
    db = Database(path)
    job_id = db.add_reply_job("sample-room", "message-1", "{}", 7)
    assert job_id is not None
    assert db.add_reply_job("sample-room", "message-1", "{}", 7) is None
    assert db.start_reply_job(job_id)

    reopened = Database(path)
    reopened.recover_reply_jobs()
    jobs = reopened.list_queued_reply_jobs()
    assert [job["id"] for job in jobs] == [job_id]
    assert jobs[0]["context_id"] == 7
    assert reopened.start_reply_job(job_id)
    reopened.finish_reply_job(job_id)
    assert not reopened.list_queued_reply_jobs()


def test_background_summary_is_persisted(tmp_path):
    db = Database(tmp_path / "example.sqlite3")
    store = ContextStore(db)
    for i in range(85):
        store.add_message("sample-room", "speaker", "user", f"Topic {i} has a new decision.")
    model = Mock()
    model.chat.return_value = "Several decisions were recorded."
    compressor = ContextCompressor(db, model, AppConfig())
    try:
        compressor.refresh("sample-room", 10)
    finally:
        compressor.close()
    assert db.get_setting("group_context_summary:sample-room", {})["summary"] == model.chat.return_value

