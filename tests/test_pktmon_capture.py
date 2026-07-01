"""Safety and lifecycle tests for bounded Pktmon diagnostics."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest


def _plan(monkeypatch, tmp_path, **overrides):
    import app.core.pktmon_capture as capture

    exe = tmp_path / "pktmon.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.setattr(capture, "_pktmon_path", lambda: exe)
    values = {
        "port": 2302,
        "ip": "203.0.113.25",
        "protocol": "udp",
        "duration_seconds": 5,
        "output_dir": tmp_path / "captures",
        "now": datetime(2026, 6, 25, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return capture.build_capture_plan(**values)


def test_capture_plan_is_bounded_and_filter_required(
    monkeypatch,
    tmp_path,
) -> None:
    plan = _plan(monkeypatch, tmp_path)
    payload = plan.as_dict(redact_paths=False)

    assert payload["filter"] == {
        "ip": "203.0.113.25",
        "port": 2302,
        "protocol": "UDP",
    }
    assert payload["limits"]["duration_seconds"] == 5
    assert payload["limits"]["file_size_mb"] == 32
    assert payload["limits"]["packet_bytes"] == 64
    assert payload["privacy"]["automatic_capture"] is False


@pytest.mark.parametrize("duration", [0, 31, 999])
def test_capture_plan_rejects_unbounded_duration(
    monkeypatch,
    tmp_path,
    duration,
) -> None:
    with pytest.raises(ValueError, match="between 1 and 30"):
        _plan(monkeypatch, tmp_path, duration_seconds=duration)


def test_capture_requires_both_explicit_confirmations(
    monkeypatch,
    tmp_path,
) -> None:
    import app.core.pktmon_capture as capture

    plan = _plan(monkeypatch, tmp_path)
    with pytest.raises(PermissionError, match="preview-only"):
        capture.execute_capture(plan)
    with pytest.raises(PermissionError, match="acknowledgement"):
        capture.execute_capture(plan, apply=True)


def test_capture_refuses_existing_global_filters(
    monkeypatch,
    tmp_path,
) -> None:
    import app.core.pktmon_capture as capture

    plan = _plan(monkeypatch, tmp_path)
    monkeypatch.setattr(capture, "is_admin", lambda: True)
    calls = []

    def fake_run(_plan_value, args, intent):
        calls.append((args, intent))
        return SimpleNamespace(stdout="Filter 1: OperatorFilter", stderr="")

    monkeypatch.setattr(capture, "_run", fake_run)

    with pytest.raises(RuntimeError, match="already has filters"):
        capture.execute_capture(
            plan,
            apply=True,
            accept_sensitive_capture=True,
        )

    assert calls == [(["filter", "list"], "pktmon.filter_list")]


def test_capture_stops_converts_and_cleans_filters(
    monkeypatch,
    tmp_path,
) -> None:
    import app.core.pktmon_capture as capture

    plan = _plan(monkeypatch, tmp_path)
    monkeypatch.setattr(capture, "is_admin", lambda: True)
    monkeypatch.setattr(capture.time, "sleep", lambda _seconds: None)
    calls = []

    def fake_run(_plan_value, args, intent):
        calls.append((list(args), intent))
        if args == ["filter", "list"]:
            return SimpleNamespace(stdout="No filters are active.", stderr="")
        if args[0] == "etl2pcap":
            Path(plan.pcapng_path).write_bytes(b"pcap")
        return SimpleNamespace(stdout="", stderr="")

    monkeypatch.setattr(capture, "_run", fake_run)

    result = capture.execute_capture(
        plan,
        apply=True,
        accept_sensitive_capture=True,
    )

    intents = [intent for _args, intent in calls]
    assert intents == [
        "pktmon.filter_list",
        "pktmon.filter_add",
        "pktmon.capture_start",
        "pktmon.capture_stop",
        "pktmon.filter_remove",
        "pktmon.etl2pcap",
    ]
    start_args = next(args for args, intent in calls if intent == "pktmon.capture_start")
    assert "--file-size" in start_args
    assert start_args[start_args.index("--file-size") + 1] == "32"
    assert result["ok"] is True


def test_capture_cleanup_runs_when_start_fails(
    monkeypatch,
    tmp_path,
) -> None:
    import app.core.pktmon_capture as capture

    plan = _plan(monkeypatch, tmp_path)
    monkeypatch.setattr(capture, "is_admin", lambda: True)
    calls = []

    def fake_run(_plan_value, args, intent):
        calls.append(intent)
        if intent == "pktmon.filter_list":
            return SimpleNamespace(stdout="No filters are active.", stderr="")
        if intent == "pktmon.capture_start":
            raise RuntimeError("start failed")
        return SimpleNamespace(stdout="", stderr="")

    monkeypatch.setattr(capture, "_run", fake_run)

    with pytest.raises(RuntimeError, match="start failed"):
        capture.execute_capture(
            plan,
            apply=True,
            accept_sensitive_capture=True,
        )

    assert "pktmon.filter_remove" in calls
