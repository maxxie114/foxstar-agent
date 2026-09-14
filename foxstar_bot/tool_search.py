from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from .config import AppConfig

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    source: str


class SearchTool:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def should_search(self, text: str) -> bool:
        lowered = text.lower()
        triggers = [
            "最新",
            "查一下",
            "搜一下",
            "核实",
            "验证",
            "fact check",
            "真的假的",
            "是真的吗",
            "新闻",
            "价格",
            "版本",
            "政策",
            "论文",
            "公司",
            "发布",
            "today",
            "latest",
            "verify",
            "source",
        ]
        return any(token in lowered for token in triggers)

    def search(self, query: str, max_results: int = 5, *, published_after_days: int | None = None) -> list[SearchResult]:
        query = " ".join((query or "").split()).strip()
        if not query:
            raise ValueError("search query is empty")
        LOG.info("search request preferred_provider=%s query=%r max_results=%s fresh_days=%s", self.config.tools.preferred_search_provider, query, max_results, published_after_days)
        provider = self.config.tools.preferred_search_provider.lower()
        if provider == "exa" and self.config.exa_api_key:
            return self._exa(query, max_results, published_after_days=published_after_days)
        if self.config.tavily_api_key:
            return self._tavily(query, max_results)
        if self.config.exa_api_key:
            return self._exa(query, max_results, published_after_days=published_after_days)
        raise RuntimeError("未配置 TAVILY_API_KEY 或 EXA_API_KEY，不能进行 web search")

    def _tavily(self, query: str, max_results: int) -> list[SearchResult]:
        LOG.info("search provider=tavily query=%r max_results=%s", query, max_results)
        payload = {
            "api_key": self.config.tavily_api_key,
            "query": query,
            "search_depth": "advanced",
            "max_results": max_results,
            "include_answer": False,
        }
        response = requests.post("https://api.tavily.com/search", json=payload, timeout=20)
        response.raise_for_status()
        data = response.json()
        results = [
            SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("content", ""),
                source="tavily",
            )
            for item in data.get("results", [])
        ]
        LOG.info("search provider=tavily query=%r results=%s", query, len(results))
        return results

    def _exa(self, query: str, max_results: int, *, published_after_days: int | None = None) -> list[SearchResult]:
        search_type = (self.config.tools.exa_search_type or "auto").strip().lower()
        LOG.info("search provider=exa query=%r max_results=%s type=%s fresh_days=%s", query, max_results, search_type, published_after_days)
        headers = {"x-api-key": self.config.exa_api_key, "Content-Type": "application/json"}
        payload: dict[str, Any] = {
            "query": query,
            "numResults": max_results,


            "contents": {"text": {"maxCharacters": 4000}},
        }
        if published_after_days and published_after_days > 0:
            cutoff = datetime.now(timezone.utc) - timedelta(days=int(published_after_days))
            payload["startPublishedDate"] = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
        if search_type and search_type not in {"default", "none"}:
            payload["type"] = search_type
            if search_type == "deep":
                payload["outputSchema"] = {"type": "text"}
                payload["contents"] = {"highlights": True}
        response = requests.post("https://api.exa.ai/search", headers=headers, json=payload, timeout=20)
        response.raise_for_status()
        data = response.json()
        results = [
            SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=_exa_snippet(item),
                source="exa",
            )
            for item in data.get("results", [])
        ]
        LOG.info("search provider=exa query=%r results=%s", query, len(results))
        return results


def render_search_results(results: list[SearchResult]) -> str:
    if not results:
        return "Web search 没有找到可用结果。"
    lines = ["Web search 结果："]
    for idx, item in enumerate(results, 1):
        snippet = item.snippet.replace("\n", " ").strip()
        lines.append(f"{idx}. {item.title}\nURL: {item.url}\n摘要: {snippet[:500]}")
    return "\n".join(lines)


def _exa_snippet(item: dict[str, Any]) -> str:
    text = item.get("text") or item.get("summary") or ""
    highlights = item.get("highlights") or []
    if highlights:
        rendered = []
        for highlight in highlights:
            if isinstance(highlight, str):
                rendered.append(highlight)
            elif isinstance(highlight, dict):
                rendered.append(str(highlight.get("text") or highlight.get("highlight") or ""))
        highlight_text = "\n".join(part for part in rendered if part.strip())
        if highlight_text.strip():
            text = highlight_text
    return str(text)[:1600]
