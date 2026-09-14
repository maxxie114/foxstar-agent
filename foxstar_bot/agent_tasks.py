from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .llm_client import LLMClient
from .persistence import Database
from .tool_research import WebResearchAgent

LOG = logging.getLogger(__name__)

AGENT_TASK_MAX_ROUNDS = 12
AGENT_TASK_TIMEOUT_SECONDS = 600.0
AGENT_TASK_RESULT_PREVIEW_CHARS = 1200


class AgentTaskRunner:
    def __init__(self, db: Database, llm: LLMClient, research: WebResearchAgent) -> None:
        self.db = db
        self.llm = llm
        self.research = research
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="AgentTask")
        self._closed = False

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._executor.shutdown(wait=False, cancel_futures=True)

    def submit_pending(self) -> None:
        if self._closed:
            return


        self._executor.submit(self._drain_worker)

    def _drain_worker(self) -> None:
        try:
            for _ in range(3):
                task = self.db.claim_pending_agent_task()
                if task is None:
                    return
                self._run_task(task)
        except Exception:
            LOG.exception("agent_task worker crashed")

    def _run_task(self, task: dict[str, Any]) -> None:
        task_id = int(task["id"])
        chat_id = str(task["chat_id"])
        instruction = str(task["instruction"] or "").strip()
        LOG.info("agent_task start id=%s chat=%s instruction=%r", task_id, chat_id, instruction[:120])
        started = time.monotonic()

        def research_tool(query: str, max_rounds: int = 2) -> dict[str, Any]:
            lookup = " ".join(str(query or "").split()).strip()
            if not lookup:
                return {"ok": False, "error": "query is required"}
            self.db.update_agent_task(task_id, progress_note=f"researching: {lookup[:200]}")
            result = self.research.research(lookup, max_rounds=max(1, min(int(max_rounds or 2), 3)),
                                            max_pages=3, chat_id=f"agent-task-{task_id}")
            return {"ok": True, "content": result}

        def finish_task(report: str) -> dict[str, Any]:
            return {"__terminal_response__": True, "text": str(report or "")}

        tools = [
            {
                "type": "function",
                "name": "research",
                "description": "Run web research on a query and get a sourced brief. Use multiple targeted queries for multi-part tasks.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Focused search query."},
                        "max_rounds": {"type": "integer", "description": "1-3, default 2."},
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "finish_task",
                "description": "Finish with the final answer/report for the original instruction. Chinese, compact, cite sources when research was used.",
                "parameters": {
                    "type": "object",
                    "properties": {"report": {"type": "string", "description": "Final report."}},
                    "required": ["report"],
                    "additionalProperties": False,
                },
            },
        ]
        elapsed_deadline = started + AGENT_TASK_TIMEOUT_SECONDS
        try:
            answer = self.llm.chat_with_tools(
                [
                    {
                        "role": "system",
                        "content": (
                            "You are a background research task runner. Work autonomously: research what the "
                            "instruction needs with the research tool (multiple queries allowed), then call "
                            "finish_task with the final compact Chinese report. No chat small talk."
                        ),
                    },
                    {"role": "user", "content": f"Task instruction:\n{instruction}"},
                ],
                tools,
                {"research": research_tool, "finish_task": finish_task},
                max_output_tokens=4000,
                reasoning_effort="medium",
                provider="openai",
                max_tool_rounds=AGENT_TASK_MAX_ROUNDS,
                usage_context={"chat_id": chat_id, "feature": "agent_task"},
            )
        except Exception as exc:
            LOG.warning("agent_task failed id=%s reason=%s", task_id, exc)
            self.db.update_agent_task(task_id, status="failed", error=str(exc)[:2000])
            return
        result = " ".join((answer or "").strip().split())
        if not result:
            self.db.update_agent_task(task_id, status="failed", error="empty final report")
            return
        self.db.update_agent_task(task_id, status="done", result=result[:20000])
        LOG.info(
            "agent_task done id=%s chat=%s elapsed=%.1fs chars=%s",
            task_id, chat_id, time.monotonic() - started, len(result),
        )
