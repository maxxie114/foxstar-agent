from __future__ import annotations

import re

AI_PHRASES = [
    "作为一个AI模型，",
    "作为AI模型，",
    "作为一个人工智能，",
    "作为人工智能，",
    "我不能浏览互联网",
    "我是一个AI",
    "我是 AI",
    "我是AI",
    "我是个AI",
    "我是个 AI",
    "我是群里的AI助手",
    "我是群里的 AI 助手",
    "我是群里的助手",
    "我是个聊天助手",
    "我是一个聊天助手",
    "不方便透露具体型号",
    "能力边界",
    "需要我帮你",
    "如果你要",
    "我可以继续",
    "要详细链接或更多内容？",
]

def polish_reply(text: str, max_chars: int = 140) -> str:
    text = (text or "").strip()
    for phrase in AI_PHRASES:
        text = text.replace(phrase, "")
    text = _strip_markdown(text)
    text = _normalize_lines(text)
    if len(text) <= max_chars:
        return text
    trimmed = text[:max_chars].rstrip()
    end = max(trimmed.rfind("。"), trimmed.rfind("\n"), trimmed.rfind("！"), trimmed.rfind("？"))
    if end > 8:
        trimmed = trimmed[: end + 1]
    return trimmed

def _strip_markdown(text: str) -> str:
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"^\s*[-*•]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+[.)）]\s+", "", text, flags=re.MULTILINE)
    text = text.replace("**", "").replace("###", "").replace("##", "").replace("#", "")
    return text

def _normalize_lines(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()

def _split_sentences(text: str) -> list[str]:
    parts: list[str] = []
    start = 0
    index = 0
    while index < len(text):
        char = text[index]
        if char in "。！？!?；;":
            end = index + 1
            while end < len(text) and text[end] in "」』】）)\"'":
                end += 1
            part = text[start:end].strip(" \n，,")
            if part:
                parts.append(part)
            start = end
            index = end
            continue
        index += 1
    tail = text[start:].strip(" \n，,")
    if tail:
        parts.append(tail)
    return parts or [text.strip()]

def _merge_standalone_emoji_lines(lines: list[str]) -> list[str]:
    merged: list[str] = []
    for line in lines:
        if _is_standalone_emoji(line) and merged:
            merged[-1] = f"{merged[-1]}{line}"
        else:
            merged.append(line)
    return merged

def _is_standalone_emoji(text: str) -> bool:
    value = text.strip()
    if not value:
        return False
    if re.fullmatch(r"(?:\[[^\[\]\s]{1,8}\]){1,3}", value):
        return True
    return bool(re.fullmatch(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]{1,4}", value))
