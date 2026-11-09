"""Regression tests for the schedule_task tool.

The tool's `timezone: str` parameter shadowed `datetime.timezone`, so every
`.astimezone(timezone.utc)` call inside the function raised
`'str' object has no attribute 'utc'` and the task was never persisted. These
tests exercise the real tool handler so the bug cannot silently come back.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from foxstar_bot.commands import CommandProcessor
from foxstar_bot.config import AppConfig
from foxstar_bot.context_store import ContextStore
from foxstar_bot.memory_store import MemoryStore
from foxstar_bot.persistence import Database, MAX_ENABLED_SCHEDULED_TASKS_PER_CHAT, ScheduledTaskLimitError
from foxstar_bot.router import MessageRouter
from foxstar_bot.wcf_adapter import IncomingMessage


def _build_router(tmp_path):
    db = Database(tmp_path / "bot.sqlite3")
    cfg = AppConfig(openai_api_key="x")
    router = MessageRouter(
        config=cfg,
        db=db,
        auth=MagicMock(),
        limiter=MagicMock(),
        context=ContextStore(db),
        memory=MemoryStore(db),
        commands=MagicMock(),
        search=MagicMock(),
        url_fetch=MagicMock(),
        research=MagicMock(),
        code=MagicMock(),
        docs=MagicMock(),
        vision=MagicMock(),
        llm=MagicMock(),
        prompt_path=Path("PROMPT.md"),
        skills=MagicMock(),
        clan=None,
    )
    return router, db


def test_schedule_task_cron_persists(tmp_path):
    router, db = _build_router(tmp_path)
    handlers = router._tool_handlers(
        MagicMock(), "room@chatroom", "wxid_owner", is_admin=True, original_text="set up btc hourly"
    )
    result = handlers["schedule_task"](
        schedule_type="cron",
        payload="get decision, btc",
        cron_expr="0 * * * *",
        timezone="America/Los_Angeles",
    )

    assert result.get("ok") is True, f"cron schedule failed: {result}"
    assert result["next_run_at"].endswith("+00:00")
    rows = db.list_scheduled_tasks("room@chatroom")
    assert len(rows) == 1
    assert rows[0]["schedule_type"] == "cron"
    assert rows[0]["cron_expr"] == "0 * * * *"


def test_schedule_task_once_delay_seconds(tmp_path):
    router, db = _build_router(tmp_path)
    handlers = router._tool_handlers(
        MagicMock(), "room@chatroom", "wxid_owner", is_admin=True, original_text="remind me"
    )
    result = handlers["schedule_task"](
        schedule_type="once",
        payload="remind max",
        delay_seconds=3600,
    )

    assert result.get("ok") is True, f"once delay failed: {result}"
    assert result["next_run_at"].endswith("+00:00")
    rows = db.list_scheduled_tasks("room@chatroom")
    assert len(rows) == 1
    assert rows[0]["schedule_type"] == "once"


def test_schedule_task_once_run_at_with_offset_timezone(tmp_path):
    # The Asia/Shanghai case from production logs (with an explicit +08:00 offset).
    router, db = _build_router(tmp_path)
    handlers = router._tool_handlers(
        MagicMock(), "room@chatroom", "wxid_owner", is_admin=True, original_text="remind"
    )
    result = handlers["schedule_task"](
        schedule_type="once",
        payload="提醒 Example User 发布帮战接龙",
        run_at="2026-06-10T12:00:00+08:00",
    )

    assert result.get("ok") is True, f"once run_at failed: {result}"
    # Noon +08:00 == 04:00 UTC.
    assert result["next_run_at"] == "2026-06-10T04:00:00+00:00"


def test_schedule_task_exact_duplicate_is_idempotent(tmp_path):
    router, db = _build_router(tmp_path)
    handler = router._tool_handlers(
        MagicMock(), "room@chatroom", "wxid_owner", is_admin=True, original_text="daily report"
    )["schedule_task"]

    first = handler(
        schedule_type="cron",
        payload="每日汇总交易记录",
        cron_expr="0 20 * * *",
        timezone="Asia/Shanghai",
    )
    second = handler(
        schedule_type="cron",
        payload="每日汇总交易记录",
        cron_expr="0 20 * * *",
        timezone="Asia/Shanghai",
    )

    assert first["created"] is True
    assert second["created"] is False
    assert second["duplicate"] is True
    assert second["id"] == first["id"]
    assert len(db.list_scheduled_tasks("room@chatroom")) == 1


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


def test_scheduled_execution_has_no_scheduling_tool_or_handler_access(tmp_path):
    router, _ = _build_router(tmp_path)

    specs = router._tool_specs({}, is_admin=True, allow_scheduling=False)
    handlers = router._tool_handlers(
        MagicMock(),
        "room@chatroom",
        "wxid_owner",
        is_admin=True,
        allow_scheduling=False,
    )
    blocked = handlers["schedule_task"](
        schedule_type="cron",
        payload="recursive child",
        cron_expr="0 20 * * *",
    )

    assert "schedule_task" not in {spec["name"] for spec in specs}
    assert blocked["ok"] is False
    assert "cannot create" in blocked["error"]


def test_non_admin_has_no_scheduling_tool_and_handler_rejects_direct_access(tmp_path):
    router, _ = _build_router(tmp_path)

    specs = router._tool_specs({}, is_admin=False, allow_scheduling=True)
    handlers = router._tool_handlers(
        MagicMock(),
        "room@chatroom",
        "wxid_example027",
        is_admin=False,
        allow_scheduling=True,
    )
    blocked = handlers["schedule_task"](
        schedule_type="cron",
        payload="should not be created",
        cron_expr="0 20 * * *",
    )

    assert "schedule_task" not in {spec["name"] for spec in specs}
    assert blocked == {"ok": False, "error": "scheduled tasks are whitelist/admin only"}


def test_non_admin_schedule_command_cannot_create_task(tmp_path):
    db = Database(tmp_path / "bot.sqlite3")
    config = AppConfig(openai_api_key="x")
    processor = CommandProcessor(config, db, MemoryStore(db))

    result = processor.handle(
        "/schedule 0 20 * * * daily report",
        "room@chatroom",
        True,
        is_admin=False,
        sender_id="wxid_example027",
    )

    assert result.handled is True
    assert result.reply == ""
    assert db.list_scheduled_tasks("room@chatroom") == []


def test_scheduled_prompt_is_marked_as_execution_not_configuration(tmp_path):
    router, _ = _build_router(tmp_path)
    settings = router._group_settings("room@chatroom")
    msg = IncomingMessage(
        id=0,
        sender="wxid_owner",
        chat_id="room@chatroom",
        room_id="room@chatroom",
        content="每日汇总交易记录",
        msg_type=1,
        is_group=True,
        is_self=False,
    )

    messages = router._assemble_messages(
        msg,
        msg.content,
        [],
        settings,
        is_admin=True,
        allow_scheduling=False,
    )
    system_text = "\n".join(item["content"] for item in messages if item["role"] == "system")

    assert "current execution of an existing scheduled task" in system_text
    assert "use the schedule_task tool" not in system_text


def test_scheduled_schedule_command_is_blocked(tmp_path):
    router, _ = _build_router(tmp_path)
    adapter = MagicMock()

    result = router._execute_scheduled_task(
        adapter,
        {
            "id": 99,
            "chat_id": "room@chatroom",
            "created_by": "wxid_owner",
            "payload": "/schedule 0 20 * * * recursive child",
        },
    )

    assert result.startswith("blocked:")
    router.commands.handle.assert_not_called()
