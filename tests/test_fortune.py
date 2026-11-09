from foxstar_bot.tool_fortune import LocalFortuneTool


def test_constellation_fortune_varies_by_sign():
    tool = LocalFortuneTool()
    aries = tool.get_fortune("constellation", "aries").content
    taurus = tool.get_fortune("constellation", "taurus").content
    assert aries != taurus
    assert "白羊" in aries
    assert "金牛" in taurus
