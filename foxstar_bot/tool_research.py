from __future__ import annotations

import json

import logging

from dataclasses import dataclass

from .llm_client import LLMClient

from .tool_search import SearchResult, SearchTool

from .tool_url import FetchedPage, UrlFetchTool

LOG = logging.getLogger(__name__)

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

    def _fetch_result(self, result: SearchResult) -> ResearchPage | None:
        try:
            page = self.url_fetch.fetch(result.url, limit=7000)
            text = page.text or result.snippet
            title = page.title or result.title
            LOG.info("web_research fetched url=%s chars=%s", result.url, len(text or ""))
            return ResearchPage(title=title, url=page.url, text=text[:7000], source=result.source)
        except Exception as exc:
            LOG.warning("web_research fetch failed url=%s reason=%s", result.url, exc)
            snippet = (result.snippet or "").strip()
            if not snippet:
                return None
            return ResearchPage(title=result.title, url=result.url, text=snippet[:2000], source=result.source)

    def _plan_followups(self, original_query: str, searched: list[str], pages: list[ResearchPage]) -> list[str]:
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
                return [str(item).strip()[:180] for item in values if str(item).strip()]
        except Exception as exc:
            LOG.warning("web_research followup planning failed reason=%s", exc)
        return []

def _page_note(page: ResearchPage, limit: int) -> str:
    text = " ".join((page.text or "").split())[:limit]
    return f"Title: {page.title}\nURL: {page.url}\nSource: {page.source}\nText: {text}"

def _strip_json_fence(text: str) -> str:
    value = (text or "").strip()
    if value.startswith("```"):
        value = value.strip("`")
        if value.lower().startswith("json"):
            value = value[4:].strip()
    return value
