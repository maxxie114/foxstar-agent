from foxstar_bot.reply_style import polish_reply, split_reply_messages


def test_polish_removes_ai_phrase():
    reply = polish_reply("作为一个AI模型，我觉得先核实来源。")

    assert "AI模型" not in reply
    assert "核实来源" in reply


def test_polish_removes_markdown():
    reply = polish_reply("**别急。**\n1. 先看证据。\n2. 定义没清楚。", max_chars=80)

    assert "**" not in reply
    assert "1." not in reply
    assert "2." not in reply


def test_split_reply_messages_short_lines():
    messages = split_reply_messages("定义先搞清楚。证据不够。别急着下结论。")

    assert messages == ["定义先搞清楚。", "证据不够。", "别急着下结论。"]
    assert all(len(item) <= 30 for item in messages)


def test_split_reply_messages_single_short_paragraph():
    messages = split_reply_messages("这事证据不够，先别急着站队。")

    assert messages == ["这事证据不够，先别急着站队。"]
