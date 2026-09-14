from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from foxstar_bot.tool_research import WebResearchAgent, _wants_freshness
from foxstar_bot.tool_search import SearchTool


def _config(exa=True, openai=True, provider="auto"):
    return SimpleNamespace(
        exa_api_key="exa-key" if exa else "",
        tavily_api_key="",
        openai_api_key="oai-key" if openai else "",
        tools=SimpleNamespace(
            preferred_search_provider="exa",
            exa_search_type="auto",
            web_research_provider=provider,
        ),
    )


def test_wants_freshness():
    assert _wants_freshness("NVDA 最新财报") is True
    assert _wants_freshness("who won latest f1 race") is True
    assert _wants_freshness("红楼梦作者是谁") is False


def test_exa_payload_full_text_and_date_filter():
    tool = SearchTool(_config())
    captured = {}
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"results": [{"title": "t", "url": "http://x", "text": "body"}]}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["payload"] = json
        return response

    with patch("foxstar_bot.tool_search.requests.post", side_effect=fake_post):
        tool.search("测试 query", max_results=5, published_after_days=30)

    payload = captured["payload"]
    assert payload["contents"]["text"]["maxCharacters"] == 4000
    assert payload["startPublishedDate"].startswith("20")

    with patch("foxstar_bot.tool_search.requests.post", side_effect=fake_post):
        tool.search("evergreen query", max_results=5)
    assert "startPublishedDate" not in captured["payload"]


def test_cascade_reaches_exa_when_sonar_dead():
    agent = WebResearchAgent(search=SimpleNamespace(config=_config(provider="openrouter")),
                             url_fetch=MagicMock(), llm=MagicMock())
    calls = []
    agent._openrouter_sonar_search = lambda *a, **k: calls.append("sonar") or (_ for _ in ()).throw(RuntimeError("sonar dead"))
    agent._exa_research = lambda *a, **k: calls.append("exa") or "Exa research result: ok"
    agent._openai_web_search = lambda *a, **k: calls.append("openai") or "should not reach"

    result = agent.research("test query", chat_id="r")

    assert result.startswith("Exa research result")
    assert "sonar" in calls and "exa" in calls


    assert "openai" not in calls


def test_cascade_default_order_exa_first():
    agent = WebResearchAgent(search=SimpleNamespace(config=_config(provider="auto")),
                             url_fetch=MagicMock(), llm=MagicMock())
    calls = []
    agent._exa_research = lambda *a, **k: calls.append("exa") or "Exa research result: ok"
    agent._openai_web_search = lambda *a, **k: calls.append("openai") or ""
    agent._openrouter_sonar_search = lambda *a, **k: calls.append("sonar") or ""

    result = agent.research("test query", chat_id="r")

    assert result.startswith("Exa research result")
    assert calls == ["exa"]


def test_cascade_without_exa_key_falls_to_sonar():
    agent = WebResearchAgent(search=SimpleNamespace(config=_config(exa=False, provider="openrouter")),
                             url_fetch=MagicMock(), llm=MagicMock())
    agent._openrouter_sonar_search = lambda *a, **k: "OpenRouter Sonar search result: ok"
    agent._openai_web_search = lambda *a, **k: "OpenAI web_search subagent result: ok"

    result = agent.research("test query", chat_id="r")
    assert result.startswith("OpenRouter Sonar")


def test_exa_deep_search_payload_and_parse():
    from foxstar_bot.tool_research import WebResearchAgent
    agent = WebResearchAgent(search=SimpleNamespace(config=_config()), url_fetch=MagicMock(), llm=MagicMock())
    captured = {}
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "output": " 合成结论：XYZ。 ",
        "results": [{"title": "t", "url": "http://x"}],
    }

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["payload"] = json
        return response

    import foxstar_bot.tool_research as tr
    with patch.object(tr.requests, "post", side_effect=fake_post):
        result = agent._exa_deep_search("研究一下", run_id="r1")

    assert captured["payload"]["type"] == "deep"
    assert captured["payload"]["outputSchema"] == {"type": "text"}
    assert "Beijing" in captured["payload"]["systemPrompt"]
    assert result.startswith("Exa deep search result:")
    assert "合成结论" in result and "http://x" in result


def test_cascade_exa_deep_first_then_quick_on_failure():
    from foxstar_bot.tool_research import WebResearchAgent
    agent = WebResearchAgent(search=SimpleNamespace(config=_config(provider="auto")),
                             url_fetch=MagicMock(), llm=MagicMock())
    calls = []

    def deep_fail(*a, **k):
        calls.append("exa_deep")
        raise RuntimeError("deep timeout")

    agent._exa_deep_search = deep_fail
    agent._exa_research = lambda *a, **k: calls.append("exa_quick") or "Exa research result: ok"

    result = agent.research("test query", chat_id="r")
    assert result.startswith("Exa research result")
    assert calls == ["exa_deep", "exa_quick"]


def test_exa_deep_output_unwraps_content_dict():
    from foxstar_bot.tool_research import WebResearchAgent, _extract_exa_output

    assert _extract_exa_output({"content": "结论A"}) == "结论A"

    assert _extract_exa_output('{"content": "结论B"}') == "结论B"

    assert _extract_exa_output("plain brief") == "plain brief"
    assert _extract_exa_output(None) == ""

    agent = WebResearchAgent(search=SimpleNamespace(config=_config()), url_fetch=MagicMock(), llm=MagicMock())
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"output": {"content": "干净结论"}, "results": [{"title": "t", "url": "http://x"}]}
    import foxstar_bot.tool_research as tr
    with patch.object(tr.requests, "post", return_value=response):
        result = agent._exa_deep_search("q", run_id="r")
    assert result.startswith("Exa deep search result:\n干净结论")
    assert "{'content'" not in result
