from foxstar_bot.tool_fortune import LocalFortuneTool


def render_examples() -> dict[str, str]:
    tool = LocalFortuneTool()
    return {
        "all": tool.get_fortune("all").content,
        "star_aries": tool.get_fortune("constellation", "aries").content,
        "huangli": tool.get_fortune("huangli").content,
        "divination": tool.get_fortune("divination").content,
    }
