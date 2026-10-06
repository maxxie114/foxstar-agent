from __future__ import annotations

import logging
import subprocess
import time
from typing import Any

from .persistence import Database

LOG = logging.getLogger(__name__)

ALERT_COOLDOWN_SECONDS = 1800
GATE_FAILURE_ALERT_THRESHOLD = 5
SILENCE_ALERT_SECONDS = 900


class HealthMonitor:

    def __init__(self, db: Database, owner_wxid: str) -> None:
        self.db = db
        self.owner_wxid = owner_wxid
        self.gate_failures = 0
        self.gate_recent_errors: list[str] = []
        self.last_gate_degraded_alert = 0.0
        self.last_gate_alert = 0.0
        self.last_reply_time = time.time()
        self.last_silence_alert = 0.0
        self._active_alerts: dict[str, str] = {}

    def record_gate_success(self) -> None:
        self.gate_failures = 0
        self._clear_alert("gate_down")
        self._clear_alert("gate_degraded")

    def _remember_gate_error(self, entry: str) -> None:
        entry = entry[:160]
        if entry not in self.gate_recent_errors:
            self.gate_recent_errors.append(entry)
            self.gate_recent_errors = self.gate_recent_errors[-5:]

    def record_gate_degraded(self, stage: str, model: str, provider: str, exc: Exception | str, fallback_model: str = "") -> None:
        entry = f"{stage} {model}@{provider}: {str(exc)[:120]}"
        self._remember_gate_error(entry)
        now = time.time()
        if now - self.last_gate_degraded_alert < ALERT_COOLDOWN_SECONDS:
            return
        self.last_gate_degraded_alert = now
        self._alert(
            "gate_degraded",
            "⚠️ Reply gate degraded (bot still replying)\n"
            f"{entry}\n"
            f"Fallback ({fallback_model or 'unknown'}) is carrying the gate.\n"
            "No action needed unless a DOWN alert follows.",
        )

    def record_gate_failure(self, reason: str) -> None:
        self._remember_gate_error(reason)
        self.gate_failures += 1
        if self.gate_failures >= GATE_FAILURE_ALERT_THRESHOLD:
            details = "\n".join("• " + e for e in self.gate_recent_errors[-5:]) or "• (none recorded)"
            self._alert(
                "gate_down",
                f"🚨 Reply gate DOWN ({self.gate_failures} consecutive full-chain failures)\n"
                f"Bot is silent in ALL auto-reply groups.\n"
                f"Recent errors:\n{details}\n"
                f"Check: /api/stats or logs/bot-debug.log",
            )

    def record_reply_sent(self) -> None:
        self.last_reply_time = time.time()
        self._clear_alert("bot_silent")

    def check_silence(self) -> None:
        silent_for = time.time() - self.last_reply_time
        if silent_for > SILENCE_ALERT_SECONDS:
            self._alert(
                "bot_silent",
                f"⚠️ Bot has been silent for {silent_for / 60:.0f} minutes.\n"
                f"Last reply was at {time.strftime('%H:%M', time.localtime(self.last_reply_time))}.\n"
                f"Possible causes: gate down, provider outage, or no messages received.",
            )

    def _alert(self, alert_type: str, message: str) -> None:
        now = time.time()
        if alert_type == "gate_down":
            if now - self.last_gate_alert < ALERT_COOLDOWN_SECONDS:
                return
            self.last_gate_alert = now
        elif alert_type == "bot_silent":
            if now - self.last_silence_alert < ALERT_COOLDOWN_SECONDS:
                return
            self.last_silence_alert = now

        self._active_alerts[alert_type] = message[:200]
        LOG.warning("HEALTH ALERT [%s]: %s", alert_type, message[:120])


    def _clear_alert(self, alert_type: str) -> None:
        if alert_type in self._active_alerts:
            resolved = self._active_alerts.pop(alert_type)
            LOG.info("HEALTH RESOLVED [%s]: was: %s", alert_type, resolved[:80])

    @property
    def pending_alerts(self) -> list[str]:
        return list(self._active_alerts.values())

    def status(self) -> dict[str, Any]:
        return {
            "gate_consecutive_failures": self.gate_failures,
            "gate_down": self.gate_failures >= GATE_FAILURE_ALERT_THRESHOLD,
            "minutes_since_last_reply": round((time.time() - self.last_reply_time) / 60, 1),
            "active_alerts": list(self._active_alerts.keys()),
        }
