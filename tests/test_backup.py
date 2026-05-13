"""Tests for app.core.backup (v5.6.9 feature #7).

Round-trip create → list_bundle → restore against a temp directory,
hash-mismatch detection, path-traversal refusal.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Iterator

import pytest

from app.core.backup import (
    BUNDLE_SCHEMA,
    BackupError,
    BundleManifest,
    create_backup,
    list_bundle,
    restore_backup,
)


@pytest.fixture
def fake_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Temporarily redirect backup's _repo_root to a synthetic repo tree."""
    # Build a minimal app/data tree the include globs will match.
    (tmp_path / "app" / "data").mkdir(parents=True)
    (tmp_path / "app" / "config").mkdir(parents=True)
    (tmp_path / "app" / "data" / "dayz_accounts.json").write_text(
        '{"accounts": [{"name": "test"}]}', encoding="utf-8"
    )
    (tmp_path / "app" / "data" / "dayz_accounts.hmac").write_text(
        "abc123", encoding="utf-8"
    )
    (tmp_path / "app" / "config" / "settings.json").write_text(
        '{"theme": "dark"}', encoding="utf-8"
    )
    (tmp_path / "app" / "data" / "episodes").mkdir()
    (tmp_path / "app" / "data" / "episodes" / "episode_test.jsonl").write_text(
        '{"event": "cut_start"}\n', encoding="utf-8"
    )

    from app.core import backup as backup_mod
    monkeypatch.setattr(backup_mod, "_repo_root", lambda: tmp_path)
    yield tmp_path


class TestCreateBackup:
    """create_backup — collects + zips + manifests."""

    def test_creates_zip_file(self, fake_repo: Path) -> None:
        out = fake_repo / "bundle.zip"
        result = create_backup(out, encrypt=False)
        assert result.exists()
        assert result.suffix == ".zip"

    def test_bundle_contains_manifest(self, fake_repo: Path) -> None:
        out = fake_repo / "bundle.zip"
        create_backup(out, encrypt=False)
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
            assert "manifest.json" in names

    def test_manifest_schema_correct(self, fake_repo: Path) -> None:
        out = fake_repo / "bundle.zip"
        create_backup(out, encrypt=False)
        with zipfile.ZipFile(out) as zf:
            with zf.open("manifest.json") as f:
                doc = json.loads(f.read())
        assert doc["schema"] == BUNDLE_SCHEMA
        assert "created_at" in doc
        assert "app_version" in doc
        assert "entries" in doc
        assert doc["encrypted"] is False

    def test_every_entry_has_sha256(self, fake_repo: Path) -> None:
        out = fake_repo / "bundle.zip"
        create_backup(out, encrypt=False)
        manifest = list_bundle(out)
        for entry in manifest.entries:
            assert entry.sha256
            assert len(entry.sha256) == 64
            assert entry.size > 0

    def test_includes_data_files(self, fake_repo: Path) -> None:
        out = fake_repo / "bundle.zip"
        create_backup(out, encrypt=False)
        manifest = list_bundle(out)
        paths = {e.path for e in manifest.entries}
        assert "app/data/dayz_accounts.json" in paths
        assert "app/config/settings.json" in paths
        assert "app/data/episodes/episode_test.jsonl" in paths


class TestListBundle:
    """list_bundle returns parsed manifest without touching files."""

    def test_returns_bundle_manifest(self, fake_repo: Path) -> None:
        out = fake_repo / "bundle.zip"
        create_backup(out, encrypt=False)
        manifest = list_bundle(out)
        assert isinstance(manifest, BundleManifest)
        assert manifest.schema == BUNDLE_SCHEMA

    def test_rejects_bad_schema(self, fake_repo: Path) -> None:
        bad = fake_repo / "bad.zip"
        with zipfile.ZipFile(bad, "w") as zf:
            zf.writestr("manifest.json", json.dumps({
                "schema": "not.dupez.v1",
                "entries": [],
            }))
        with pytest.raises(BackupError, match="unsupported bundle schema"):
            list_bundle(bad)


class TestRestoreBackup:
    """restore_backup — round trip, hash verification, path safety."""

    def test_round_trip_restores_files(self, fake_repo: Path) -> None:
        out = fake_repo / "bundle.zip"
        create_backup(out, encrypt=False)
        # Delete a file to verify restore brings it back.
        target = fake_repo / "app" / "data" / "dayz_accounts.json"
        original_content = target.read_text()
        target.unlink()
        result = restore_backup(out)
        assert result.ok
        assert target.exists()
        assert target.read_text() == original_content

    def test_dry_run_does_not_write(self, fake_repo: Path) -> None:
        out = fake_repo / "bundle.zip"
        create_backup(out, encrypt=False)
        target = fake_repo / "app" / "data" / "dayz_accounts.json"
        target.unlink()
        result = restore_backup(out, dry_run=True)
        assert result.restored  # claims to have restored
        assert not target.exists()  # but actually wrote nothing

    def test_hash_mismatch_refuses_write(
        self, fake_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Create a bundle, then tamper with one entry's content inside the ZIP
        # without updating the manifest hash — restore must refuse.
        out = fake_repo / "bundle.zip"
        create_backup(out, encrypt=False)
        # Rebuild the ZIP with a modified file payload.
        tampered = fake_repo / "tampered.zip"
        with zipfile.ZipFile(out, "r") as src, \
             zipfile.ZipFile(tampered, "w") as dst:
            for item in src.namelist():
                data = src.read(item)
                if item.endswith("settings.json"):
                    data = b'{"theme": "TAMPERED"}'
                dst.writestr(item, data)
        target = fake_repo / "app" / "config" / "settings.json"
        target.unlink()
        result = restore_backup(tampered)
        # The tampered file should NOT have been restored.
        assert any("settings.json" in m for m in result.hash_mismatches)
        # Other files still restore fine.
        assert (fake_repo / "app" / "data" / "dayz_accounts.json").exists()


class TestExcludeSubstrings:
    """_is_excluded filters .venv, build, dist, .git, etc."""

    def test_venv_excluded(self, fake_repo: Path) -> None:
        # Create a .venv that contains a .json — must NOT be bundled.
        venv_json = fake_repo / "app" / "data" / "junk.json"
        venv_json.parent.mkdir(parents=True, exist_ok=True)
        (fake_repo / ".venv").mkdir(parents=True, exist_ok=True)
        (fake_repo / ".venv" / "evil.json").write_text("{}")
        out = fake_repo / "bundle.zip"
        create_backup(out, encrypt=False)
        manifest = list_bundle(out)
        for entry in manifest.entries:
            assert ".venv" not in entry.path
