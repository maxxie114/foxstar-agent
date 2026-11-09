"""Tests for the /bugreport command.

Bug reports are global tickets, not per-chat: a report filed in one group must be
visible and actionable (list/close/reopen) from any other group. This was broken
because list/close/reopen all filtered by chat_id.
"""

from foxstar_bot.commands import CommandProcessor
from foxstar_bot.config import AppConfig
from foxstar_bot.memory_store import MemoryStore
from foxstar_bot.persistence import Database


def _processor(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    return CommandProcessor(config, db, MemoryStore(db)), db


def test_bug_reports_are_shared_across_groups(tmp_path):
    processor, _ = _processor(tmp_path)
    room_a = "11111111111@chatroom"
    room_b = "22222222222@chatroom"

    # File a report in room A.
    filed = processor.handle(
        "/bugreport finance json truncates on long analysis",
        room_a, True, is_admin=True, sender_id="wxid_example009dmin",
    )
    assert filed.handled is True
    assert "recorded" in filed.reply

    # It must be visible from room B (the regression: previously empty here).
    listed_in_b = processor.handle("/bugreport list", room_b, True, is_admin=True)
    assert listed_in_b.handled is True
    assert "finance json truncates" in listed_in_b.reply

    # The listing should show the origin chat label.
    assert "11111111111" in listed_in_b.reply


def test_bug_report_can_be_closed_from_a_different_group(tmp_path):
    processor, _ = _processor(tmp_path)
    room_a = "11111111111@chatroom"
    room_b = "22222222222@chatroom"

    filed = processor.handle(
        "/bugreport scheduler does not fire",
        room_a, True, is_admin=True, sender_id="wxid_example009dmin",
    )
    assert filed.handled is True
    # Extract the ticket id from "bug report #<id> recorded: ..."
    bug_id = filed.reply.split("#")[1].split(" ")[0]
    assert bug_id.isdigit()

    # Close it from room B (the regression: previously "no bug report found").
    closed = processor.handle(f"/bugreport close {bug_id}", room_b, True, is_admin=True)
    assert closed.handled is True
    assert "marked closed" in closed.reply

    # Default listing is open-only, so it should no longer appear.
    open_list = processor.handle("/bugreport list", room_a, True, is_admin=True)
    assert "scheduler does not fire" not in open_list.reply

    # But it should appear in the closed listing.
    closed_list = processor.handle("/bugreport list closed", room_a, True, is_admin=True)
    assert "scheduler does not fire" in closed_list.reply


def test_bug_report_can_be_reopened_globally(tmp_path):
    processor, _ = _processor(tmp_path)
    room_a = "11111111111@chatroom"
    room_b = "22222222222@chatroom"

    filed = processor.handle(
        "/bugreport flaky quote tool",
        room_a, True, is_admin=True, sender_id="wxid_example009dmin",
    )
    bug_id = filed.reply.split("#")[1].split(" ")[0]
    processor.handle(f"/bugreport close {bug_id}", room_b, True, is_admin=True)

    reopened = processor.handle(f"/bugreport reopen {bug_id}", room_b, True, is_admin=True)
    assert reopened.handled is True
    assert "marked open" in reopened.reply

    # Back in the open listing for room A.
    open_list = processor.handle("/bugreport list", room_a, True, is_admin=True)
    assert "flaky quote tool" in open_list.reply
