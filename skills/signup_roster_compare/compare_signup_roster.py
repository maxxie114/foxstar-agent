import json

# Fill these before execution.
ROSTER = [
    # "逆噬",
]

SIGNUPS = [
    # {"raw": "绯雪", "canonical": "绯雪", "status": "参加"},
]

ALIASES = {
    # "糊啊呼噜": "糊阿呼噜",
}


def normalize_name(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    return ALIASES.get(text, text)


def build_report() -> dict:
    roster_set = {normalize_name(name) for name in ROSTER if normalize_name(name)}
    normalized = []
    for item in SIGNUPS:
        raw = str(item.get("raw", "")).strip()
        canonical = normalize_name(str(item.get("canonical", raw)).strip() or raw)
        status = str(item.get("status", "参加")).strip() or "参加"
        normalized.append({"raw": raw, "canonical": canonical, "status": status})

    present = []
    leave = []
    substitutes = []
    unknown = []
    for item in normalized:
        name = item["canonical"]
        status = item["status"]
        bucket = present
        if "请假" in status or "不请" in status:
            bucket = leave
        elif "替补" in status or "可替补" in status:
            bucket = substitutes
        if name in roster_set:
            bucket.append(name)
        else:
            unknown.append(item)

    present_unique = sorted(set(present))
    leave_unique = sorted(set(leave))
    substitutes_unique = sorted(set(substitutes))
    touched = set(present_unique) | set(leave_unique) | set(substitutes_unique)
    missing = sorted(roster_set - touched)

    return {
        "ok": True,
        "roster_count": len(roster_set),
        "signup_total": len(normalized),
        "present_count": len(present_unique),
        "leave_count": len(leave_unique),
        "substitute_count": len(substitutes_unique),
        "missing_count": len(missing),
        "present": present_unique,
        "leave": leave_unique,
        "substitutes": substitutes_unique,
        "missing": missing,
        "unknown_signup_names": unknown,
    }


if __name__ == "__main__":
    print(json.dumps(build_report(), ensure_ascii=False))
