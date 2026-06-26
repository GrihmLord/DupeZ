"""Tests for the privacy-preserving authorized-use acknowledgement."""

from __future__ import annotations

import json


def test_record_and_read_acknowledgement(tmp_path) -> None:
    from app.core.operator_acknowledgement import (
        POLICY_VERSION,
        acknowledgement_status,
        record_acknowledgement,
    )

    path = tmp_path / "operator-ack.json"
    record_acknowledgement(path, acknowledged_at=1_700_000_000)

    status = acknowledgement_status(path)
    assert status == {
        "schema": "dupez.operator-acknowledgement.v1",
        "policy_version": POLICY_VERSION,
        "acknowledged": True,
        "acknowledged_at": 1_700_000_000,
    }
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert set(payload) == {
        "schema",
        "policy_version",
        "acknowledged",
        "acknowledged_at",
    }


def test_old_policy_version_requires_acknowledgement_again(tmp_path) -> None:
    from app.core.operator_acknowledgement import (
        SCHEMA,
        is_acknowledged,
    )

    path = tmp_path / "operator-ack.json"
    path.write_text(
        json.dumps({
            "schema": SCHEMA,
            "policy_version": 0,
            "acknowledged": True,
            "acknowledged_at": 1,
        }),
        encoding="utf-8",
    )

    assert is_acknowledged(path) is False


def test_corrupt_acknowledgement_fails_closed(tmp_path) -> None:
    from app.core.operator_acknowledgement import is_acknowledged

    path = tmp_path / "operator-ack.json"
    path.write_text("{broken", encoding="utf-8")

    assert is_acknowledged(path) is False


def test_clear_acknowledgement(tmp_path) -> None:
    from app.core.operator_acknowledgement import (
        clear_acknowledgement,
        is_acknowledged,
        record_acknowledgement,
    )

    path = tmp_path / "operator-ack.json"
    record_acknowledgement(path)
    clear_acknowledgement(path)

    assert not path.exists()
    assert is_acknowledged(path) is False


def test_default_path_uses_local_appdata(monkeypatch, tmp_path) -> None:
    import app.core.operator_acknowledgement as acknowledgement

    monkeypatch.setattr(acknowledgement.os, "name", "nt")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert acknowledgement.default_acknowledgement_path() == (
        tmp_path / "DupeZ" / "operator-acknowledgement.json"
    )
