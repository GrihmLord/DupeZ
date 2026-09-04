"""Tests for installed-runtime path separation and verified migration."""

from __future__ import annotations

import json
from pathlib import Path


def test_source_checkout_keeps_repo_data_path(monkeypatch) -> None:
    import app.core.app_paths as paths

    monkeypatch.delenv("DUPEZ_FORCE_USER_DATA", raising=False)
    monkeypatch.delenv("DUPEZ_USER_ROOT", raising=False)
    monkeypatch.setattr(paths.sys, "frozen", False, raising=False)

    assert paths.data_dir() == paths.source_root() / "app" / "data"
    assert paths.config_dir() == paths.source_root() / "app" / "config"


def test_installed_runtime_uses_per_user_root(monkeypatch, tmp_path) -> None:
    import app.core.app_paths as paths

    monkeypatch.setenv("DUPEZ_FORCE_USER_DATA", "1")
    monkeypatch.setenv("DUPEZ_USER_ROOT", str(tmp_path / "DupeZ"))

    assert paths.data_dir() == tmp_path / "DupeZ" / "data"
    assert paths.config_dir() == tmp_path / "DupeZ" / "config"
    assert paths.captures_dir() == tmp_path / "DupeZ" / "captures"
    assert paths.backups_dir() == tmp_path / "DupeZ" / "backups"


def test_build_analysis_never_migrates_checkout_data(
    monkeypatch,
    tmp_path,
) -> None:
    import app.core.app_paths as paths

    monkeypatch.setattr(paths.sys, "frozen", False, raising=False)
    monkeypatch.setenv("DUPEZ_BUILD_ANALYSIS", "1")
    monkeypatch.setenv("DUPEZ_FORCE_USER_DATA", "1")
    monkeypatch.setenv("DUPEZ_USER_ROOT", str(tmp_path / "analysis-user"))
    monkeypatch.setattr(
        paths,
        "migrate_legacy_files",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("build analysis attempted legacy-data migration")
        ),
    )

    assert paths.ensure_runtime_migration() is None


def test_frozen_runtime_cannot_use_build_marker_to_skip_migration(
    monkeypatch,
    tmp_path,
) -> None:
    import app.core.app_paths as paths

    calls = []

    def fake_migration(*args, **kwargs):
        calls.append((args, kwargs))
        return object()

    monkeypatch.setattr(paths.sys, "frozen", True, raising=False)
    monkeypatch.setenv("DUPEZ_BUILD_ANALYSIS", "1")
    monkeypatch.setattr(paths, "legacy_runtime_root", lambda: tmp_path / "old")
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path / "new-data")
    monkeypatch.setattr(paths, "config_dir", lambda: tmp_path / "new-config")
    monkeypatch.setattr(paths, "logs_dir", lambda: tmp_path / "new-logs")
    monkeypatch.setattr(paths, "crashes_dir", lambda: tmp_path / "new-crashes")
    monkeypatch.setattr(paths, "migrate_legacy_files", fake_migration)

    result = paths.ensure_runtime_migration()

    assert result is not None
    assert len(result) == 4
    assert len(calls) == 4


def test_migration_copies_and_verifies_without_deleting_legacy(
    tmp_path,
) -> None:
    from app.core.app_paths import migrate_legacy_files

    legacy = tmp_path / "legacy"
    destination = tmp_path / "new"
    source_file = legacy / "episodes" / "episode_1.jsonl"
    source_file.parent.mkdir(parents=True)
    source_file.write_text('{"event":"test"}\n', encoding="utf-8")

    result = migrate_legacy_files(
        legacy,
        destination,
        patterns=("episodes/*.jsonl",),
        marker_name=".migration.json",
    )

    assert result.ok
    assert result.copied == ("episodes/episode_1.jsonl",)
    assert source_file.exists()
    assert (destination / "episodes" / "episode_1.jsonl").read_bytes() == (
        source_file.read_bytes()
    )
    marker = json.loads(
        (destination / ".migration.json").read_text(encoding="utf-8")
    )
    assert marker["legacy_files_deleted"] is False


def test_migration_preserves_destination_conflict(tmp_path) -> None:
    from app.core.app_paths import migrate_legacy_files

    legacy = tmp_path / "legacy"
    destination = tmp_path / "new"
    legacy.mkdir()
    destination.mkdir()
    (legacy / "settings.json").write_text('{"old":true}', encoding="utf-8")
    target = destination / "settings.json"
    target.write_text('{"new":true}', encoding="utf-8")

    result = migrate_legacy_files(
        legacy,
        destination,
        patterns=("settings.json",),
        marker_name=".migration.json",
    )

    assert result.conflicts == ("settings.json",)
    assert target.read_text(encoding="utf-8") == '{"new":true}'


def test_migration_retries_after_copy_error(monkeypatch, tmp_path) -> None:
    import app.core.app_paths as paths

    legacy = tmp_path / "legacy"
    destination = tmp_path / "new"
    legacy.mkdir()
    (legacy / "data.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        paths,
        "_copy_verified",
        lambda *_args: (_ for _ in ()).throw(OSError("blocked")),
    )

    result = paths.migrate_legacy_files(
        legacy,
        destination,
        patterns=("*.json",),
        marker_name=".migration.json",
    )

    assert not result.ok
    assert result.marker == ""
    assert not (destination / ".migration.json").exists()
