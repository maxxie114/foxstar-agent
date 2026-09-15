import time
from unittest.mock import MagicMock

from foxstar_bot.health import HealthMonitor
from foxstar_bot.persistence import Database


def _monitor(tmp_path):
    db = Database(tmp_path / "hm.sqlite3")
    return HealthMonitor(db, "wxid_test_1987")


def test_gate_failure_alerts_after_threshold(tmp_path):
    hm = _monitor(tmp_path)
    for i in range(4):
        hm.record_gate_failure(f"timeout {i}")
        assert not hm.pending_alerts

    hm.record_gate_failure("timeout 5")
    alerts = hm.pending_alerts
    assert len(alerts) == 1
    assert "Reply gate DOWN" in alerts[0]
    assert "timeout 5" in alerts[0]


def test_gate_success_clears_alert(tmp_path):
    hm = _monitor(tmp_path)
    for _ in range(6):
        hm.record_gate_failure("err")
    assert hm.pending_alerts

    hm.record_gate_success()
    assert not hm.pending_alerts
    assert hm.status()["gate_down"] is False


def test_alert_cooldown(tmp_path):
    hm = _monitor(tmp_path)
    for _ in range(5):
        hm.record_gate_failure("err")
    assert len(hm.pending_alerts) == 1


    for _ in range(10):
        hm.record_gate_failure("more errors")
    assert len(hm.pending_alerts) == 1


    hm.last_gate_alert = time.time() - 1801
    hm._active_alerts.clear()
    for _ in range(5):
        hm.record_gate_failure("new round")
    assert len(hm.pending_alerts) == 1


def test_silence_detection(tmp_path):
    hm = _monitor(tmp_path)
    hm.record_reply_sent()
    assert not hm.pending_alerts


    hm.last_reply_time = time.time() - 960
    hm.check_silence()
    alerts = hm.pending_alerts
    assert any("silent" in a for a in alerts)


def test_status_shape(tmp_path):
    hm = _monitor(tmp_path)
    s = hm.status()
    assert "gate_consecutive_failures" in s
    assert "gate_down" in s
    assert "minutes_since_last_reply" in s
    assert "active_alerts" in s
