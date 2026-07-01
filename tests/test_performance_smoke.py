"""Tests for local performance smoke checks."""

from __future__ import annotations


def test_performance_smoke_reports_budgeted_checks() -> None:
    from app.core.performance_smoke import run_performance_smoke

    payload = run_performance_smoke(iterations=1)

    assert payload["schema"] == "dupez.performance-smoke.v1"
    assert payload["iterations"] == 1
    assert payload["checks"]
    assert {check["name"] for check in payload["checks"]} == {
        "storage_status",
        "retention_empty_roots",
        "scenario_report",
    }
    assert all("budget_ms" in check for check in payload["checks"])


def test_performance_smoke_can_include_support_bundle(monkeypatch) -> None:
    import app.core.performance_smoke as perf

    monkeypatch.setattr(perf, "_bench_support_bundle", lambda: None)

    payload = perf.run_performance_smoke(
        iterations=1,
        include_support_bundle=True,
    )

    assert "support_bundle" in {check["name"] for check in payload["checks"]}
