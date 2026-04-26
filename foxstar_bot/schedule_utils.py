from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from zoneinfo import ZoneInfoNotFoundError


DEFAULT_SCHEDULE_TZ = "America/Los_Angeles"


@dataclass(frozen=True)
class ParsedSchedule:
    schedule_type: str
    cron_expr: str
    next_run_at: str
    timezone: str
    payload: str


def parse_cron_expression(expr: str) -> str:
    parts = [part.strip() for part in str(expr or "").split() if part.strip()]
    if len(parts) != 5:
        raise ValueError("cron must have 5 fields: minute hour day month weekday")
    minute, hour, day, month, weekday = parts
    _validate_cron_field(minute, 0, 59)
    _validate_cron_field(hour, 0, 23)
    _validate_cron_field(day, 1, 31)
    _validate_cron_field(month, 1, 12)
    _validate_cron_field(weekday, 0, 6)
    return " ".join(parts)


def next_cron_run(expr: str, *, now: datetime | None = None, timezone_name: str = DEFAULT_SCHEDULE_TZ) -> datetime:
    cron = parse_cron_expression(expr)
    tz = _resolve_timezone(timezone_name, now=now)
    current = (now or datetime.now(timezone.utc)).astimezone(tz).replace(second=0, microsecond=0) + timedelta(minutes=1)
    minute_expr, hour_expr, day_expr, month_expr, weekday_expr = cron.split()
    for _ in range(0, 60 * 24 * 400):
        if not _cron_field_matches(minute_expr, current.minute):
            current += timedelta(minutes=1)
            continue
        if not _cron_field_matches(hour_expr, current.hour):
            current += timedelta(minutes=1)
            continue
        if not _cron_field_matches(month_expr, current.month):
            current += timedelta(minutes=1)
            continue
        if not _cron_day_matches(day_expr, weekday_expr, current):
            current += timedelta(minutes=1)
            continue
        return current
    raise ValueError("could not find next cron run within 400 days")


def parse_duration_seconds(value: str) -> int:
    text = str(value or "").strip().lower()
    if not text:
        raise ValueError("duration is required")
    if text.isdigit():
        seconds = int(text)
        if seconds <= 0:
            raise ValueError("duration must be positive")
        return seconds
    total = 0
    matched = False
    for amount, unit in re.findall(r"(\d+)\s*([smhd])", text):
        matched = True
        number = int(amount)
        if unit == "s":
            total += number
        elif unit == "m":
            total += number * 60
        elif unit == "h":
            total += number * 3600
        elif unit == "d":
            total += number * 86400
    if not matched or total <= 0:
        raise ValueError("duration must look like 30m, 2h, 1d, or 3600")
    return total


def format_schedule_summary(schedule_type: str, cron_expr: str, next_run_at: str, timezone_name: str) -> str:
    if schedule_type == "once":
        return f"once at {next_run_at}"
    return f"cron {cron_expr} ({timezone_name}), next {next_run_at}"


def _validate_cron_field(expr: str, minimum: int, maximum: int) -> None:
    if not expr:
        raise ValueError("empty cron field")
    for part in expr.split(","):
        part = part.strip()
        if not part:
            raise ValueError("empty cron segment")
        if part == "*":
            continue
        if part.startswith("*/"):
            _validate_int(part[2:], minimum=1, maximum=max(1, maximum - minimum + 1))
            continue
        if "/" in part:
            base, step = part.split("/", 1)
            _validate_int(step, minimum=1, maximum=max(1, maximum - minimum + 1))
            if base == "*":
                continue
            if "-" in base:
                start, end = base.split("-", 1)
                _validate_int(start, minimum=minimum, maximum=maximum)
                _validate_int(end, minimum=minimum, maximum=maximum)
                continue
            raise ValueError(f"invalid cron segment: {part}")
        if "-" in part:
            start, end = part.split("-", 1)
            _validate_int(start, minimum=minimum, maximum=maximum)
            _validate_int(end, minimum=minimum, maximum=maximum)
            continue
        _validate_int(part, minimum=minimum, maximum=maximum)


def _validate_int(value: str, *, minimum: int, maximum: int) -> None:
    number = int(value)
    if number < minimum or number > maximum:
        raise ValueError(f"value {number} outside {minimum}-{maximum}")


def _cron_field_matches(expr: str, value: int) -> bool:
    for part in expr.split(","):
        part = part.strip()
        if part == "*":
            return True
        if part.startswith("*/"):
            step = int(part[2:])
            if value % step == 0:
                return True
            continue
        if "/" in part:
            base, step_text = part.split("/", 1)
            step = int(step_text)
            if base == "*":
                if value % step == 0:
                    return True
                continue
            if "-" in base:
                start, end = (int(item) for item in base.split("-", 1))
                if start <= value <= end and (value - start) % step == 0:
                    return True
                continue
        if "-" in part:
            start, end = (int(item) for item in part.split("-", 1))
            if start <= value <= end:
                return True
            continue
        if int(part) == value:
            return True
    return False


def _cron_day_matches(day_expr: str, weekday_expr: str, value: datetime) -> bool:
    day_match = _cron_field_matches(day_expr, value.day)
    weekday_match = _cron_field_matches(weekday_expr, (value.weekday() + 1) % 7)
    day_any = day_expr == "*"
    weekday_any = weekday_expr == "*"
    if day_any and weekday_any:
        return True
    if day_any:
        return weekday_match
    if weekday_any:
        return day_match
    return day_match or weekday_match


def _resolve_timezone(name: str, *, now: datetime | None = None):
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        if name == DEFAULT_SCHEDULE_TZ:
            return _fallback_california_tz(now=now)
        raise


def _fallback_california_tz(*, now: datetime | None = None):
    current = now or datetime.now(timezone.utc)
    year = current.year
    start = _nth_weekday_of_month(year, 3, 6, 2).replace(hour=10, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)
    end = _nth_weekday_of_month(year, 11, 6, 1).replace(hour=9, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)
    offset = -7 if start <= current.replace(tzinfo=current.tzinfo or timezone.utc).astimezone(timezone.utc) < end else -8
    return timezone(timedelta(hours=offset), name="America/Los_Angeles")


def _nth_weekday_of_month(year: int, month: int, weekday: int, nth: int) -> datetime:
    current = datetime(year, month, 1)
    while current.weekday() != weekday:
        current += timedelta(days=1)
    current += timedelta(days=7 * (nth - 1))
    return current
