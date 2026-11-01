"""Tests for runtime storage and migration status reporting."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_storage_status_reports_source_mode(monkeypatch) -> None:
    import app.core.app_paths as paths
    from app.core.storage_status import build_storage_status

    monkeypatch.delenv("DUPEZ_FORCE_USER_DATA", raising=False)
    monkeypatch.delenv("DUPEZ_USER_ROOT", raising=False)
    monkeypatch.setattr(paths.sys, "frozen", False, raising=False)

    status = build_storage_status()

    assert status["schema"] == "dupez.storage-status.v1"
    assert status["runtime"]["installed"] is False
    assert status["roots"]["data"]["path"].endswith("app\\data") or (
        status["roots"]["data"]["path"].endswith("app/data")
    )
    assert status["recommendations"]


def test_storage_status_reports_installed_roots_and_migration_marker(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.core.storage_status import build_storage_status

    user_root = tmp_path / "DupeZ"
    data_dir = user_root / "data"
    data_dir.mkdir(parents=True)
    marker = data_dir / ".migration-data-v1.json"
    marker.write_text(
        json.dumps({
            "schema": "dupez.data-migration.v1",
            "copied": ["device_cache.json"],
            "conflicts": [],
            "errors": [],
            "legacy_files_deleted": False,
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("DUPEZ_FORCE_USER_DATA", "1")
    monkeypatch.setenv("DUPEZ_USER_ROOT", str(user_root))

    status = build_storage_status()

    assert status["runtime"]["installed"] is True
    assert status["roots"]["backups"]["path"] == str(user_root / "backups")
    data_marker = status["migration"]["markers"]["data"]
    assert data_marker["exists"] is True
    assert data_marker["ok"] is True
    assert data_marker["copied"] == 1


def test_storage_status_handles_corrupt_marker(monkeypatch, tmp_path: Path) -> None:
    from app.core.storage_status import build_storage_status

    user_root = tmp_path / "DupeZ"
    data_dir = user_root / "data"
    data_dir.mkdir(parents=True)
    (data_dir / ".migration-data-v1.json").write_text("{bad", encoding="utf-8")
    monkeypatch.setenv("DUPEZ_FORCE_USER_DATA", "1")
    monkeypatch.setenv("DUPEZ_USER_ROOT", str(user_root))

    status = build_storage_status()

    data_marker = status["migration"]["markers"]["data"]
    assert data_marker["exists"] is True
    assert data_marker["ok"] is False
    assert data_marker["error"]


@pytest.mark.parametrize("document", [
    None,
    [],
    "not an object",
    {"schema": "dupez.data-migration.v1"},
    {"schema": "unrelated.schema", "copied": [], "conflicts": [], "errors": []},
    {"schema": "dupez.data-migration.v1", "copied": None},
    {"schema": "dupez.data-migration.v1", "copied": "private filename"},
    {
        "schema": "dupez.data-migration.v1",
        "copied": [], "conflicts": {}, "errors": [],
    },
    {
        "schema": "dupez.data-migration.v1",
        "copied": [], "conflicts": [], "errors": [False],
    },
    {
        "schema": "dupez.data-migration.v1",
        "copied": [], "conflicts": [], "errors": [],
        "legacy_files_deleted": "false",
    },
])
def test_storage_status_rejects_malformed_marker_shape_without_crashing(
    monkeypatch, tmp_path: Path, document,
) -> None:
    from app.core.storage_status import build_storage_status

    user_root = tmp_path / "DupeZ"
    data_dir = user_root / "data"
    data_dir.mkdir(parents=True)
    marker = data_dir / ".migration-data-v1.json"
    original = json.dumps(document).encode("utf-8")
    marker.write_bytes(original)
    monkeypatch.setenv("DUPEZ_FORCE_USER_DATA", "1")
    monkeypatch.setenv("DUPEZ_USER_ROOT", str(user_root))

    status = build_storage_status()

    data_marker = status["migration"]["markers"]["data"]
    assert data_marker["exists"] is True
    assert data_marker["ok"] is False
    assert data_marker["error"]
    assert "private filename" not in json.dumps(data_marker)
    assert any("migration marker" in item for item in status["recommendations"])
    assert marker.read_bytes() == original


@pytest.mark.parametrize("contents", [b"\xff\xfeinvalid UTF-8", b"[" * 2000])
def test_storage_status_handles_undecodable_or_over_nested_marker(
    monkeypatch, tmp_path: Path, contents: bytes,
) -> None:
    from app.core.storage_status import build_storage_status

    user_root = tmp_path / "DupeZ"
    data_dir = user_root / "data"
    data_dir.mkdir(parents=True)
    marker = data_dir / ".migration-data-v1.json"
    marker.write_bytes(contents)
    monkeypatch.setenv("DUPEZ_FORCE_USER_DATA", "1")
    monkeypatch.setenv("DUPEZ_USER_ROOT", str(user_root))

    status = build_storage_status()

    data_marker = status["migration"]["markers"]["data"]
    assert data_marker["ok"] is False
    assert data_marker["error"]
    assert marker.read_bytes() == contents


def test_storage_status_reports_failed_migration_marker(monkeypatch, tmp_path) -> None:
    from app.core.storage_status import build_storage_status

    user_root = tmp_path / "DupeZ"
    data_dir = user_root / "data"
    data_dir.mkdir(parents=True)
    (data_dir / ".migration-data-v1.json").write_text(json.dumps({
        "schema": "dupez.data-migration.v1",
        "copied": ["private-file.json"],
        "conflicts": [],
        "errors": ["private-file.json: unreadable"],
        "legacy_files_deleted": False,
    }), encoding="utf-8")
    monkeypatch.setenv("DUPEZ_FORCE_USER_DATA", "1")
    monkeypatch.setenv("DUPEZ_USER_ROOT", str(user_root))

    status = build_storage_status()

    data_marker = status["migration"]["markers"]["data"]
    assert data_marker["ok"] is False
    assert data_marker["copied"] == 1
    assert data_marker["errors"] == 1
    assert "private-file" not in json.dumps(data_marker)
    assert any("migration marker" in item for item in status["recommendations"])
