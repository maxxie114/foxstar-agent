from pathlib import Path

from foxstar_bot.tool_knowledge import KnowledgeTool


def test_search_knowledge_prefers_roster_section(tmp_path: Path):
    path = tmp_path / 'knowledge.md'
    path.write_text(
        '# Synthetic Knowledge Base\n\n'
        '## 示例接龙统计规则\n\n'
        '- 统计时先做别名归并。\n\n'
        '## 示例帮众正式名单\n\n'
        '- 测试成员甲 -> 职业甲\n'
        '- 测试成员乙 -> 职业乙\n'
        '- 测试成员丙 -> 职业丙\n',
        encoding='utf-8',
    )
    tool = KnowledgeTool(path)
    result = tool.search('帮众名单 职业', max_results=1)
    assert '示例帮众正式名单' in result
    assert '测试成员甲 -> 职业甲' in result
