from pathlib import Path
from unittest.mock import MagicMock

from foxstar_bot.agent_tasks import AgentTaskRunner
from foxstar_bot.config import AppConfig
from foxstar_bot.memory_store import MemoryStore
from foxstar_bot.persistence import Database


class _FakeToolLLM:

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

    assert llm.calls and llm.calls[0]["messages"] == 2

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
