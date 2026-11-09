"""Integrated agent behavior with invented inputs and no vendor runtime."""
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from foxstar_bot import app
from foxstar_bot.auth import AuthService
from foxstar_bot.config import AppConfig
from foxstar_bot.wcf_adapter import IncomingMessage


@pytest.fixture
def framework(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(app, 'configure_logging', lambda level: None)
    Path('PROMPT.md').write_text('You are a helpful AI assistant.')
    skill = Path('skills/example')
    skill.mkdir(parents=True)
    (skill / 'SKILL.md').write_text('# Example\n\nSummarize a synthetic document.')
    Path('config.yaml').write_text(yaml.safe_dump({
        'owner_user_id': 'test-owner',
        'whitelist_user_ids': ['test-owner'],
        'whitelist_room_ids': ['test-room@chatroom'],
        'storage': {'sqlite_path': str(tmp_path / 'test.sqlite3')},
        'tools': {'web_search_enabled': False, 'code_execution_enabled': False},
    }))
    adapter = Mock()
    adapter.display_name.return_value = "Test User"
    adapter.is_image_message.return_value = False
    adapter.is_file_message.return_value = False
    model = Mock()
    model.chat.return_value = 'Synthetic summary.'
    router, returned_adapter = app.build_router('config.yaml', adapter=adapter, llm=model)
    assert returned_adapter is adapter
    assert router.llm is model
    yield router, adapter
    router.close()


def test_startup_uses_empty_memory_and_generic_prompt(framework):
    router, _ = framework
    assert router.config.owner_user_id == 'test-owner'
    assert router._knowledge_prompt() == ''
    assert not router.context.recent_messages('test-room@chatroom')
    assert 'helpful AI assistant' in router._system_prompt('test-room@chatroom')
    assert router.skills.get_skill('example') is not None
    assert 'synthetic document' in router.skills.load_skill('example')


def test_model_command_updates_router_selection(framework):
    router, _ = framework
    result = router.commands.handle('/model openrouter example/model', 'test-room@chatroom', True, True)
    assert result.handled
    settings = router._group_settings('test-room@chatroom')
    assert router._reply_provider(settings) == 'openrouter'
    assert router._reply_model(settings) == 'example/model'


def test_whitelist_command_updates_live_auth_and_survives_restart(framework):
    router, adapter = framework
    msg = IncomingMessage(1, 'test-owner', 'test-owner', '', '/whitelist add test-guest', 1, False, False)
    assert router.handle_fast_command(adapter, msg, 'test-bot')
    assert router.auth.is_whitelist_user('test-guest')
    assert AuthService(AppConfig(), db=router.db).is_whitelist_user('test-guest')
    assert 'test-guest' not in Path('config.yaml').read_text()


def test_due_scheduled_command_runs_once_and_delivers(framework):
    router, adapter = framework
    task_id, created = router.db.add_scheduled_task(
        chat_id='test-room@chatroom', created_by='test-owner', kind='command',
        schedule_type='once', cron_expr='', timezone_name='UTC', payload='/status',
        next_run_at='2000-01-01T00:00:00+00:00',
    )
    assert created
    assert router.run_due_scheduled_tasks(adapter) == 1
    adapter.send_text.assert_called_once()
    assert adapter.send_text.call_args.args[0] == 'test-room@chatroom'
    assert router.run_due_scheduled_tasks(adapter) == 0


def test_calculator_tool_preserves_decimal_accuracy(framework):
    router, adapter = framework
    handlers = router._tool_handlers(adapter, 'test-room@chatroom', 'test-owner', True, 'calculate', finance_mode=True)
    result = handlers['calculate_finance_values']('sum', ['0.1', '0.2'])
    assert result['ok']
    assert str(result['result']) == '0.3'


def test_control_api_does_not_log_generated_secrets(monkeypatch, caplog):
    from foxstar_bot import agent_api
    monkeypatch.setattr('dotenv.load_dotenv', lambda *args, **kwargs: None)
    monkeypatch.delenv('AGENT_API_TOKEN_READ', raising=False)
    monkeypatch.delenv('AGENT_API_TOKEN_WRITE', raising=False)
    generated = iter(['test-generated-read', 'test-generated-write'])
    monkeypatch.setattr(agent_api.secrets, 'token_urlsafe', lambda size: next(generated))
    assert agent_api._load_tokens() == ('test-generated-read', 'test-generated-write')
    assert 'test-generated-read' not in caplog.text
    assert 'test-generated-write' not in caplog.text
