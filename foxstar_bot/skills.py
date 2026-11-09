from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True)
class SkillInfo:
    name: str
    path: Path
    title: str
    summary: str
    content_preview: str = ""


class SkillRegistry:
    def __init__(self, root: Path) -> None:
        self.root = root

    def list_skills(self) -> list[SkillInfo]:
        if not self.root.exists():
            return []
        items: list[SkillInfo] = []
        for child in sorted(self.root.iterdir(), key=lambda item: item.name.lower()):
            if not child.is_dir():
                continue
            skill_file = child / "SKILL.md"
            if not skill_file.exists():
                continue
            title, summary = _extract_skill_metadata(skill_file)
            items.append(
                SkillInfo(
                    name=child.name,
                    path=skill_file,
                    title=title or child.name,
                    summary=summary,
                    content_preview=_skill_preview(skill_file),
                )
            )
        return items

    def search_skills(self, query: str, max_results: int = 8) -> list[SkillInfo]:
        skills = self.list_skills()
        lookup = (query or "").strip().lower()
        if not lookup:
            return skills[: max(1, min(max_results, 20))]
        tokens = _skill_tokens(query)
        scored: list[tuple[float, SkillInfo]] = []
        for skill in skills:
            haystack = f"{skill.name}\n{skill.title}\n{skill.summary}\n{skill.content_preview}".lower()
            score = 0.0
            if lookup in skill.name.lower():
                score += 200.0
            if lookup in skill.title.lower():
                score += 160.0
            if lookup in haystack:
                score += 80.0
            for token in tokens:
                token_l = token.lower()
                if token_l in skill.name.lower():
                    score += 50.0
                if token_l in skill.title.lower():
                    score += 30.0
                if token_l in skill.summary.lower():
                    score += 10.0
                if token_l in skill.content_preview.lower():
                    score += 4.0
            if score > 0:
                scored.append((score, skill))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [skill for _, skill in scored[: max(1, min(max_results, 20))]]

    def get_skill(self, name: str) -> SkillInfo | None:
        normalized = _normalize_skill_name(name)
        if not normalized:
            return None
        for skill in self.list_skills():
            if _normalize_skill_name(skill.name) == normalized:
                return skill
        return None

    def load_skill(self, name: str, max_chars: int = 12000) -> str:
        skill = self.get_skill(name)
        if skill is None:
            return ""
        sections = [skill.path.read_text(encoding="utf-8", errors="ignore").strip()]
        budget = max(0, max_chars - len(sections[0]))
        if budget > 200:
            for extra in _skill_companion_files(skill.path.parent, max_chars=budget):
                if budget <= 0:
                    break
                chunk = extra if len(extra) <= budget else extra[:budget]
                sections.append(chunk)
                budget -= len(chunk)
        text = "\n\n".join(part for part in sections if part).strip()
        if len(text) <= max_chars:
            return text
        return text[:max_chars]


def _normalize_skill_name(value: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "", (value or "").strip().lower())


def _skill_tokens(query: str) -> list[str]:
    seen: list[str] = []
    for token in re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_-]+", query or ""):
        value = token.strip()
        if not value or value in seen:
            continue
        seen.append(value)
    return seen


def _extract_skill_metadata(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    lines = [line.rstrip() for line in text.splitlines()]
    title = ""
    summary = ""
    for line in lines:
        if line.startswith("#"):
            title = line.lstrip("#").strip()
            break
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("- ") or stripped.startswith("* "):
            continue
        summary = stripped
        break
    return title or path.parent.name, summary


def _skill_preview(path: Path, max_chars: int = 6000) -> str:
    text = path.read_text(encoding="utf-8", errors="ignore").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars]


def _skill_companion_files(skill_dir: Path, max_chars: int = 6000) -> list[str]:
    allowed_suffixes = {".py", ".txt", ".json", ".yaml", ".yml", ".sh", ".ps1"}
    parts: list[str] = []
    budget = max_chars
    for path in sorted(skill_dir.iterdir(), key=lambda item: item.name.lower()):
        if not path.is_file() or path.name.upper() == "SKILL.MD" or path.suffix.lower() not in allowed_suffixes:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore").strip()
        if not text:
            continue
        header = f"Reference file: {path.name}\n```{path.suffix.lstrip('.') or 'text'}\n"
        footer = "\n```"
        body_budget = max(0, budget - len(header) - len(footer))
        if body_budget <= 0:
            break
        body = text[:body_budget]
        rendered = f"{header}{body}{footer}"
        parts.append(rendered)
        budget -= len(rendered)
        if budget <= 0:
            break
    return parts
