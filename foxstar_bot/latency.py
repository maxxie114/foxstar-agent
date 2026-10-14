from __future__ import annotations

import logging
import time
from typing import Any

from .persistence import Database, utc_now

LOG = logging.getLogger(__name__)


class LatencyTracker:
    def __init__(self) -> None:
        self.t0 = time.perf_counter()
        self._last = self.t0
        self.stages: list[dict[str, float]] = []

    def mark(self, stage: str) -> float:
        now = time.perf_counter()
        duration = (now - self._last) * 1000
        self._last = now
        self.stages.append({"stage": stage, "ms": round(duration, 1)})
        return duration

    def total(self) -> float:
        return (time.perf_counter() - self.t0) * 1000

    def summary(self) -> str:
        parts = [f"{s['stage']}={s['ms']:.0f}ms" for s in self.stages]
        parts.append(f"total={self.total():.0f}ms")
        return " ".join(parts)

    def persist(self, db: Database, chat_id: str, msg_id: Any, replied: bool) -> None:
        try:
            with db.connect() as conn:
                conn.execute(
                    """
                    INSERT INTO latency_log(chat_id, msg_id, replied, total_ms, stages, created_at)
                    VALUES(?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chat_id,
                        str(msg_id or ""),
                        1 if replied else 0,
                        round(self.total(), 1),
                        json_stages(self.stages),
                        utc_now(),
                    ),
                )
        except Exception:
            LOG.debug("latency_persist_failed", exc_info=True)


def json_stages(stages: list[dict[str, float]]) -> str:
    import json
    return json.dumps(stages, ensure_ascii=False)
