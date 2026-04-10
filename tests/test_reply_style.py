from foxstar_bot.reply_style import polish_reply


def test_polish_removes_ai_phrase():
    reply = polish_reply("作为一个AI模型，我觉得先核实来源。")

    assert "AI模型" not in reply
    assert "核实来源" in reply
