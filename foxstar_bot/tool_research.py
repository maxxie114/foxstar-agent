from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import requests

from .llm_client import LLMClient
from .tool_search import SearchResult, SearchTool
from .tool_url import FetchedPage, UrlFetchTool

LOG = logging.getLogger(__name__)
AGENTIC_RESEARCH_TIMEOUT_SECONDS = 40.0


@dataclass(frozen=True)
class ResearchPage:
    title: str
    url: str
    text: str
    source: str


class WebResearchAgent:
    def __init__(self, search: SearchTool, url_fetch: UrlFetchTool, llm: LLMClient) -> None:
        self.search = search
        self.url_fetch = url_fetch
        self.llm = llm

    def research(self, query: str, *, max_rounds: int = 2, max_pages: int = 5, original_query: str = "", chat_id: str = "") -> str:
        query = " ".join((query or "").split()).strip()
        original_query = " ".join((original_query or "").split()).strip()
        if not query and original_query:
            query = original_query
        if not query:
            return "Web research failed: empty query."

        max_rounds = max(1, min(max_rounds, 2))
        max_pages = max(1, min(max_pages, 5))
        run_id = uuid4().hex[:8]
        provider = (self.search.config.tools.web_research_provider or "openrouter").strip().lower()
        LOG.info(
            "web_research start run=%s provider=%s query=%r max_rounds=%s max_pages=%s",
            run_id,
            provider,
            query,
            max_rounds,
            max_pages,
        )
        research_input = _research_input(query, original_query)


        tiers: list[tuple[str, Any]] = []
        if self.search.config.exa_api_key:


            tiers.append(("exa_deep", lambda: self._exa_deep_search(research_input, run_id=run_id, chat_id=chat_id)))
            tiers.append(("exa_quick", lambda: self._exa_research(research_input, run_id=run_id, chat_id=chat_id, max_pages=max_pages)))
        if self.search.config.openai_api_key:
            tiers.append(("openai_web_search", lambda: self._openai_web_search(research_input, run_id=run_id, chat_id=chat_id)))
        tiers.append(("sonar", lambda: self._openrouter_sonar_search(research_input, run_id=run_id, chat_id=chat_id)))
        preference = {
            "openrouter": "sonar",
            "openrouter_sonar": "sonar",
            "sonar": "sonar",
            "sonar_pro": "sonar",
            "sonar_pro_search": "sonar",
            "openai": "openai_web_search",
            "openai_web_search": "openai_web_search",
            "web_search": "openai_web_search",
            "exa": "exa_deep",
            "auto": None,
        }.get(provider)
        if preference:
            tiers.sort(key=lambda item: 0 if item[0] == preference else 1)
        for tier_name, runner in tiers:
            try:
                result = runner()
                if result.strip():
                    LOG.info("web_research done run=%s mode=%s chars=%s", run_id, tier_name, len(result))
                    return result
            except Exception as exc:
                LOG.warning("web_research %s failed run=%s; falling back reason=%s", tier_name, run_id, exc)
        try:
            result = self._agentic_research(research_input, max_rounds=max_rounds, max_pages=max_pages, run_id=run_id, chat_id=chat_id)
            if result.strip():
                LOG.info("web_research done run=%s mode=agentic chars=%s", run_id, len(result))
                return result
        except Exception as exc:
            LOG.warning("web_research agentic loop failed run=%s; falling back reason=%s", run_id, exc)
        result = self._deterministic_research(research_input, max_rounds=max_rounds, max_pages=max_pages, run_id=run_id, chat_id=chat_id)
        LOG.info("web_research done run=%s mode=fallback chars=%s", run_id, len(result))
        return result

    def _exa_deep_search(self, query: str, *, run_id: str, chat_id: str = "") -> str:
        beijing_now = datetime.now(timezone(timedelta(hours=8)))
        search_type = str(getattr(self.search.config.tools, "exa_deep_search_type", "") or "deep").strip().lower()
        if search_type not in {"deep", "deep-lite"}:
            search_type = "deep"
        headers = {"x-api-key": self.search.config.exa_api_key, "Content-Type": "application/json"}
        payload = {
            "query": query,
            "type": search_type,
            "outputSchema": {"type": "text"},
            "systemPrompt": (
                "You are a web research subagent for a Chinese WeChat group bot. "
                f"Current time (Beijing): {beijing_now.strftime('%Y-%m-%d %H:%M')}. "
                "Produce a compact Chinese research brief (English only if the query is English): "
                "key facts as short bullets, uncertainty and source conflicts called out, "
                "recency verified for latest/today queries, and cite source names inline. "
                "Keep it under 300 words so the caller model can integrate it."
            ),
        }
        LOG.info("web_research exa_deep run=%s type=%s query=%r", run_id, search_type, query[:120])
        response = requests.post("https://api.exa.ai/search", headers=headers, json=payload, timeout=35.0)
        response.raise_for_status()
        data = response.json()
        synthesized = str(
            data.get("output")
            or data.get("answer")
            or data.get("text")
            or ""
        ).strip()
        results = data.get("results") or []
        sources = "\n".join(
            f"- {item.get('title') or item.get('url')}: {item.get('url')}" for item in results[:6] if item.get("url")
        )
        LOG.info(
            "web_research exa_deep done run=%s synthesized_chars=%s results=%s",
            run_id, len(synthesized), len(results),
        )
        if not synthesized and not results:
            raise RuntimeError("exa deep search returned nothing")
        if not synthesized:
            raise RuntimeError("exa deep search returned no synthesized output")
        body = " ".join(synthesized.split())
        if len(body) > 2600:
            body = body[:2600].rstrip() + "..."
        out = f"Exa deep search result:\n{body}"
        if sources:
            out += f"\n\nSources:\n{sources}"
        return out

    def _exa_research(self, query: str, *, run_id: str, chat_id: str = "", max_pages: int = 3) -> str:
        beijing_now = datetime.now(timezone(timedelta(hours=8)))
        fresh_days = 30 if _wants_freshness(query) else None
        pages: list[ResearchPage] = []
        queries: list[str] = []

        def exa_search(search_query: str) -> list[ResearchPage]:
            queries.append(search_query)
            results = self.search.search(search_query, max_results=6, published_after_days=fresh_days)
            pages_new: list[ResearchPage] = []
            for item in results:
                if not item.url or any(p.url == item.url for p in pages):
                    continue
                pages_new.append(ResearchPage(title=item.title, url=item.url, text=item.snippet, source="exa"))
            pages.extend(pages_new)
            LOG.info("web_research exa run=%s query=%r fresh_days=%s new_pages=%s total=%s", run_id, search_query, fresh_days, len(pages_new), len(pages))
            return pages_new

        exa_search(query)
        if len(pages) < 2 or all(len((p.text or "").strip()) < 300 for p in pages):
            followup = self._exa_followup(query, pages, run_id)
            if followup and followup not in queries:
                exa_search(followup)
        if not pages:
            raise RuntimeError("exa returned no usable pages")
        return self._exa_brief(query, pages, beijing_now)

    def _exa_followup(self, original_query: str, pages: list[ResearchPage], run_id: str) -> str:
        notes = "\n".join(f"- {p.title}: {p.url}" for p in pages[:6]) or "- (no results)"
        prompt = (
            "You are a search query optimizer. The first search returned weak results. "
            'Return JSON only: {"follow_up_query": "..."} with ONE better query '
            "(different angle, add context words, or translate Chinese<->English). Empty string if no better idea.\n"
            f"Original query: {original_query}\nResults so far:\n{notes}"
        )
        try:
            raw = self.llm.responses_text(
                [{"role": "system", "content": "Return compact valid JSON only."},
                 {"role": "user", "content": prompt}],
                max_output_tokens=160,
                reasoning_effort="low",
                verbosity="low",
                timeout=8.0,
                usage_context={"feature": "web_research"},
            )
            value = str(json.loads(_strip_json_fence(raw)).get("follow_up_query") or "").strip()[:180]
            LOG.info("web_research exa_followup run=%s followup=%r", run_id, value)
            return value
        except Exception as exc:
            LOG.warning("web_research exa followup planning failed run=%s reason=%s", run_id, exc)
            return ""

    def _exa_brief(self, query: str, pages: list[ResearchPage], beijing_now: datetime) -> str:
        chosen = pages[:5]
        notes = "\n\n".join(_page_note(p, limit=1200) for p in chosen)
        prompt = (
            "You are a research subagent. Use ONLY the page texts below. "
            "Write a compact evidence brief (Chinese unless the query is English): "
            "up to 6 short bullets, facts separated from uncertainty, note conflicts. "
            "Tie time-sensitive claims to what the pages actually say.\n"
            f"Current time (Beijing): {beijing_now.strftime('%Y-%m-%d %H:%M')}\n"
            f"Query: {query}\n\nPages:\n{notes}"
        )
        try:
            answer = self.llm.responses_text(
                [{"role": "system", "content": "Produce a concise evidence brief."},
                 {"role": "user", "content": prompt}],
                max_output_tokens=1800,
                reasoning_effort="low",
                verbosity="low",
                timeout=25.0,
                usage_context={"feature": "web_research"},
            )
        except Exception as exc:
            LOG.warning("web_research exa synthesis failed reason=%s", exc)
            answer = "Synthesis failed; raw excerpts follow.\n" + notes[:5000]
        answer = " ".join((answer or "").strip().split())
        if len(answer) > 1800:
            answer = answer[:1800].rstrip() + "..."
        sources = "\n".join(f"- {p.title or p.url}: {p.url}" for p in chosen)
        return f"Exa research result:\n{answer}\n\nSources:\n{sources}"

    def _openai_web_search(self, query: str, *, run_id: str, chat_id: str = "") -> str:
        model = self.search.config.tools.openai_web_search_model or "gpt-5"
        effort = self.search.config.tools.openai_web_search_reasoning_effort or "low"
        max_tokens = self.search.config.tools.openai_web_search_max_output_tokens or 3000
        LOG.info(
            "web_research openai_web_search run=%s model=%s reasoning=%s max_output_tokens=%s",
            run_id,
            model,
            effort,
            max_tokens,
        )
        result = self.llm.web_search(
            query,
            model=model,
            reasoning_effort=effort,
            max_output_tokens=max_tokens,
            timeout=55.0,
            usage_context={"chat_id": chat_id, "feature": "web_research"},
        )
        return f"OpenAI web_search subagent result:\n{result}"

    def _openrouter_sonar_search(self, query: str, *, run_id: str, chat_id: str = "") -> str:
        model = self.search.config.tools.openrouter_web_search_model or "perplexity/sonar-pro-search"
        max_tokens = self.search.config.tools.openrouter_web_search_max_output_tokens or 3000
        prompt = (
            "你是一个快速 web research 子代理。"
            "直接使用联网搜索能力，产出一份简洁、可靠、带来源的中文 research brief。"
            "优先最新、权威、原始来源。"
            "如果用户要求 today/latest/current/realtime，一定显式核实时间新鲜度。"
            "如果来源冲突，明确写冲突点，不要硬下结论。"
            "输出尽量短，方便传回主模型继续整合。"
            f"\n\nResearch request:\n{query}"
        )
        LOG.info(
            "web_research openrouter_sonar run=%s model=%s max_output_tokens=%s",
            run_id,
            model,
            max_tokens,
        )
        result = self.llm.chat(
            [{"role": "user", "content": prompt}],
            max_completion_tokens=max_tokens,
            model=model,
            provider="openrouter",
            reasoning_effort="none",
            timeout=90.0,
            usage_context={"chat_id": chat_id, "feature": "web_research"},
        )
        return f"OpenRouter Sonar search result:\n{result}"

    def _agentic_research(self, query: str, *, max_rounds: int, max_pages: int, run_id: str, chat_id: str = "") -> str:
        searched: list[str] = []
        fetched: list[ResearchPage] = []
        started_at = time.monotonic()
        max_search_calls = max(1, min(max_rounds + 1, 3))
        max_pages = max(1, min(max_pages, 3))

        def budget_error() -> str | None:
            elapsed = time.monotonic() - started_at
            if elapsed > AGENTIC_RESEARCH_TIMEOUT_SECONDS:
                return f"time budget exhausted ({elapsed:.1f}s)"
            return None

        def search_web(query: str, max_results: int = 5) -> dict[str, Any]:
            search_query = " ".join(str(query or "").split()).strip()
            LOG.info("web_research tool_call run=%s tool=search_web query=%r max_results=%s", run_id, search_query, max_results)
            if error := budget_error():
                return {"ok": False, "error": error, "must_finish": True}
            if not search_query:
                return {"ok": False, "error": "query is required"}
            if len(searched) >= max_search_calls:
                return {"ok": False, "error": f"search budget exhausted ({max_search_calls})", "must_finish": True}
            searched.append(search_query)
            results = self.search.search(search_query, max_results=max(1, min(int(max_results or 3), 5)))
            LOG.info("web_research tool_result run=%s tool=search_web query=%r results=%s", run_id, search_query, len(results))
            return {
                "ok": True,
                "query": search_query,
                "results": [
                    {"title": item.title, "url": item.url, "snippet": item.snippet[:900], "source": item.source}
                    for item in results
                    if item.url
                ],
            }

        def fetch_url(url: str) -> dict[str, Any]:
            target = str(url or "").strip()
            LOG.info("web_research tool_call run=%s tool=fetch_url url=%s", run_id, target)
            if error := budget_error():
                return {"ok": False, "error": error, "must_finish": True}
            if not target.startswith(("http://", "https://")):
                return {"ok": False, "error": "url must start with http:// or https://"}
            if len(fetched) >= max_pages:
                return {"ok": False, "error": f"page budget exhausted ({max_pages})", "must_finish": True}
            page = self.url_fetch.fetch(target, limit=5500)
            fetched.append(ResearchPage(title=page.title, url=page.url, text=page.text[:5500], source="fetch_url"))
            LOG.info("web_research tool_result run=%s tool=fetch_url url=%s title=%r chars=%s", run_id, page.url, page.title, len(page.text or ""))
            return {"ok": True, "url": page.url, "title": page.title, "text": page.text[:5000]}

        def finish_research(report: str) -> dict[str, Any]:
            LOG.info("web_research tool_call run=%s tool=finish_research report_chars=%s searched=%s fetched=%s", run_id, len(str(report or "")), len(searched), len(fetched))
            return {"__terminal_response__": True, "text": self._format_agent_report(str(report or ""), searched, fetched)}

        tools = [
            {
                "type": "function",
                "name": "search_web",
                "description": "Search the web for candidate pages. Use multiple precise queries if initial results are weak or ambiguous.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Precise search query."},
                        "max_results": {"type": "integer", "description": "1-8 results. Default 5."},
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "fetch_url",
                "description": "Fetch and extract readable text from a specific search result URL. Prefer primary or authoritative pages.",
                "parameters": {
                    "type": "object",
                    "properties": {"url": {"type": "string", "description": "HTTP or HTTPS URL to read."}},
                    "required": ["url"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "finish_research",
                "description": "Finish with a compact sourced research brief after searching and reading enough pages.",
                "parameters": {
                    "type": "object",
                    "properties": {"report": {"type": "string", "description": "Concise research brief."}},
                    "required": ["report"],
                    "additionalProperties": False,
                },
            },
        ]
        prompt = (
            "Run multi-step web research for another chat model.\n"
            f"Original user query: {query}\n"
            f"Budgets: up to {max_search_calls} search_web calls and {max_pages} fetch_url calls.\n\n"
            "Process:\n"
            "1. Search with a precise query.\n"
            "2. Read the most relevant URLs with fetch_url; do not rely on snippets alone.\n"
            "3. If results are irrelevant, stale, too broad, or conflict, reformulate and search again.\n"
            "4. Prefer primary sources, official pages, reputable data providers, or directly relevant pages.\n"
            "5. When enough evidence is gathered, call finish_research.\n"
            "6. If any tool returns must_finish=true or a budget error, immediately call finish_research with the evidence already gathered.\n\n"
            "Report requirements: Chinese unless the query asks otherwise; compact; separate facts from uncertainty; "
            "mention conflicts between sources; include source names/URLs in the report. "
            "If the request asks for latest/current/today/realtime information, explicitly verify recency, prefer the most recent authoritative source available, "
            "and say when a source may be stale or unverified."
        )
        answer = self.llm.chat_with_tools(
            [
                {
                    "role": "system",
                    "content": "You are a careful web research subagent. You must search and fetch pages before answering.",
                },
                {"role": "user", "content": prompt},
            ],
            tools,
            {"search_web": search_web, "fetch_url": fetch_url, "finish_research": finish_research},
            max_output_tokens=3600,
            model=_research_model(self.llm.config.name),
            reasoning_effort="medium",
            verbosity="low",
            provider="openai",
            max_tool_rounds=max_search_calls + max_pages,
            usage_context={"chat_id": chat_id, "feature": "web_research"},
        )
        LOG.info("web_research agent_return run=%s searched=%s fetched=%s answer_chars=%s", run_id, len(searched), len(fetched), len(answer or ""))
        return self._format_agent_report(answer, searched, fetched)

    def _deterministic_research(self, query: str, *, max_rounds: int, max_pages: int, run_id: str = "fallback", chat_id: str = "") -> str:
        seen_urls: set[str] = set()
        queries = [query]
        pages: list[ResearchPage] = []
        searched: list[str] = []

        for round_index in range(max_rounds):
            current_queries = [item for item in queries if item not in searched][:2]
            if not current_queries:
                break
            round_results: list[SearchResult] = []
            for current_query in current_queries:
                searched.append(current_query)
                try:
                    results = self.search.search(current_query, max_results=5)
                    round_results.extend(results)
                    LOG.info("web_research fallback_search run=%s query=%r results=%s", run_id, current_query, len(results))
                except Exception as exc:
                    LOG.warning("web_research search failed query=%r reason=%s", current_query, exc)

            for result in round_results:
                if len(pages) >= max_pages:
                    break
                if not result.url or result.url in seen_urls:
                    continue
                seen_urls.add(result.url)
                page = self._fetch_result(result)
                if page:
                    pages.append(page)

            if round_index + 1 >= max_rounds or len(pages) >= max_pages:
                break
            followups = self._plan_followups(query, searched, pages, run_id=run_id, chat_id=chat_id)
            for followup in followups:
                if followup and followup not in searched and followup not in queries:
                    queries.append(followup)

        return self._synthesize(query, searched, pages, chat_id=chat_id)

    def _format_agent_report(self, report: str, searched: list[str], pages: list[ResearchPage]) -> str:
        body = " ".join((report or "").strip().split())
        if not body:
            body = "Web research agent returned no final report."
        if len(body) > 2600:
            body = body[:2600].rstrip() + "..."
        sources = "\n".join(f"- {page.title or page.url}: {page.url}" for page in pages[:8])
        if not sources:
            sources = "- no pages fetched"
        return f"Web research subagent result:\n{body}\n\nQueries searched: {searched}\nSources checked:\n{sources}"

    def _fetch_result(self, result: SearchResult) -> ResearchPage | None:
        try:
            page = self.url_fetch.fetch(result.url, limit=4500)
            text = page.text or result.snippet
            title = page.title or result.title
            LOG.info("web_research fetched url=%s chars=%s", result.url, len(text or ""))
            return ResearchPage(title=title, url=page.url, text=text[:4500], source=result.source)
        except Exception as exc:
            LOG.warning("web_research fetch failed url=%s reason=%s", result.url, exc)
            snippet = (result.snippet or "").strip()
            if not snippet:
                return None
            return ResearchPage(title=result.title, url=result.url, text=snippet[:2000], source=result.source)

    def _plan_followups(self, original_query: str, searched: list[str], pages: list[ResearchPage], run_id: str = "fallback", chat_id: str = "") -> list[str]:
        page_notes = "\n\n".join(_page_note(page, limit=900) for page in pages[:5])
        prompt = (
            "You are a web research planner. The current search results may be irrelevant.\n"
            "Return JSON only: {\"follow_up_queries\": [\"query1\", \"query2\"]}.\n"
            "Generate 0-2 precise follow-up search queries that would improve relevance. "
            "Do not repeat already searched queries.\n\n"
            f"Original query: {original_query}\n"
            f"Already searched: {searched}\n"
            f"Fetched pages:\n{page_notes}"
        )
        try:
            raw = self.llm.responses_text(
                [
                    {"role": "system", "content": "Return compact valid JSON only."},
                    {"role": "user", "content": prompt},
                ],
                max_output_tokens=220,
                reasoning_effort="low",
                verbosity="low",
                timeout=8.0,
                usage_context={"chat_id": chat_id, "feature": "web_research"},
            )
            data = json.loads(_strip_json_fence(raw))
            values = data.get("follow_up_queries", [])
            if isinstance(values, list):
                followups = [str(item).strip()[:180] for item in values if str(item).strip()]
                LOG.info("web_research fallback_followups run=%s followups=%s", run_id, followups)
                return followups
        except Exception as exc:
            LOG.warning("web_research followup planning failed reason=%s", exc)
        return []

    def _synthesize(self, original_query: str, searched: list[str], pages: list[ResearchPage], chat_id: str = "") -> str:
        if not pages:
            return f"Web research did not find usable pages.\nQueries searched: {searched}"
        page_notes = "\n\n".join(_page_note(page, limit=1000) for page in pages[:6])
        prompt = (
            "You are a research subagent. Use only the fetched pages below. "
            "Return a compact research brief for another chat model to use. "
            "Do not write a long article. No Markdown headings. "
            "Limit the answer to 6 short bullet lines plus uncertainty notes. "
            "If sources are irrelevant or weak, say so clearly. "
            "Keep price/time-sensitive claims tied to the source timestamp when available. "
            "Prioritize official, primary, or otherwise authoritative sources over secondary summaries. "
            "If the query asks for latest/current/today/realtime facts, explicitly say whether the fetched evidence looks current enough, and highlight any staleness risk.\n\n"
            f"Original query: {original_query}\n"
            f"Queries searched: {searched}\n\n"
            f"Fetched pages:\n{page_notes}"
        )
        try:
            answer = self.llm.responses_text(
                [
                    {"role": "system", "content": "Produce a concise research brief in Chinese unless the query asks otherwise."},
                    {"role": "user", "content": prompt},
                ],
                max_output_tokens=2400,
                reasoning_effort="low",
                verbosity="low",
                timeout=25.0,
                usage_context={"chat_id": chat_id, "feature": "web_research"},
            )
        except Exception as exc:
            LOG.warning("web_research synthesis failed reason=%s", exc)
            answer = "Web research synthesis failed; raw fetched notes follow.\n" + page_notes[:6000]
        sources = "\n".join(f"- {page.title or page.url}: {page.url}" for page in pages[:5])
        answer = " ".join(answer.strip().split())
        if len(answer) > 1800:
            answer = answer[:1800].rstrip() + "..."
        return f"Web research subagent result:\n{answer}\n\nSources checked:\n{sources}"


def _page_note(page: ResearchPage, limit: int) -> str:
    text = " ".join((page.text or "").split())[:limit]
    return f"Title: {page.title}\nURL: {page.url}\nSource: {page.source}\nText: {text}"


def _research_input(query: str, original_query: str) -> str:
    query = " ".join((query or "").split()).strip()
    original_query = " ".join((original_query or "").split()).strip()
    if not original_query or original_query == query:
        return query
    return (
        "Original user request:\n"
        f"{original_query}\n\n"
        "Model-proposed search query, possibly lossy:\n"
        f"{query}\n\n"
        "Research instruction:\n"
        "Use the original request as authoritative. Preserve exact dates, named sources, outlets, amounts, entities, and requested information sources. "
        "Rewrite/search in both Chinese and English when useful. Do not treat the model-proposed query as complete if it dropped constraints. "
        "When the user asks for latest/current/today/realtime information, verify freshness explicitly, prefer authoritative primary sources, and say if evidence may be stale."
    )


def _strip_json_fence(text: str) -> str:
    value = (text or "").strip()
    if value.startswith("```"):
        value = value.strip("`")
        if value.lower().startswith("json"):
            value = value[4:].strip()
    return value


def _wants_freshness(query: str) -> bool:
    value = (query or "").lower()
    return any(token in value for token in (
        "最新", "今天", "现在", "刚刚", "新闻", "latest", "today", "current", "recent", "now", "2026", "2025",
    ))


def _research_model(model_name: str) -> str:
    value = (model_name or "").strip()
    if not value or "/" in value:
        return "gpt-5.4"
    return value
