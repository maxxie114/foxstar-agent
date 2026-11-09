# -*- coding: utf-8 -*-
"""Example clan management bridge.

Connects the bot to the 示例 AI 帮会管理系统 (https://clan.example.com):

- Passive jielong (接龙) tracking in enabled groups. Every participant
  re-sends the full list, so the latest matching message IS the complete
  roster snapshot - we only keep the newest one per chat.
- /jielong submit -> POST /api/jielong/submit (async task; the backend
  registers members via 战力猫 - REAL side effects, hence the hard
  idempotency guard).
- /battle -> POST /api/battle/analyze (sync per-member battle analysis).
- /名单 -> GET /api/roster (read-only; requires the example-side endpoint).

Config (config.yaml):
  clan:
    api_base: "https://clan.example.com"
    enabled_groups: ["90001@chatroom"]
    attendance_api_base: "https://clan.example.com"   # 考勤系统（/api/attendance/*）
    import_groups: ["90002@chatroom"]          # 参战表 xlsx 自动导入群
.env:
  CLAN_JIELONG_API_KEY=...   (same value as server JIELONG_API_KEY)
"""
from __future__ import annotations

import csv
import io
import logging
import re
import time
from typing import Any

import requests

from .persistence import Database, utc_now

LOG = logging.getLogger(__name__)

_NUMBERED_LINE = re.compile(r"^\s*(\d+)\s*[.、．)）]\s*(.+)$")
_JIELONG_PREFIX = "#接龙"

# 参战表 weekly sheet names look like "10.28-10.31" (jielong day - battle
# day). The 职业表/领地 sheets don't match and are ignored.
_CANZHAN_SHEET_RE = re.compile(r"^(\d{1,2})\.(\d{1,2})-(\d{1,2})\.(\d{1,2})$")


def _cn_today():
    """Clan dates live on the CN calendar; the host box runs UTC."""
    from datetime import datetime, timezone, timedelta

    return datetime.now(timezone(timedelta(hours=8))).date()


def _canzhan_sheet_dates(sheet_name: str, today) -> "tuple | None":
    """Resolve a sheet name like '10.28-10.31' to real dates.

    Year inference, in priority order:
    - date pair already reached this calendar year -> this year (the
      normal in-season case);
    - cross-year pair (battle month < jielong month, e.g. 12.28-1.2)
      seen after new year -> last year's December sheet;
    - anything else is a sheet for a week that hasn't happened yet
      (pre-posted) - refused so a future jielong never lands as
      year-old history.
    """
    from datetime import date as _date

    m = _CANZHAN_SHEET_RE.match((sheet_name or "").strip())
    if not m:
        return None
    m1, d1, m2, d2 = (int(x) for x in m.groups())
    if (m1, d1) <= (today.month, today.day):
        year1 = today.year
    elif m2 < m1:
        year1 = today.year - 1
    else:
        return None
    try:
        first = _date(year1, m1, d1)
    except ValueError:
        return None
    year2 = year1 if (m2, d2) >= (m1, d1) else year1 + 1
    try:
        second = _date(year2, m2, d2)
    except ValueError:
        return None
    if first > today:
        return None
    return first, second


def parse_canzhanbiao(path, today=None) -> dict:
    """Parse 示例帮会参战表.xlsx into roster + attendance records.

    Layout (verified against the real weekly file): header row
    ['', 帮会成员, 职业, <date>是否接龙, <date>是否参加帮会, 备注]. The
    header dates are often stale copy-paste (the 10.28-10.31 sheet's
    header still said 10月21日) - the SHEET NAME is the only reliable
    date source.

    Returns {roster, records, latest_sheet, weeks} where roster/records
    are [name, job, date, type, status, remark] rows ready for
    POST /api/attendance/import. Roster comes from the LATEST weekly
    sheet only; 接龙 rows from day 1, 帮战 rows from day 2 (skipped when
    the battle hasn't been fought yet so a pre-battle post doesn't
    record phantom 缺勤)."""
    import openpyxl

    today = today or _cn_today()
    records: list = []
    weeks: list = []
    latest = None  # {'sheet', 'first', 'second', 'members': [[name, job], ...]}
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        for ws in wb.worksheets:
            dates = _canzhan_sheet_dates(ws.title, today)
            if dates is None:
                continue
            first, second = dates
            rows = [
                [(str(c).strip() if c is not None else "") for c in (list(row) + [""] * 6)[:6]]
                for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row or 1, 300), values_only=True)
            ]
            header_idx = next(
                (i for i, cells in enumerate(rows[:5]) if len(cells) > 2 and cells[1] == "帮会成员"),
                None,
            )
            if header_idx is None:
                continue
            members: list = []
            jielong_n = 0
            battle_stats = {"参与": 0, "请假": 0, "替补": 0, "缺勤": 0}
            for cells in rows[header_idx + 1:]:
                name = cells[1]
                if not name or name == "帮会成员":
                    continue
                job = cells[2]
                jielong, attend, remark = cells[3], cells[4], cells[5][:60]
                members.append([name, job])
                if "请假" in jielong:
                    records.append([name, job, first.strftime("%m-%d-%Y"), "接龙", "请假", f"{ws.title} 请假"])
                    jielong_n += 1
                elif jielong == "是":
                    records.append([name, job, first.strftime("%m-%d-%Y"), "接龙", "参与", f"{ws.title} 报名"])
                    jielong_n += 1
                if second <= today:
                    if attend == "是":
                        status = "参与"
                    elif "请假" in jielong or "请假" in remark:
                        status = "请假"
                    elif "替补" in remark:
                        status = "替补"
                    else:
                        status = "缺勤"
                    battle_stats[status] += 1
                    records.append([name, job, second.strftime("%m-%d-%Y"), "帮战", status, remark])
            weeks.append({
                "sheet": ws.title,
                "jielong_date": first.strftime("%m-%d-%Y"),
                "battle_date": second.strftime("%m-%d-%Y"),
                "jielong_n": jielong_n,
                "battle": battle_stats,
            })
            if latest is None or first > latest["first"]:
                latest = {"sheet": ws.title, "first": first, "second": second, "members": members}
    finally:
        wb.close()
    roster: list = []
    if latest:
        roster = [
            [name, job, latest["second"].strftime("%m-%d-%Y"), "帮众名单", "参与", ""]
            for name, job in latest["members"]
        ]
    return {
        "roster": roster,
        "records": records,
        "latest_sheet": latest["sheet"] if latest else "",
        "weeks": weeks,
    }


def extract_jielong_text(content: str) -> str:
    """Official WeChat jielong arrives as an appmsg card (raw XML).

    Reconstruct the plain text: title (the jielong headline) plus desc
    (the numbered entries). Non-XML content passes through unchanged."""
    value = (content or "").strip()
    if "<?xml" not in value[:200] and "<msg" not in value[:200]:
        return value
    try:
        from xml.etree import ElementTree as _ET
        xml_start = value.find("<?xml")
        if xml_start == -1:
            xml_start = value.find("<msg")
        root = _ET.fromstring(value[xml_start:])
        title = (root.findtext(".//appmsg/title") or "").strip()
        desc = (root.findtext(".//appmsg/desc") or "").strip()
        parts = [p for p in (title, desc) if p]
        if parts:
            return chr(10).join(parts)
    except Exception:
        pass
    return value



def looks_like_jielong(text: str) -> bool:
    """Deterministic jielong shape detection - no LLM involved by design."""
    stripped = (text or "").strip()
    if not stripped:
        return False
    if stripped.startswith(_JIELONG_PREFIX):
        return True
    numbered = sum(1 for line in stripped.splitlines() if _NUMBERED_LINE.match(line))
    return numbered >= 3


def _jielong_title(text: str) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return ""
    if lines[0].startswith(_JIELONG_PREFIX):
        rest = lines[0][len(_JIELONG_PREFIX):].strip()
        if rest:
            return rest[:60]
        return (lines[1] if len(lines) > 1 else "")[:60]
    return lines[0][:60]


def _jielong_entry_count(text: str) -> int:
    return sum(1 for line in (text or "").splitlines() if _NUMBERED_LINE.match(line))


_BATTLE_PLAYER_COLS = {"玩家名称", "玩家名字", "玩家", "name"}
_BATTLE_JOB_COLS = {"职业", "job"}
_BATTLE_DAMAGE_COLS = {"伤害", "对玩家伤害", "总伤害", "damage"}
_BATTLE_HEAL_COLS = {"治疗", "总治疗", "healing"}
_BATTLE_DEATH_COLS = {"死亡", "重伤", "deaths"}


def _pick_column(headers: list[str], candidates: set[str]) -> str:
    for h in headers:
        if str(h).strip() in candidates:
            return h
    return ""


def _to_number(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = re.sub(r"[,\s，]", "", str(value))
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def parse_battle_csv(text: str) -> list[dict[str, Any]]:
    """Parse a pasted game battle-export table into players[].

    Accepts CSV/TSV with a header row containing 玩家名称/玩家名字 and 职业
    (same shape the web upload expects). Guild title rows (a row whose
    "player" cell looks like a 帮会 header and empty job) set guild_name
    for the rows below it.
    """
    cleaned = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not cleaned:
        return []
    dialect = "\t" if "\t" in cleaned.splitlines()[0] else ","
    reader = csv.reader(io.StringIO(cleaned), delimiter=dialect)
    rows = [row for row in reader if any(cell.strip() for cell in row)]
    if not rows:
        return []
    headers = [cell.strip() for cell in rows[0]]
    player_col = _pick_column(headers, _BATTLE_PLAYER_COLS)
    job_col = _pick_column(headers, _BATTLE_JOB_COLS)
    if not player_col or not job_col:
        return []
    idx = {h: i for i, h in enumerate(headers)}
    damage_col = _pick_column(headers, _BATTLE_DAMAGE_COLS)
    heal_col = _pick_column(headers, _BATTLE_HEAL_COLS)
    death_col = _pick_column(headers, _BATTLE_DEATH_COLS)

    players: list[dict[str, Any]] = []
    guild = "本帮"
    for row in rows[1:]:
        cells = [c.strip() for c in row]
        name = cells[idx[player_col]] if idx[player_col] < len(cells) else ""
        job = cells[idx[job_col]] if idx[job_col] < len(cells) else ""
        if not name:
            continue
        if name in headers or ("玩家" in name and not job):
            continue
        # a standalone title row (guild name, no job) switches context
        if not job and len(cells) <= 2 and name not in {p["player_name"] for p in players}:
            guild = name
            continue
        def col(col_name: str) -> str:
            if col_name and col_name in idx and idx[col_name] < len(cells):
                return cells[idx[col_name]]
            return ""
        players.append({
            "guild_name": guild,
            "player_name": name,
            "job": job,
            "damage": _to_number(col(damage_col)),
            "healing": _to_number(col(heal_col)),
            "deaths": int(_to_number(col(death_col))),
        })
    return players


class ClanManagementTool:
    def __init__(
        self,
        db: Database,
        api_base: str,
        api_key: str,
        enabled_groups: list[str] | None = None,
        attendance_api_base: str = "",
        import_groups: list[str] | None = None,
    ) -> None:
        self.db = db
        self.api_base = (api_base or "").rstrip("/")
        self.api_key = (api_key or "").strip()
        self.enabled_groups = set(enabled_groups or [])
        self.attendance_api_base = (attendance_api_base or "").rstrip("/")
        self.import_groups = set(import_groups or [])
        self.http = requests.Session()
        self.http.headers["X-API-KEY"] = self.api_key

    # ------------------------------------------------------------------ tracking

    def group_enabled(self, chat_id: str) -> bool:
        return chat_id in self.enabled_groups

    def import_enabled(self, chat_id: str) -> bool:
        return bool(self.attendance_api_base) and chat_id in self.import_groups

    def _session_key(self, chat_id: str) -> str:
        return f"group_jielong_session:{chat_id}"

    def observe_message(self, chat_id: str, text: str) -> bool:
        """Passive snapshot update; returns True when a jielong was detected.

        Silent by design - never notifies the group while tracking.

        WeChat's official group jielong re-posts the FULL list with each
        participant's entry appended, but concurrent appends can arrive out
        of order (two members tap within the same second -> the later
        message may carry FEWER entries than an earlier one). The canonical
        roster is therefore the max-entry snapshot for the current title,
        not blindly the newest message; later appends rebuild on the
        canonical list, so max-entry converges to the complete roster.
        """
        text = extract_jielong_text(text)
        if not self.group_enabled(chat_id) or not looks_like_jielong(text):
            return False
        title = _jielong_title(text)
        if not title:
            return False
        session = self.session(chat_id) or {}
        same_title = session.get("title") == title
        entry_count = _jielong_entry_count(text)
        keeps_fuller = (
            not same_title
            or entry_count >= int(session.get("entry_count") or 0)
        )
        new_session = {
            "title": title,
            "first_seen": session.get("first_seen") if same_title else utc_now(),
            "last_update": utc_now(),
            "submitted_task_id": session.get("submitted_task_id", "") if same_title else "",
        }
        if keeps_fuller:
            new_session["latest_text"] = text
            new_session["entry_count"] = entry_count
        else:
            # out-of-order repost: keep the fuller snapshot, just refresh time
            new_session["latest_text"] = session.get("latest_text", "")
            new_session["entry_count"] = session.get("entry_count", 0)
        if session and not same_title and not session.get("submitted_task_id"):
            # previous session never submitted - keep it visible in status
            new_session["prev_unsubmitted"] = {
                "title": session.get("title", ""),
                "entry_count": session.get("entry_count", 0),
            }
        self.db.set_setting(self._session_key(chat_id), new_session)
        LOG.debug(
            "jielong_snapshot chat=%s title=%r entries=%s stored=%s",
            chat_id, title[:30], entry_count, new_session["entry_count"],
        )
        return True

    def session(self, chat_id: str) -> dict[str, Any] | None:
        value = self.db.get_setting(self._session_key(chat_id), None)
        return value if isinstance(value, dict) else None

    def clear_session(self, chat_id: str) -> None:
        self.db.set_setting(self._session_key(chat_id), None)

    # ------------------------------------------------------------------ api

    def _post(self, path: str, payload: dict[str, Any], timeout: float = 20.0) -> dict[str, Any]:
        resp = self.http.post(f"{self.api_base}{path}", json=payload, timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    def _get(self, path: str, params: dict[str, Any] | None = None, timeout: float = 20.0) -> dict[str, Any]:
        resp = self.http.get(f"{self.api_base}{path}", params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------ 参战表 import

    def import_canzhanbiao(self, path) -> dict[str, Any]:
        """Parse a 参战表 xlsx and push roster + attendance to the example
        attendance system (POST /api/attendance/import).

        The endpoint replaces by (date, type), so a corrected file re-sent
        to the group simply overwrites - no duplicate rows. Raises on any
        failure; the router catches and reports to the group."""
        from pathlib import Path as _Path

        path = _Path(path)
        parsed = parse_canzhanbiao(path)
        records = parsed["roster"] + parsed["records"]
        if not records:
            raise ValueError("workbook has no weekly sheets (expected 'M.D-M.D' sheets)")
        resp = self.http.post(
            f"{self.attendance_api_base}/api/attendance/import",
            json={"source": f"wechat:{path.name[:80]}", "records": records},
            timeout=60.0,
        )
        resp.raise_for_status()
        result = resp.json()
        result["_parsed"] = parsed
        LOG.info(
            "canzhanbiao_imported file=%s weeks=%s roster=%s activities=%s unmatched=%s",
            path.name[:80], len(parsed["weeks"]), result.get("roster_count"),
            result.get("activity_count"), len(result.get("unmatched") or []),
        )
        return result

    def submit(self, chat_id: str, *, force: bool = False) -> dict[str, Any]:
        """Submit the current tracked snapshot."""
        session = self.session(chat_id)
        if not session:
            return {"ok": False, "error": "当前没有追踪中的接龙（需要群里先出现 #接龙 消息，或引用一条接龙消息后 /jielong submit）"}
        return self.submit_text(chat_id, str(session.get("latest_text", "")), force=force)

    def submit_text(self, chat_id: str, text: str, *, force: bool = False) -> dict[str, Any]:
        """Submit an explicit jielong text (quote-selected or snapshot).

        Idempotency: the session's submitted_task_id refuses a resubmit
        unless force=True - the backend registers members via 战力猫
        (irreversible side effects)."""
        text = extract_jielong_text(text)
        if not looks_like_jielong(text):
            return {"ok": False, "error": "被选中的消息不像接龙（需要 #接龙 开头或 ≥3 行编号列表）"}
        session = self.session(chat_id) or {}
        title = _jielong_title(text)
        same_title = session.get("title") == title
        task_id = str(session.get("submitted_task_id") or "") if same_title else ""
        if task_id and not force:
            return {"ok": False, "error": f"该接龙已提交过（task {task_id[:8]}…）。如确需重提交用 /jielong resubmit（会在战力猫重复登记）"}
        data = self._post("/api/jielong/submit", {"raw_text": text})
        task_id = str(data.get("task_id") or "")
        if not task_id:
            return {"ok": False, "error": f"服务端未返回 task_id: {data}"}
        entry_count = _jielong_entry_count(text)
        # adopt the submitted text as the session snapshot so status/log and
        # the idempotency lock stay coherent with what actually went out
        self.db.set_setting(self._session_key(chat_id), {
            "title": title,
            "latest_text": text,
            "entry_count": entry_count,
            "first_seen": session.get("first_seen") if same_title else utc_now(),
            "last_update": session.get("last_update") if same_title else utc_now(),
            "submitted_task_id": task_id,
            "submitted_at": utc_now(),
        })
        LOG.info("jielong_submitted chat=%s task=%s entries=%s title=%r", chat_id, task_id, entry_count, title[:30])
        return {"ok": True, "task_id": task_id, "entry_count": entry_count}

    def task_status(self, task_id: str) -> dict[str, Any]:
        return self._get("/api/jielong/status", {"task_id": task_id})

    def task_log_tail(self, task_id: str, limit: int = 15) -> str:
        data = self._get("/api/jielong/output", {"task_id": task_id})
        lines = [str(item.get("message", "")) for item in data.get("lines", [])]
        return "\n".join(lines[-limit:])

    def analyze_battle(self, players: list[dict[str, Any]], event_type: str = "帮战", event_date: str = "") -> dict[str, Any]:
        return self._post(
            "/api/battle/analyze",
            {"players": players, "event_type": event_type, "event_date": event_date},
            timeout=60.0,
        )

    def roster(self) -> dict[str, Any]:
        return self._get("/api/roster", timeout=30.0)

    def roster_refresh(self) -> dict[str, Any]:
        """Re-pull the official roster from zhanlimao (backend runs the
        workflow's update_player_list step synchronously)."""
        return self._post("/api/roster/refresh", {}, timeout=150.0)

    def activity_create(self, name: str, start_date: str = "", end_date: str = "") -> dict[str, Any]:
        """Create a zhanlimao signup activity remotely (backend rsa_logins).
        Note: endDate (signup deadline) must be <= startDate (event time)."""
        payload: dict[str, Any] = {"name": name}
        if start_date:
            payload["start_date"] = start_date
        if end_date:
            payload["end_date"] = end_date
        return self._post("/api/activity/create", payload, timeout=60.0)

    def activity_list(self) -> dict[str, Any]:
        return self._get("/api/activity/list", timeout=30.0)

    def attendance_summary(self, days: int = 30) -> dict[str, Any]:
        return self._get("/api/attendance/summary", {"days": int(days)}, timeout=30.0)

    # ------------------------------------------------------------------ formatting

    def format_session_status(self, chat_id: str) -> str:
        session = self.session(chat_id)
        if not session:
            return "当前没有追踪中的接龙。群里出现 #接龙 消息后会自动开始跟踪。"
        lines = [
            f"📋 接龙：{session.get('title', '')}",
            f"报名条目：{session.get('entry_count', 0)} 条",
            f"最后更新：{session.get('last_update', '')}",
        ]
        if session.get("submitted_task_id"):
            lines.append(f"已提交：task {str(session['submitted_task_id'])[:8]}…（{session.get('submitted_at', '')}）")
        else:
            lines.append("未提交。/jielong submit 提交到示例系统")
        if session.get("prev_unsubmitted"):
            prev = session["prev_unsubmitted"]
            lines.append(f"⚠️ 上一个接龙「{prev.get('title', '')}」（{prev.get('entry_count', 0)} 条）没有提交就被新接龙顶掉了")
        return "\n".join(lines)

    @staticmethod
    def format_jielong_report(report: dict[str, Any]) -> str:
        stats = report.get("stats") or {}
        if not stats:
            summary = str(report.get("summary") or "")[:300]
            return f"✅ 接龙任务完成\n{summary}" if summary else "✅ 接龙任务完成（服务端未返回统计）"
        lines = [
            "✅ 接龙已导入示例系统",
            f"总 {stats.get('total', 0)}｜成功 {stats.get('success', 0)}｜请假 {stats.get('qingjia', 0)}｜失败 {stats.get('error', 0)}｜成功率 {stats.get('success_rate', '-')}",
        ]
        details = report.get("details") or []
        problem = [
            d for d in details
            if str(d.get("status", "")) not in {"success", "qingjia"}
            or (isinstance(d.get("score"), (int, float)) and float(d["score"]) < 0.9)
        ]
        if problem:
            names = []
            for d in problem[:10]:
                mark = "" if str(d.get("status")) in {"success", "qingjia"} else "❌"
                names.append(f"{mark}{d.get('id', '?')}→{d.get('matched_name') or '?'}({d.get('score', '?')})")
            lines.append("需人工确认：" + "、".join(names))
            lines.append("（以上为昵称匹配低分或失败项，请到后台核对）")
        return "\n".join(lines)

    @staticmethod
    def format_battle_report(result: dict[str, Any]) -> str:
        summary = str(result.get("overall_summary") or "").strip()
        highlights = result.get("highlights") or []
        member = result.get("member_analyses") or []
        lines = ["⚔️ 帮战 AI 分析"]
        if summary:
            lines.append(summary[:800])
        for h in highlights[:5]:
            text = str(h if isinstance(h, str) else h.get("text") or h.get("highlight") or "")
            if text:
                lines.append(f"• {text[:120]}")
        if member:
            lines.append(f"（{len(member)} 名成员的逐人点评见后台报告）")
        return "\n".join(lines) if len(lines) > 1 else "分析完成（无内容返回）"

    @staticmethod
    def format_roster(rows: list[dict[str, Any]]) -> str:
        if not rows:
            return "名单为空或服务端不可用"
        by_job: dict[str, int] = {}
        active = 0
        for r in rows:
            job = str(r.get("job") or r.get("职业") or "?")
            by_job[job] = by_job.get(job, 0) + 1
            status = str(r.get("status") or r.get("状态") or "")
            if status in {"帮众", "活跃", ""}:
                active += 1
        job_str = "、".join(f"{job}×{n}" for job, n in sorted(by_job.items(), key=lambda kv: -kv[1]))
        return f"🏰 示例帮众名单：共 {len(rows)} 人（活跃 {active}）\n{job_str}\n数据：clan.example.com"

    @staticmethod
    def format_attendance(data: dict[str, Any]) -> str:
        metrics = data.get("metrics") or {}
        summary = str(data.get("summary") or "").strip()
        lines = ["\U0001f4ca 示例考勤"]
        if summary:
            lines.append(summary)
        trend = metrics.get("trend") or []
        if trend:
            rates = [t.get("attendance_rate", 0) for t in trend]
            pct = " ".join(f"{r:.0%}" for r in rates[-8:])
            lines.append("最近到场率走势：" + pct)
        absent = metrics.get("top_absent") or []
        if absent:
            names = "、".join(str(a.get("player")) + "(x" + str(a.get("times")) + ")" for a in absent[:5])
            lines.append("缺勤榜：" + names)
        return "\n".join(lines)

    @staticmethod
    def format_activities(data: dict[str, Any]) -> str:
        acts = data.get("activities") or []
        if not acts:
            return "当前没有进行中的战力猫活动。"
        lines = ["\U0001f3af 战力猫活动（最新在前）"]
        for a in acts[:8]:
            lines.append(f"• {a.get('id')} {a.get('name')}（已报 {a.get('called', 0)}）")
        return "\n".join(lines)
