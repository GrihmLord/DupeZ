"""Tests for installed-runtime path separation and verified migration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


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


@pytest.mark.parametrize("marker_data", [
    b"null",
    b"[]",
    b'"not an object"',
    b"7",
    b'{"schema":"unrelated","copied":[],"conflicts":[],"errors":[]}',
    b'{"schema":"dupez.data-migration.v1","copied":null}',
    b'{"schema":"dupez.data-migration.v1","copied":0}',
    b'{"schema":"dupez.data-migration.v1","copied":"not a list"}',
    b'{"schema":"dupez.data-migration.v1","copied":[],"conflicts":{},"errors":[]}',
    b'{"schema":"dupez.data-migration.v1","copied":[],"conflicts":[],"errors":[false]}',
    b'\xffinvalid UTF-8',
    b"[" * 2000,
    json.dumps({
        "schema": "dupez.data-migration.v1", "copied": [], "conflicts": [],
        "errors": [], "legacy_files_deleted": "false",
    }).encode(),
    json.dumps({
        "schema": "dupez.data-migration.v1", "copied": [], "conflicts": [],
        "errors": ["last attempt failed"], "legacy_files_deleted": False,
    }).encode(),
])
def test_migration_retries_invalid_or_failed_marker(tmp_path, marker_data) -> None:
    import app.core.app_paths as paths

    legacy = tmp_path / "legacy"
    destination = tmp_path / "new"
    legacy.mkdir()
    destination.mkdir()
    original = legacy / "data.json"
    original.write_bytes(b"{}")
    marker = destination / ".migration.json"
    marker.write_bytes(marker_data)

    result = paths.migrate_legacy_files(
        legacy, destination, patterns=("data.json",), marker_name=marker.name,
    )

    assert result.ok
    assert result.copied == ("data.json",)
    assert original.read_bytes() == b"{}"
    assert (destination / "data.json").read_bytes() == b"{}"
    assert paths.read_migration_marker(marker)["copied"] == ["data.json"]


def test_migration_keeps_valid_completed_marker_without_rerunning(tmp_path) -> None:
    import app.core.app_paths as paths

    legacy = tmp_path / "legacy"
    destination = tmp_path / "new"
    legacy.mkdir()
    first = legacy / "data.json"
    first.write_bytes(b"{}")
    original = paths.migrate_legacy_files(
        legacy, destination, patterns=("*.json",), marker_name=".migration.json",
    )
    marker = Path(original.marker)
    marker_contents = marker.read_bytes()
    (legacy / "later.json").write_bytes(b"{}")

    repeated = paths.migrate_legacy_files(
        legacy, destination, patterns=("*.json",), marker_name=marker.name,
    )

    assert repeated == original
    assert marker.read_bytes() == marker_contents
    assert not (destination / "later.json").exists()


def test_migration_preserves_fixed_stage_names(tmp_path) -> None:
    from app.core.app_paths import migrate_legacy_files

    legacy = tmp_path / "legacy"
    destination = tmp_path / "new"
    legacy.mkdir()
    destination.mkdir()
    (legacy / "data.json").write_bytes(b"{}")
    existing_data_stage = destination / "data.json.migrating"
    existing_marker_stage = destination / ".migration.json.tmp"
    existing_data_stage.write_bytes(b"existing staged data")
    existing_marker_stage.write_bytes(b"existing marker data")

    result = migrate_legacy_files(
        legacy, destination, patterns=("data.json",), marker_name=".migration.json",
    )

    assert result.ok
    assert existing_data_stage.read_bytes() == b"existing staged data"
    assert existing_marker_stage.read_bytes() == b"existing marker data"


@pytest.mark.parametrize("winner_contents", [b"{}", b'{"new":true}'])
def test_migration_preserves_racing_destination(
    monkeypatch, tmp_path, winner_contents,
) -> None:
    import app.core.app_paths as paths

    legacy = tmp_path / "legacy"
    destination = tmp_path / "new"
    legacy.mkdir()
    (legacy / "data.json").write_bytes(b"{}")
    real_copy = paths._copy_verified

    def racing_copy(source, target):
        target.write_bytes(winner_contents)
        return real_copy(source, target)

    monkeypatch.setattr(paths, "_copy_verified", racing_copy)

    result = paths.migrate_legacy_files(
        legacy, destination, patterns=("data.json",), marker_name=".migration.json",
    )

    assert result.ok
    assert result.copied == ()
    assert result.conflicts == (() if winner_contents == b"{}" else ("data.json",))
    assert (destination / "data.json").read_bytes() == winner_contents
    assert sorted(path.name for path in destination.iterdir()) == [
        ".migration.json", "data.json",
    ]


def test_concurrent_verified_copies_publish_one_complete_file(monkeypatch, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    import app.core.app_paths as paths

    source_a = tmp_path / "a.json"
    source_b = tmp_path / "b.json"
    source_a.write_bytes(b"first" * 1000)
    source_b.write_bytes(b"second" * 1000)
    destination = tmp_path / "destination" / "result.json"
    barrier = Barrier(2)
    real_copystat = paths.shutil.copystat

    def synchronized_copystat(source, staged):
        real_copystat(source, staged)
        barrier.wait(timeout=5)

    monkeypatch.setattr(paths.shutil, "copystat", synchronized_copystat)

    def copy_result(source):
        try:
            paths._copy_verified(source, destination)
        except FileExistsError:
            return "already-present"
        return "copied"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(copy_result, (source_a, source_b)))

    assert sorted(outcomes) == ["already-present", "copied"]
    assert destination.read_bytes() in (source_a.read_bytes(), source_b.read_bytes())
    assert list(destination.parent.iterdir()) == [destination]


def test_failed_copy_cleans_owned_stage_and_preserves_original(monkeypatch, tmp_path):
    import app.core.app_paths as paths

    source = tmp_path / "original.json"
    destination = tmp_path / "destination" / "result.json"
    source.write_bytes(b"original")

    def partial_copy(_incoming, handle):
        handle.write(b"partial")
        raise OSError("simulated copy failure")

    monkeypatch.setattr(paths.shutil, "copyfileobj", partial_copy)

    with pytest.raises(OSError, match="simulated copy failure"):
        paths._copy_verified(source, destination)

    assert source.read_bytes() == b"original"
    assert list(destination.parent.iterdir()) == []


def test_racing_read_only_copy_cleans_its_owned_stage(tmp_path):
    import stat

    import app.core.app_paths as paths

    source = tmp_path / "original.json"
    destination = tmp_path / "destination" / "result.json"
    source.write_bytes(b"original")
    source.chmod(stat.S_IREAD)
    destination.parent.mkdir()
    destination.write_bytes(b"preserved winner")
    try:
        with pytest.raises(FileExistsError):
            paths._copy_verified(source, destination)
    finally:
        source.chmod(stat.S_IWRITE | stat.S_IREAD)

    assert source.read_bytes() == b"original"
    assert destination.read_bytes() == b"preserved winner"
    assert list(destination.parent.iterdir()) == [destination]


def test_copy_cleanup_failure_does_not_hide_original_error(monkeypatch, tmp_path):
    import app.core.app_paths as paths

    source = tmp_path / "original.json"
    destination = tmp_path / "destination" / "result.json"
    source.write_bytes(b"original")

    def fail_copy(*_args):
        raise OSError("original copy failure")

    def fail_cleanup(_path):
        raise PermissionError("cleanup failure")

    with monkeypatch.context() as stage_patch:
        stage_patch.setattr(paths.shutil, "copyfileobj", fail_copy)
        stage_patch.setattr(paths, "_discard_migration_stage", fail_cleanup)
        with pytest.raises(OSError, match="original copy failure") as failure:
            paths._copy_verified(source, destination)

    assert "cleanup also failed" in failure.value.__notes__[0]
    assert source.read_bytes() == b"original"
    assert not destination.exists()
    stages = list(destination.parent.iterdir())
    assert len(stages) == 1
    # This test intentionally prevented cleanup of its own unique stage.
    stages[0].unlink()


def test_marker_failure_is_reported_and_retried(monkeypatch, tmp_path):
    import app.core.app_paths as paths

    legacy = tmp_path / "legacy"
    destination = tmp_path / "new"
    legacy.mkdir()
    (legacy / "data.json").write_bytes(b"{}")

    def fail_publish(*_args):
        raise PermissionError("simulated marker failure")

    with monkeypatch.context() as marker_patch:
        marker_patch.setattr(paths.os, "replace", fail_publish)
        failed = paths.migrate_legacy_files(
            legacy, destination, patterns=("data.json",), marker_name=".migration.json",
        )

    assert not failed.ok
    assert failed.marker == ""
    assert failed.copied == ("data.json",)
    assert "simulated marker failure" in failed.errors[0]
    assert list(destination.iterdir()) == [destination / "data.json"]
    succeeded = paths.migrate_legacy_files(
        legacy, destination, patterns=("data.json",), marker_name=".migration.json",
    )
    assert succeeded.ok
    assert Path(succeeded.marker).is_file()
    assert (legacy / "data.json").read_bytes() == b"{}"
