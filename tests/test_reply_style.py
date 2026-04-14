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


def test_split_reply_messages_keeps_more_information():
    messages = split_reply_messages("斜着过还不够。门的对角线只有约2.24米。除非竹竿能先伸出门外再转角。")

    assert len(messages) == 3
    assert "2.24" in messages[1]


def test_split_reply_messages_does_not_hard_split_long_sentence():
    text = "这是一整句很长的话，里面有逗号，也有很多补充说明，但是没有真正结束，所以不要因为长度把它拆成两条。"
    messages = split_reply_messages(text, max_messages=3, max_line_chars=12, split_on_sentences=False)

    assert messages == [text]


def test_split_reply_messages_merges_standalone_wechat_emoji():
    messages = split_reply_messages("又来这套？\n论证是空的。\n[白眼]", max_messages=3, split_on_sentences=False)

    assert messages == ["又来这套？", "论证是空的。[白眼]"]
