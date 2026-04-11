from __future__ import annotations

from dataclasses import dataclass
import re

import requests


URL_RE = re.compile(r"https?://[^\s<>\]\)\"']+")


@dataclass(frozen=True)
class FetchedPage:
    url: str
    title: str
    text: str


class UrlFetchTool:
    def fetch(self, url: str, limit: int = 8000) -> FetchedPage:
        response = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 FoxStarBot/1.0"},
            timeout=20,
        )
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if "text" not in content_type and "html" not in content_type and "json" not in content_type:
            raise RuntimeError(f"unsupported content type: {content_type or 'unknown'}")
        raw = response.text[:200000]
        title = _extract_title(raw)
        text = _html_to_text(raw)[:limit]
        return FetchedPage(url=url, title=title, text=text)


def extract_urls(text: str) -> list[str]:
    urls = []
    for match in URL_RE.findall(text or ""):
        url = match.rstrip("。。，，、")
        if url not in urls:
            urls.append(url)
    return urls


def render_fetched_page(page: FetchedPage) -> str:
    title = f"\n标题: {page.title}" if page.title else ""
    return f"URL 读取结果：\nURL: {page.url}{title}\n正文摘录:\n{page.text[:8000]}"


def _extract_title(raw: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", raw, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return _clean_text(match.group(1))[:200]


def _html_to_text(raw: str) -> str:
    text = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", raw)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return _clean_text(text)


def _clean_text(text: str) -> str:
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    return re.sub(r"\s+", " ", text).strip()
