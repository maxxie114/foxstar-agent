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
