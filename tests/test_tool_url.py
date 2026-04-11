from foxstar_bot.tool_url import extract_urls


def test_extract_urls_strips_chinese_punctuation():
    assert extract_urls("读一下 https://example.com/a?b=1。") == ["https://example.com/a?b=1"]
