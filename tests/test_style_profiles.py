from foxstar_bot.style_profiles import parse_stored_style, parse_style_tokens, style_personality_prompt


def test_parse_style_combines_format_mbti_and_zodiac():
    style, error = parse_style_tokens(["human", "INTJ", "leo"])

    assert error == ""
    assert style is not None
    assert style.format_style == "human"
    assert style.personality_traits == ("intj", "leo")
    assert style.storage_value == "human intj leo"


def test_parse_style_accepts_chinese_zodiac_alias():
    style, error = parse_style_tokens(["enfp", "\u53cc\u9c7c\u5ea7"])

    assert error == ""
    assert style is not None
    assert style.format_style == "strict"
    assert style.personality_traits == ("enfp", "pisces")


def test_personality_prompt_mentions_traits_without_claiming_identity():
    style = parse_stored_style("free infj aries")

    prompt = style_personality_prompt(style)

    assert "INFJ" in prompt
    assert "aries" in prompt
    assert "Do not claim" in prompt


def test_parse_style_accepts_feminine_soft_aries():
    style, error = parse_style_tokens(["human", "女生", "柔软", "白羊座"])

    assert error == ""
    assert style is not None
    assert style.storage_value == "human feminine soft aries"


def test_feminine_prompt_is_voice_not_identity():
    style = parse_stored_style("human feminine soft aries")

    prompt = style_personality_prompt(style)

    assert "feminine-coded voice" in prompt
    assert "softer" in prompt
    assert "aries" in prompt
    assert "do not claim to be a woman" in prompt
