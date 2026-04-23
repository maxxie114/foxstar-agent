from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


ROSTER_TERMS = (
    "\u5e2e\u4f17\u540d\u5355",
    "\u6b63\u5f0f\u540d\u5355",
    "\u6210\u5458\u540d\u5355",
    "\u804c\u4e1a",
    "guild roster",
)
SIGNUP_TERMS = (
    "\u63a5\u9f99",
    "\u8bf7\u5047",
    "\u66ff\u8865",
    "\u672a\u63a5\u9f99",
)
ROSTER_MARKER = "\u5e2e\u4f17\u6b63\u5f0f\u540d\u5355"
SIGNUP_MARKER = "\u63a5\u9f99\u7edf\u8ba1"


@dataclass(frozen=True)
class KnowledgeChunk:
    title: str
    content: str
    order: int


class KnowledgeTool:
    def __init__(self, path: Path) -> None:
        self.path = path

    def search(self, query: str, max_results: int = 4, max_chars: int = 8000) -> str:
        text = self._read()
        if not text:
            return "knowledge.md is empty."
        query = (query or "").strip()
        if not query:
            return self._truncate(text, max_chars)
        chunks = self._chunks(text)
        if not chunks:
            return self._truncate(text, max_chars)
        ranked = self._rank_chunks(chunks, query)
        limit = max(1, min(int(max_results or 4), 8))
        selected = [chunk for score, chunk in ranked[:limit] if score > 0]
        if not selected:
            return self._truncate(text, max_chars)
        rendered: list[str] = []
        budget = max(800, max_chars)
        for chunk in selected:
            block = f"[{chunk.title}]\n{chunk.content.strip()}"
            if not block.strip():
                continue
            if rendered:
                candidate = "\n\n".join(rendered + [block])
                if len(candidate) > budget:
                    break
            rendered.append(block)
        if not rendered:
            return self._truncate(selected[0].content, budget)
        return "\n\n".join(rendered)[:budget]

    def _read(self) -> str:
        if not self.path.exists():
            return ""
        return self.path.read_text(encoding="utf-8", errors="ignore").strip()

    def _chunks(self, text: str) -> list[KnowledgeChunk]:
        lines = text.splitlines()
        chunks: list[KnowledgeChunk] = []
        current_title = "Document"
        current_lines: list[str] = []
        order = 0
        for raw_line in lines:
            line = raw_line.rstrip()
            if line.startswith("#"):
                if current_lines:
                    chunks.append(
                        KnowledgeChunk(
                            title=current_title,
                            content="\n".join(current_lines).strip(),
                            order=order,
                        )
                    )
                    order += 1
                    current_lines = []
                current_title = line.lstrip("#").strip() or current_title
                continue
            current_lines.append(line)
        if current_lines:
            chunks.append(
                KnowledgeChunk(
                    title=current_title,
                    content="\n".join(current_lines).strip(),
                    order=order,
                )
            )
        return [chunk for chunk in chunks if chunk.content.strip()]

    def _rank_chunks(self, chunks: list[KnowledgeChunk], query: str) -> list[tuple[float, KnowledgeChunk]]:
        q = query.strip().lower()
        keywords = _keywords(query)
        ranked: list[tuple[float, KnowledgeChunk]] = []
        for chunk in chunks:
            title_l = chunk.title.lower()
            content_l = chunk.content.lower()
            score = 0.0
            if q and q in title_l:
                score += 300.0
            if q and q in content_l:
                score += 120.0
            if any(term in q for term in ROSTER_TERMS):
                if ROSTER_MARKER in chunk.title or ROSTER_MARKER in chunk.content:
                    score += 400.0
            if any(term in q for term in SIGNUP_TERMS):
                if SIGNUP_MARKER in chunk.title or SIGNUP_MARKER in chunk.content:
                    score += 220.0
            for token in keywords:
                token_l = token.lower()
                if token_l in title_l:
                    score += 40.0
                score += min(content_l.count(token_l), 8) * 8.0
            score -= chunk.order * 0.01
            ranked.append((score, chunk))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return ranked

    @staticmethod
    def _truncate(text: str, max_chars: int) -> str:
        value = (text or "").strip()
        if len(value) <= max_chars:
            return value
        return value[:max_chars]


def _keywords(query: str) -> list[str]:
    raw_tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_]+", query)
    seen: list[str] = []
    for token in raw_tokens:
        value = token.strip()
        if not value or value in seen:
            continue
        seen.append(value)
    return seen
