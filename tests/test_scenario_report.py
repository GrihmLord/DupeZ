"""Tests for reproducible, privacy-preserving scenario reports."""

from __future__ import annotations

import json
from datetime import datetime, timezone


def _operation():
    return {
        "target": "192.168.1.x",
        "methods": ["lag", "drop"],
        "params_fingerprint": "abc123",
        "elapsed_seconds": 12,
        "deadline_at": 1_800_000_000.0,
        "remaining_seconds": 288,
        "automatic_stop_armed": True,
        "process_running": True,
    }


def test_report_id_is_deterministic_for_identical_content() -> None:
    from app.core.scenario_report import build_scenario_report

    first = build_scenario_report(
        [_operation()],
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    second = build_scenario_report(
        [_operation()],
        generated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )

    assert first["report_id"] == second["report_id"]
    assert first["generated_at"] != second["generated_at"]
    assert first["operations"][0]["methods"] == ["drop", "lag"]


def test_report_masks_free_text_network_identifiers() -> None:
    from app.core.scenario_report import build_scenario_report

    report = build_scenario_report(
        [_operation()],
        observation={
            "notes": "peer 192.168.1.44 mac aa:bb:cc:dd:ee:ff",
        },
    )
    rendered = json.dumps(report)

    assert "192.168.1.44" not in rendered
    assert "aa:bb:cc:dd:ee:ff" not in rendered.lower()
    assert report["privacy"]["parameter_values_included"] is False


def test_parameter_fingerprint_is_order_independent() -> None:
    from app.core.scenario_report import fingerprint_params

    assert fingerprint_params({"a": 1, "b": 2}) == fingerprint_params(
        {"b": 2, "a": 1}
    )
    assert fingerprint_params({}) == "none"


def test_report_write_is_atomic_and_idempotent(tmp_path) -> None:
    from app.core.scenario_report import (
        build_scenario_report,
        write_scenario_report,
    )

    first = build_scenario_report(
        [_operation()],
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    second = build_scenario_report(
        [_operation()],
        generated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )

    path = write_scenario_report(first, output_dir=tmp_path)
    repeated = write_scenario_report(second, output_dir=tmp_path)

    assert path == repeated
    assert not path.with_suffix(".json.tmp").exists()
    assert json.loads(path.read_text(encoding="utf-8")) == first
