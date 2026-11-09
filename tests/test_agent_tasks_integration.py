# -*- coding: utf-8 -*-
"""Long-task framework (#31): runner, tools, command."""
from pathlib import Path
from unittest.mock import MagicMock

from foxstar_bot.agent_tasks import AgentTaskRunner
from foxstar_bot.commands import CommandProcessor
from foxstar_bot.config import AppConfig
from foxstar_bot.memory_store import MemoryStore
from foxstar_bot.persistence import Database


class _FakeToolLLM:
    """chat_with_tools that calls the research handler once then finishes."""

    def __init__(self):
        self.calls = []

    def chat_with_tools(self, messages, tools, tool_handlers, **kwargs):
        self.calls.append({"tools": [t["name"] for t in tools], "messages": len(messages)})
        research = tool_handlers["research"]("测试查询 猫娘")
        assert research["ok"]
        return tool_handlers["finish_task"]("研究报告：结论X。")["text"]


def _runner(tmp_path):
    db = Database(tmp_path / "bot.sqlite3")
    llm = _FakeToolLLM()
    research = MagicMock()
    research.research.return_value = "Exa deep search result: 测试简报"
    runner = AgentTaskRunner(db, llm, research)
    return runner, db, llm, research


def test_agent_task_runner_end_to_end(tmp_path):
    runner, db, llm, research = _runner(tmp_path)
    task_id = db.add_agent_task(chat_id="room", created_by="u1", instruction="研究一下猫娘文化的历史")
    runner._drain_worker()

    task = db.get_agent_task(task_id)
    assert task["status"] == "done"
    assert "结论X" in task["result"]
    assert task["started_at"] and task["finished_at"]
    # the isolated runner passed no group-chat context
    assert llm.calls and llm.calls[0]["messages"] == 2
    # research tool routed through WebResearchAgent
    research.research.assert_called_once()
    runner.close()


def test_agent_task_runner_failure_marks_failed(tmp_path):
    db = Database(tmp_path / "bot.sqlite3")

    class _Boom:
        def chat_with_tools(self, *a, **k):
            raise RuntimeError("provider exploded")

    runner = AgentTaskRunner(db, _Boom(), MagicMock())
    task_id = db.add_agent_task(chat_id="room", created_by="u1", instruction="x" * 20)
    runner._drain_worker()
    task = db.get_agent_task(task_id)
    assert task["status"] == "failed"
    assert "provider exploded" in task["error"]
    runner.close()


def test_tasks_command_flow(tmp_path):
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(AppConfig(openai_api_key="x"), db, MemoryStore(db))

    empty = processor.handle("/tasks", "room", True, is_admin=True)
    assert "没有后台任务" in empty.reply

    task_id = db.add_agent_task(chat_id="room", created_by="u1", instruction="研究X并汇报")
    listing = processor.handle("/tasks", "room", True, is_admin=True)
    assert f"#{task_id}" in listing.reply and "pending" in listing.reply

    status = processor.handle(f"/tasks status {task_id}", "room", True, is_admin=True)
    assert f"#{task_id} [pending]" in status.reply

    cancel = processor.handle(f"/tasks cancel {task_id}", "room", True, is_admin=True)
    assert "已标记取消" in cancel.reply
    assert db.get_agent_task(task_id)["status"] == "cancelled"

    other_room = processor.handle(f"/tasks status {task_id}", "other", True, is_admin=True)
    assert "不存在" in other_room.reply


def test_router_registers_agent_task_tools(tmp_path):
    import sys

    sys.path.insert(0, ".")
    from foxstar_bot.context_store import ContextStore
    from foxstar_bot.router import MessageRouter

    db = Database(tmp_path / "bot.sqlite3")
    router = MessageRouter(
        config=AppConfig(openai_api_key="x"), db=db, auth=MagicMock(), limiter=MagicMock(),
        context=ContextStore(db), memory=MagicMock(), commands=MagicMock(), search=MagicMock(),
        url_fetch=MagicMock(), research=MagicMock(), code=MagicMock(), docs=MagicMock(),
        vision=MagicMock(), llm=MagicMock(), prompt_path=Path("PROMPT.md"), skills=MagicMock(),
        clan=None,
    )
    handlers = router._tool_handlers(MagicMock(), "room", "u1", True, "帮我后台研究一下示例主题")
    assert "start_agent_task" in handlers
    assert "get_task_status" in handlers

    result = handlers["start_agent_task"]("帮我后台研究一下逆水寒经济系统并写总结")
    assert result["ok"] is True and result["task_id"] >= 1
    status = handlers["get_task_status"](result["task_id"])
    assert status["ok"] is True and status["status"] == "pending"
    router.close()
