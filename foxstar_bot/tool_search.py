from __future__ import annotations

import logging

from dataclasses import dataclass

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

    def _tavily(self, query: str, max_results: int) -> list[SearchResult]:
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
        return [
            SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("content", ""),
                source="tavily",
            )
            for item in data.get("results", [])
        ]

    def _exa(self, query: str, max_results: int) -> list[SearchResult]:
        headers = {"x-api-key": self.config.exa_api_key, "Content-Type": "application/json"}
        payload: dict[str, Any] = {
            "query": query,
            "numResults": max_results,
            "contents": {"text": {"maxCharacters": 800}},
        }
        response = requests.post("https://api.exa.ai/search", headers=headers, json=payload, timeout=20)
        response.raise_for_status()
        data = response.json()
        return [
            SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=(item.get("text") or item.get("summary") or "")[:1200],
                source="exa",
            )
            for item in data.get("results", [])
        ]

def render_search_results(results: list[SearchResult]) -> str:
    if not results:
        return "Web search 没有找到可用结果。"
    lines = ["Web search 结果："]
    for idx, item in enumerate(results, 1):
        snippet = item.snippet.replace("\n", " ").strip()
        lines.append(f"{idx}. {item.title}\nURL: {item.url}\n摘要: {snippet[:500]}")
    return "\n".join(lines)
