# -*- coding: utf-8 -*-
"""Agent Control API: full read/write HTTP surface over the bot (#32).

Runs as its OWN process (python -m foxstar_bot.agent_api); the bot never
imports this module. Opens its own WAL database connection and its own
CommandProcessor for the /command passthrough. Binds 127.0.0.1 only -
access via SSH tunnel. Dual bearer tokens from .env:

    AGENT_API_TOKEN_READ   - read endpoints
    AGENT_API_TOKEN_WRITE  - read + write endpoints (superset)

PowerShell quick start:
    ssh -L 8790:localhost:8790 Administrator@<server>
    Invoke-RestMethod http://127.0.0.1:8790/api/stats -Headers @{Authorization="Bearer <read>"}
    Invoke-RestMethod -Method Post http://127.0.0.1:8790/api/command `
        -Headers @{Authorization="Bearer <write>"} `
        -ContentType "application/json; charset=utf-8" `
        -Body ([System.Text.Encoding]::UTF8.GetBytes('{"chat_id":"...","text":"/status"}'))
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import time
from pathlib import Path
from typing import Any

import time

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .commands import CommandProcessor
from .config import AppConfig, load_config
from .memory_store import MemoryStore
from .persistence import Database
from .privacy import redact_private_ids

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
LOG = logging.getLogger("foxstar_bot.agent_api")

CONFIG_SETTING_PREFIXES = ("group_", "foxstar_")
LOG_FILES = {
    "bot-debug": "logs/bot-debug.log",
    "reply-gate": "logs/reply-gate.log",
    "error": "logs/error.log",
    "game": "logs/game.log",
    "tool-trace": "logs/tool-trace.log",
}
LOG_TAIL_MAX = 1000


# ---------------------------------------------------------------------------
# auth


def _load_tokens() -> tuple[str, str]:
    # tokens live in .env; load it so the scheduled-task launch (no shell
    # profile) still gets the persistent tokens instead of ephemeral ones
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass
    read_token = os.environ.get("AGENT_API_TOKEN_READ", "").strip()
    write_token = os.environ.get("AGENT_API_TOKEN_WRITE", "").strip()
    if not read_token or not write_token:
        read_token = read_token or secrets.token_urlsafe(24)
        write_token = write_token or secrets.token_urlsafe(24)
        LOG.warning(
            "AGENT_API_TOKEN_READ/WRITE not set; generated inaccessible ephemeral tokens. "
            "Configure both environment variables to access the API.",
        )
    return read_token, write_token


READ_TOKEN, WRITE_TOKEN = _load_tokens()

# brute-force lockout: N failed attempts within the window block the source
# IP for the window duration (in-memory; resets on API restart).
_AUTH_FAILS: dict[str, list[float]] = {}
AUTH_FAIL_LIMIT = 5
AUTH_FAIL_WINDOW_SECONDS = 900.0


def _register_auth_failure(request: Request) -> None:
    ip = request.client.host if request.client else "?"
    now = time.time()
    fails = [t for t in _AUTH_FAILS.get(ip, []) if now - t < AUTH_FAIL_WINDOW_SECONDS]
    fails.append(now)
    _AUTH_FAILS[ip] = fails


def _auth_locked_out(request: Request) -> bool:
    ip = request.client.host if request.client else "?"
    now = time.time()
    fails = [t for t in _AUTH_FAILS.get(ip, []) if now - t < AUTH_FAIL_WINDOW_SECONDS]
    return len(fails) >= AUTH_FAIL_LIMIT


async def require_read(request: Request) -> None:
    if _auth_locked_out(request):
        raise HTTPException(status_code=429, detail="too many failed auth attempts, retry later")
    header = request.headers.get("authorization", "")
    token = header.removeprefix("Bearer ").strip()
    if token not in {READ_TOKEN, WRITE_TOKEN}:
        _register_auth_failure(request)
        raise HTTPException(status_code=401, detail="invalid or missing bearer token")


async def require_write(request: Request) -> None:
    if _auth_locked_out(request):
        raise HTTPException(status_code=429, detail="too many failed auth attempts, retry later")
    header = request.headers.get("authorization", "")
    token = header.removeprefix("Bearer ").strip()
    if token == WRITE_TOKEN:
        return
    if token == READ_TOKEN:
        raise HTTPException(status_code=403, detail="write endpoints require the write token")
    _register_auth_failure(request)
    raise HTTPException(status_code=401, detail="invalid or missing bearer token")


# ---------------------------------------------------------------------------
# write models


class CommandRequest(BaseModel):
    chat_id: str
    text: str


class ConfigRequest(BaseModel):
    key: str
    value: Any


class TaskRequest(BaseModel):
    action: str  # create | cancel
    chat_id: str = ""
    instruction: str = ""
    task_id: int = 0


class MemoryRequest(BaseModel):
    chat_id: str
    key: str
    value: str


# ---------------------------------------------------------------------------
# app factory


def create_app(config: AppConfig | None = None, db: Database | None = None,
               commands: CommandProcessor | None = None) -> FastAPI:
    """Build the API app. Injectable deps for tests; production builds its own."""
    cfg = config or load_config("config.yaml")
    database = db or Database(Path(cfg.storage.sqlite_path))
    processor = commands or CommandProcessor(cfg, database, MemoryStore(database))
    started_at = time.time()

    app = FastAPI(title="FoxStar Agent API", version="1.0.0", docs_url=None)
    # token-header auth (no cookies); any origin may call - the bearer token
    # is the gate. Lets a future panel on any host talk to this API.
    # /docs disabled: no point advertising the surface on a public port.
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    app.state.db = database
    app.state.commands = processor

    # ---- read endpoints ----

    @app.get("/api/health", dependencies=[Depends(require_read)])
    async def health() -> dict[str, Any]:
        try:
            with database.connect() as conn:
                conn.execute("SELECT 1").fetchone()
                last_msg = conn.execute(
                    "SELECT MAX(created_at) AS m FROM messages"
                ).fetchone()["m"]
            db_ok = True
        except Exception as exc:
            db_ok, last_msg = False, str(exc)[:120]
        return {"ok": db_ok, "uptime_seconds": round(time.time() - started_at, 1),
                "db_reachable": db_ok, "last_message_at": str(last_msg or "")}

    @app.get("/api/stats", dependencies=[Depends(require_read)])
    async def stats() -> dict[str, Any]:
        out: dict[str, Any] = {}
        try:
            with database.connect() as conn:
                out["bug_reports_open"] = conn.execute(
                    "SELECT COUNT(*) c FROM bug_reports WHERE status='open'").fetchone()["c"]
                out["agent_tasks"] = {
                    row["status"]: row["c"] for row in conn.execute(
                        "SELECT status, COUNT(*) c FROM agent_tasks GROUP BY status")}
                out["messages_total"] = conn.execute("SELECT COUNT(*) c FROM messages").fetchone()["c"]
                out["notebook_total"] = conn.execute(
                    "SELECT COUNT(*) c FROM finance_noteboard_entries").fetchone()["c"]
                out["today_token_usage"] = [
                    dict(row) for row in conn.execute(
                        "SELECT provider, model, SUM(input_tokens) in_tok, SUM(output_tokens) out_tok, SUM(cached_tokens) cache_tok, SUM(requests) calls "
                        "FROM token_usage_daily WHERE bucket_date = date('now') GROUP BY provider, model ORDER BY 3 DESC LIMIT 20")]
        except Exception as exc:
            out["error"] = str(exc)[:200]
        return out

    @app.get("/api/logs", dependencies=[Depends(require_read)])
    async def logs(file: str = "bot-debug", lines: int = 200, grep: str = "", rotation: int = 0) -> dict[str, Any]:
        key = file.lower().removesuffix(".log")
        if key not in LOG_FILES:
            raise HTTPException(400, f"unknown log file {file!r}; one of {sorted(LOG_FILES)}")
        suffix = f".{rotation}" if rotation > 0 else ""
        path = Path(LOG_FILES[key] + suffix)
        if not path.exists():
            return {"file": str(path), "lines": [], "note": "not found"}
        lines_n = max(1, min(lines, LOG_TAIL_MAX))
        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                tail = f.readlines()[-lines_n:]
        except OSError as exc:
            raise HTTPException(500, f"log read failed: {exc}")
        if grep:
            pattern = re.compile(grep, re.IGNORECASE)
            tail = [line for line in tail if pattern.search(line)]
        return {"file": str(path), "count": len(tail),
                "lines": [line.rstrip("\n") for line in tail]}

    @app.get("/api/notebook", dependencies=[Depends(require_read)])
    async def notebook(chat: str = "", status: str = "", limit: int = 50, offset: int = 0,
                       include_chatter: bool = False) -> dict[str, Any]:
        rows = database.list_finance_noteboard_entries(
            chat or "____none____", days=None, limit=max(1, min(limit, 500)),
            include_chatter=include_chatter) if chat else []
        if status:
            status_map = {"pending": 0, "transaction": 1, "chatter": -1}
            if status not in status_map:
                raise HTTPException(400, "status one of pending|transaction|chatter")
            rows = [r for r in rows if _notebook_classified(database, r["id"]) == status_map[status]]
        return {"chat": chat, "count": len(rows),
                "entries": [_redact_row(r) for r in rows]}

    @app.get("/api/bugreports", dependencies=[Depends(require_read)])
    async def bugreports(status: str = "open", limit: int = 30) -> dict[str, Any]:
        if status not in {"open", "closed", "all"}:
            raise HTTPException(400, "status must be open, closed, or all")
        with database.connect() as conn:
            clause = "WHERE status = ?" if status != "all" else ""
            params = (status,) if status != "all" else ()
            rows = conn.execute(
                f"SELECT id, chat_id, created_by, description, status, created_at, closed_at FROM bug_reports {clause} ORDER BY id DESC LIMIT ?",
                params + (max(1, min(limit, 200)),)).fetchall()
        return {"count": len(rows), "reports": [dict(r) for r in rows]}

    @app.get("/api/messages", dependencies=[Depends(require_read)])
    async def messages(chat: str = "", hours: int = 24, q: str = "", limit: int = 50) -> dict[str, Any]:
        from datetime import datetime, timedelta, timezone as tz

        cutoff = (datetime.now(tz.utc) - timedelta(hours=max(1, min(hours, 720)))).isoformat(timespec="seconds")
        clauses, params = ["created_at >= ?"], [cutoff]
        if chat:
            clauses.append("chat_id = ?")
            params.append(chat)
        if q:
            clauses.append("content LIKE ?")
            params.append(f"%{q}%")
        params.append(max(1, min(limit, 500)))
        with database.connect() as conn:
            rows = conn.execute(
                f"SELECT created_at, chat_id, user_id, role, content FROM messages "
                f"WHERE {' AND '.join(clauses)} ORDER BY id DESC LIMIT ?",
                tuple(params)).fetchall()
        return {"count": len(rows), "messages": [_redact_row(dict(r)) for r in rows]}

    @app.get("/api/config", dependencies=[Depends(require_read)])
    async def config_view() -> dict[str, Any]:
        with database.connect() as conn:
            rows = conn.execute(
                "SELECT key, value FROM settings ORDER BY key LIMIT 500").fetchall()
        safe = {}
        for row in rows:
            if any(row["key"].startswith(p) for p in CONFIG_SETTING_PREFIXES):
                safe[row["key"]] = _mask_config_value(row["key"], row["value"])
        return {"count": len(safe), "settings": safe}

    @app.get("/api/tasks", dependencies=[Depends(require_read)])
    async def tasks_list(limit: int = 10) -> dict[str, Any]:
        rows = database.list_agent_tasks(limit=max(1, min(limit, 50)))
        return {"count": len(rows), "tasks": [_redact_row(r) for r in rows]}

    # ---- write endpoints ----

    @app.post("/api/command", dependencies=[Depends(require_write)])
    async def command(req: CommandRequest) -> dict[str, Any]:
        text = req.text.strip()
        if not text:
            raise HTTPException(400, "text is required")
        if not text.startswith("/"):
            raise HTTPException(400, "text must be a slash command (start with /)")
        chat_id = req.chat_id.strip()
        if not chat_id:
            raise HTTPException(400, "chat_id is required")
        is_group = chat_id.endswith("@chatroom")
        result = processor.handle(text, chat_id, is_group, True, sender_id="agent-api")
        return {"handled": result.handled, "reply": result.reply}

    @app.post("/api/config", dependencies=[Depends(require_write)])
    async def config_set(req: ConfigRequest) -> dict[str, Any]:
        key = req.key.strip()
        if not any(key.startswith(p) for p in CONFIG_SETTING_PREFIXES):
            raise HTTPException(400, f"key must start with one of {CONFIG_SETTING_PREFIXES}")
        value = req.value if isinstance(req.value, (bool, int, float)) else str(req.value)
        database.set_setting(key, value)
        return {"ok": True, "key": key, "value": value}

    @app.post("/api/tasks", dependencies=[Depends(require_write)])
    async def tasks_write(req: TaskRequest) -> dict[str, Any]:
        if req.action == "create":
            instruction = req.instruction.strip()
            if len(instruction) < 8:
                raise HTTPException(400, "instruction too short (min 8 chars)")
            task_id = database.add_agent_task(
                chat_id=req.chat_id.strip() or "private", created_by="agent-api",
                instruction=instruction)
            return {"ok": True, "task_id": task_id, "note": "task queued; deliver via bot scheduler tick"}
        if req.action == "cancel":
            task = database.get_agent_task(req.task_id)
            if task is None:
                raise HTTPException(404, f"task {req.task_id} not found")
            if task["status"] not in {"pending", "running"}:
                return {"ok": False, "note": f"task is {task['status']}, nothing to cancel"}
            database.update_agent_task(req.task_id, status="cancelled")
            return {"ok": True, "task_id": req.task_id, "status": "cancelled"}
        raise HTTPException(400, "action must be create|cancel")

    @app.post("/api/memory", dependencies=[Depends(require_write)])
    async def memory_write(req: MemoryRequest) -> dict[str, Any]:
        key = req.key.strip()
        if not key:
            raise HTTPException(400, "key is required")
        ok = _ms_store(database).upsert(
            "chat", req.chat_id.strip(), key, req.value.strip(),
            priority=100, source_user_id="agent-api")
        return {"ok": ok, "chat_id": req.chat_id, "key": key}

    @app.post("/api/deploy", dependencies=[Depends(require_write)])
    async def deploy() -> dict[str, Any]:
        """Pull latest code and trigger a bot restart (hot patch).
        The bot process exits; restart it with NSSM/wrapper/auto-restart."""
        from .health import run_deploy
        result = run_deploy(str(Path(".").resolve()))
        return result

    return app


def _ms_store(database: Database) -> MemoryStore:
    return MemoryStore(database)


def _redact_row(row: dict[str, Any]) -> dict[str, Any]:
    if "content" in row and isinstance(row["content"], str):
        row["content"] = redact_private_ids(row["content"])
    if "user_id" in row:
        row["user_id"] = "[redacted]"
    if "created_by" in row:
        row["created_by"] = "[redacted]"
    if "sender_id" in row:
        row["sender_id"] = "[redacted]"
    return row


def _mask_config_value(key: str, value: str) -> str:
    lowered = key.lower()
    if any(s in lowered for s in ("token", "key", "secret", "password")):
        return "***"
    return str(value)[:200]


def _notebook_classified(db: Database, entry_id: int) -> int:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT classified FROM finance_noteboard_entries WHERE id = ?", (entry_id,)).fetchone()
    return int(row["classified"]) if row else 0


def main() -> None:
    import uvicorn

    port = int(os.environ.get("AGENT_API_PORT", "8790"))
    host = os.environ.get("AGENT_API_HOST", "127.0.0.1")
    app = create_app()
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
