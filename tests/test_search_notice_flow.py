"""Search notices use a fake model; no live provider or stored conversation."""
from types import SimpleNamespace
from unittest.mock import Mock

from foxstar_bot.router import MessageRouter


def test_search_notice_uses_model_and_trims_extra_lines():
    model = Mock()
    model.cerebras_text.return_value = '先查一下资料。\nextra line'
    router = SimpleNamespace(llm=model)
    message = SimpleNamespace(chat_id='test-room')
    notice = MessageRouter._search_progress_notice(router, message, '查一下天气', 'example weather')
    assert notice == '先查一下资料。'
    model.cerebras_text.assert_called_once()


def test_search_notice_failure_does_not_invent_a_notice():
    model = Mock()
    model.cerebras_text.side_effect = RuntimeError('synthetic outage')
    assert MessageRouter._search_progress_notice(SimpleNamespace(llm=model), SimpleNamespace(chat_id='test-room'), 'query', 'query') == ''
