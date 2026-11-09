# -*- coding: utf-8 -*-
"""Agent Control API (#32): auth, endpoints, command passthrough."""
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ["AGENT_API_TOKEN_READ"] = "test-read-token"
os.environ["AGENT_API_TOKEN_WRITE"] = "test-write-token"

from foxstar_bot.agent_api import create_app  # noqa: E402
from foxstar_bot.commands import CommandProcessor  # noqa: E402
from foxstar_bot.config import AppConfig  # noqa: E402
from foxstar_bot.memory_store import MemoryStore  # noqa: E402
from foxstar_bot.persistence import Database  # noqa: E402

READ = {"Authorization": "Bearer test-read-token"}
WRITE = {"Authorization": "Bearer test-write-token"}
BAD = {"Authorization": "Bearer wrong-token"}


@pytest.fixture()
def client(tmp_path):
    db = Database(tmp_path / "api.sqlite3")
    config = AppConfig(openai_api_key="x")
    commands = CommandProcessor(config, db, MemoryStore(db))
    # seed data
    db.add_finance_noteboard_entry(
        chat_id="room", source_message_id="m1", sender_id="u1", sender_name="Alice",
        content="玲50", numeric_values=[{"raw": "50", "value": "50", "unit": ""}])
    db.add_agent_task(chat_id="room", created_by="u", instruction="研究一下什么什么")
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO bug_reports(chat_id, created_by, description, status, created_at, updated_at) "
            "VALUES('room', 'u', 'test bug', 'open', datetime('now'), datetime('now'))")
        conn.execute(
            "INSERT INTO messages(chat_id, user_id, role, content, kind, created_at) "
            "VALUES('room', 'wxid_secret123', 'user', 'hello world', 'text', datetime('now'))")
    app = create_app(config=config, db=db, commands=commands)
    with TestClient(app) as c:
        yield c


# ---- auth ----

def test_no_token_401(client):
    assert client.get("/api/health").status_code == 401

def test_bad_token_401(client):
    assert client.get("/api/stats", headers=BAD).status_code == 401

def test_read_token_cannot_write(client):
    r = client.post("/api/command", headers=READ, json={"chat_id": "room", "text": "/status"})
    assert r.status_code == 403

def test_write_token_can_read(client):
    assert client.get("/api/health", headers=WRITE).status_code == 200


# ---- read endpoints ----

def test_health(client):
    r = client.get("/api/health", headers=READ)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["db_reachable"] is True

def test_stats(client):
    r = client.get("/api/stats", headers=READ)
    assert r.status_code == 200
    body = r.json()
    assert body["bug_reports_open"] == 1
    assert body.get("agent_tasks", {}).get("pending") == 1

def test_logs_unknown_file(client):
    assert client.get("/api/logs?file=nope", headers=READ).status_code == 400

def test_logs_tail_and_grep(client):
    # write a test log
    Path("logs").mkdir(exist_ok=True)
    Path("logs/bot-debug.log").write_text("line1 alpha\nline2 beta\nline3 gamma\n", encoding="utf-8")
    r = client.get("/api/logs?file=bot-debug&lines=2", headers=READ)
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2 and "beta" in body["lines"][0]
    r2 = client.get("/api/logs?file=bot-debug&grep=alpha", headers=READ)
    assert r2.json()["count"] == 1

def test_bugreports(client):
    r = client.get("/api/bugreports?status=open", headers=READ)
    body = r.json()
    assert body["count"] == 1 and body["reports"][0]["description"] == "test bug"

@pytest.mark.parametrize("status,expected", [("open", 1), ("closed", 1), ("all", 2)])
def test_bugreport_status_filters(client, status, expected):
    with client.app.state.db.connect() as conn:
        conn.execute(
            "INSERT INTO bug_reports(chat_id, created_by, description, status, created_at, updated_at) "
            "VALUES('room', 'u', 'resolved example', 'closed', datetime('now'), datetime('now'))"
        )
    response = client.get(f"/api/bugreports?status={status}", headers=READ)
    assert response.status_code == 200
    assert response.json()["count"] == expected
    if status != "all":
        assert all(row["status"] == status for row in response.json()["reports"])

def test_bugreport_invalid_status_is_rejected(client):
    assert client.get("/api/bugreports?status=invalid", headers=READ).status_code == 400

@pytest.mark.parametrize("override,expected", [(None, "127.0.0.1"), ("0.0.0.0", "0.0.0.0")])
def test_api_bind_address_is_local_unless_explicitly_configured(monkeypatch, override, expected):
    import sys
    from types import SimpleNamespace
    from unittest.mock import Mock
    from foxstar_bot import agent_api

    monkeypatch.delenv("AGENT_API_HOST", raising=False)
    if override is not None:
        monkeypatch.setenv("AGENT_API_HOST", override)
    server = Mock()
    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=server))
    application = object()
    monkeypatch.setattr(agent_api, "create_app", lambda: application)
    agent_api.main()
    server.assert_called_once()
    assert server.call_args.args == (application,)
    assert server.call_args.kwargs["host"] == expected

def test_messages_redacted(client):
    r = client.get("/api/messages?chat=room", headers=READ)
    body = r.json()
    assert body["count"] == 1
    assert "wxid_secret123" not in json_dumps(body)

def test_notebook(client):
    r = client.get("/api/notebook?chat=room", headers=READ)
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1 and "玲50" in body["entries"][0]["content"]

def test_config_masks_secrets(client):
    client.app.state.db.set_setting("group_api_token:room", "super-secret-value")
    r = client.get("/api/config", headers=READ)
    assert r.json()["settings"].get("group_api_token:room") == "***"

def test_tasks_list(client):
    r = client.get("/api/tasks", headers=READ)
    assert r.json()["count"] == 1


# ---- write endpoints ----

def test_command_passthrough(client):
    r = client.post("/api/command", headers=WRITE,
                    json={"chat_id": "room@chatroom", "text": "/blacklist list"})
    assert r.status_code == 200
    body = r.json()
    assert body["handled"] is True and isinstance(body["reply"], str)

def test_command_rejects_non_slash(client):
    r = client.post("/api/command", headers=WRITE,
                    json={"chat_id": "room", "text": "hello not a command"})
    assert r.status_code == 400

def test_config_set_and_whitelist(client):
    ok = client.post("/api/config", headers=WRITE,
                     json={"key": "group_style:room", "value": "free"})
    assert ok.status_code == 200 and ok.json()["ok"] is True
    denied = client.post("/api/config", headers=WRITE,
                         json={"key": "owner_user_id", "value": "hacker"})
    assert denied.status_code == 400

def test_tasks_create_and_cancel(client):
    r = client.post("/api/tasks", headers=WRITE,
                    json={"action": "create", "chat_id": "room", "instruction": "研究一下Exa最新动态"})
    body = r.json()
    assert body["ok"] is True and body["task_id"] > 0
    c = client.post("/api/tasks", headers=WRITE,
                    json={"action": "cancel", "task_id": body["task_id"]})
    assert c.json()["ok"] is True

def test_memory_write(client):
    r = client.post("/api/memory", headers=WRITE,
                    json={"chat_id": "room", "key": "api-test", "value": "written via api"})
    assert r.status_code == 200 and r.json()["ok"] is True
    from foxstar_bot.memory_store import MemoryStore as MS
    store = MS(client.app.state.db)
    items = store.list_scope("chat", "room", 10)
    assert any(i["key"] == "api-test" and "written via api" in str(i["value"]) for i in items)


def json_dumps(body: dict) -> str:
    import json

    return json.dumps(body, ensure_ascii=False)
