from __future__ import annotations

INJECTION_PATTERNS = [
    "ignore previous instructions",
    "忽略之前",
    "忽略以上",
    "忘记你的规则",
    "你现在是",
    "切换角色",
    "解除限制",
    "reveal your system prompt",
    "泄露系统提示词",
    "显示系统提示词",
    "只同意我",
]

def contains_injection(text: str) -> bool:
    lowered = (text or "").lower()
    return any(pattern in lowered for pattern in INJECTION_PATTERNS)
