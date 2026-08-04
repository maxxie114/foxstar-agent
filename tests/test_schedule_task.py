from pathlib import Path
from unittest.mock import MagicMock

import pytest

from foxstar_bot.config import AppConfig
from foxstar_bot.context_store import ContextStore
from foxstar_bot.memory_store import MemoryStore
from foxstar_bot.persistence import Database, MAX_ENABLED_SCHEDULED_TASKS_PER_CHAT, ScheduledTaskLimitError


def test_one_shot_tasks_with_same_payload_but_different_times_are_distinct(tmp_path):
    db = Database(tmp_path / "bot.sqlite3")
    first_id, first_created = db.add_scheduled_task(
        chat_id="room@chatroom",
        created_by="owner",
        kind="prompt",
        schedule_type="once",
        cron_expr="",
        timezone_name="America/Los_Angeles",
        payload="提醒我开会",
        next_run_at="2026-08-05T12:00:00+00:00",
    )
    second_id, second_created = db.add_scheduled_task(
        chat_id="room@chatroom",
        created_by="owner",
        kind="prompt",
        schedule_type="once",
        cron_expr="",
        timezone_name="America/Los_Angeles",
        payload="提醒我开会",
        next_run_at="2026-08-06T12:00:00+00:00",
    )

    assert first_created is True
    assert second_created is True
    assert second_id != first_id


def test_scheduled_task_active_limit_is_enforced_atomically(tmp_path):
    db = Database(tmp_path / "bot.sqlite3")
    for index in range(MAX_ENABLED_SCHEDULED_TASKS_PER_CHAT):
        _, created = db.add_scheduled_task(
            chat_id="room@chatroom",
            created_by="owner",
            kind="prompt",
            schedule_type="cron",
            cron_expr="0 20 * * *",
            timezone_name="Asia/Shanghai",
            payload=f"report {index}",
            next_run_at="2026-08-05T12:00:00+00:00",
        )
        assert created is True

    with pytest.raises(ScheduledTaskLimitError):
        db.add_scheduled_task(
            chat_id="room@chatroom",
            created_by="owner",
            kind="prompt",
            schedule_type="cron",
            cron_expr="0 20 * * *",
            timezone_name="Asia/Shanghai",
            payload="one task too many",
            next_run_at="2026-08-05T12:00:00+00:00",
        )
