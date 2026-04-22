from __future__ import annotations

import re
from html import unescape
from xml.etree import ElementTree


def normalize_wechat_content(content: str, msg_type: int) -> str:
    text = content or ""
    stripped = text.strip()
    if not stripped:
        return text

    if stripped.startswith("<emoji") or "<emoji " in stripped[:200]:
        return "[动画表情]"

    if "<msg" not in stripped[:200]:
        return text

    root = _parse_xml(stripped)
    if root is None:
        return text

    if msg_type == 3 and root.find(".//img") is not None:
        return _render_image_message(root)

    app_type = _find_text(root, ".//appmsg/type")
    if msg_type == 49 and app_type == "57":
        return _render_quote_message(root) or text
    if msg_type == 49:
        return _render_app_message(root, app_type) or text

    return text


def wechat_appmsg_type(content: str) -> str:
    stripped = (content or "").strip()
    if "<msg" not in stripped[:200]:
        return ""
    root = _parse_xml(stripped)
    if root is None:
        return ""
    return _find_text(root, ".//appmsg/type")


def wechat_is_document_appmsg(content: str) -> bool:
    return wechat_appmsg_type(content) in {"6", "74"}


def wechat_image_length(content: str) -> int | None:
    stripped = (content or "").strip()
    if "<msg" not in stripped[:200]:
        return None
    root = _parse_xml(stripped)
    if root is None:
        return None
    img = root.find(".//img")
    if img is None:
        return None
    length = img.attrib.get("length") or img.attrib.get("hdlength")
    if not length or not length.isdigit():
        return None
    return int(length)


def _render_quote_message(root: ElementTree.Element) -> str:
    title = _clean_text(_find_text(root, ".//appmsg/title"))
    quoted_author = _clean_text(_find_text(root, ".//refermsg/displayname"))
    quoted_user = _clean_text(_find_text(root, ".//refermsg/chatusr"))
    quoted_type = _find_text(root, ".//refermsg/type")
    quoted = _clean_quoted_text(_find_text(root, ".//refermsg/content"), quoted_type)

    lines = ["[引用消息]"]
    if title:
        lines.append(f"当前回复: {title}")
    if quoted:
        author = quoted_author or quoted_user
        prefix = f"{author}: " if author else ""
        lines.append(f"引用原文: {prefix}{quoted}")
    elif quoted_author or quoted_user:
        author = quoted_author or quoted_user
        lines.append(f"引用原文: {author}")

    return "\n".join(lines) if len(lines) > 1 else ""


def _render_image_message(root: ElementTree.Element) -> str:
    img = root.find(".//img")
    if img is None:
        return "[图片]"
    width = img.attrib.get("cdnthumbwidth") or img.attrib.get("cdnmidwidth") or img.attrib.get("width")
    height = img.attrib.get("cdnthumbheight") or img.attrib.get("cdnmidheight") or img.attrib.get("height")
    if width and height and width != "0" and height != "0":
        return f"[图片 {width}x{height}]"
    return "[图片]"


def _render_app_message(root: ElementTree.Element, app_type: str) -> str:
    title = _clean_text(_find_text(root, ".//appmsg/title"))
    desc = _clean_text(_find_text(root, ".//appmsg/des"))
    if app_type in {"6", "74"}:
        if title:
            return f"[文件] {title}"
        return "[文件]"
    if app_type == "5":
        if title and desc:
            return f"[分享] {title} - {desc}"
        if title:
            return f"[分享] {title}"
        return "[分享]"
    if title and desc:
        return f"[卡片] {title} - {desc}"
    if title:
        return f"[卡片] {title}"
    if desc:
        return f"[卡片] {desc}"
    return "[卡片]"


def _parse_xml(text: str) -> ElementTree.Element | None:
    try:
        return ElementTree.fromstring(text)
    except ElementTree.ParseError:
        return None


def _find_text(root: ElementTree.Element, path: str) -> str:
    value = root.findtext(path)
    return value or ""


def _clean_text(text: str) -> str:
    value = unescape(text or "")
    value = re.sub(r"<msgsource>.*?</msgsource>", " ", value, flags=re.DOTALL)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _clean_quoted_text(text: str, msg_type: str) -> str:
    value = _clean_text(text)
    if value.startswith("<?xml") or value.startswith("<msg"):
        normalized = normalize_wechat_content(value, int(msg_type) if msg_type.isdigit() else 0)
        if normalized != value:
            return normalized
    return value
