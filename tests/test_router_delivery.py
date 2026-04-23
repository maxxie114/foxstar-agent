from foxstar_bot.router import delivery_parts_for_style


def test_free_style_delivery_keeps_multiline_code_in_one_message():
    reply = "Reason:\n```python\ndef f():\n    return 1\n```\nDone."

    messages = delivery_parts_for_style(reply, "free", line_chars=40)

    assert messages == [reply]
