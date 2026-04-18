from __future__ import annotations

import hashlib
import re


WXID_RE = re.compile(r"\bwxid_[A-Za-z0-9_-]+\b", re.IGNORECASE)
CHATROOM_RE = re.compile(r"\b\d{6,}@chatroom\b", re.IGNORECASE)
DIRECT_WECHAT_ID_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9_-]{5,31}\b")
MENTION_ID_RE = re.compile(
    r"@(?P<name>[^\s@()（）:：]{1,32})\s*[（(](?P<id>wxid_[A-Za-z0-9_-]+|[A-Za-z][A-Za-z0-9_-]{5,31})[）)]",
    re.IGNORECASE,
)
NAME_ID_RE = re.compile(
    r"(?P<name>[^\s@()（）:：]{1,32})\s*[（(](?P<id>wxid_[A-Za-z0-9_-]+|[A-Za-z][A-Za-z0-9_-]{5,31})[）)]",
    re.IGNORECASE,
)
LABELED_ID_RE = re.compile(
    r"(?i)\b(?:wechat\s*id|weixin\s*id|wxid|微信号|微信ID)\s*[:：]\s*(?:wxid_[A-Za-z0-9_-]+|[A-Za-z][A-Za-z0-9_-]{5,31})"
)


def redact_private_ids(text: str) -> str:
    value = str(text or "")
    if not value:
        return ""
    value = MENTION_ID_RE.sub(lambda match: f"@{match.group('name')}", value)
    value = NAME_ID_RE.sub(lambda match: match.group("name"), value)
    value = LABELED_ID_RE.sub("微信号：[已隐藏]", value)
    value = WXID_RE.sub("[已隐藏ID]", value)
    value = CHATROOM_RE.sub("[已隐藏群ID]", value)
    return value


def public_display_name(display: str, raw_id: str) -> str:
    name = redact_private_ids(str(display or "").strip())
    raw = str(raw_id or "").strip()
    if name and name != raw and not _looks_like_private_id(name):
        return name
    return f"用户{_short_hash(raw)}" if raw else "用户"


def public_participant_label(label: str) -> str:
    value = redact_private_ids(str(label or "").strip())
    if not value:
        return "用户"
    if _looks_like_private_id(value):
        return f"用户{_short_hash(value)}"
    return value


def _looks_like_private_id(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if WXID_RE.search(text) or CHATROOM_RE.search(text):
        return True
    if DIRECT_WECHAT_ID_RE.fullmatch(text) and not _has_cjk(text) and len(text) >= 6:
        return True
    return False


def _has_cjk(value: str) -> bool:
    return any("\u3400" <= char <= "\u9fff" for char in value)


def _short_hash(value: str) -> str:
    if not value:
        return "0000"
    return hashlib.sha1(value.encode("utf-8", errors="ignore")).hexdigest()[:4]
