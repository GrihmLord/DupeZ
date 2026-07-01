"""Regression tests for the unified Network Health snapshot."""

from __future__ import annotations

import json
from types import SimpleNamespace


def test_health_snapshot_score_and_privacy(monkeypatch) -> None:
    import app.core.network_health as health
    from app.core.diagnostics import CheckResult, CheckStatus

    monkeypatch.setattr(
        health,
        "run_all_checks",
        lambda: [
            CheckResult("Good", CheckStatus.PASS, "ready"),
            CheckResult(
                "Warning",
                CheckStatus.WARN,
                r"adapter at 192.168.1.25 under C:\Users\Owner",
                "Review 192.168.1.25",
            ),
            CheckResult("Broken", CheckStatus.FAIL, "not ready", "Repair it"),
        ],
    )
    monkeypatch.setattr(
        health,
        "_collect_adapter_summary",
        lambda: {
            "available": True,
            "adapter_count": 2,
            "up_adapter_count": 1,
        },
    )
    monkeypatch.setattr(
        health,
        "_collect_route_summary",
        lambda: {
            "available": True,
            "kind": "wifi",
            "local_ip": "192.168.1.x",
            "reason": "test",
        },
    )
    monkeypatch.setattr(
        health,
        "_collect_safety_summary",
        lambda: {"acknowledgement": {"acknowledged": True}},
    )
    monkeypatch.setattr(health, "_pktmon_available", lambda: True)
    monkeypatch.setattr(
        health,
        "OperationJournal",
        lambda: SimpleNamespace(is_pending=lambda: False),
    )

    snapshot = health.build_network_health_snapshot()
    rendered = json.dumps(snapshot)

    assert snapshot["schema"] == "dupez.network-health.v1"
    assert snapshot["overall"] == {
        "status": "critical",
        "score": 75,
        "summary": {"pass": 1, "warn": 1, "fail": 1},
    }
    assert snapshot["capabilities"]["pcapng_export_supported"] is True
    assert "192.168.1.25" not in rendered
    assert r"C:\Users\Owner" not in rendered
    assert snapshot["privacy"]["packet_payloads_included"] is False


def test_health_snapshot_redacts_adapter_display_names(monkeypatch) -> None:
    import app.core.network_health as health
    from app.core.diagnostics import CheckResult, CheckStatus

    monkeypatch.setattr(
        health,
        "run_all_checks",
        lambda: [
            CheckResult(
                "WiFi adapter path",
                CheckStatus.PASS,
                "default route uses WiFi adapter 'Owner Private Wi-Fi'",
            ),
        ],
    )
    monkeypatch.setattr(health, "_collect_adapter_summary", lambda: {})
    monkeypatch.setattr(health, "_collect_route_summary", lambda: {})
    monkeypatch.setattr(health, "_collect_safety_summary", lambda: {})
    monkeypatch.setattr(health, "_pktmon_available", lambda: False)
    monkeypatch.setattr(
        health,
        "OperationJournal",
        lambda: SimpleNamespace(is_pending=lambda: False),
    )

    rendered = json.dumps(health.build_network_health_snapshot())

    assert "Owner Private Wi-Fi" not in rendered
    assert "adapter '<redacted>'" in rendered


def test_adapter_summary_contains_no_identifiers(monkeypatch) -> None:
    import app.core.network_health as health

    fake_psutil = SimpleNamespace(
        net_if_stats=lambda: {
            "Owner Wi-Fi": SimpleNamespace(isup=True, speed=866),
            "Ethernet": SimpleNamespace(isup=False, speed=1000),
        },
        net_io_counters=lambda: SimpleNamespace(
            bytes_sent=10,
            bytes_recv=20,
            errin=1,
            errout=2,
            dropin=3,
            dropout=4,
        ),
    )
    monkeypatch.setitem(__import__("sys").modules, "psutil", fake_psutil)

    summary = health._collect_adapter_summary()

    assert summary["adapter_count"] == 2
    assert summary["up_adapter_count"] == 1
    assert summary["max_link_speed_mbps"] == 866
    assert "Owner Wi-Fi" not in json.dumps(summary)
