from foxstar_bot.llm_client import _chat_messages_for_provider

def test_minimax_collapses_multiple_system_messages():
    messages = [
        {"role": "system", "content": "Rule A"},
        {"role": "system", "content": "Rule B"},
        {"role": "user", "content": "hello"},
    ]

    rendered = _chat_messages_for_provider(messages, provider_name="minimax")

    assert rendered == [
        {"role": "system", "content": "Rule A\n\nRule B"},
        {"role": "user", "content": "hello"},
    ]
