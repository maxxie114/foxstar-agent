from foxstar_bot.reply_style import split_reply_messages


def test_split_reply_messages_uses_strong_endings_not_commas():
    messages = split_reply_messages(
        "A, still one sentence。 B?[ok]",
        max_messages=3,
        split_on_sentences=True,
    )

    assert messages == ["A, still one sentence。", "B?[ok]"]
