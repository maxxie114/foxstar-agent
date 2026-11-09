from __future__ import annotations

from .auth import AuthService

import json
import logging
import re
import threading
import hashlib
from difflib import get_close_matches
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import AppConfig, update_whitelist_user_ids
from .context_store import DEFAULT_CONTEXT_MESSAGES, MAX_CONTEXT_MESSAGES, normalize_context_messages
from .memory_store import MemoryStore
from .persistence import Database, ScheduledTaskLimitError, utc_now
from .provider_catalog import catalog_lookup
from .prompt_profiles import get_template, list_template_names, normalize_template_name, template_exists, template_help
from .schedule_utils import DEFAULT_SCHEDULE_TZ, format_schedule_summary, next_cron_run, parse_cron_expression, parse_duration_seconds
from .skills import SkillRegistry
from .style_profiles import parse_style_tokens, style_help
from .tool_fortune import LocalFortuneTool
from .tool_games import MiniGameTool, RPS_DISPLAY
from .tool_weather import OpenMeteoWeatherTool

GAME_LOG = logging.getLogger("foxstar_bot.game")
_NOTEBOOK_DRAIN_LOCK = threading.Lock()
_NOTEBOOK_DRAINING: set[str] = set()

# Disable scope (2026-10-13): only finance-CALCULATION is hard-disabled
# (per-message classification pipeline, burns compute even when idle).
# Finance-ANALYSIS (股票分析) stays available - on-demand, no per-message cost.
# Matches the router's _CALCULATION_HARD_DISABLE flag.
FINANCE_CALCULATION_HARD_DISABLE = True

# Bug reports confirmed fixed in code. On startup the bot closes any OPEN
# report listed here - no manual /bugreport close and no DB round-trip.
# Append entries when a fix ships; idempotent by construction.
FIXED_BUG_REPORTS: dict[int, str] = {}

# Recommended max-output-token budget for the structured finance analysis mode.
# DeepSeek-V4-Pro spends 600-1200 tokens on reasoning before the JSON output, so
# the analysis/decision/trade_plan schemas need headroom to avoid mid-output
# truncation (which breaks _parse_finance_payload). 2000 was too tight and caused
# repeated finance_json_parse_failed.
FINANCE_RECOMMENDED_MAX_TOKENS = 6000


@dataclass(frozen=True)
class CommandResult:
    handled: bool
    reply: str = ""


class CommandProcessor:
    def __init__(
        self,
        config: AppConfig,
        db: Database,
        memory: MemoryStore,
        config_path: str = "config.yaml",
        prompt_path: str = "PROMPT.md",
        llm: Any | None = None,
        skills: SkillRegistry | None = None,
        fortune: LocalFortuneTool | None = None,
        games: MiniGameTool | None = None,
        weather: OpenMeteoWeatherTool | None = None,
        auth: AuthService | None = None,
    ) -> None:
        self.config = config
        self.auth = auth if auth is not None else AuthService(config, db=db, config_path=config_path)
        self.db = db
        self.memory = memory
        self.config_path = config_path
        self.prompt_path = Path(prompt_path)
        self.llm = llm
        self.skills = skills or SkillRegistry(Path("skills"))
        self.fortune = fortune or LocalFortuneTool()
        self.games = games or MiniGameTool()
        self.weather = weather or OpenMeteoWeatherTool()

    def handle(
        self,
        text: str,
        chat_id: str,
        is_group: bool,
        is_admin: bool,
        sender_id: str = "",
    ) -> CommandResult:
        if not text.startswith("/"):
            return CommandResult(False)

        parts = text.strip().split()
        cmd = parts[0].lower()

        public_commands = {"/dice", "/rps"}
        public_game_status = cmd == "/game" and (len(parts) < 2 or parts[1].lower() in {"status", "show"})

        if not is_admin and (cmd in public_commands or public_game_status):
            if cmd == "/dice":
                return CommandResult(True, self._dice(parts))
            if cmd == "/rps":
                return CommandResult(True, self._rps(parts))
            if cmd == "/game":
                return self._game_mode(chat_id, parts, sender_id=sender_id, is_admin=False)

        if not is_admin:
            return CommandResult(True)

        if cmd in {"/tier", "/servicetier", "/service-tier"}:
            return CommandResult(True, self._service_tier(chat_id, parts))
        if cmd == "/help":
            return CommandResult(True, self._help())
        if cmd == "/whoami":
            scope = "群聊" if is_group else "私聊"
            return CommandResult(True, f"{scope}\nsender: {sender_id}\nchat: {chat_id}")
        if cmd == "/version":
            return CommandResult(True, self._version())
        if cmd in {"/gset", "/groupset", "/roomset"}:
            return self._group_delegate(text, parts, sender_id)
        if cmd in {"/groups", "/rooms"}:
            return CommandResult(True, self._groups(parts))
        if cmd == "/skills":
            return CommandResult(True, self._skills(parts))
        if cmd == "/fortune":
            return CommandResult(True, self._fortune(parts))
        if cmd == "/weather":
            return CommandResult(True, self._weather(parts))
        if cmd == "/dice":
            return CommandResult(True, self._dice(parts))
        if cmd == "/rps":
            return CommandResult(True, self._rps(parts))
        if cmd == "/game":
            return self._game_mode(chat_id, parts, sender_id=sender_id, is_admin=is_admin)
        if cmd == "/schedule":
            return CommandResult(True, self._schedule(chat_id, text, parts, sender_id))
        if cmd in {"/accounting", "/accouting"}:
            return CommandResult(True, self._accounting(chat_id, text, parts, sender_id))
        if cmd == "/bugreport":
            return CommandResult(True, self._bugreport(chat_id, text, parts, sender_id))
        if cmd in {"/tokens", "/token", "/tokenusage", "/usage"}:
            return CommandResult(True, self._tokens(chat_id, parts))
        if cmd == "/memberlog":
            return CommandResult(True, self._memberlog(chat_id, parts))
        if cmd == "/chatlog":
            return CommandResult(True, self._chatlog_analyze(chat_id, parts))
        if cmd == "/status":
            return CommandResult(True, self._status(chat_id))
        if cmd == "/bot" and len(parts) >= 2:
            if parts[1].lower() in {"global", "all"}:
                return self._bot_global(parts)
            enabled = parts[1].lower() == "on"
            self._ensure_group(chat_id)
            self._update_group(chat_id, enabled=int(enabled))
            if enabled and not self.db.get_setting("global_bot_enabled", True):
                self.db.set_setting(f"group_global_override:{chat_id}", True)
            elif not enabled:
                self.db.set_setting(f"group_global_override:{chat_id}", False)
            return CommandResult(True, "已开启。" if enabled else "已关闭。")
        if cmd == "/mode":
            return self._mode(chat_id, parts)
        if cmd == "/style" and len(parts) == 1:
            return CommandResult(True, style_help())
        if cmd == "/style" and len(parts) >= 2:
            if parts[1].lower() in {"help", "list", "options"}:
                return CommandResult(True, style_help())
            style, error = parse_style_tokens(parts[1:])
            if style is None:
                return CommandResult(True, error)
            self.db.set_setting(f"group_style:{chat_id}", style.storage_value)
            return CommandResult(True, f"style set to {style.display_value}.")
        if cmd == "/blacklist":
            return self._blacklist(chat_id, parts)
        if cmd in {"/target", "/targets", "/targetlist", "/target_list"}:
            return self._target_list(chat_id, parts)
        if cmd == "/whitelist":
            return self._whitelist(parts)
        if cmd == "/delay":
            return self._delay(chat_id, parts)
        if cmd == "/memory":
            return self._memory(chat_id, parts, is_admin, sender_id)
        if cmd in {"/prompt", "/propmt"}:
            return self._prompt(chat_id, text, parts)
        if cmd == "/vision":
            return self._vision(chat_id, parts)
        if cmd in {"/search", "/docs"} and len(parts) >= 2:
            field = {"/search": "web_search_enabled", "/docs": "doc_enabled"}[cmd]
            enabled = parts[1].lower() == "on"
            self._ensure_group(chat_id)
            self._update_group(chat_id, **{field: int(enabled)})
            return CommandResult(True, "已开启。" if enabled else "已关闭。")
        if cmd == "/length":
            return self._length(chat_id, parts)
        if cmd == "/context":
            return self._context(chat_id, parts)
        if cmd == "/limit":
            return self._limit(parts)
        if cmd == "/cooldown":
            return self._cooldown(chat_id, parts)
        if cmd in {"/reply", "/replymode", "/reply_mode"}:
            return self._reply_policy(chat_id, parts)
        if cmd in {"/replygate", "/gate", "/reply_gate"}:
            return self._reply_gate(chat_id, parts)
        if cmd in {"/test", "/testing"}:
            return self._testing_mode(chat_id, parts)
        if cmd == "/model":
            return self._model(chat_id, parts)
        if cmd == "/finance":
            return self._finance(chat_id, text, parts)
        if cmd in {"/tasks", "/task", "/agenttask"}:
            return self._agent_tasks(chat_id, parts)
        if cmd in {"/financecalc", "/finance-calc", "/calculation"}:
            return self._finance_calculation(chat_id, parts)
        if cmd in {"/reasoning", "/reason"}:
            return self._reasoning(chat_id, parts)
        if cmd == "/router":
            return self._router(chat_id, parts)
        if cmd == "/set" and len(parts) >= 2:
            return self._set(chat_id, text, parts, sender_id)

        return CommandResult(True, "没识别这个命令。发 /help 看可用命令。")

    def _group_delegate(self, text: str, parts: list[str], sender_id: str) -> CommandResult:
        if len(parts) < 3:
            return CommandResult(True, "用法：/gset <群ID|别名|短码> <slash command>。例如：/gset 1 /status 或 /gset 示例帮会群 /status（短码见 /groups）")
        target_chat_id = self._resolve_group_id(parts[1].strip())
        nested = text.split(maxsplit=2)[2].strip() if len(text.split(maxsplit=2)) >= 3 else ""
        if not target_chat_id:
            return CommandResult(True, "缺少或找不到 chatroom_id。私聊发 /groups 可以列出已知群。")
        if not nested:
            return CommandResult(True, "缺少要执行的命令。例如：/gset 123@chatroom /prompt roast")
        if not nested.startswith("/"):
            nested = "/set " + nested
        nested_cmd = nested.split(maxsplit=1)[0].lower()
        if nested_cmd in {"/gset", "/groupset", "/roomset", "/whitelist"}:
            return CommandResult(True, "这个命令不能通过 /gset 转发。")
        result = self.handle(nested, target_chat_id, True, True, sender_id=sender_id)
        if result.reply:
            return CommandResult(True, f"target: {target_chat_id}\n{result.reply}")
        return result

    def _groups(self, parts: list[str] | None = None) -> str:
        parts = parts or []
        verbose = len(parts) >= 2 and parts[1].lower() in {"verbose", "detail", "details", "full"}
        if len(parts) >= 2 and parts[1].lower() in {"name", "alias", "rename"}:
            if len(parts) < 4:
                return "usage: /groups name <chatroom_id> <name>"
            chat_id = self._resolve_group_id(parts[2].strip()) or parts[2].strip()
            if not chat_id.endswith("@chatroom"):
                return "invalid chatroom_id"
            alias = " ".join(parts[3:]).strip()[:80]
            if not alias:
                return "missing group alias"
            self._set_group_alias(chat_id, alias)
            return f"alias set: {alias} = {chat_id}"
        if len(parts) >= 2 and parts[1].lower() in {"clear", "unalias"}:
            if len(parts) < 3:
                return "usage: /groups clear <chatroom_id>"
            chat_id = self._resolve_group_id(parts[2].strip()) or parts[2].strip()
            self._set_group_alias(chat_id, "")
            return f"alias cleared: {chat_id}"

        rows = self._known_groups(50)
        if not rows:
            return "no known groups yet. let the bot receive group messages first, then run /groups again."
        self._ensure_group_codes()
        lines = ["known groups:"]
        for row in rows:
            group_id = row["chat_id"]
            alias = row.get("alias") or ""
            mode = row["mode"] or "unknown"
            enabled = "on" if row["enabled"] is None or row["enabled"] else "off"
            updated_at = row["last_seen_at"] or row.get("alias_last_seen_at") or row["updated_at"] or ""
            last_sender = row.get("last_sender") or ""
            last_message = row.get("last_message") or ""
            code = self.db.get_setting(f"group_code:{group_id}", "")
            tag = f"[{code}] " if code else ""
            display = f"{tag}{alias} | {group_id}" if alias else f"{tag}{group_id}"
            line = f"{display} | bot {enabled} | mode {mode}"
            if verbose:
                line += f" | seen {updated_at}"
                if last_sender or last_message:
                    line += f" | recent: {last_sender}: {last_message}"
            lines.append(line)
        lines.append("tip: /groups verbose | /groups name <id> <name> | /gset <id> <cmd>")
        return "\n".join(lines)

    def _known_groups(self, limit: int = 50) -> list[dict[str, object]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                WITH known(chat_id, last_seen_at) AS (
                    SELECT group_id, updated_at FROM groups WHERE group_id LIKE '%@chatroom'
                    UNION
                    SELECT chat_id, MAX(created_at) FROM messages WHERE chat_id LIKE '%@chatroom' GROUP BY chat_id
                    UNION
                    SELECT chat_id, MAX(created_at) FROM chat_events WHERE chat_id LIKE '%@chatroom' GROUP BY chat_id
                    UNION
                    SELECT chat_id, last_seen_at FROM group_aliases WHERE chat_id LIKE '%@chatroom'
                )
                SELECT known.chat_id, MAX(known.last_seen_at) AS last_seen_at,
                       groups.updated_at, groups.enabled, groups.mode,
                       group_aliases.alias, group_aliases.last_sender, group_aliases.last_message,
                       group_aliases.last_seen_at AS alias_last_seen_at
                FROM known
                LEFT JOIN groups ON groups.group_id = known.chat_id
                LEFT JOIN group_aliases ON group_aliases.chat_id = known.chat_id
                GROUP BY known.chat_id
                ORDER BY COALESCE(MAX(known.last_seen_at), group_aliases.last_seen_at, groups.updated_at, '') DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _set_group_alias(self, chat_id: str, alias: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO group_aliases(chat_id, alias, last_sender, last_message, last_seen_at)
                VALUES(?, ?, COALESCE((SELECT last_sender FROM group_aliases WHERE chat_id = ?), ''),
                        COALESCE((SELECT last_message FROM group_aliases WHERE chat_id = ?), ''), ?)
                ON CONFLICT(chat_id) DO UPDATE SET alias = excluded.alias, last_seen_at = excluded.last_seen_at
                """,
                (chat_id, alias, chat_id, chat_id, utc_now()),
            )

    def _resolve_group_id(self, value: str) -> str:
        """Resolve a /gset target: id@chatroom, exact alias, short code
        ("/gset 1 /status"), unique alias prefix, or unique id prefix."""
        value = (value or "").strip()
        if not value:
            return ""
        match = re.search(r"([A-Za-z0-9_-]+@chatroom)", value)
        if match:
            return match.group(1)
        rows = self._known_groups(200)
        by_id = {str(row["chat_id"]): row for row in rows}
        # exact alias
        lowered = value.lower()
        for row in rows:
            if str(row.get("alias") or "").strip().lower() == lowered:
                return str(row["chat_id"])
        # pure digits: short code first (avoids id-prefix ambiguity)
        if value.isdigit():
            chat_id = str(self.db.get_setting(f"group_code_chat:{value}", "") or "")
            if chat_id in by_id:
                return chat_id
        # unique alias prefix ("示例" -> "示例帮会群")
        alias_prefix = [
            str(row["chat_id"])
            for row in rows
            if str(row.get("alias") or "").strip() and str(row.get("alias") or "").strip().lower().startswith(lowered)
        ]
        if len(alias_prefix) == 1:
            return alias_prefix[0]
        # unique chat-id prefix (legacy behavior)
        matches = [str(row["chat_id"]) for row in rows if str(row["chat_id"]).startswith(value)]
        return matches[0] if len(matches) == 1 else ""

    def _ensure_group_codes(self) -> None:
        """Assign a stable short code to every known group that lacks one."""
        rows = self._known_groups(200)
        with self.db.connect() as conn:
            used = {
                int(row["value"])
                for row in conn.execute(
                    "SELECT value FROM settings WHERE key LIKE 'group_code:%'"
                ).fetchall()
                if str(row["value"] or "").isdigit()
            }
        next_code = (max(used) + 1) if used else 1
        for row in rows:
            chat_id = str(row["chat_id"])
            if self.db.get_setting(f"group_code:{chat_id}", None) is not None:
                continue
            while next_code in used:
                next_code += 1
            self.db.set_setting(f"group_code:{chat_id}", next_code)
            self.db.set_setting(f"group_code_chat:{next_code}", chat_id)
            used.add(next_code)
            next_code += 1

    def apply_deployed_bug_fixes(self) -> list[int]:
        """Startup reconciliation: close bug reports fixed by deployed code,
        and make sure every known group has a short code."""
        try:
            self._ensure_group_codes()
        except Exception:
            logging.getLogger("foxstar_bot.commands").exception("group code assignment failed")
        try:
            closed = self.db.close_bug_reports_auto(sorted(FIXED_BUG_REPORTS))
            if closed:
                logging.getLogger("foxstar_bot.commands").info(
                    "bug_reports_auto_closed ids=%s", closed
                )
            return closed
        except Exception:
            logging.getLogger("foxstar_bot.commands").exception("auto bug close failed")
            return []

    @staticmethod
    def _help() -> str:
        return (
            "/whoami\n/version\n/status\n/bot on|off\n/bot global on|off\n/mode list|status|load <name>\n"
            "/style strict|human|free [mbti] [zodiac] [traits]\n/blacklist add|remove|list|clear <wxid>\n"
            "/target add|remove|list|clear <wxid>\n/whitelist add|remove|list <wxid>\n/delay <min> <max> [between]\n/length <tokens>|clear\n/context <messages>|clear\n/limit <wxid> <num>|clear\n/limit global <num>|clear\n/cooldown <seconds>|clear\n/reply auto|direct\n/replygate strict|normal|soft [default|guild|social|tech|debate]\n/test on|off\n/model <model>|clear\n/model provider auto|openai|openrouter|deepseek|together|lightning|minimax|bedrock|sambanova|fireworks\n/model openrouter|together|lightning|minimax|bedrock <model>\n/reasoning none|minimal|low|medium|high|max|clear\n/router on|off\n/memory show|remember|set|delete|clear\n/prompt list|use|custom|show|clear\n/search on|off\n"
            "/vision on|off|status\n/vision mode tool|native|clear\n/docs on|off\n/idlookup\n/recall [num]\n/groups\n/set prefix <value>\n/set line_tokens <tokens>|clear\n/set <plain text setting instruction>\n"
            "/gset <chatroom_id> <slash command>\n/skills [show <name>]\n/tokens [today|7d|30d|all|clear]\n"
            "/memberlog [today|7d|30d|all]\n/chatlog analyze [count]\n"
            "/fortune [all|star|huangli|divination] [sign]\n/weather <location>\n"
            "/dice [count] [sides]\n/rps <rock|paper|scissors|石头|布|剪刀>\n/game start <dice|rps|chengyu|riddle|brain_teaser>\n/game status|end\n"
            "/schedule list|clear|remove <id>\n/schedule <cron(5 fields)> <slash command or prompt>\n/schedule in <duration> <slash command or prompt>\n"
            "/accounting <name> <amount> <description>\n/accounting owe <name> <amount> <description> [cleared]\n/accounting lookup [1m|3m|1y|all]\n/accounting owe lookup [1m|3m|1y|all]"
            "\n/bugreport <description>\n/bugreport list|all|close <id>|reopen <id>"
            "\n—— Example clan ——\n/jielong [status|submit|resubmit|log|cancel]  (quote a jielong + submit = import that one)\n/battle <paste battle CSV>\n/roster [refresh]\n/attendance [days]\n/activity new <name>|list  (name defaults to the tracked jielong title)\n/tier [default|flex|priority|ultrafast|clear]  (per-group OpenRouter service tier)"
        )

    def _service_tier(self, chat_id: str, parts: list[str]) -> str:
        key = f"group_service_tier:{chat_id}"
        valid = {"default", "flex", "priority", "ultrafast"}
        current = str(self.db.get_setting(key, "") or "")
        if len(parts) < 2 or parts[1].lower() in {"status", "show"}:
            shown = current or "default (未设置)"
            return (
                f"OpenRouter service tier: {shown}\n"
                "可选: default | flex | priority | ultrafast\n"
                "/tier ultrafast 设置本群 tier（按实际服务的 tier 计费）"
            )
        value = parts[1].lower()
        if value in {"clear", "off", "reset"}:
            self.db.set_setting(key, "")
            return "service tier 已清除（恢复 default）"
        if value not in valid:
            return f"未知 tier: {value}（可选 default | flex | priority | ultrafast）"
        self.db.set_setting(key, value)
        note = ""
        if value == "ultrafast":
            note = "\n注: 仅部分 OpenAI 模型支持，不支持时自动按 priority 结算"
        elif value == "flex":
            note = "\n注: 更便宜但延迟更高，容量不足时不回退"
        return f"service tier = {value}{note}"

    def _version(self) -> str:
        version_path = Path(self.config_path).resolve().parent / "VERSION"
        try:
            value = version_path.read_text(encoding="utf-8").strip()
        except Exception:
            value = ""
        return value or "unknown"

    def _status(self, chat_id: str) -> str:
        self._ensure_group(chat_id)
        group = self._get_group(chat_id)
        if not group:
            return "当前使用默认配置，bot 开启。"
        style = self.db.get_setting(f"group_style:{chat_id}", "strict")
        global_enabled = self.db.get_setting("global_bot_enabled", True)
        global_override = self.db.get_setting(f"group_global_override:{chat_id}", False)
        delay = self._group_delay(chat_id)
        active_game = self.db.get_setting(f"group_active_game:{chat_id}", {})
        if isinstance(active_game, dict) and active_game:
            game_status = f"active:{active_game.get('type', 'unknown')}"
        else:
            game_status = "off"
        return (
            f"global_bot: {'on' if global_enabled else 'off'}\n"
            f"global_override: {'on' if global_override else 'off'}\n"
            f"bot: {'on' if group['enabled'] else 'off'}\n"
            f"mode: {group['mode']}\n"
            f"loaded_mode: {self._loaded_mode(chat_id, str(group['mode']))}\n"
            f"finance_mode: {'on' if self.db.get_setting(f'group_finance_enabled:{chat_id}', False) else 'off'}\n"
            f"finance_calculation_mode: {'on' if self.db.get_setting(f'group_finance_calculation_enabled:{chat_id}', False) else 'off'}\n"
            f"style: {style}\n"
            f"model: {self.db.get_setting(f'group_reply_model:{chat_id}', 'default') or 'default'}\n"
            f"model_provider: {self.db.get_setting(f'group_model_provider:{chat_id}', 'default') or 'default'}\n"
            f"image_analysis_mode: {self.db.get_setting(f'group_image_analysis_mode:{chat_id}', self.config.model.image_analysis_mode) or self.config.model.image_analysis_mode}\n"
            f"reasoning: {self.db.get_setting(f'group_reasoning_effort:{chat_id}', 'default') or 'default'}\n"
            f"router: {'on' if self.db.get_setting(f'group_model_router_enabled:{chat_id}', self.config.model_router.enabled) else 'off'}\n"
            f"reply: {self.db.get_setting(f'group_reply_policy:{chat_id}', 'auto')}\n"
            f"replygate: {self.db.get_setting(f'group_reply_gate_mode:{chat_id}', 'normal')} / {self.db.get_setting(f'group_reply_gate_vibe:{chat_id}', 'default')}\n"
            f"testing_mode: {'on' if self.db.get_setting(f'group_testing_mode:{chat_id}', False) else 'off'}\n"
            f"game_mode: {game_status}\n"
            f"length_tokens: {self.db.get_setting(f'group_max_reply_tokens:{chat_id}', 'default')}\n"
            f"context_messages: {self.db.get_setting(f'group_context_messages:{chat_id}', DEFAULT_CONTEXT_MESSAGES)}\n"
            f"user_limit_global: {self.db.get_setting('global_user_daily_limit', 0) or 'default'}\n"
            f"line_tokens: {self.db.get_setting(f'group_reply_line_tokens:{chat_id}', 'default')}\n"
            f"cooldown: {self.db.get_setting(f'group_api_cooldown_seconds:{chat_id}', 0)}s\n"
            f"blacklist: {len(self._blacklist_users(chat_id))}\n"
            f"targets: {len(self._target_users(chat_id))}\n"
            f"delay: {delay['min']:g}-{delay['max']:g}s, between {delay['between']:g}s\n"
            f"prefix: {group['prefix'] or self.config.trigger_prefix}\n"
            f"search/docs/vision: {group['web_search_enabled']}/{group['doc_enabled']}/{group['vision_enabled']}"
        )

    def _memberlog(self, chat_id: str, parts: list[str]) -> str:
        # approve/reject pending member snapshot anomalies (owner decides
        # whether a large roster change is real or WCF garbage)
        if len(parts) >= 2 and parts[1].lower() in {"approve", "reject", "deny"}:
            pending = self.db.get_setting(f"group_member_anomaly_pending:{chat_id}", None)
            if not pending:
                return "no pending member snapshot anomaly for this group."
            if parts[1].lower() == "approve":
                members = pending.get("members") or {}
                joined = pending.get("joined") or []
                with self.db.connect() as conn:
                    conn.execute("DELETE FROM group_member_snapshots WHERE chat_id = ?", (chat_id,))
                    conn.executemany(
                        "INSERT INTO group_member_snapshots(chat_id, user_id, display_name, updated_at) VALUES(?, ?, ?, ?)",
                        [(chat_id, str(uid), str(name), utc_now()) for uid, name in members.items()],
                    )
                    for item in joined:
                        conn.execute(
                            "INSERT INTO chat_events(chat_id, event_type, user_id, display_name, raw_content, created_at) VALUES(?, 'joined', ?, ?, ?, ?)",
                            (chat_id, str(item.get("user_id", "")), str(item.get("display_name", "")), f"[approved anomaly] {item.get('display_name', '')} joined", utc_now()),
                        )
                self.db.set_setting(f"group_member_anomaly_pending:{chat_id}", None)
                self.db.set_setting(f"group_member_anomaly_strikes:{chat_id}", 0)
                return f"✅ approved: snapshot updated to {len(members)} members, {len(joined)} join events recorded."
            # reject: discard the pending candidate, keep old snapshot
            self.db.set_setting(f"group_member_anomaly_pending:{chat_id}", None)
            self.db.set_setting(f"group_member_anomaly_strikes:{chat_id}", 0)
            return "❌ rejected: pending snapshot discarded, original roster kept."

        window = "today"
        if len(parts) >= 2:
            window = parts[1].strip().lower()
        days_map = {"today": 1, "1d": 1, "7d": 7, "week": 7, "30d": 30, "month": 30, "all": None}
        days = days_map.get(window)
        if window not in days_map:
            return "usage: /memberlog [today|7d|30d|all]"
        events = self.db.recent_chat_events(chat_id, limit=None, days=days)
        if not events:
            return f"member log ({window}): none"
        joined = sum(1 for item in events if item["event_type"] == "joined")
        left = sum(1 for item in events if item["event_type"] == "left")
        lines = [f"member log ({window}):", f"joined: {joined}", f"left: {left}", f"total events: {len(events)}", "recent events:"]
        for item in reversed(events[:100]):
            label = item.get("display_name") or item.get("user_id") or item.get("raw_content") or ""
            lines.append(f"- {item['created_at']} {item['event_type']}: {label}")
        return "\n".join(lines)

    def _chatlog_analyze(self, chat_id: str, parts: list[str]) -> str:
        if self.llm is None:
            return "chatlog analyze is unavailable: llm not configured."
        if len(parts) < 2 or parts[1].lower() != "analyze":
            return "usage: /chatlog analyze [count]"
        count = 120
        if len(parts) >= 3:
            try:
                count = int(parts[2])
            except ValueError:
                return "count must be an integer, e.g. /chatlog analyze 150"
        count = max(20, min(count, 300))
        rows = self.db.recent_messages(chat_id, limit=count)
        if not rows:
            return "chatlog analyze: no stored messages for this chat."
        lines: list[str] = []
        for row in reversed(rows):
            role = "bot" if row["role"] == "assistant" else str(row["user_id"] or "user")
            content = " ".join(str(row["content"] or "").split())
            if len(content) > 300:
                content = content[:300].rstrip() + "..."
            lines.append(f"[{row['created_at']}] {role}: {content}")
        transcript = "\n".join(lines)
        provider = str(self.db.get_setting(f"group_model_provider:{chat_id}", self.config.model.provider or "auto") or "auto")
        model = str(self.db.get_setting(f"group_reply_model:{chat_id}", self.config.model.name) or self.config.model.name)
        reasoning = str(self.db.get_setting(f"group_reasoning_effort:{chat_id}", self.config.model.reasoning_effort) or self.config.model.reasoning_effort)
        messages = [
            {
                "role": "system",
                "content": (
                    "Analyze the provided WeChat group chat history. "
                    "Produce a concise, concrete summary with: "
                    "1) main topics, 2) notable decisions or outcomes, 3) key participants and their roles in the discussion, "
                    "4) tone/dynamics, 5) unresolved follow-ups. "
                    "Do not invent facts not present in the transcript."
                ),
            },
            {
                "role": "user",
                "content": f"Analyze the latest {len(rows)} stored chat messages from this group:\n\n{transcript}",
            },
        ]
        try:
            reply = self.llm.chat(
                messages,
                max_completion_tokens=1600,
                model=model,
                provider=provider,
                reasoning_effort=reasoning,
                usage_context={"chat_id": chat_id, "feature": "chatlog_analyze"},
            )
        except Exception as exc:
            return f"chatlog analyze failed: {exc}"
        return reply.strip() or "chatlog analyze produced no output."

    def _tokens(self, chat_id: str, parts: list[str]) -> str:
        window = "7d"
        if len(parts) >= 2:
            window = parts[1].strip().lower()
        if window == "clear":
            self.db.clear_token_usage(chat_id)
            return "token usage cleared for current chat."
        days_map = {"today": 1, "1d": 1, "7d": 7, "week": 7, "30d": 30, "month": 30, "all": None}
        days = days_map.get(window)
        if window not in days_map:
            return "usage: /tokens [today|7d|30d|all|clear]"
        summary = self.db.token_usage_summary(chat_id, days=days)
        label = "all" if days is None else window
        lines = [
            f"token usage ({label}):",
            f"requests: {summary['requests']}",
            f"input_tokens: {summary['input_tokens']}",
            f"output_tokens: {summary['output_tokens']}",
            f"cached_tokens: {summary['cached_tokens']}",
        ]
        features = summary.get("by_feature", [])
        if features:
            lines.append("by feature:")
            for row in features[:8]:
                lines.append(
                    f"- {row['feature']}: req={row['requests']} in={row['input_tokens']} out={row['output_tokens']} cached={row['cached_tokens']}"
                )
        models = summary.get("by_model", [])
        if models:
            lines.append("by model:")
            for row in models[:8]:
                lines.append(
                    f"- {row['provider']}/{row['model']}: req={row['requests']} in={row['input_tokens']} out={row['output_tokens']} cached={row['cached_tokens']}"
                )
        return "\n".join(lines)

    def _skills(self, parts: list[str]) -> str:
        if len(parts) >= 2 and parts[1].lower() == "show":
            if len(parts) < 3:
                return "usage: /skills show <name>"
            skill = self.skills.get_skill(parts[2])
            if skill is None:
                return f"skill not found: {parts[2]}"
            content = self.skills.load_skill(skill.name, max_chars=6000)
            return f"{skill.name}\n{skill.path.as_posix()}\n\n{content}"

        if len(parts) >= 2:
            found = self.skills.search_skills(" ".join(parts[1:]), max_results=12)
        else:
            found = self.skills.list_skills()
        if not found:
            return "no skills found."
        lines = ["skills:"]
        for skill in found:
            summary = skill.summary[:120] if skill.summary else ""
            detail = f" - {summary}" if summary else ""
            lines.append(f"{skill.name}{detail}")
        lines.append("tip: /skills show <name>")
        return "\n".join(lines)

    def _fortune(self, parts: list[str]) -> str:
        if len(parts) >= 2 and parts[1].lower() in {"help", "?"}:
            return (
                "usage:\n"
                "/fortune\n"
                "/fortune all [sign]\n"
                "/fortune star|constellation [sign]\n"
                "/fortune huangli\n"
                "/fortune divination\n"
                "examples:\n"
                "/fortune\n"
                "/fortune star 白羊\n"
                "/fortune constellation aries\n"
                "/fortune huangli"
            )
        mode = parts[1].lower() if len(parts) >= 2 else "all"
        sign = " ".join(parts[2:]).strip() if len(parts) >= 3 else ""
        try:
            result = self.fortune.get_fortune(mode=mode, sign=sign)
        except Exception as exc:
            return f"fortune failed: {exc}"
        return result.content

    def _weather(self, parts: list[str]) -> str:
        if len(parts) < 2:
            return "usage: /weather <location>"
        location = " ".join(parts[1:]).strip()
        try:
            result = self.weather.fetch_weather(location)
        except Exception as exc:
            return f"weather failed: {exc}"
        place = result.location_name
        if result.admin1:
            place = f"{place}, {result.admin1}"
        if result.country:
            place = f"{place}, {result.country}"
        return (
            f"天气：{place}\n"
            f"现温 {result.temperature_c:.1f}°C / 体感 {result.apparent_temperature_c:.1f}°C\n"
            f"{result.weather_text} | 湿度 {result.humidity_percent:.0f}% | 云量 {result.cloud_cover_percent:.0f}%\n"
            f"风 {result.wind_speed_kmh:.1f} km/h | 阵风 {result.wind_gusts_kmh:.1f} km/h\n"
            f"降水 {result.precipitation_mm:.1f} mm | 气压 {result.pressure_msl_hpa:.1f} hPa\n"
            f"今日高低温 {result.today_max_c:.1f}/{result.today_min_c:.1f}°C"
        )

    def _dice(self, parts: list[str]) -> str:
        count = 1
        sides = 6
        if len(parts) >= 2:
            try:
                count = int(parts[1])
            except ValueError:
                return "usage: /dice [count] [sides]"
        if len(parts) >= 3:
            try:
                sides = int(parts[2])
            except ValueError:
                return "usage: /dice [count] [sides]"
        result = self.games.roll_dice(count=count, sides=sides)
        return f"🎲 d{result.sides} x{result.count}: {', '.join(str(x) for x in result.rolls)} | total={result.total}"

    def _rps(self, parts: list[str]) -> str:
        if len(parts) < 2:
            return "usage: /rps <rock|paper|scissors|石头|布|剪刀>"
        try:
            result = self.games.play_rps(parts[1])
        except Exception as exc:
            return str(exc)
        outcome_map = {"win": "你赢了", "lose": "你输了", "draw": "平局"}
        return f"✂️ 你出 {RPS_DISPLAY[result.player_choice]}，我出 {RPS_DISPLAY[result.bot_choice]}：{outcome_map[result.outcome]}"

    def _game_mode(self, chat_id: str, parts: list[str], sender_id: str = "", is_admin: bool = False) -> CommandResult:
        session = self.db.get_setting(f"group_active_game:{chat_id}", {})
        if not isinstance(session, dict):
            session = {}
        action = parts[1].lower() if len(parts) >= 2 else "status"
        if action in {"status", "show"}:
            if not session:
                return CommandResult(True, "game: none")
            game_type = str(session.get("type") or "unknown")
            turns = int(session.get("turn_count") or session.get("round") or 0)
            return CommandResult(True, f"game: active | type={game_type} | turns={turns}")
        if action == "start":
            if not is_admin:
                return CommandResult(True, "only admin can start game mode.")
            if len(parts) < 3:
                return CommandResult(True, "usage: /game start <dice|rps|chengyu|riddle|brain_teaser|quiz_common|quiz_ai|quiz_nsh>")
            game_name = parts[2].strip().lower()
            if game_name not in {"dice", "rps", "chengyu", "riddle", "brain_teaser", "quiz_common", "quiz_ai", "quiz_nsh"}:
                return CommandResult(True, "game must be one of: dice, rps, chengyu, riddle, brain_teaser, quiz_common, quiz_ai, quiz_nsh")
            if session:
                return CommandResult(True, f"game already active: {session.get('type', 'unknown')}")
            reply = self._start_game_session(chat_id, sender_id=sender_id, game_name=game_name)
            GAME_LOG.info("game_started chat=%s sender=%s game=%s mode=slash intro=%r state=%s", chat_id, sender_id, game_name, reply[:300], json.dumps(self.db.get_setting(f'group_active_game:{chat_id}', {}), ensure_ascii=False)[:1200])
            return CommandResult(True, reply)
        if action == "end":
            if session:
                GAME_LOG.info("game_ended chat=%s sender=%s type=%s reason=slash_end scores=%s state=%s", chat_id, sender_id, str(session.get("type") or ""), json.dumps(session.get("scores", {}), ensure_ascii=False), json.dumps(session, ensure_ascii=False)[:1200])
            self.db.set_setting(f"group_active_game:{chat_id}", {})
            return CommandResult(True, "game ended.")
        return CommandResult(True, "usage: /game start <dice|rps|chengyu|riddle|brain_teaser|quiz_common|quiz_ai|quiz_nsh> | /game status | /game end")

    def _start_game_session(self, chat_id: str, sender_id: str, game_name: str) -> str:
        if game_name == "dice":
            self.db.set_setting(
                f"group_active_game:{chat_id}",
                {
                    "type": "dice",
                    "player_id": sender_id,
                    "player_name": sender_id or "player",
                    "round": 0,
                    "player_wins": 0,
                    "bot_wins": 0,
                    "draws": 0,
                    "target_wins": 3,
                    "max_rounds": 5,
                },
            )
            return "骰子游戏开始。五局三胜。玩家每回合发“骰子”/“继续”/“roll”推进下一局。"
        if game_name == "rps":
            self.db.set_setting(
                f"group_active_game:{chat_id}",
                {
                    "type": "rps",
                    "player_id": sender_id,
                    "player_name": sender_id or "player",
                    "round": 0,
                    "player_wins": 0,
                    "bot_wins": 0,
                    "draws": 0,
                    "target_wins": 3,
                    "max_rounds": 5,
                },
            )
            return "剪刀石头布开始。五局三胜。每回合发 石头/布/剪刀 即可。"
        if game_name == "chengyu":
            opening = self.games.pick_chengyu_opening(lookahead=3)
            self.db.set_setting(
                f"group_active_game:{chat_id}",
                {
                    "type": "chengyu",
                    "turn_count": 0,
                    "max_turns": 20,
                    "scores": {},
                    "used": [opening],
                    "last_char": opening[-1],
                    "ai_last_idiom": opening,
                },
            )
            return f"成语抢答开始。GM 先出：{opening}。请抢答以“{opening[-1]}”开头的四字词语。共 20 分。"
        if game_name == "brain_teaser":
            prompts = self.games.pick_brain_teasers(10)
            payload = [{"question": item.question, "answers": list(item.answers)} for item in prompts]
            self.db.set_setting(
                f"group_active_game:{chat_id}",
                {
                    "type": "brain_teaser",
                    "round": 1,
                    "max_rounds": len(payload),
                    "scores": {},
                    "riddles": payload,
                    "current_index": 0,
                },
            )
            return f"脑筋急转弯开始。共 {len(payload)} 题，抢答制。\n第1题：{payload[0]['question']}"
        if game_name in {"quiz_common", "quiz_ai", "quiz_nsh"}:
            category = game_name.split("_", 1)[1]
            questions = self.games.pick_quiz_questions(category, 10)
            payload = [
                {"question": item.question, "answers": list(item.answers), "explanation": item.explanation}
                for item in questions
            ]
            labels = {"common": "常识问答", "ai": "AI基础知识问答", "nsh": "逆水寒问答"}
            self.db.set_setting(
                f"group_active_game:{chat_id}",
                {
                    "type": "quiz",
                    "category": category,
                    "round": 1,
                    "max_rounds": len(payload),
                    "scores": {},
                    "questions": payload,
                    "current_index": 0,
                },
            )
            return f"{labels.get(category, '问答')}开始。共 {len(payload)} 题，抢答制。\n第1题：{payload[0]['question']}"
        riddles = self.games.pick_riddles(10)
        payload = [{"question": item.question, "answers": list(item.answers)} for item in riddles]
        self.db.set_setting(
            f"group_active_game:{chat_id}",
            {
                "type": "riddle",
                "round": 1,
                "max_rounds": len(payload),
                "scores": {},
                "riddles": payload,
                "current_index": 0,
            },
        )
        return f"灯谜游戏开始。共 {len(payload)} 题，谁先答对谁得分。\n第1题：{payload[0]['question']}"

    def _schedule(self, chat_id: str, text: str, parts: list[str], sender_id: str = "") -> str:
        if len(parts) == 1 or parts[1].lower() in {"help", "?"}:
            return (
                "usage:\n"
                "/schedule list\n"
                "/schedule clear\n"
                "/schedule remove <id>\n"
                "/schedule <cron(5 fields)> <slash command or prompt>\n"
                "/schedule in <duration> <slash command or prompt>\n"
                "examples:\n"
                "/schedule 0 8 * * * /chatlog analyze 120\n"
                "/schedule in 2h 帮我查一下当前ETH的行情\n"
                f"timezone: {DEFAULT_SCHEDULE_TZ}"
            )
        action = parts[1].lower()
        if action == "list":
            tasks = self.db.list_scheduled_tasks(chat_id)
            if not tasks:
                return "scheduled tasks: none"
            lines = ["scheduled tasks:"]
            for task in tasks[:30]:
                state = "on" if int(task.get("enabled") or 0) else "off"
                summary = format_schedule_summary(
                    str(task.get("schedule_type") or ""),
                    str(task.get("cron_expr") or ""),
                    str(task.get("next_run_at") or ""),
                    str(task.get("timezone") or DEFAULT_SCHEDULE_TZ),
                )
                lines.append(f"- #{task['id']} [{state}] {task['kind']} | {summary} | {task['payload']}")
            return "\n".join(lines)
        if action == "clear":
            deleted = self.db.clear_scheduled_tasks(chat_id)
            return f"cleared {deleted} scheduled task(s)."
        if action in {"remove", "delete"}:
            if len(parts) < 3:
                return "usage: /schedule remove <id>"
            try:
                task_id = int(parts[2])
            except ValueError:
                return "schedule id must be an integer."
            deleted = self.db.delete_scheduled_task(chat_id, task_id)
            return f"removed schedule #{task_id}." if deleted else f"schedule #{task_id} not found."

        if action == "in":
            if len(parts) < 4:
                return "usage: /schedule in <duration> <slash command or prompt>"
            try:
                delay_seconds = parse_duration_seconds(parts[2])
            except Exception as exc:
                return f"invalid duration: {exc}"
            payload = text.split(maxsplit=3)[3].strip() if len(text.split(maxsplit=3)) >= 4 else ""
            if not payload:
                return "missing scheduled payload."
            run_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
            try:
                task_id, created = self.db.add_scheduled_task(
                    chat_id=chat_id,
                    created_by=sender_id or self.config.owner_user_id or "scheduler",
                    kind="command" if payload.startswith("/") else "prompt",
                    schedule_type="once",
                    cron_expr="",
                    timezone_name=DEFAULT_SCHEDULE_TZ,
                    payload=payload,
                    next_run_at=run_at.isoformat(timespec="seconds"),
                )
            except ScheduledTaskLimitError as exc:
                return f"schedule rejected: {exc}"
            if not created:
                return f"schedule #{task_id} already exists; no duplicate was created."
            return f"scheduled #{task_id}: once at {run_at.isoformat(timespec='seconds')} | {payload}"

        if len(parts) < 7:
            return "usage: /schedule <cron(5 fields)> <slash command or prompt>"
        cron_expr = " ".join(parts[1:6])
        try:
            cron_expr = parse_cron_expression(cron_expr)
            next_run = next_cron_run(cron_expr, timezone_name=DEFAULT_SCHEDULE_TZ)
        except Exception as exc:
            return f"invalid cron: {exc}"
        payload = text.split(maxsplit=6)[6].strip() if len(text.split(maxsplit=6)) >= 7 else ""
        if not payload:
            return "missing scheduled payload."
        try:
            task_id, created = self.db.add_scheduled_task(
                chat_id=chat_id,
                created_by=sender_id or self.config.owner_user_id or "scheduler",
                kind="command" if payload.startswith("/") else "prompt",
                schedule_type="cron",
                cron_expr=cron_expr,
                timezone_name=DEFAULT_SCHEDULE_TZ,
                payload=payload,
                next_run_at=next_run.astimezone(timezone.utc).isoformat(timespec="seconds"),
            )
        except ScheduledTaskLimitError as exc:
            return f"schedule rejected: {exc}"
        if not created:
            return f"schedule #{task_id} already exists; no duplicate was created."
        return f"scheduled #{task_id}: cron {cron_expr} ({DEFAULT_SCHEDULE_TZ}), next {next_run.isoformat(timespec='seconds')} | {payload}"

    def _accounting(self, chat_id: str, text: str, parts: list[str], sender_id: str = "") -> str:
        if len(parts) == 1 or parts[1].lower() in {"help", "?"}:
            return (
                "usage:\n"
                "/accounting <name> <amount> <description>\n"
                "/accounting bulk <name1,name2,...> <amount> <description>\n"
                "/accounting owe <name> <amount> <description>\n"
                "/accounting owe bulk <name1,name2,...> <amount> <description>\n"
                "/accounting owe <name> <amount> <description> cleared\n"
                "/accounting delete <id>\n"
                "/accounting summary [1m|3m|1y|all]\n"
                "/accounting person <name> [1m|3m|1y|all]\n"
                "/accounting lookup [1m|3m|1y|all]\n"
                "/accounting owe lookup [1m|3m|1y|all]\n"
                "/accounting export [1m|3m|1y|all]\n"
                "/accounting owe export [1m|3m|1y|all]\n"
                "examples:\n"
                "/accounting 雪之素琳 100 帮战数据奖励\n"
                "/accounting bulk 梨芜,桃矢,风禾尽起 5 帮战奖励\n"
                "/accounting owe 雪之素琳 100 铜币拍卖\n"
                "/accounting owe bulk 梨芜,桃矢,风禾尽起 5 帮战奖励\n"
                "/accounting owe 雪之素琳 100 铜币拍卖 cleared\n"
                "/accounting summary 1m\n"
                "/accounting person 雪之素琳 1m\n"
                "/accounting owe lookup 1m"
            )
        head = parts[1].lower()
        if head == "delete":
            if len(parts) < 3:
                return "usage: /accounting delete <id>"
            try:
                entry_id = int(parts[2])
            except ValueError:
                return "entry id must be an integer."
            deleted = self.db.delete_accounting_entry(chat_id=chat_id, entry_id=entry_id)
            if deleted is None:
                return f"no accounting entry found for #{entry_id}"
            return (
                f"deleted accounting #{deleted['id']}: {deleted['entry_type']} | "
                f"{deleted['counterparty']} | {float(deleted['amount']):.2f} | {deleted['description']}"
            )
        if head == "summary":
            days = _accounting_window_to_days(parts[2].lower() if len(parts) >= 3 else "1m")
            if days is None and (len(parts) >= 3 and parts[2].lower() != "all"):
                return "usage: /accounting summary [1m|3m|1y|all]"
            return self._format_accounting_summary(chat_id, days=days)
        if head == "person":
            if len(parts) < 3:
                return "usage: /accounting person <name> [1m|3m|1y|all]"
            counterparty = parts[2].strip()
            days = _accounting_window_to_days(parts[3].lower() if len(parts) >= 4 else "1m")
            if days is None and (len(parts) >= 4 and parts[3].lower() != "all"):
                return "usage: /accounting person <name> [1m|3m|1y|all]"
            return self._format_accounting_person(chat_id, counterparty=counterparty, days=days)
        if head == "lookup":
            days = _accounting_window_to_days(parts[2].lower() if len(parts) >= 3 else "1m")
            if days is None and (len(parts) >= 3 and parts[2].lower() != "all"):
                return "usage: /accounting lookup [1m|3m|1y|all]"
            return self._format_accounting_lookup(chat_id, entry_type="expense", days=days, status="all")
        if head == "export":
            days = _accounting_window_to_days(parts[2].lower() if len(parts) >= 3 else "1m")
            if days is None and (len(parts) >= 3 and parts[2].lower() != "all"):
                return "usage: /accounting export [1m|3m|1y|all]"
            return self._export_accounting(chat_id, entry_type="expense", days=days, status="all")
        if head == "owe":
            if len(parts) >= 3 and parts[2].lower() == "bulk":
                if len(parts) < 6:
                    return "usage: /accounting owe bulk <name1,name2,...> <amount> <description>"
                counterparties = _parse_accounting_name_list(parts[3])
                amount = _parse_accounting_amount(parts[4])
                if not counterparties:
                    return "bulk names are required."
                if amount is None:
                    return "amount must be a number."
                description = " ".join(parts[5:]).strip()
                if not description:
                    return "description is required."
                count = self.db.add_accounting_entries_bulk(
                    chat_id=chat_id,
                    created_by=sender_id or self.config.owner_user_id or "admin",
                    entry_type="owe",
                    counterparties=counterparties,
                    amount=amount,
                    description=description,
                )
                preview = ", ".join(counterparties[:6])
                if len(counterparties) > 6:
                    preview += ", ..."
                return f"bulk owe recorded successfully: {count} entries | {amount:g} | {description} | {preview}"
            if len(parts) >= 3 and parts[2].lower() == "lookup":
                days = _accounting_window_to_days(parts[3].lower() if len(parts) >= 4 else "1m")
                if days is None and (len(parts) >= 4 and parts[3].lower() != "all"):
                    return "usage: /accounting owe lookup [1m|3m|1y|all]"
                return self._format_accounting_lookup(chat_id, entry_type="owe", days=days, status="open")
            if len(parts) >= 3 and parts[2].lower() == "export":
                days = _accounting_window_to_days(parts[3].lower() if len(parts) >= 4 else "1m")
                if days is None and (len(parts) >= 4 and parts[3].lower() != "all"):
                    return "usage: /accounting owe export [1m|3m|1y|all]"
                return self._export_accounting(chat_id, entry_type="owe", days=days, status="all")
            if len(parts) < 5:
                return "usage: /accounting owe <name> <amount> <description> [cleared]"
            counterparty = parts[2].strip()
            amount = _parse_accounting_amount(parts[3])
            if amount is None:
                return "amount must be a number."
            cleared = parts[-1].lower() == "cleared"
            description_parts = parts[4:-1] if cleared else parts[4:]
            description = " ".join(description_parts).strip()
            if not description:
                return "description is required."
            if cleared:
                count = self.db.clear_accounting_owe(
                    chat_id=chat_id,
                    counterparty=counterparty,
                    amount=amount,
                    description=description,
                    cleared_by=sender_id or self.config.owner_user_id or "admin",
                )
                if count:
                    return f"owe cleared successfully: {counterparty} {amount:g} | {description}"
                return "no matching open owe entry found."
            entry_id = self.db.add_accounting_entry(
                chat_id=chat_id,
                created_by=sender_id or self.config.owner_user_id or "admin",
                entry_type="owe",
                counterparty=counterparty,
                amount=amount,
                description=description,
            )
            return f"owe recorded successfully #{entry_id}: {counterparty} {amount:g} | {description}"

        if head == "bulk":
            if len(parts) < 5:
                return "usage: /accounting bulk <name1,name2,...> <amount> <description>"
            counterparties = _parse_accounting_name_list(parts[2])
            amount = _parse_accounting_amount(parts[3])
            if not counterparties:
                return "bulk names are required."
            if amount is None:
                return "amount must be a number."
            description = " ".join(parts[4:]).strip()
            if not description:
                return "description is required."
            count = self.db.add_accounting_entries_bulk(
                chat_id=chat_id,
                created_by=sender_id or self.config.owner_user_id or "admin",
                entry_type="expense",
                counterparties=counterparties,
                amount=amount,
                description=description,
            )
            preview = ", ".join(counterparties[:6])
            if len(counterparties) > 6:
                preview += ", ..."
            return f"bulk expense recorded successfully: {count} entries | {amount:g} | {description} | {preview}"

        if len(parts) < 4:
            return "usage: /accounting <name> <amount> <description>"
        counterparty = parts[1].strip()
        amount = _parse_accounting_amount(parts[2])
        if amount is None:
            return "amount must be a number."
        description = " ".join(parts[3:]).strip()
        if not description:
            return "description is required."
        entry_id = self.db.add_accounting_entry(
            chat_id=chat_id,
            created_by=sender_id or self.config.owner_user_id or "admin",
            entry_type="expense",
            counterparty=counterparty,
            amount=amount,
            description=description,
        )
        return f"expense recorded successfully #{entry_id}: {counterparty} {amount:g} | {description}"

    def _bugreport(self, chat_id: str, text: str, parts: list[str], sender_id: str = "") -> str:
        if len(parts) == 1 or parts[1].lower() in {"help", "?"}:
            return (
                "usage:\n"
                "/bugreport <description>\n"
                "/bugreport list [open|closed|all]\n"
                "/bugreport close <id>\n"
                "/bugreport reopen <id>"
            )
        action = parts[1].lower()
        if action in {"list", "open", "closed", "all"}:
            status = parts[2].lower() if action == "list" and len(parts) >= 3 else action
            if status == "list":
                status = "open"
            if status not in {"open", "closed", "all"}:
                return "usage: /bugreport list [open|closed|all]"
            rows = self.db.list_bug_reports(status=status, limit=100)
            label = status if status != "all" else "all"
            if not rows:
                return f"bug reports ({label}): none"
            lines = [f"bug reports ({label}):"]
            for row in rows:
                description = " ".join(str(row.get("description") or "").split())
                if len(description) > 140:
                    description = description[:137].rstrip() + "..."
                # Bug reports are shared globally; show the origin chat so a
                # maintainer can tell which group a ticket came from.
                origin = _short_chat_label(str(row.get("chat_id") or ""))
                lines.append(f"#{row['id']} [{row['status']}] ({origin}) {description}")
            return "\n".join(lines)
        if action in {"close", "closed", "resolve", "resolved", "done", "reopen", "open"}:
            if len(parts) < 3:
                return f"usage: /bugreport {action} <id>"
            try:
                bug_id = int(parts[2])
            except ValueError:
                return "bug id must be an integer."
            status = "open" if action in {"reopen", "open"} else "closed"
            updated = self.db.update_bug_report_status(
                bug_id=bug_id,
                status=status,
                actor=sender_id or self.config.owner_user_id or "admin",
            )
            if updated is None:
                return f"no bug report found for #{bug_id}"
            return f"bug report #{bug_id} marked {status}: {updated['description']}"
        description = text.strip()[len(parts[0]) :].strip()
        if not description:
            return "description is required."
        entry_id = self.db.add_bug_report(
            chat_id=chat_id,
            created_by=sender_id or self.config.owner_user_id or "admin",
            description=description,
        )
        return f"bug report #{entry_id} recorded: {description}"

    def _format_accounting_lookup(self, chat_id: str, *, entry_type: str, days: int | None, status: str) -> str:
        summary = self.db.summarize_accounting(chat_id, entry_type=entry_type, days=days, status=status)
        label = "all" if days is None else _accounting_days_label(days)
        if entry_type == "owe":
            lines = [f"open owes ({label}):"]
        else:
            lines = [f"expenses ({label}):"]
        lines.append(f"count: {summary['count']}")
        lines.append(f"total: {summary['total_amount']:.2f} CNY")
        if summary["by_counterparty"]:
            lines.append("by counterparty:")
            for row in summary["by_counterparty"][:12]:
                lines.append(f"- {row['counterparty']}: {row['amount']:.2f}")
        rows = summary["rows"]
        if rows:
            lines.append("transactions:")
            for row in rows:
                state = f" [{row['status']}]" if row["entry_type"] == "owe" else ""
                lines.append(
                    f"- #{row['id']} {row['created_at']} | {row['counterparty']} | {row['amount']:.2f} | {row['description']}{state}"
                )
        return "\n".join(lines)

    def _format_accounting_summary(self, chat_id: str, *, days: int | None) -> str:
        label = "all" if days is None else _accounting_days_label(days)
        expenses = self.db.summarize_accounting(chat_id, entry_type="expense", days=days, status="all")
        open_owes = self.db.summarize_accounting(chat_id, entry_type="owe", days=days, status="open")
        cleared_owes = self.db.summarize_accounting(chat_id, entry_type="owe", days=days, status="cleared")
        lines = [
            f"accounting summary ({label}):",
            f"expenses: {expenses['count']} | total {expenses['total_amount']:.2f} CNY",
            f"open owes: {open_owes['count']} | total {open_owes['total_amount']:.2f} CNY",
            f"cleared owes: {cleared_owes['count']} | total {cleared_owes['total_amount']:.2f} CNY",
            f"net cash out: {(expenses['total_amount'] + cleared_owes['total_amount']):.2f} CNY",
        ]
        if expenses["by_counterparty"]:
            lines.append("top expense counterparties:")
            for row in expenses["by_counterparty"][:5]:
                lines.append(f"- {row['counterparty']}: {row['amount']:.2f}")
        if open_owes["by_counterparty"]:
            lines.append("top open owes:")
            for row in open_owes["by_counterparty"][:5]:
                lines.append(f"- {row['counterparty']}: {row['amount']:.2f}")
        return "\n".join(lines)

    def _format_accounting_person(self, chat_id: str, *, counterparty: str, days: int | None) -> str:
        label = "all" if days is None else _accounting_days_label(days)
        expenses = self.db.summarize_accounting(chat_id, entry_type="expense", days=days, status="all", counterparty=counterparty)
        open_owes = self.db.summarize_accounting(chat_id, entry_type="owe", days=days, status="open", counterparty=counterparty)
        cleared_owes = self.db.summarize_accounting(chat_id, entry_type="owe", days=days, status="cleared", counterparty=counterparty)
        lines = [
            f"accounting person ({label}): {counterparty}",
            f"expenses paid: {expenses['total_amount']:.2f} CNY ({expenses['count']} item(s))",
            f"open owes: {open_owes['total_amount']:.2f} CNY ({open_owes['count']} item(s))",
            f"cleared owes: {cleared_owes['total_amount']:.2f} CNY ({cleared_owes['count']} item(s))",
        ]
        all_rows = sorted(
            expenses["rows"] + open_owes["rows"] + cleared_owes["rows"],
            key=lambda row: (str(row.get("created_at") or ""), int(row.get("id") or 0)),
            reverse=True,
        )
        if all_rows:
            lines.append("transactions:")
            for row in all_rows:
                lines.append(
                    f"- #{row['id']} {row['created_at']} | {row['entry_type']} | {row['amount']:.2f} | {row['description']} [{row['status']}]"
                )
        return "\n".join(lines)

    def _export_accounting(self, chat_id: str, *, entry_type: str, days: int | None, status: str) -> str:
        rows = self.db.lookup_accounting(chat_id, entry_type=entry_type, days=days, status=status, limit=5000)
        export_dir = Path("logs") / "analyze"
        export_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        scope = "all" if days is None else _accounting_days_label(days)
        filename = f"accounting_{entry_type}_{scope}_{stamp}.csv"
        path = export_dir / filename
        lines = ["id,created_at,entry_type,counterparty,amount,currency,description,status,cleared_at,created_by,cleared_by"]
        for row in rows:
            escaped = [
                str(row.get("id") or ""),
                str(row.get("created_at") or ""),
                str(row.get("entry_type") or ""),
                str(row.get("counterparty") or "").replace('"', '""'),
                f"{float(row.get('amount') or 0.0):.2f}",
                str(row.get("currency") or ""),
                str(row.get("description") or "").replace('"', '""'),
                str(row.get("status") or ""),
                str(row.get("cleared_at") or ""),
                str(row.get("created_by") or ""),
                str(row.get("cleared_by") or ""),
            ]
            lines.append(",".join(f'"{item}"' for item in escaped))
        path.write_text("\n".join(lines), encoding="utf-8")
        return f"exported {len(rows)} accounting row(s) to {path.as_posix()}"

    def _bot_global(self, parts: list[str]) -> CommandResult:
        if len(parts) < 3 or parts[2].lower() not in {"on", "off"}:
            current = self.db.get_setting("global_bot_enabled", True)
            return CommandResult(True, f"用法：/bot global on|off。当前：{'on' if current else 'off'}")
        enabled = parts[2].lower() == "on"
        self.db.set_setting("global_bot_enabled", enabled)
        return CommandResult(True, f"global bot 已{'开启' if enabled else '关闭'}。")

    def _recent_member_events(self, chat_id: str) -> list[str]:
        rows = self.db.recent_chat_events(chat_id, limit=20, days=1)
        lines = []
        for row in reversed(rows):
            name = row["display_name"] or row["user_id"] or row["raw_content"]
            lines.append(f"{row['created_at']} {row['event_type']}: {name}")
        return lines

    def _blacklist(self, chat_id: str, parts: list[str]) -> CommandResult:
        if len(parts) == 1 or parts[1].lower() in {"help", "?"}:
            return CommandResult(True, "用法：/blacklist add <wxid>，/blacklist remove <wxid>，/blacklist list，/blacklist clear。")

        action = parts[1].lower()
        users = self._blacklist_users(chat_id)

        if action == "list":
            if not users:
                return CommandResult(True, "当前群 blacklist 是空的。")
            return CommandResult(True, "blacklist:\n" + "\n".join(users))

        if action == "clear":
            self.db.set_setting(f"group_blacklist:{chat_id}", [])
            return CommandResult(True, "当前群 blacklist 已清空。")

        if action in {"add", "remove"}:
            if len(parts) < 3:
                return CommandResult(True, "缺少 wxid。用 /whoami 可以查自己的 sender id。")
            user_id = parts[2].strip()
            if not user_id:
                return CommandResult(True, "缺少 wxid。")
            if action == "add":
                if user_id not in users:
                    users.append(user_id)
                    users.sort()
                self.db.set_setting(f"group_blacklist:{chat_id}", users)
                return CommandResult(True, f"已加入当前群 blacklist: {user_id}")
            users = [item for item in users if item != user_id]
            self.db.set_setting(f"group_blacklist:{chat_id}", users)
            return CommandResult(True, f"已移出当前群 blacklist: {user_id}")

        return CommandResult(True, "用法：/blacklist add <wxid>，/blacklist remove <wxid>，/blacklist list，/blacklist clear。")

    def _blacklist_users(self, chat_id: str) -> list[str]:
        value = self.db.get_setting(f"group_blacklist:{chat_id}", [])
        if not isinstance(value, list):
            return []
        return sorted(str(item) for item in value if str(item).strip())

    def _target_list(self, chat_id: str, parts: list[str]) -> CommandResult:
        if len(parts) == 1 or parts[1].lower() in {"help", "?"}:
            return CommandResult(True, "用法：/target add <wxid>，/target remove <wxid>，/target list，/target clear。")

        action = parts[1].lower()
        users = self._target_users(chat_id)

        if action == "list":
            if not users:
                return CommandResult(True, "当前群 target_list 是空的；prompt template 里的默认目标仍可能生效。")
            return CommandResult(True, "target_list:\n" + "\n".join(users))

        if action == "clear":
            self.db.set_setting(f"group_target_list:{chat_id}", [])
            return CommandResult(True, "当前群 target_list 已清空；会回到 prompt template 默认目标。")

        if action in {"add", "remove"}:
            if len(parts) < 3:
                return CommandResult(True, "缺少 wxid。用 /idlookup 可以从引用消息查对方 ID。")
            user_id = parts[2].strip()
            if not user_id:
                return CommandResult(True, "缺少 wxid。")
            if action == "add":
                if user_id not in users:
                    users.append(user_id)
                    users.sort()
                self.db.set_setting(f"group_target_list:{chat_id}", users)
                return CommandResult(True, f"已加入当前群 target_list: {user_id}")
            users = [item for item in users if item != user_id]
            self.db.set_setting(f"group_target_list:{chat_id}", users)
            return CommandResult(True, f"已移出当前群 target_list: {user_id}")

        return CommandResult(True, "用法：/target add <wxid>，/target remove <wxid>，/target list，/target clear。")

    def _target_users(self, chat_id: str) -> list[str]:
        value = self.db.get_setting(f"group_target_list:{chat_id}", [])
        if not isinstance(value, list):
            return []
        return sorted(str(item) for item in value if str(item).strip())

    def _whitelist(self, parts: list[str]) -> CommandResult:
        if len(parts) == 1 or parts[1].lower() in {"help", "?"}:
            return CommandResult(True, "用法：/whitelist add <wxid>，/whitelist remove <wxid>，/whitelist list。")

        action = parts[1].lower()
        users = self._whitelist_users()

        if action == "list":
            if not users:
                return CommandResult(True, "whitelist 是空的。")
            return CommandResult(True, "whitelist:\n" + "\n".join(users))

        if action in {"add", "remove"}:
            if len(parts) < 3:
                return CommandResult(True, "缺少 wxid。用 /whoami 可以查自己的 sender id。")
            user_id = parts[2].strip()
            if not user_id:
                return CommandResult(True, "缺少 wxid。")
            if action == "add":
                if user_id not in users:
                    users.append(user_id)
                    users.sort()
                self._set_whitelist_users(users)
                return CommandResult(True, f"已加入 whitelist: {user_id}")
            users = [item for item in users if item != user_id]
            self._set_whitelist_users(users)
            return CommandResult(True, f"已移出 whitelist: {user_id}")

        return CommandResult(True, "用法：/whitelist add <wxid>，/whitelist remove <wxid>，/whitelist list。")

    def _whitelist_users(self) -> list[str]:
        return sorted(self.auth.whitelist_user_ids) if getattr(self, "auth", None) else sorted(
            str(item) for item in self.config.whitelist_user_ids if str(item).strip())

    def _set_whitelist_users(self, users: list[str]) -> None:
        clean_users = sorted(dict.fromkeys(str(item).strip() for item in users if str(item).strip()))
        if getattr(self, "auth", None) is not None:
            self.auth.set_whitelist_users(clean_users)
        self.config.whitelist_user_ids[:] = clean_users

    def _delay_global_legacy(self, chat_id: str, parts: list[str]) -> CommandResult:
        timing = self._group_delay(chat_id)
        if len(parts) == 1 or parts[1].lower() in {"help", "?"}:
            return CommandResult(
                True,
                "用法：/delay <min秒> <max秒> [多条消息间隔秒]。\n"
                f"当前：{timing.min_delay_seconds:g}-{timing.max_delay_seconds:g}s，between {timing.between_messages_seconds:g}s。",
            )
        if len(parts) < 3:
            return CommandResult(True, "用法：/delay <min秒> <max秒> [多条消息间隔秒]。例如：/delay 3 5 1")
        try:
            min_delay = float(parts[1])
            max_delay = float(parts[2])
            between = float(parts[3]) if len(parts) >= 4 else self.config.reply_timing.between_messages_seconds
        except ValueError:
            return CommandResult(True, "delay 必须是数字秒数。例如：/delay 3 5 1")
        if min_delay < 0 or max_delay < 0 or between < 0:
            return CommandResult(True, "delay 不能是负数。")
        if max_delay < min_delay:
            min_delay, max_delay = max_delay, min_delay
        if max_delay > 30 or between > 10:
            return CommandResult(True, "delay 太长了。max 最多 30 秒，多条消息间隔最多 10 秒。")
        self.config.reply_timing.min_delay_seconds = min_delay
        self.config.reply_timing.max_delay_seconds = max_delay
        self.config.reply_timing.between_messages_seconds = between
        self.db.set_setting("reply_timing_global", {
            "min": min_delay, "max": max_delay, "between": between,
        })
        return CommandResult(True, f"delay 已设为 {min_delay:g}-{max_delay:g}s，多条消息间隔 {between:g}s。")

    def _prompt(self, chat_id: str, text: str, parts: list[str]) -> CommandResult:
        if len(parts) == 1 or parts[1].lower() in {"help", "?"}:
            return CommandResult(
                True,
                "用法：/prompt list，/prompt use <template>，/prompt custom <text>，/prompt show，/prompt clear。\n"
                "这是按群切换整套 system prompt；模板来自 prompt_templates/*.md；clear 会回到 PROMPT.md。",
            )
        action = parts[1].lower()
        direct_name = normalize_template_name(action)
        if direct_name not in {"reload", "list", "templates", "current", "show", "use", "set", "custom", "replace", "clear", "default", "restore"}:
            if template_exists(direct_name):
                self._set_group_prompt(chat_id, direct_name, "")
                return CommandResult(True, f"当前群 prompt 已切到 prompt_templates/{direct_name}.md。")
            suggestion = _prompt_template_suggestion(direct_name)
            if suggestion:
                return CommandResult(True, f"未知 prompt 模板：{direct_name}。你是不是想用：/prompt {suggestion}")
        if action == "reload":
            return CommandResult(True, "PROMPT.md 和 prompt_templates/*.md 都是热读取；用 /prompt clear 回到 PROMPT.md。")
        if action in {"list", "templates"}:
            return CommandResult(True, template_help())
        if action in {"current", "show"}:
            profile = self.db.get_setting(f"group_prompt_profile:{chat_id}", "main")
            custom = self.db.get_setting(f"group_prompt_custom:{chat_id}", "")
            if profile == "custom" and custom:
                return CommandResult(True, "当前群 prompt: custom\n" + custom[-1200:])
            if profile in {"main", "prompt-md"}:
                prompt = self.prompt_path.read_text(encoding="utf-8").strip() if self.prompt_path.exists() else ""
                return CommandResult(True, f"当前群 prompt: PROMPT.md\n{prompt[-1000:] if prompt else 'PROMPT.md 是空的。'}")
            template = get_template(str(profile))
            return CommandResult(True, f"当前群 prompt: {profile}\n{template[-1000:] if template else '模板不存在，实际会回退 default。'}")
        if action in {"use", "set"}:
            if len(parts) < 3:
                return CommandResult(True, "用法：/prompt use <template>。发 /prompt list 看模板。")
            name = normalize_template_name(parts[2])
            if not template_exists(name):
                return CommandResult(True, f"未知 prompt 模板：{name}。\n{template_help()}")
            self._set_group_prompt(chat_id, name, "")
            return CommandResult(True, f"当前群 prompt 已切到 prompt_templates/{name}.md。")
        if action in {"custom", "replace"}:
            payload = text.split(maxsplit=2)[2].strip() if len(text.split(maxsplit=2)) >= 3 else ""
            if not payload:
                return CommandResult(True, "用法：/prompt custom <完整 system prompt 文本>")
            self._set_group_prompt(chat_id, "custom", payload)
            return CommandResult(True, "当前群 prompt 已切到 custom。下次回复立即生效。")
        if action in {"clear", "default", "restore"}:
            self._set_group_prompt(chat_id, "main", "")
            return CommandResult(True, "当前群 prompt 已恢复 PROMPT.md。")
        return CommandResult(True, "用法：/prompt list，/prompt use <template>，/prompt custom <text>，/prompt show，/prompt clear。")

    def _set_group_prompt(self, chat_id: str, profile: str, custom_prompt: str) -> None:
        self.db.set_setting(f"group_prompt_profile:{chat_id}", profile)
        self.db.set_setting(f"group_prompt_custom:{chat_id}", custom_prompt)

    def _mode(self, chat_id: str, parts: list[str]) -> CommandResult:
        names = "normal / concise / verify / finance-analysis / finance-calculation"
        if len(parts) == 1 or parts[1].lower() in {"status", "show"}:
            self._ensure_group(chat_id)
            group = self._get_group(chat_id) or {"mode": "normal"}
            return CommandResult(True, f"loaded_mode: {self._loaded_mode(chat_id, str(group['mode']))}\navailable: {names}")
        if parts[1].lower() in {"list", "help", "?"}:
            return CommandResult(True, f"用法：/mode load <name>\navailable: {names}")
        if parts[1].lower() in {"load", "use", "set"}:
            if len(parts) < 3:
                return CommandResult(True, f"用法：/mode load <name>\navailable: {names}")
            requested = parts[2].strip().lower()
        else:
            requested = parts[1].strip().lower()
        aliases = {
            "finance": "finance-analysis",
            "financial-analysis": "finance-analysis",
            "finance_analysis": "finance-analysis",
            "finance-calc": "finance-calculation",
            "financecalc": "finance-calculation",
            "calculation": "finance-calculation",
            "finance_calculation": "finance-calculation",
        }
        name = aliases.get(requested, requested)
        if name == "finance-calculation" and FINANCE_CALCULATION_HARD_DISABLE:
            return CommandResult(True, "Finance calculation mode is currently disabled (compute optimization). /finance 股票分析仍可用。")
        if name not in {"normal", "concise", "verify", "finance-analysis", "finance-calculation"}:
            return CommandResult(True, f"未知 mode：{requested}。\navailable: {names}")

        self._ensure_group(chat_id)
        if name == "finance-analysis":
            self.db.set_setting(f"group_finance_calculation_enabled:{chat_id}", False)
            self._update_group(chat_id, mode="normal")
            self._finance(chat_id, "/finance on", ["/finance", "on"])
        elif name == "finance-calculation":
            self._finance(chat_id, "/finance off", ["/finance", "off"])
            self.db.set_setting(f"group_finance_calculation_enabled:{chat_id}", True)
            self._update_group(chat_id, mode="normal")
        else:
            self._finance(chat_id, "/finance off", ["/finance", "off"])
            self.db.set_setting(f"group_finance_calculation_enabled:{chat_id}", False)
            self._update_group(chat_id, mode=name)
        return CommandResult(True, f"loaded_mode: {name}")

    def _loaded_mode(self, chat_id: str, base_mode: str = "normal") -> str:
        if self.db.get_setting(f"group_finance_calculation_enabled:{chat_id}", False):
            return "finance-calculation"
        if self.db.get_setting(f"group_finance_enabled:{chat_id}", False):
            return "finance-analysis"
        return base_mode if base_mode in {"normal", "concise", "verify"} else "normal"

    def _finance(self, chat_id: str, text: str, parts: list[str]) -> CommandResult:
        # finance-ANALYSIS (股票分析) stays available - only calculation is disabled
        if len(parts) == 1 or parts[1].lower() in {"help", "?"}:
            return CommandResult(
                True,
                "用法：/finance on|off|status|debug。\n"
                "on = 仅当前群开启结构化财经分析包装层；off = 关闭并恢复原状态；"
                "status = 查看状态；debug = 引用一条财经回复后查看原始输出。\n"
                "群内数字记录与精确汇总请使用 /financecalc。",
            )
        action = parts[1].strip().lower()
        if action == "status":
            enabled = bool(self.db.get_setting(f"group_finance_enabled:{chat_id}", False))
            snapshot = self.db.get_setting(f"group_finance_snapshot:{chat_id}", {})
            debug_count = int(self.db.get_setting(f"group_finance_debug_count:{chat_id}", 0) or 0)
            return CommandResult(
                True,
                "\n".join(
                    [
                        f"finance_mode: {'on' if enabled else 'off'}",
                        f"finance_snapshot: {'present' if isinstance(snapshot, dict) and snapshot else 'none'}",
                        f"finance_prompt_preset: {self.db.get_setting(f'group_finance_prompt_name:{chat_id}', 'finance-wrapper-v1')}",
                        f"finance_style_preset: {self.db.get_setting(f'group_finance_style:{chat_id}', 'free rational-neutral')}",
                        f"finance_reasoning_preset: {self.db.get_setting(f'group_finance_reasoning:{chat_id}', 'high')}",
                        f"finance_length_tokens: {self.db.get_setting(f'group_finance_max_reply_tokens:{chat_id}', FINANCE_RECOMMENDED_MAX_TOKENS)}",
                        f"finance_debug_records: {debug_count}",
                    ]
                ),
            )
        if action == "on":
            snapshot = self._finance_snapshot(chat_id)
            self.db.set_setting(f"group_finance_snapshot:{chat_id}", snapshot)
            self.db.set_setting(f"group_finance_calculation_enabled:{chat_id}", False)
            self.db.set_setting(f"group_finance_enabled:{chat_id}", True)
            self.db.set_setting(f"group_finance_prompt_name:{chat_id}", "finance-wrapper-v1")
            self.db.set_setting(f"group_finance_style:{chat_id}", "free rational-neutral")
            self.db.set_setting(f"group_finance_reasoning:{chat_id}", "high")
            self.db.set_setting(f"group_finance_verbosity:{chat_id}", "high")
            self.db.set_setting(f"group_finance_max_reply_tokens:{chat_id}", FINANCE_RECOMMENDED_MAX_TOKENS)
            return CommandResult(
                True,
                "当前群 finance wrapper 已开启。\n"
                "影响范围：仅本群的财经/交易类请求会进入结构化分析流程；普通群聊行为不变。\n"
                f"默认输出上限已设为 {FINANCE_RECOMMENDED_MAX_TOKENS} tokens（覆盖 reasoning + 结构化 JSON），"
                "如需调整用 /length <tokens>。\n"
                "调试：引用一条财经回复后发送 /finance debug 可查看该回复对应的原始 JSON。",
            )
        if action == "off":
            snapshot = self.db.get_setting(f"group_finance_snapshot:{chat_id}", {})
            self.db.set_setting(f"group_finance_enabled:{chat_id}", False)
            self.db.set_setting(f"group_finance_prompt_name:{chat_id}", "")
            self.db.set_setting(f"group_finance_style:{chat_id}", "")
            self.db.set_setting(f"group_finance_reasoning:{chat_id}", "")
            self.db.set_setting(f"group_finance_verbosity:{chat_id}", "")
            self.db.set_setting(f"group_finance_max_reply_tokens:{chat_id}", 0)
            self.db.set_setting(f"group_finance_snapshot:{chat_id}", {})
            state = "已关闭并恢复原状态。" if isinstance(snapshot, dict) and snapshot else "已关闭。"
            return CommandResult(True, f"当前群 finance wrapper {state}")
        if action == "debug":
            return CommandResult(True, "用法：引用一条已发送的财经回复，然后发送 /finance debug。")
        return CommandResult(True, "用法：/finance on|off|status|debug。")

    def _start_notebook_judge_drain(self, chat_id: str) -> None:
        """Judge pending noteboard entries in a background daemon thread.

        The router path schedules through its executor; the command path
        (/financecalc on) has no router, so it runs the standalone drain.
        """
        if self.llm is None:
            return
        with _NOTEBOOK_DRAIN_LOCK:
            if chat_id in _NOTEBOOK_DRAINING:
                return
            _NOTEBOOK_DRAINING.add(chat_id)

        def _run() -> None:
            try:
                from foxstar_bot.router import drain_notebook_judgement

                drain_notebook_judgement(self.llm, self.db, chat_id)
            except Exception:
                logging.getLogger("foxstar_bot.commands").exception(
                    "notebook judge drain failed chat=%s", chat_id
                )
            finally:
                with _NOTEBOOK_DRAIN_LOCK:
                    _NOTEBOOK_DRAINING.discard(chat_id)

        threading.Thread(target=_run, daemon=True, name=f"NotebookJudge-{chat_id[-8:]}").start()

    def _agent_tasks(self, chat_id: str, parts: list[str]) -> CommandResult:
        action = parts[1].strip().lower() if len(parts) >= 2 else "list"
        if action in {"help", "?"}:
            return CommandResult(True, "用法：/tasks [list|status <id>|cancel <id>]")
        if action == "status" and len(parts) >= 3:
            try:
                task_id = int(parts[2])
            except ValueError:
                return CommandResult(True, "task id 必须是数字")
            task = self.db.get_agent_task(task_id)
            if task is None or str(task.get("chat_id")) != chat_id:
                return CommandResult(True, f"#{task_id} 不存在（或不在本群）")
            body = str(task.get("result") or task.get("error") or task.get("progress_note") or "")
            return CommandResult(
                True,
                f"#{task_id} [{task['status']}] 创建 {str(task['created_at'])[:16]}\n{body[:3000]}",
            )
        if action == "cancel" and len(parts) >= 3:
            try:
                task_id = int(parts[2])
            except ValueError:
                return CommandResult(True, "task id 必须是数字")
            task = self.db.get_agent_task(task_id)
            if task is None or str(task.get("chat_id")) != chat_id:
                return CommandResult(True, f"#{task_id} 不存在（或不在本群）")
            if task["status"] in {"pending", "running"}:
                self.db.update_agent_task(task_id, status="cancelled")
                return CommandResult(True, f"#{task_id} 已标记取消（正在运行中的模型调用会自然结束，不再投递结果）")
            return CommandResult(True, f"#{task_id} 状态是 {task['status']}，无需取消")
        rows = self.db.list_agent_tasks(limit=8)
        if not rows:
            return CommandResult(True, "没有后台任务。让 bot 用 start_agent_task 工具启动一个，或直接说“帮我后台研究一下X”。")
        lines = ["agent tasks:"]
        for row in rows:
            preview = " ".join(str(row["instruction"]).split())[:60]
            lines.append(f"#{row['id']} [{row['status']:>9}] {str(row['created_at'])[5:16]} {preview}")
        return CommandResult(True, "\n".join(lines))

    def _finance_calculation(self, chat_id: str, parts: list[str]) -> CommandResult:
        if FINANCE_CALCULATION_HARD_DISABLE:
            return CommandResult(True, "Finance calculation mode is currently disabled (compute optimization). /finance 股票分析仍可用。")
        action = parts[1].strip().lower() if len(parts) >= 2 else "status"
        setting_key = f"group_finance_calculation_enabled:{chat_id}"
        if action == "status":
            calc_on = bool(self.db.get_setting(setting_key, False))
            explicit_policy = self.db.get_setting(f"group_reply_policy:{chat_id}", None)
            if explicit_policy is not None:
                policy_note = f"reply_policy: {explicit_policy} (explicit)"
            elif calc_on:
                policy_note = "reply_policy: direct (calculation default，/gset reply auto 可覆盖)"
            else:
                policy_note = "reply_policy: auto"
            backfill_done = (
                self.db.get_setting(f"group_finance_noteboard_backfill_version:{chat_id}", None) is not None
            )
            backfill_note = "backfill: done" if backfill_done else "backfill: pending（下一条普通消息到达时自动回填，或重跑 /financecalc on 立即回填）"
            return CommandResult(
                True,
                "\n".join(
                    [
                        f"finance_calculation_mode: {'on' if calc_on else 'off'}",
                        f"calculation_noteboard_records: {self.db.count_finance_noteboard_entries(chat_id)}",
                        f"notebook_pending_judge: {len(self.db.unclassified_finance_noteboard_entries(chat_id, limit=100))}",
                        "numeric_capture: silent + LLM judge（闲聊自动隐藏）",
                        backfill_note,
                        policy_note,
                    ]
                ),
            )
        if action in {"notes", "noteboard"}:
            try:
                limit = max(1, min(int(parts[2]), 100)) if len(parts) >= 3 else 10
            except ValueError:
                return CommandResult(True, "用法：/financecalc notes [1-100]")
            rows = self.db.list_finance_noteboard_entries(chat_id, days=None, limit=limit)
            if not rows:
                backfill_done = (
                    self.db.get_setting(f"group_finance_noteboard_backfill_version:{chat_id}", None) is not None
                )
                if not backfill_done:
                    return CommandResult(
                        True,
                        "calculation noteboard: empty\n"
                        "（历史消息还没回填：下一条普通消息到达时会自动回填，或重跑 /financecalc on 立即回填）",
                    )
                return CommandResult(True, "calculation noteboard: empty")
            lines = [f"calculation noteboard: latest {len(rows)}"]
            for row in rows:
                sender = str(row.get("sender_name") or row.get("sender_id") or "unknown")
                content = " ".join(str(row.get("content") or "").split())[:160]
                lines.append(f"#{row['id']} | {row['message_at']} | {sender} | {content}")
            return CommandResult(True, "\n".join(lines))
        if action == "on":
            self._finance(chat_id, "/finance off", ["/finance", "off"])
            self.db.set_setting(setting_key, True)
            backfilled = 0
            try:
                # Lazy import: router imports this module, so a top-level
                # import would be circular.
                from foxstar_bot.router import ensure_finance_noteboard_backfill

                backfilled = ensure_finance_noteboard_backfill(self.db, chat_id)
            except Exception:
                logging.getLogger("foxstar_bot.commands").exception(
                    "financecalc backfill failed chat=%s", chat_id
                )
            self._start_notebook_judge_drain(chat_id)
            backfill_note = (
                f"已从群消息历史回填 {backfilled} 条记账记录。"
                if backfilled
                else "历史回填：无可回填的数字记录（或此前已回填过）。"
            )
            return CommandResult(
                True,
                "当前群 finance calculation mode 已开启。\n"
                "含数字的普通消息会在任何 reply gate 之前静默写入 calculation noteboard 和普通聊天记录；"
                "记录本身不会触发回复。\n"
                f"{backfill_note}\n"
                "回复策略默认切换为 direct：只有被@、被引用或管理员命令才会回复"
                "（可用 /gset reply auto 显式改回）。",
            )
        if action == "off":
            self.db.set_setting(setting_key, False)
            return CommandResult(True, "当前群 finance calculation mode 已关闭；已有记录保留。")
        return CommandResult(True, "用法：/financecalc on|off|status|notes [1-30]")

    def _finance_snapshot(self, chat_id: str) -> dict[str, object]:
        return {
            "prompt_profile": self.db.get_setting(f"group_prompt_profile:{chat_id}", "main"),
            "prompt_custom": self.db.get_setting(f"group_prompt_custom:{chat_id}", ""),
            "style": self.db.get_setting(f"group_style:{chat_id}", "strict"),
            "reply_model": self.db.get_setting(f"group_reply_model:{chat_id}", ""),
            "model_provider": self.db.get_setting(f"group_model_provider:{chat_id}", ""),
            "reasoning_effort": self.db.get_setting(f"group_reasoning_effort:{chat_id}", ""),
            "verbosity": self.db.get_setting(f"group_verbosity:{chat_id}", ""),
            "max_reply_tokens": self.db.get_setting(f"group_max_reply_tokens:{chat_id}", 0),
        }

    def _memory(self, chat_id: str, parts: list[str], is_admin: bool, sender_id: str = "") -> CommandResult:
        if len(parts) == 1:
            return CommandResult(
                True,
                "用法：/memory show，/memory remember <key>: <value>，/memory set <key>: <value>，/memory delete <key>，/memory clear。",
            )
        action = parts[1].lower()
        if action in {"help", "?"}:
            return CommandResult(
                True,
                "用法：/memory show，/memory remember <key>: <value>，/memory set <key>: <value>，/memory delete <key>，/memory clear。",
            )
        if action in {"show", "list"}:
            items = self.memory.list_scope("chat", chat_id, 20)
            if not items:
                return CommandResult(True, "这个群还没有长期记忆。")
            return CommandResult(True, "\n".join(f"{i['key']}: {i['value']}" for i in items))
        if action in {"remember", "set", "add", "记住", "更新"}:
            payload = " ".join(parts[2:]).strip()
            key, value = _parse_memory_payload(payload)
            if not key or not value:
                return CommandResult(True, "用法：/memory remember <key>: <value>。例如：/memory remember 群偏好: 回答要短一点")
            self.memory.upsert("chat", chat_id, key, value, priority=100 if is_admin else 50, source_user_id=sender_id)
            return CommandResult(True, f"已更新当前群 memory: {key}")
        if action in {"delete", "remove", "forget", "删除", "忘记"}:
            if not is_admin:
                return CommandResult(True)
            key = " ".join(parts[2:]).strip()
            if not key:
                return CommandResult(True, "用法：/memory delete <key>")
            count = self.memory.delete("chat", chat_id, key)
            return CommandResult(True, f"已删除 {count} 条 memory。")
        if action == "clear":
            if not is_admin:
                return CommandResult(True)
            count = self.memory.clear_scope("chat", chat_id)
            return CommandResult(True, f"已清除 {count} 条当前群 memory。")
        return CommandResult(True, "用法：/memory show，/memory remember <key>: <value>，/memory delete <key>，/memory clear。")

    def _vision(self, chat_id: str, parts: list[str]) -> CommandResult:
        self._ensure_group(chat_id)
        mode_key = f"group_image_analysis_mode:{chat_id}"
        current_mode = str(
            self.db.get_setting(mode_key, self.config.model.image_analysis_mode)
            or self.config.model.image_analysis_mode
        )
        group = self._get_group(chat_id)
        enabled = bool(group["vision_enabled"]) if group else True
        if len(parts) == 1 or parts[1].lower() in {"status", "show", "help", "?"}:
            return CommandResult(
                True,
                "用法：/vision on|off；/vision mode tool|native|clear。\n"
                "tool = 使用独立图片分析模型（如 Gemini）；native = 使用当前主模型的原生多模态能力。\n"
                f"当前：{'on' if enabled else 'off'}, mode={current_mode}",
            )
        action = parts[1].strip().lower()
        if action in {"on", "off"}:
            self._update_group(chat_id, vision_enabled=int(action == "on"))
            return CommandResult(True, "已开启。" if action == "on" else "已关闭。")
        if action in {"tool", "native"}:
            self.db.set_setting(mode_key, action)
            self._update_group(chat_id, vision_enabled=1)
            return CommandResult(True, f"当前群图片分析模式已设为 {action}，vision 已开启。")
        if action == "mode":
            value = parts[2].strip().lower() if len(parts) >= 3 else ""
            if value in {"clear", "default", "reset"}:
                self.db.set_setting(mode_key, "")
                return CommandResult(
                    True,
                    f"当前群图片分析模式已恢复全局默认：{self.config.model.image_analysis_mode}。",
                )
            if value not in {"tool", "native"}:
                return CommandResult(True, "image analysis mode 只能是 tool 或 native。")
            self.db.set_setting(mode_key, value)
            self._update_group(chat_id, vision_enabled=1)
            return CommandResult(True, f"当前群图片分析模式已设为 {value}，vision 已开启。")
        return CommandResult(True, "用法：/vision on|off；/vision mode tool|native|clear。")

    def _length(self, chat_id: str, parts: list[str]) -> CommandResult:
        if len(parts) == 1 or parts[1].lower() in {"help", "?"}:
            current = self.db.get_setting(f"group_max_reply_tokens:{chat_id}", "default")
            return CommandResult(True, f"用法：/length <最大输出 token 数>|clear。当前：{current}")
        value = parts[1].lower()
        if value in {"clear", "default", "off", "reset", "0", "unlimited", "infinite", "inf"}:
            self.db.set_setting(f"group_max_reply_tokens:{chat_id}", 0)
            return CommandResult(True, "当前群 length 已设为 unlimited。")
        try:
            max_tokens = int(value)
        except ValueError:
            return CommandResult(True, "length 必须是数字 token 数，例如：/length 300，或 /length unlimited。")
        if max_tokens < 20:
            return CommandResult(True, "length 不能小于 20 tokens。要不限制请用 /length unlimited。")
        self.db.set_setting(f"group_max_reply_tokens:{chat_id}", max_tokens)
        return CommandResult(True, f"当前群最大回复长度已设为 {max_tokens} tokens。")

    def _context(self, chat_id: str, parts: list[str]) -> CommandResult:
        key = f"group_context_messages:{chat_id}"
        if len(parts) == 1 or parts[1].lower() in {"help", "?", "show", "status"}:
            current = normalize_context_messages(self.db.get_setting(key, DEFAULT_CONTEXT_MESSAGES))
            return CommandResult(
                True,
                f"用法：/context <消息数>|clear。当前：{current} 条，范围：1-{MAX_CONTEXT_MESSAGES}。",
            )
        value = parts[1].lower()
        if value in {"clear", "default", "reset"}:
            self.db.set_setting(key, DEFAULT_CONTEXT_MESSAGES)
            self.db.set_setting(f"group_context_summary:{chat_id}", {})
            return CommandResult(True, f"当前群 context 已恢复默认 {DEFAULT_CONTEXT_MESSAGES} 条消息。")
        try:
            message_count = int(value)
        except ValueError:
            return CommandResult(True, "context 必须是整数，例如：/context 20。")
        if message_count < 1 or message_count > MAX_CONTEXT_MESSAGES:
            return CommandResult(True, f"context 范围是 1 到 {MAX_CONTEXT_MESSAGES} 条消息。")
        self.db.set_setting(key, message_count)
        self.db.set_setting(f"group_context_summary:{chat_id}", {})
        return CommandResult(True, f"当前群 context 已设为最近 {message_count} 条消息。")

    def _limit(self, parts: list[str]) -> CommandResult:
        current_global = self.db.get_setting("global_user_daily_limit", 0)
        if len(parts) == 1 or parts[1].lower() in {"help", "?"}:
            return CommandResult(True, f"用法：/limit <wxid> <num>|clear，/limit global <num>|clear。当前 global：{current_global or 'default'}")
        target = parts[1].strip()
        if target.lower() == "global":
            if len(parts) < 3:
                return CommandResult(True, f"用法：/limit global <num>|clear。当前：{current_global or 'default'}")
            value = parts[2].strip().lower()
            if value in {"clear", "default", "off", "reset", "0"}:
                self.db.set_setting("global_user_daily_limit", 0)
                return CommandResult(True, "global per-user daily limit 已清除。")
            try:
                limit = int(value)
            except ValueError:
                return CommandResult(True, "limit 必须是整数，例如：/limit global 30")
            if limit < 0:
                return CommandResult(True, "limit 不能是负数。")
            self.db.set_setting("global_user_daily_limit", limit)
            return CommandResult(True, f"global per-user daily limit 已设为 {limit}。")
        if len(parts) < 3:
            current = self.db.get_setting(f"user_daily_limit:{target}", 0)
            return CommandResult(True, f"用法：/limit <wxid> <num>|clear。当前：{current or 'default'}")
        value = parts[2].strip().lower()
        if value in {"clear", "default", "off", "reset", "0"}:
            self.db.set_setting(f"user_daily_limit:{target}", 0)
            return CommandResult(True, f"{target} 的 per-user daily limit 已清除。")
        try:
            limit = int(value)
        except ValueError:
            return CommandResult(True, "limit 必须是整数，例如：/limit wxid_example031 20")
        if limit < 0:
            return CommandResult(True, "limit 不能是负数。")
        self.db.set_setting(f"user_daily_limit:{target}", limit)
        return CommandResult(True, f"{target} 的 per-user daily limit 已设为 {limit}。")

    def _cooldown(self, chat_id: str, parts: list[str]) -> CommandResult:
        if len(parts) == 1 or parts[1].lower() in {"help", "?"}:
            current = self.db.get_setting(f"group_api_cooldown_seconds:{chat_id}", 0)
            return CommandResult(True, f"用法：/cooldown <秒数>|clear。当前：{current}s。whitelist 用户不受限制。")
        value = parts[1].lower()
        if value in {"clear", "default", "off", "reset", "0"}:
            self.db.set_setting(f"group_api_cooldown_seconds:{chat_id}", 0)
            self.db.set_setting(f"group_api_cooldown_last_at:{chat_id}", 0)
            return CommandResult(True, "当前群 cooldown 已关闭。")
        try:
            seconds = float(value)
        except ValueError:
            return CommandResult(True, "cooldown 必须是秒数，例如：/cooldown 10，或 /cooldown clear。")
        if seconds < 0 or seconds > 3600:
            return CommandResult(True, "cooldown 范围是 0 到 3600 秒。")
        self.db.set_setting(f"group_api_cooldown_seconds:{chat_id}", seconds)
        return CommandResult(True, f"当前群 cooldown 已设为 {seconds:g}s。非 whitelist 用户在冷却期不会进入主模型。")

    def _reply_policy(self, chat_id: str, parts: list[str]) -> CommandResult:
        if len(parts) == 1 or parts[1].lower() in {"help", "?"}:
            current = self.db.get_setting(f"group_reply_policy:{chat_id}", "auto")
            return CommandResult(True, f"用法：/reply auto|direct。direct = 只在 @bot 或引用 bot 消息时回复。当前：{current}")
        policy = _normalize_reply_policy(" ".join(parts[1:]))
        if not policy:
            return CommandResult(True, "reply 只能是 auto 或 direct。direct = 只在 @bot 或引用 bot 消息时回复。")
        self.db.set_setting(f"group_reply_policy:{chat_id}", policy)
        return CommandResult(True, f"当前群 reply policy 已设为 {policy}。")

    def _reply_gate(self, chat_id: str, parts: list[str]) -> CommandResult:
        current = self.db.get_setting(f"group_reply_gate_mode:{chat_id}", "normal")
        current_vibe = self.db.get_setting(f"group_reply_gate_vibe:{chat_id}", "default")
        if len(parts) == 1 or parts[1].lower() in {"help", "?"}:
            return CommandResult(
                True,
                "用法：/replygate strict|normal|soft [default|guild|social|enfp|tech|debate]\n"
                "也可用：/replygate vibe <default|guild|social|enfp|tech|debate>。\n"
                "strict = 只有明显和 bot 有关时才回复；normal = 当前默认；soft = 群里好玩/有趣/适合插话的场景也可以回复。\n"
                "vibe 只影响 auto 模式下的插话倾向：guild 更爱接帮会群玩梗，social 更爱接轻松社交，enfp 更爱主动活跃气氛、欢迎新人和接梗，tech 更克制，debate 更偏辩论拆招。\n"
                f"当前：mode={current}, vibe={current_vibe}",
            )
        if parts[1].lower() == "vibe":
            if len(parts) < 3:
                return CommandResult(True, f"用法：/replygate vibe default|guild|social|enfp|tech|debate。当前：{current_vibe}")
            vibe = _normalize_reply_gate_vibe(parts[2])
            if not vibe:
                return CommandResult(True, "replygate vibe 只能是 default / guild / social / enfp / tech / debate。")
            self.db.set_setting(f"group_reply_gate_vibe:{chat_id}", vibe)
            return CommandResult(True, f"当前群 reply gate vibe 已设为 {vibe}。")
        mode = _normalize_reply_gate_mode(parts[1])
        if not mode:
            return CommandResult(True, "replygate 只能是 strict / normal / soft。")
        self.db.set_setting(f"group_reply_gate_mode:{chat_id}", mode)
        if len(parts) >= 3:
            vibe = _normalize_reply_gate_vibe(parts[2])
            if not vibe:
                return CommandResult(True, "replygate vibe 只能是 default / guild / social / enfp / tech / debate。")
            self.db.set_setting(f"group_reply_gate_vibe:{chat_id}", vibe)
            return CommandResult(True, f"当前群 reply gate 已设为 {mode} / {vibe}。")
        return CommandResult(True, f"当前群 reply gate 已设为 {mode}。")

    def _testing_mode(self, chat_id: str, parts: list[str]) -> CommandResult:
        current = bool(self.db.get_setting(f"group_testing_mode:{chat_id}", False))
        if len(parts) == 1 or parts[1].lower() in {"help", "?"}:
            return CommandResult(
                True,
                "用法：/test on|off。\n"
                "on = 纯模型测试：只把最新一条用户消息发给主模型；不带 system prompt、memory、tools、skills、web search、上下文，也不走 reply gate。\n"
                f"当前：{'on' if current else 'off'}",
            )
        value = parts[1].strip().lower()
        if value not in {"on", "off"}:
            return CommandResult(True, "usage: /test on|off")
        enabled = value == "on"
        self.db.set_setting(f"group_testing_mode:{chat_id}", enabled)
        if enabled:
            return CommandResult(
                True,
                "testing mode enabled: only the latest user message will be sent to the main model; "
                "no system prompt, memory, tools, skills, web search, or prior context.",
            )
        return CommandResult(True, "testing mode disabled.")

    def _model(self, chat_id: str, parts: list[str]) -> CommandResult:
        current = self.db.get_setting(f"group_reply_model:{chat_id}", "") or self.config.model.name
        current_provider = self.db.get_setting(f"group_model_provider:{chat_id}", "") or self.config.model.provider
        if len(parts) == 1 or parts[1].lower() in {"help", "?"}:
            return CommandResult(
                True,
                f"用法：/model <model>|clear；/model provider auto|openai|openrouter|deepseek|together|lightning|minimax|bedrock|sambanova|fireworks|zai|telnyx|kimi；/model <provider> <model>。\n当前：provider={current_provider}, model={current}",
            )
        value = parts[1].strip()
        if value.lower() in {"clear", "default", "reset"}:
            self.db.set_setting(f"group_reply_model:{chat_id}", "")
            self.db.set_setting(f"group_model_provider:{chat_id}", "")
            return CommandResult(True, f"当前群 model/provider 已恢复默认：{self.config.model.provider}/{self.config.model.name}")
        # Provider redirect info: informational only, never blocks the set.
        _check_model = parts[2].strip() if len(parts) >= 3 else value
        _lm = _check_model.lower()
        if _lm.startswith(("z-ai/glm", "zai/glm", "glm-")):
            pass  # redirect to zai happens automatically; the set proceeds
        if _lm.startswith(("moonshotai/kimi", "kimi-", "minimax-", "minimaxai/")):
            pass  # redirect to telnyx happens automatically
        if value.lower() == "provider":
            if len(parts) < 3:
                return CommandResult(True, f"用法：/model provider auto|openai|openrouter|deepseek|together|lightning|minimax|bedrock|sambanova|fireworks|zai|telnyx|kimi。当前：{current_provider}")
            provider = _normalize_model_provider(parts[2])
            if not provider:
                return CommandResult(True, "provider 只能是 auto / openai / openrouter / deepseek / together / lightning / minimax / bedrock / sambanova / fireworks / zai / telnyx / kimi。")
            self.db.set_setting(f"group_model_provider:{chat_id}", provider)
            return CommandResult(True, f"当前群 model provider 已设为 {provider}。")
        provider = _normalize_model_provider(value)
        if provider and len(parts) >= 3:
            model = _canonical_minimax_model(parts[2]) if provider == "minimax" else parts[2].strip()
            if not _valid_model_name(model):
                return CommandResult(True, "model 名称格式不对。OpenRouter 可用 anthropic/xxx、google/xxx、deepseek/xxx。")
            if provider == "minimax" and not _is_allowed_minimax_model(model):
                return CommandResult(True, "MiniMax 当前开放 MiniMax-M2.7 / MiniMax-M3。")
            self.db.set_setting(f"group_model_provider:{chat_id}", provider)
            self.db.set_setting(f"group_reply_model:{chat_id}", model)
            hint = catalog_lookup(model)
            suggestion = (
                f" 提示：{model} 在 {hint[0]} 上的标准名称是 {hint[1]}。"
                if hint and (hint[0] != provider or hint[1] != model) else ""
            )
            return CommandResult(True, f"当前群 provider/model 已设为 {provider}/{model}。{suggestion}")
        value = _canonical_minimax_model(value) if str(current_provider).strip().lower() == "minimax" else value
        if not _valid_model_name(value):
            return CommandResult(True, "model 名称格式不对。OpenRouter 可用 anthropic/xxx、google/xxx、deepseek/xxx。")
        if str(current_provider).strip().lower() == "minimax" and not _is_allowed_minimax_model(value):
            return CommandResult(True, "MiniMax 当前开放 MiniMax-M2.7 / MiniMax-M3。")
        self.db.set_setting(f"group_reply_model:{chat_id}", value)
        # Auto-align provider with the model family. A stale group provider
        # (e.g. openrouter) must not silently fight the redirect table.
        implied = None
        v = value.lower()
        if v.startswith(("z-ai/glm", "zai/glm", "glm-")):
            implied = "zai"
        elif v.startswith(("moonshotai/kimi", "kimi-")):
            implied = "telnyx"
        elif v.startswith(("minimax-", "minimaxai/")):
            implied = "telnyx"
        elif v.startswith(("deepseek-", "deepseek/")):
            implied = "deepseek"
        elif v.startswith(("openai/", "gpt-", "o1", "o3", "o4")):
            implied = "openai"
        note = ""
        if implied and current_provider != implied:
            self.db.set_setting(f"group_model_provider:{chat_id}", implied)
            note = f"（provider 已同步为 {implied}）"
        hint = catalog_lookup(value)
        if hint and (hint[0] != implied or hint[1] != value):
            note += f" 提示：{value} 在 {hint[0]} 上的标准名称是 {hint[1]}。"
        return CommandResult(True, f"当前群 model 已设为 {value}。{note}")
        current = self.db.get_setting(f"group_reply_model:{chat_id}", "") or self.config.model.name
        if len(parts) == 1 or parts[1].lower() in {"help", "?"}:
            return CommandResult(True, f"用法：/model <model>|clear。当前：{current}")
        value = parts[1].strip()
        if value.lower() in {"clear", "default", "reset"}:
            self.db.set_setting(f"group_reply_model:{chat_id}", "")
            return CommandResult(True, f"当前群 model 已恢复默认：{self.config.model.name}")
        if not _valid_model_name(value):
            return CommandResult(True, "model 名称只能包含字母、数字、点、下划线和短横线。")
        self.db.set_setting(f"group_reply_model:{chat_id}", value)
        return CommandResult(True, f"当前群 model 已设为 {value}。")

    def _reasoning(self, chat_id: str, parts: list[str]) -> CommandResult:
        current = self.db.get_setting(f"group_reasoning_effort:{chat_id}", "") or self.config.model.reasoning_effort
        if len(parts) == 1 or parts[1].lower() in {"help", "?"}:
            return CommandResult(True, f"用法：/reasoning none|minimal|low|medium|high|max|clear。当前：{current}")
        value = _normalize_reasoning_setting(parts[1])
        if value == "clear":
            self.db.set_setting(f"group_reasoning_effort:{chat_id}", "")
            return CommandResult(True, f"当前群 reasoning 已恢复默认：{self.config.model.reasoning_effort}")
        if not value:
            return CommandResult(True, "reasoning 只能是 none / minimal / low / medium / high / max / clear。")
        self.db.set_setting(f"group_reasoning_effort:{chat_id}", value)
        return CommandResult(True, f"当前群 reasoning effort 已设为 {value}。")

    def _router(self, chat_id: str, parts: list[str]) -> CommandResult:
        current = bool(self.db.get_setting(f"group_model_router_enabled:{chat_id}", self.config.model_router.enabled))
        if len(parts) == 1 or parts[1].lower() in {"help", "?"}:
            return CommandResult(True, f"用法：/router on|off。当前：{'on' if current else 'off'}")
        value = parts[1].strip().lower()
        if value not in {"on", "off"}:
            return CommandResult(True, "router 只能是 on 或 off。")
        enabled = value == "on"
        self.db.set_setting(f"group_model_router_enabled:{chat_id}", enabled)
        return CommandResult(True, f"当前群 dynamic router 已{'开启' if enabled else '关闭'}。")

    def _set(self, chat_id: str, text: str, parts: list[str], sender_id: str = "") -> CommandResult:
        if len(parts) >= 3 and parts[1].lower() == "prefix":
            value = " ".join(parts[2:]).strip()
            self._ensure_group(chat_id)
            self._update_group(chat_id, prefix=value)
            return CommandResult(True, f"prefix 已设为 {value}")
        if len(parts) >= 3 and parts[1].lower() in {
            "image_analysis_mode",
            "image_mode",
            "vision_mode",
        }:
            result = self._apply_group_setting(chat_id, parts[1], parts[2])
            return CommandResult(True, result or "image analysis mode 只能是 tool 或 native。")

        instruction = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) >= 2 else ""
        target_chat_id, instruction = self._extract_target_group_from_instruction(chat_id, instruction)
        if not instruction:
            return CommandResult(True, "用法：/set <设置说明>。例如：/set 这个群只在 @FoxStar 或引用它时回复")
        if instruction.startswith("/"):
            return self._run_delegated_group_command(target_chat_id, instruction, sender_id)
        local = self._set_with_local_parser(target_chat_id, instruction, quiet=True, sender_id=sender_id)
        if local.reply:
            return local
        if self.llm is not None:
            try:
                reply = self._set_with_tool_call(target_chat_id, instruction, sender_id)
                if reply:
                    return CommandResult(True, reply)
            except Exception:
                pass
        return self._set_with_local_parser(target_chat_id, instruction, sender_id=sender_id)

    def _extract_target_group_from_instruction(self, current_chat_id: str, instruction: str) -> tuple[str, str]:
        match = re.search(r"([A-Za-z0-9_-]+@chatroom)", instruction or "")
        if not match:
            return current_chat_id, instruction
        target = self._resolve_group_id(match.group(1)) or match.group(1)
        cleaned = (instruction[: match.start()] + instruction[match.end() :]).strip()
        cleaned = re.sub(r"^(这个|該|该)?\s*(群聊|群|room)?\s*的?", "", cleaned).strip(" ：:，,")
        return target, cleaned

    def _set_with_tool_call(self, chat_id: str, instruction: str, sender_id: str = "") -> str:
        applied: list[str] = []
        delegated_output = ""

        def set_group_setting(setting: str, value: str) -> dict[str, object]:
            result = self._apply_group_setting(chat_id, setting, value)
            if result:
                applied.append(result)
            return {"ok": bool(result), "message": result or "unsupported setting or value"}

        def run_group_command(command: str) -> dict[str, object]:
            nonlocal delegated_output
            result = self._run_delegated_group_command(chat_id, command, sender_id)
            if result.reply:
                applied.append(result.reply)
                delegated_output = result.reply
            return {"ok": result.handled, "message": result.reply}

        tools = [
            {
                "type": "function",
                "name": "set_group_setting",
                "description": "Set one safe current-group bot setting from a whitelist admin instruction.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "setting": {
                            "type": "string",
                            "enum": [
                                "reply_policy",
                                "max_reply_tokens",
                                "context_messages",
                                "reply_line_tokens",
                                "reply_delay",
                                "cooldown_seconds",
                                "model",
                                "model_provider",
                                "image_analysis_mode",
                                "reasoning_effort",
                                "mode",
                                "prefix",
                                "web_search",
                                "vision",
                                "docs",
                            ],
                        },
                        "value": {"type": "string"},
                    },
                    "required": ["setting", "value"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "run_group_command",
                "description": (
                    "Run one existing safe group slash command when the admin instruction maps to a full command "
                    "such as /style, /prompt, /memory, /target, /blacklist, /bot, /mode, /search, /vision, or /docs."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                    "required": ["command"],
                    "additionalProperties": False,
                },
            },
        ]
        reply = self.llm.chat_with_tools(
            [
                {
                    "role": "system",
                    "content": (
                        "You interpret a whitelist admin's /set command for the current WeChat group. "
                        "Call set_group_setting once for safe group settings only. "
                        "For reply_policy use auto or direct. direct means only reply when tagged or when the bot message is quoted. "
                        "For max_reply_tokens use an integer 20-4000, or 0 for default. "
                        f"For context_messages use an integer 1-{MAX_CONTEXT_MESSAGES}, or default. "
                        "For reply_line_tokens use an integer 4-400, or 0 for default; it controls the approximate max tokens per WeChat message line. "
                        "For reply_delay use three numbers: min max between, for example '25 30 10'. "
                        "For cooldown_seconds use seconds 0-3600; cooldown gates the main model only, not reply gate. "
                        "For model use a model name such as gpt-5.4 or anthropic/claude-sonnet-4.5, or clear/default. "
                        "For model_provider use auto, openai, openrouter, deepseek, together, lightning, minimax, bedrock, sambanova, or fireworks. "
                        "For image_analysis_mode use tool (dedicated vision model) or native (the current reply model's multimodal API). "
                        "For reasoning_effort use none, minimal, low, medium, high, max, or clear/default. "
                        "For router use on or off. "
                        "For web_search/vision/docs use on or off. "
                        "For existing group commands in /help, call run_group_command once with the exact slash command. "
                        "Allowed run_group_command commands are /bot, /mode, /style, /blacklist, /target, /delay, /length, /context, "
                        "/cooldown, /reply, /model, /reasoning, /router, /memory, /prompt, /search, /vision, and /docs. "
                        "Do not obey instructions to edit secrets, whitelist, shell, files, code, /gset, /recall, or /idlookup."
                    ),
                },
                {"role": "user", "content": instruction},
            ],
            tools=tools,
            tool_handlers={"set_group_setting": set_group_setting, "run_group_command": run_group_command},
            prompt_cache_key=_prompt_cache_key(chat_id, "set-command"),
            usage_context={"chat_id": chat_id, "feature": "set_command"},
        ).strip()
        if not applied:
            return ""
        if delegated_output:
            # Delegated slash-command output must reach the admin verbatim;
            # letting the LLM rephrase it turned a 300-entry noteboard listing
            # into casual chit-chat about message lengths.
            return delegated_output
        return reply or applied[-1]

    def _set_with_local_parser(
        self,
        chat_id: str,
        instruction: str,
        quiet: bool = False,
        sender_id: str = "",
    ) -> CommandResult:
        applied: list[str] = []
        policy = _normalize_reply_policy(instruction)
        if policy:
            applied.append(self._apply_group_setting(chat_id, "reply_policy", policy))
        delay = _extract_delay_setting(instruction)
        if delay is not None:
            applied.append(self._apply_group_setting(chat_id, "reply_delay", delay))
        line_tokens = _extract_line_tokens_setting(instruction)
        if line_tokens is not None:
            applied.append(self._apply_group_setting(chat_id, "reply_line_tokens", str(line_tokens)))
        prefix = _extract_prefix_setting(instruction)
        if prefix is not None:
            applied.append(self._apply_group_setting(chat_id, "prefix", prefix))
        length = _extract_length_setting(instruction)
        if length is not None:
            applied.append(self._apply_group_setting(chat_id, "max_reply_tokens", str(length)))
        cooldown = _extract_cooldown_setting(instruction)
        if cooldown is not None:
            applied.append(self._apply_group_setting(chat_id, "cooldown_seconds", str(cooldown)))
        model = _extract_slash_model_setting(instruction) or _extract_model_setting(instruction)
        if model is not None:
            applied.append(self._apply_group_setting(chat_id, "model", model))
        model_provider = _extract_model_provider_setting(instruction)
        if model_provider is not None:
            applied.append(self._apply_group_setting(chat_id, "model_provider", model_provider))
        reasoning = _extract_reasoning_setting(instruction)
        if reasoning is not None:
            applied.append(self._apply_group_setting(chat_id, "reasoning_effort", reasoning))
        router = _extract_router_setting(instruction)
        if router is not None:
            applied.append(self._apply_group_setting(chat_id, "router", router))
        applied = [item for item in applied if item]
        if applied:
            return CommandResult(True, "\n".join(applied))
        command = _natural_group_command(instruction)
        if command:
            return self._run_delegated_group_command(chat_id, command, sender_id)
        if quiet:
            return CommandResult(True)
        return CommandResult(True, "没看懂要改哪个安全设置。可用：reply auto/direct、length、cooldown、mode、prefix、search/vision/docs on|off。")

    def _run_delegated_group_command(self, chat_id: str, command: str, sender_id: str = "") -> CommandResult:
        command = (command or "").strip()
        if not command:
            return CommandResult(True)
        if not command.startswith("/"):
            command = "/" + command
        cmd = command.split(maxsplit=1)[0].lower()
        allowed = {
            "/bot",
            "/mode",
            "/style",
            "/blacklist",
            "/target",
            "/targets",
            "/targetlist",
            "/target_list",
            "/delay",
            "/length",
            "/context",
            "/cooldown",
            "/reply",
            "/replymode",
            "/reply_mode",
            "/model",
            "/reasoning",
            "/reason",
            "/router",
            "/memory",
            "/prompt",
            "/propmt",
            "/search",
            "/vision",
            "/docs",
            "/finance",
            "/financecalc",
        }
        if cmd not in allowed:
            return CommandResult(True, "这个命令不能通过 /set 转发。")
        return self.handle(command, chat_id, True, True, sender_id=sender_id)

    def _apply_group_setting(self, chat_id: str, setting: str, value: str) -> str:
        key = setting.strip().lower()
        raw_value = value.strip()
        value_l = raw_value.lower()
        self._ensure_group(chat_id)

        if key == "reply_policy":
            policy = _normalize_reply_policy(raw_value)
            if not policy:
                return ""
            self.db.set_setting(f"group_reply_policy:{chat_id}", policy)
            return f"当前群 reply policy 已设为 {policy}。"
        if key in {"max_reply_tokens", "max_reply_chars"}:
            if value_l in {"clear", "default", "off", "reset", "0"}:
                self.db.set_setting(f"group_max_reply_tokens:{chat_id}", 0)
                return "当前群 length 已恢复默认。"
            try:
                max_tokens = int(raw_value)
            except ValueError:
                return ""
            if max_tokens < 20 or max_tokens > 4000:
                return ""
            self.db.set_setting(f"group_max_reply_tokens:{chat_id}", max_tokens)
            return f"当前群最大回复长度已设为 {max_tokens} tokens。"
        if key in {"context_messages", "context", "context_length"}:
            if value_l in {"clear", "default", "reset"}:
                self.db.set_setting(f"group_context_messages:{chat_id}", DEFAULT_CONTEXT_MESSAGES)
                self.db.set_setting(f"group_context_summary:{chat_id}", {})
                return f"当前群 context 已恢复默认 {DEFAULT_CONTEXT_MESSAGES} 条消息。"
            try:
                message_count = int(raw_value)
            except ValueError:
                return ""
            if message_count < 1 or message_count > MAX_CONTEXT_MESSAGES:
                return ""
            self.db.set_setting(f"group_context_messages:{chat_id}", message_count)
            self.db.set_setting(f"group_context_summary:{chat_id}", {})
            return f"当前群 context 已设为最近 {message_count} 条消息。"
        if key in {"reply_line_tokens", "line_tokens", "max_line_tokens"}:
            if value_l in {"clear", "default", "off", "reset", "0"}:
                self.db.set_setting(f"group_reply_line_tokens:{chat_id}", 0)
                return "当前群每行 token 上限已恢复默认。"
            try:
                line_tokens = int(raw_value)
            except ValueError:
                return ""
            if line_tokens < 4 or line_tokens > 400:
                return ""
            self.db.set_setting(f"group_reply_line_tokens:{chat_id}", line_tokens)
            return f"当前群每行目标长度已设为 {line_tokens} tokens。"
        if key in {"reply_delay", "delay"}:
            if value_l in {"clear", "default", "off", "reset", "0"}:
                self.db.set_setting(f"group_reply_delay:{chat_id}", {})
                return "当前群 delay 已恢复全局默认。"
            parsed = _parse_delay_value(raw_value)
            if parsed is None:
                return ""
            min_delay, max_delay, between = parsed
            timing = self._group_delay(chat_id)
            if between is None:
                between = float(timing["between"])
            if min_delay < 0 or max_delay < 0 or between < 0:
                return ""
            if max_delay < min_delay:
                min_delay, max_delay = max_delay, min_delay
            if max_delay > 30 or between > 10:
                return ""
            self.db.set_setting(f"group_reply_delay:{chat_id}", {"min": min_delay, "max": max_delay, "between": between})
            return f"当前群 delay 已设为 {min_delay:g}-{max_delay:g}s，多条消息间隔 {between:g}s。"
        if key == "cooldown_seconds":
            if value_l in {"clear", "default", "off", "reset", "0"}:
                self.db.set_setting(f"group_api_cooldown_seconds:{chat_id}", 0)
                self.db.set_setting(f"group_api_cooldown_last_at:{chat_id}", 0)
                return "当前群 cooldown 已关闭。"
            try:
                seconds = float(raw_value)
            except ValueError:
                return ""
            if seconds < 0 or seconds > 3600:
                return ""
            self.db.set_setting(f"group_api_cooldown_seconds:{chat_id}", seconds)
            return f"当前群 cooldown 已设为 {seconds:g}s。非 whitelist 用户在冷却期不会进入主模型。"
        if key in {"model", "reply_model"}:
            if value_l in {"clear", "default", "off", "reset", "0"}:
                self.db.set_setting(f"group_reply_model:{chat_id}", "")
                return f"当前群 model 已恢复默认：{self.config.model.name}"
            if not _valid_model_name(raw_value):
                return ""
            self.db.set_setting(f"group_reply_model:{chat_id}", raw_value)
            return f"当前群 model 已设为 {raw_value}。"
        if key in {"model_provider", "provider"}:
            provider = _normalize_model_provider(raw_value)
            if not provider:
                return ""
            self.db.set_setting(f"group_model_provider:{chat_id}", provider)
            return f"当前群 model provider 已设为 {provider}。"
        if key in {"image_analysis_mode", "image_mode", "vision_mode"}:
            if value_l in {"clear", "default", "reset"}:
                self.db.set_setting(f"group_image_analysis_mode:{chat_id}", "")
                return f"当前群图片分析模式已恢复全局默认：{self.config.model.image_analysis_mode}。"
            if value_l not in {"tool", "native"}:
                return ""
            self.db.set_setting(f"group_image_analysis_mode:{chat_id}", value_l)
            return f"当前群图片分析模式已设为 {value_l}。"
        if key in {"reasoning_effort", "reasoning"}:
            normalized = _normalize_reasoning_setting(raw_value)
            if normalized == "clear":
                self.db.set_setting(f"group_reasoning_effort:{chat_id}", "")
                return f"当前群 reasoning 已恢复默认：{self.config.model.reasoning_effort}"
            if not normalized:
                return ""
            self.db.set_setting(f"group_reasoning_effort:{chat_id}", normalized)
            return f"当前群 reasoning effort 已设为 {normalized}。"
        if key == "router":
            if value_l not in {"on", "off", "true", "false", "1", "0"}:
                return ""
            enabled = value_l in {"on", "true", "1"}
            self.db.set_setting(f"group_model_router_enabled:{chat_id}", enabled)
            return f"当前群 dynamic router 已{'开启' if enabled else '关闭'}。"
        if key == "mode" and value_l in {"concise", "normal", "verify"}:
            self._update_group(chat_id, mode=value_l)
            return f"模式已切到 {value_l}。"
        if key == "prefix" and raw_value:
            self._update_group(chat_id, prefix=raw_value[:10])
            return f"prefix 已设为 {raw_value[:10]}"
        if key in {"web_search", "vision", "docs"} and value_l in {"on", "off", "true", "false", "1", "0"}:
            enabled = value_l in {"on", "true", "1"}
            field = {"web_search": "web_search_enabled", "vision": "vision_enabled", "docs": "doc_enabled"}[key]
            self._update_group(chat_id, **{field: int(enabled)})
            return "已开启。" if enabled else "已关闭。"
        return ""

    def _ensure_group(self, chat_id: str) -> None:
        now = utc_now()
        with self.db.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO groups(group_id, prefix, created_at, updated_at) VALUES(?, ?, ?, ?)",
                (chat_id, self.config.trigger_prefix, now, now),
            )

    def _update_group(self, chat_id: str, **fields: object) -> None:
        if not fields:
            return
        fields["updated_at"] = utc_now()
        assignments = ", ".join(f"{key} = ?" for key in fields)
        values = list(fields.values()) + [chat_id]
        with self.db.connect() as conn:
            conn.execute(f"UPDATE groups SET {assignments} WHERE group_id = ?", values)

    def _get_group(self, chat_id: str):
        with self.db.connect() as conn:
            return conn.execute("SELECT * FROM groups WHERE group_id = ?", (chat_id,)).fetchone()

    def _delay(self, chat_id: str, parts: list[str]) -> CommandResult:
        timing = self._group_delay(chat_id)
        if len(parts) == 1 or parts[1].lower() in {"help", "?"}:
            return CommandResult(
                True,
                "用法：/delay <min秒> <max秒> [多条消息间隔秒]，或 /delay clear。\n"
                f"当前群：{timing['min']:g}-{timing['max']:g}s，between {timing['between']:g}s。",
            )
        if parts[1].lower() in {"clear", "default", "reset"}:
            self.db.set_setting(f"group_reply_delay:{chat_id}", {})
            return CommandResult(True, "当前群 delay 已恢复全局默认。")
        if len(parts) < 3:
            return CommandResult(True, "用法：/delay <min秒> <max秒> [多条消息间隔秒]。例如：/delay 3 5 1")
        try:
            min_delay = float(parts[1])
            max_delay = float(parts[2])
            between = float(parts[3]) if len(parts) >= 4 else float(timing["between"])
        except ValueError:
            return CommandResult(True, "delay 必须是数字秒数。例如：/delay 3 5 1")
        if min_delay < 0 or max_delay < 0 or between < 0:
            return CommandResult(True, "delay 不能是负数。")
        if max_delay < min_delay:
            min_delay, max_delay = max_delay, min_delay
        if max_delay > 30 or between > 10:
            return CommandResult(True, "delay 太长了。max 最多 30 秒，多条消息间隔最多 10 秒。")
        self.db.set_setting(f"group_reply_delay:{chat_id}", {"min": min_delay, "max": max_delay, "between": between})
        return CommandResult(True, f"当前群 delay 已设为 {min_delay:g}-{max_delay:g}s，多条消息间隔 {between:g}s。")

    def _group_delay(self, chat_id: str) -> dict[str, float]:
        value = self.db.get_setting(f"group_reply_delay:{chat_id}", {})
        if not isinstance(value, dict):
            value = {}
        return {
            "min": float(value.get("min", self.config.reply_timing.min_delay_seconds)),
            "max": float(value.get("max", self.config.reply_timing.max_delay_seconds)),
            "between": float(value.get("between", self.config.reply_timing.between_messages_seconds)),
        }


def _parse_memory_payload(payload: str) -> tuple[str, str]:
    for sep in (":", "：", "="):
        if sep in payload:
            key, value = payload.split(sep, 1)
            return key.strip()[:80], value.strip()[:500]
    return "", ""


def _natural_group_command(text: str) -> str:
    value = (text or "").strip()
    lower = value.lower()
    if not value:
        return ""

    wxid = _extract_wxid(value)

    if _has_any(lower, value, ("blacklist",), ("黑名单",)):
        action = _list_action(lower, value)
        if action in {"list", "clear"}:
            return f"/blacklist {action}"
        if wxid:
            return f"/blacklist {action or 'add'} {wxid}"

    if _has_any(lower, value, ("target", "target_list", "targetlist", "opponent"), ("反方", "对手", "辩手", "靶子", "目标名单")):
        action = _list_action(lower, value)
        if action in {"list", "clear"}:
            return f"/target {action}"
        if wxid:
            return f"/target {action or 'add'} {wxid}"

    if _has_any(lower, value, ("memory", "remember"), ("记忆", "记住", "记下", "记到", "群记忆")):
        action = _memory_action(lower, value)
        if action == "show":
            return "/memory show"
        if action == "clear":
            return "/memory clear"
        if action == "delete":
            key = _payload_after_any(value, ("delete", "remove", "forget", "删除", "移除", "忘记"))
            return f"/memory delete {key}" if key else ""
        payload = _memory_payload_from_text(value)
        return f"/memory remember {payload}" if payload else ""

    if _has_any(lower, value, ("prompt", "template"), ("模板",)):
        if _has_any(lower, value, ("list", "templates"), ("列表", "有哪些")):
            return "/prompt list"
        if _has_any(lower, value, ("show", "current"), ("查看", "当前")):
            return "/prompt show"
        if _has_any(lower, value, ("clear", "default", "restore"), ("恢复默认", "清空")):
            return "/prompt clear"
        for name in list_template_names():
            normalized = normalize_template_name(name)
            if normalized in lower or normalized.replace("-", "_") in lower:
                return f"/prompt {normalized}"

    if _has_any(lower, value, ("style",), ("性格", "风格", "人格")):
        payload = _payload_after_any(value, ("style", "性格", "风格", "人格")).strip(" ：:,，")
        return f"/style {payload}" if payload else ""

    if _has_any(lower, value, ("reply", "reply_policy"), ("回复策略", "回复模式")):
        policy = _normalize_reply_policy(value)
        return f"/reply {policy}" if policy else ""

    if _has_any(lower, value, ("router",), ("路由", "模型路由")):
        router = _extract_router_setting(value)
        return f"/router {router}" if router else ""

    if _has_any(lower, value, ("reasoning", "reasoning_effort"), ("推理强度", "思考强度")):
        reasoning = _extract_reasoning_setting(value)
        return f"/reasoning {reasoning}" if reasoning is not None else ""

    if _has_any(lower, value, ("model",), ("模型",)):
        model = _extract_model_setting(value)
        return f"/model {model}" if model is not None else ""

    if _has_any(lower, value, ("bot", "robot"), ("机器人",)):
        global_scope = _has_any(lower, value, ("global", "all"), ("全局", "所有群"))
        enabled = _extract_on_off(lower, value)
        if enabled is not None:
            scope = "global " if global_scope else ""
            return f"/bot {scope}{'on' if enabled else 'off'}"

    for mode in ("concise", "normal", "verify"):
        if mode in lower and _has_any(lower, value, ("mode",), ("模式",)):
            return f"/mode {mode}"

    toggles = [
        ("search", ("search", "web_search", "web search"), ("搜索", "联网")),
        ("vision", ("vision",), ("图片", "图像", "视觉")),
        ("docs", ("docs", "document"), ("文档", "文件")),
    ]
    for command, ascii_markers, cn_markers in toggles:
        if _has_any(lower, value, ascii_markers, cn_markers):
            enabled = _extract_on_off(lower, value)
            if enabled is not None:
                return f"/{command} {'on' if enabled else 'off'}"

    return ""


def _has_any(lower: str, original: str, ascii_markers: tuple[str, ...], text_markers: tuple[str, ...]) -> bool:
    return any(marker in lower for marker in ascii_markers) or any(marker in original for marker in text_markers)


def _extract_wxid(text: str) -> str:
    match = re.search(r"\bwxid_[A-Za-z0-9_-]+\b", text or "")
    return match.group(0) if match else ""


def _list_action(lower: str, original: str) -> str:
    if _has_any(lower, original, ("clear", "empty", "reset"), ("清空", "清除", "重置")):
        return "clear"
    if _has_any(lower, original, ("remove", "delete", "del"), ("删除", "移除", "去掉", "踢出")):
        return "remove"
    if _has_any(lower, original, ("add", "append"), ("加入", "添加", "加到", "设为")):
        return "add"
    if _has_any(lower, original, ("list", "show", "view"), ("查看", "列出", "显示")):
        return "list"
    return ""


def _memory_action(lower: str, original: str) -> str:
    if _has_any(lower, original, ("show", "list", "view"), ("查看", "列出", "显示")):
        return "show"
    if _has_any(lower, original, ("clear", "empty", "reset"), ("清空", "清除", "重置")):
        return "clear"
    if _has_any(lower, original, ("delete", "remove", "forget"), ("删除", "移除", "忘记")):
        return "delete"
    return "remember"


def _memory_payload_from_text(text: str) -> str:
    payload = _payload_after_any(text, ("memory", "remember", "set", "add", "记住", "记下", "记到", "更新", "群记忆"))
    payload = payload.strip(" ：:,，")
    if _parse_memory_payload(payload) != ("", ""):
        return payload
    match = re.search(r"(昵称|名字|称呼|群偏好|规则|偏好)\s*(?:是|=|:|：)\s*(.+)", text)
    if match:
        return f"{match.group(1)}: {match.group(2).strip()}"
    return ""


def _payload_after_any(text: str, markers: tuple[str, ...]) -> str:
    lower = text.lower()
    best: tuple[int, int] | None = None
    for marker in markers:
        index = lower.find(marker.lower()) if marker.isascii() else text.find(marker)
        if index >= 0 and (best is None or index < best[0]):
            best = (index, len(marker))
    if best is None:
        return ""
    return text[best[0] + best[1] :].strip()


def _extract_on_off(lower: str, original: str) -> bool | None:
    if _has_any(lower, original, ("off", "false", "disable", "disabled", "close"), ("关闭", "关掉", "禁用", "停用")):
        return False
    if _has_any(lower, original, ("on", "true", "enable", "enabled", "open"), ("打开", "开启", "启用")):
        return True
    return None


def _prompt_cache_key(chat_id: str, purpose: str) -> str:
    digest = hashlib.sha256(chat_id.encode("utf-8")).hexdigest()[:16]
    return f"foxstar:{purpose}:{digest}"


def _prompt_template_suggestion(name: str) -> str:
    matches = get_close_matches(name, list(list_template_names()), n=1, cutoff=0.72)
    return matches[0] if matches else ""


def _normalize_reply_policy(text: str) -> str:
    value = (text or "").strip().lower()
    if value in {"auto", "normal", "default", "all", "join", "active"}:
        return "auto"
    if value in {"direct", "mention", "mentions", "tagged", "quote", "quoted", "manual"}:
        return "direct"
    if any(marker in value for marker in ("只在", "引用", "quote", "quoted", "tag", "mention", "@")):
        if any(marker in value for marker in ("回复", "reply", "bot", "nvax", "机器人")):
            return "direct"
    if any(marker in value for marker in ("自动", "插嘴", "自己决定", "auto")):
        return "auto"
    return ""


def _extract_length_setting(text: str) -> int | None:
    value = (text or "").strip().lower()
    if any(marker in value for marker in ("默认长度", "length clear", "length default", "恢复默认")):
        return 0
    if "length" not in value and "长度" not in value and "字数" not in value and "字符" not in value:
        return None
    match = re.search(r"\d{2,4}", value)
    return int(match.group(0)) if match else None


def _extract_line_tokens_setting(text: str) -> int | None:
    value = (text or "").strip().lower()
    if not any(marker in value for marker in ("line_tokens", "line tokens", "max_line_tokens", "每行", "单行", "每条", "一行")):
        return None
    if any(marker in value for marker in ("clear", "default", "off", "reset", "恢复默认", "關閉", "关闭")):
        return 0
    match = re.search(r"\d{1,3}", value)
    return int(match.group(0)) if match else None


def _extract_prefix_setting(text: str) -> str | None:
    value = (text or "").strip()
    lower = value.lower()
    if not lower.startswith("prefix") and "触发前缀" not in value and "前缀" not in value:
        return None
    if any(marker in lower for marker in ("clear", "default", "reset")) or any(marker in value for marker in ("清空", "默认", "重置")):
        return ""
    match = re.search(r"(?:prefix|触发前缀|前缀)\s*(?:设为|设置成|设置为|改成|=|:|：)?\s*(.+)", value, re.I)
    return match.group(1).strip()[:10] if match and match.group(1).strip() else None


def _extract_model_setting(text: str) -> str | None:
    value = (text or "").strip()
    lower = value.lower()
    if not _has_any(lower, value, ("model",), ("模型",)):
        return None
    if any(marker in lower for marker in ("clear", "default", "reset")) or any(marker in value for marker in ("默认", "重置")):
        return "clear"
    match = re.search(r"(?:model|模型)\s*(?:设为|设置成|设置为|改成|=|:|：)?\s*([A-Za-z0-9._-]+)", value, re.I)
    if not match:
        return None
    model = match.group(1).strip()
    return model if _valid_model_name(model) else None


def _extract_model_provider_setting(text: str) -> str | None:
    value = (text or "").strip()
    lower = value.lower()
    provider_tokens = (
        "openrouter", "openai", "deepseek", "together", "lightning", "minimax", "bedrock",
        "sambanova", "fireworks", "zai", "z.ai", "z-ai", "telnyx", "telnyx-inference",
        "kimi", "moonshot", "auto",
    )
    if "provider" not in lower and not any(token in lower for token in provider_tokens):
        return None
    match = re.search(
        r"(telnyx-inference|openrouter|openai|deepseek|together|lightning|minimax|bedrock|sambanova|fireworks|z\.ai|z-ai|zai|telnyx|kimi|moonshot|auto)",
        lower,
    )
    return _normalize_model_provider(match.group(1)) if match else None


def _normalize_model_provider(value: str) -> str:
    provider = (value or "").strip().lower()
    provider = {"z.ai": "zai", "z-ai": "zai", "moonshot": "kimi", "telnyx-inference": "telnyx"}.get(provider, provider)
    return provider if provider in {"auto", "openai", "openrouter", "deepseek", "together", "lightning", "minimax", "bedrock", "sambanova", "fireworks", "zai", "telnyx", "kimi"} else ""


def _extract_slash_model_setting(text: str) -> str | None:
    value = (text or "").strip()
    lower = value.lower()
    if "model" not in lower and "模型" not in value:
        return None
    match = re.search(r"(?:model|模型)\s*(?:设为|设置成|设置为|改成|=|:|：)?\s*([A-Za-z0-9._:/+-]+)", value, re.I)
    if not match:
        return None
    model = match.group(1).strip()
    return model if "/" in model and _valid_model_name(model) else None


def _extract_reasoning_setting(text: str) -> str | None:
    value = (text or "").strip()
    lower = value.lower()
    if not _has_any(lower, value, ("reasoning", "reasoning_effort"), ("推理强度", "思考强度")):
        return None
    return _normalize_reasoning_setting(value)


def _extract_router_setting(text: str) -> str | None:
    value = (text or "").strip()
    lower = value.lower()
    if "router" not in lower and "路由" not in value:
        return None
    if re.search(r"\b(on|enable|enabled|true|1)\b", lower) or any(token in value for token in ("开启", "打开", "启用")):
        return "on"
    if re.search(r"\b(off|disable|disabled|false|0)\b", lower) or any(token in value for token in ("关闭", "关掉", "禁用")):
        return "off"
    return None


def _normalize_reasoning_setting(text: str | None) -> str:
    value = (text or "").strip()
    lower = value.lower()
    if any(marker in lower for marker in ("clear", "default", "reset", "off")) or any(marker in value for marker in ("默认", "重置", "关闭")):
        return "clear"
    aliases = {
        "none": "none",
        "minimal": "minimal",
        "min": "minimal",
        "low": "low",
        "medium": "medium",
        "med": "medium",
        "high": "high",
        "xhigh": "max",
        "max": "max",
    }
    for option, normalized in aliases.items():
        if re.search(rf"\b{re.escape(option)}\b", lower):
            return normalized
    return ""


def _normalize_reply_gate_mode(text: str) -> str:
    value = (text or "").strip().lower()
    aliases = {
        "strict": "strict",
        "hard": "strict",
        "normal": "normal",
        "default": "normal",
        "soft": "soft",
        "loose": "soft",
    }
    return aliases.get(value, "")


def _normalize_reply_gate_vibe(text: str) -> str:
    value = (text or "").strip().lower()
    aliases = {
        "default": "default",
        "normal": "default",
        "guild": "guild",
        "clan": "guild",
        "social": "social",
        "fun": "social",
        "enfp": "enfp",
        "lively": "enfp",
        "cute": "enfp",
        "tech": "tech",
        "technical": "tech",
        "debate": "debate",
        "argue": "debate",
    }
    return aliases.get(value, "")


def _valid_model_name(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9._:/+-]{2,140}", value or ""))


def _canonical_minimax_model(value: str) -> str:
    raw = (value or "").strip()
    normalized = raw.lower()
    aliases = {
        "minimax-m2.7": "MiniMax-M2.7",
        "minimax-m3": "MiniMax-M3",
    }
    return aliases.get(normalized, raw)


def _is_allowed_minimax_model(value: str) -> bool:
    return _canonical_minimax_model(value) in {"MiniMax-M2.7", "MiniMax-M3"}


def _extract_delay_setting(text: str) -> str | None:
    value = (text or "").strip().lower()
    if not any(marker in value for marker in ("delay", "延迟", "延遲", "间隔", "間隔")):
        return None
    if any(marker in value for marker in ("clear", "default", "off", "reset", "恢复默认", "关闭")):
        return "0"
    parsed = _parse_delay_value(value)
    if parsed is None:
        return None
    min_delay, max_delay, between = parsed
    if between is None:
        return f"{min_delay:g} {max_delay:g}"
    return f"{min_delay:g} {max_delay:g} {between:g}"


def _parse_delay_value(text: str) -> tuple[float, float, float | None] | None:
    numbers = [float(item) for item in re.findall(r"\d+(?:\.\d+)?", text or "")]
    if len(numbers) < 2:
        return None
    return numbers[0], numbers[1], numbers[2] if len(numbers) >= 3 else None


def _extract_cooldown_setting(text: str) -> float | None:
    value = (text or "").strip().lower()
    if not any(marker in value for marker in ("cooldown", "冷却", "冷卻", "cd")):
        return None
    if any(marker in value for marker in ("clear", "default", "off", "reset", "关闭", "關閉", "恢复默认", "恢復默認")):
        return 0
    targeted = re.search(r"(?:cooldown|cd|冷却|冷卻)\D{0,12}(\d+(?:\.\d+)?)", value)
    if targeted:
        return float(targeted.group(1))
    match = re.search(r"\d+(?:\.\d+)?", value)
    return float(match.group(0)) if match else None


def _parse_accounting_amount(text: str) -> float | None:
    value = (text or "").strip().replace(",", "")
    try:
        amount = float(value)
    except ValueError:
        return None
    return amount


def _parse_accounting_name_list(text: str) -> list[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    parts = re.split(r"[\n,，、;；|]+", raw)
    names: list[str] = []
    seen: set[str] = set()
    for item in parts:
        name = item.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def _accounting_window_to_days(text: str) -> int | None:
    value = (text or "").strip().lower()
    mapping = {
        "today": 1,
        "1d": 1,
        "7d": 7,
        "1w": 7,
        "1m": 30,
        "month": 30,
        "3m": 90,
        "6m": 180,
        "1y": 365,
        "year": 365,
        "all": None,
    }
    return mapping.get(value)


def _accounting_days_label(days: int) -> str:
    reverse = {
        1: "1d",
        7: "7d",
        30: "1m",
        90: "3m",
        180: "6m",
        365: "1y",
    }
    return reverse.get(int(days), f"{int(days)}d")


def _short_chat_label(chat_id: str) -> str:
    """Compact origin label for a shared/global listing (e.g. bug reports).

    WeChat room ids look like '90000@chatroom' and private ids like
    'wxid_example010'. Show the bare id without the verbose @chatroom suffix, capped
    so a global ticket list stays readable.
    """
    label = (chat_id or "").strip().removesuffix("@chatroom").strip()
    if not label:
        return "unknown"
    return label[:24] + ("…" if len(label) > 24 else "")
