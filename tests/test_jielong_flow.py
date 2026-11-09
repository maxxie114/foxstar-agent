"""Offline roster-flow tests using invented participants and a mocked backend."""
from unittest.mock import Mock

from foxstar_bot.persistence import Database
from foxstar_bot.tool_clan import ClanManagementTool, extract_jielong_text, _jielong_entry_count


def test_roster_xml_is_normalized_without_private_participants():
    xml = '<msg><appmsg><title>#接龙 示例活动</title><desc>1. 测试甲 铁衣\n2. 测试乙 素问</desc></appmsg></msg>'
    text = extract_jielong_text(xml)
    assert text.startswith('#接龙 示例活动')
    assert _jielong_entry_count(text) == 2
    assert '<?xml' not in text


def test_roster_does_not_shrink_on_an_old_message(tmp_path):
    tool = ClanManagementTool(Database(tmp_path / 'test.sqlite3'), '', '', enabled_groups=['test-room'])
    first = '#接龙 示例活动\n1. 测试甲 铁衣'
    latest = first + '\n2. 测试乙 素问'
    for text in (first, latest, first):
        tool.observe_message('test-room', text)
    assert tool.session('test-room')['entry_count'] == 2
    assert '测试乙' in tool.session('test-room')['latest_text']
