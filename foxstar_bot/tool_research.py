from __future__ import annotations

import json

import logging

import time

from dataclasses import dataclass

from typing import Any

from uuid import uuid4

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

    def _openai_web_search(self, query: str, *, run_id: str) -> str:
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
        )
        return f"OpenAI web_search subagent result:\n{result}"

    def _agentic_research(self, query: str, *, max_rounds: int, max_pages: int, run_id: str) -> str:
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
            "mention conflicts between sources; include source names/URLs in the report."
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
        )
        LOG.info("web_research agent_return run=%s searched=%s fetched=%s answer_chars=%s", run_id, len(searched), len(fetched), len(answer or ""))
        return self._format_agent_report(answer, searched, fetched)

    def _deterministic_research(self, query: str, *, max_rounds: int, max_pages: int, run_id: str = "fallback") -> str:
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
            followups = self._plan_followups(query, searched, pages, run_id=run_id)
            for followup in followups:
                if followup and followup not in searched and followup not in queries:
                    queries.append(followup)

        return self._synthesize(query, searched, pages)

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

    def _plan_followups(self, original_query: str, searched: list[str], pages: list[ResearchPage], run_id: str = "fallback") -> list[str]:
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

    def _synthesize(self, original_query: str, searched: list[str], pages: list[ResearchPage]) -> str:
        if not pages:
            return f"Web research did not find usable pages.\nQueries searched: {searched}"
        page_notes = "\n\n".join(_page_note(page, limit=1000) for page in pages[:6])
        prompt = (
            "You are a research subagent. Use only the fetched pages below. "
            "Return a compact research brief for another chat model to use. "
            "Do not write a long article. No Markdown headings. "
            "Limit the answer to 6 short bullet lines plus uncertainty notes. "
            "If sources are irrelevant or weak, say so clearly. "
            "Keep price/time-sensitive claims tied to the source timestamp when available.\n\n"
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
        "Rewrite/search in both Chinese and English when useful. Do not treat the model-proposed query as complete if it dropped constraints."
    )

def _strip_json_fence(text: str) -> str:
    value = (text or "").strip()
    if value.startswith("```"):
        value = value.strip("`")
        if value.lower().startswith("json"):
            value = value[4:].strip()
    return value

def _research_model(model_name: str) -> str:
    value = (model_name or "").strip()
    if not value or "/" in value:
        return "gpt-5.4"
    return value
