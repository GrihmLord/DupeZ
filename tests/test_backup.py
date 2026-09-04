"""Tests for app.core.backup (v5.6.9 feature #7).

Round-trip create → list_bundle → restore against a temp directory,
hash-mismatch detection, path-traversal refusal.
"""

from __future__ import annotations

import io
import hashlib
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

    def test_archives_committed_update_state_not_stale_projection(
        self,
        fake_repo: Path,
    ) -> None:
        from app.core.data_persistence import (
            DataPersistenceManager,
            _compute_hmac,
        )

        target = fake_repo / "app" / "data" / "update_state.json"
        sidecar = Path(str(target) + ".hmac")
        committed = b'{"last_seen_version":"5.8.0"}'
        stale_projection = b'{"last_seen_version":"1.0.0"}'
        DataPersistenceManager._replace_authenticated_pair(
            target,
            committed,
            hmac_path=sidecar,
        )

        # Simulate a crash or adversarial rewrite after the authenticated
        # commit pointer advanced. Even a self-consistent compatibility pair
        # is not authoritative once that pointer exists.
        target.write_bytes(stale_projection)
        sidecar.write_text(
            _compute_hmac(stale_projection),
            encoding="ascii",
        )

        out = fake_repo / "authoritative-journal.zip"
        create_backup(out, encrypt=False)

        with zipfile.ZipFile(out) as zf:
            names = set(zf.namelist())
            assert zf.read("files/app/data/update_state.json") == committed
            assert zf.read(
                "files/app/data/update_state.json.hmac"
            ) == _compute_hmac(committed).encode("ascii")
        assert "files/app/data/update_state.hmac" not in names

    def test_legacy_webhook_url_never_enters_backup(
        self,
        fake_repo: Path,
    ) -> None:
        url = "https://discord.com/api/" + "webhooks/123/backup-test"
        settings = {
            "theme": "dark",
            "audit_webhook": {"enabled": True, "url": url},
        }
        (fake_repo / "app" / "data" / "settings.json").write_text(
            json.dumps(settings),
            encoding="utf-8",
        )
        (fake_repo / "app" / "data" / "settings.backup.1.json").write_text(
            json.dumps(settings),
            encoding="utf-8",
        )
        (fake_repo / "app" / "config" / "settings.json").write_text(
            json.dumps(settings),
            encoding="utf-8",
        )

        out = fake_repo / "bundle.zip"
        create_backup(out, encrypt=False)

        with zipfile.ZipFile(out) as zf:
            for name in zf.namelist():
                assert url.encode() not in zf.read(name)
            restored_settings = json.loads(
                zf.read("files/app/data/settings.json")
            )
            restored_config = json.loads(
                zf.read("files/app/config/settings.json")
            )
        assert restored_settings["audit_webhook"]["enabled"] is False
        assert "url" not in restored_settings["audit_webhook"]
        assert restored_config["audit_webhook"]["enabled"] is False
        assert "url" not in restored_config["audit_webhook"]


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

    def test_plain_zip_is_not_materialized_with_path_read_bytes(
        self,
        fake_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        archive = fake_repo / "streamed.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("manifest.json", json.dumps({
                "schema": BUNDLE_SCHEMA,
                "entries": [],
            }))

        def forbidden_read_bytes(_path: Path) -> bytes:
            raise AssertionError("ordinary ZIP bundles must remain file-backed")

        monkeypatch.setattr(Path, "read_bytes", forbidden_read_bytes)

        assert list_bundle(archive).entries == []
        assert restore_backup(archive, dry_run=True).ok

    def test_rejects_outer_archive_above_size_cap(
        self,
        fake_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.core import backup as backup_module

        archive = fake_repo / "oversized-outer.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("manifest.json", json.dumps({
                "schema": BUNDLE_SCHEMA,
                "entries": [],
            }))
        monkeypatch.setattr(
            backup_module,
            "_MAX_BUNDLE_BYTES",
            archive.stat().st_size - 1,
        )

        with pytest.raises(BackupError, match="size cap"):
            list_bundle(archive)
        result = restore_backup(archive, dry_run=True)
        assert not result.ok
        assert "size cap" in result.error

    def test_rejects_compressed_manifest_above_expanded_cap(
        self,
        fake_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.core import backup as backup_module

        archive = fake_repo / "manifest-bomb.zip"
        manifest = json.dumps({
            "schema": BUNDLE_SCHEMA,
            "padding": "A" * 4_096,
            "entries": [],
        })
        with zipfile.ZipFile(
            archive,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as zf:
            zf.writestr("manifest.json", manifest)
        monkeypatch.setattr(backup_module, "_MAX_MANIFEST_BYTES", 128)

        with pytest.raises(BackupError, match="manifest exceeds"):
            list_bundle(archive)
        result = restore_backup(archive, dry_run=True)
        assert not result.ok
        assert "manifest exceeds" in result.error

    def test_rejects_excessive_zip_member_count(
        self,
        fake_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.core import backup as backup_module

        archive = fake_repo / "too-many-members.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("manifest.json", json.dumps({
                "schema": BUNDLE_SCHEMA,
                "entries": [],
            }))
            zf.writestr("unexpected.txt", b"ignored")
        monkeypatch.setattr(backup_module, "_MAX_ARCHIVE_MEMBERS", 1)

        with pytest.raises(BackupError, match="too many ZIP members"):
            list_bundle(archive)
        result = restore_backup(archive, dry_run=True)
        assert not result.ok
        assert "too many ZIP members" in result.error

    def test_encrypted_wrapper_is_bounded_before_dpapi_decrypt(
        self,
        fake_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.core import backup as backup_module

        archive = fake_repo / "oversized.zip.dpapi"
        archive.write_bytes(b"x" * 9)
        monkeypatch.setattr(backup_module, "_MAX_BUNDLE_BYTES", 32)
        monkeypatch.setattr(backup_module, "_MAX_IN_MEMORY_BUNDLE_BYTES", 8)
        decrypt_called = False

        def forbidden_decrypt(_blob: bytes) -> bytes:
            nonlocal decrypt_called
            decrypt_called = True
            raise AssertionError("oversized ciphertext reached DPAPI")

        monkeypatch.setattr(backup_module, "_dpapi_decrypt", forbidden_decrypt)

        with pytest.raises(BackupError, match="in-memory decryption cap"):
            list_bundle(archive)
        result = restore_backup(archive, dry_run=True)
        assert not result.ok
        assert "in-memory decryption cap" in result.error
        assert decrypt_called is False


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

    def test_restore_advances_existing_authenticated_commit(
        self,
        fake_repo: Path,
    ) -> None:
        from app.core.data_persistence import DataPersistenceManager

        target = fake_repo / "app" / "data" / "devices.json"
        old_payload = b'{"value":"old"}'
        restored_payload = b'{"value":"restored"}'
        DataPersistenceManager._replace_authenticated_pair(
            target,
            old_payload,
        )
        entry_path = "app/data/devices.json"
        transported_hmac_path = "app/data/devices.hmac"
        transported_hmac = b"0" * 96
        manifest = {
            "schema": BUNDLE_SCHEMA,
            "created_at": "2026-08-21T00:00:00Z",
            "app_version": "5.8.0",
            "encrypted": False,
            "entries": [
                {
                    "path": entry_path,
                    "size": len(restored_payload),
                    "sha256": hashlib.sha256(restored_payload).hexdigest(),
                },
                {
                    "path": transported_hmac_path,
                    "size": len(transported_hmac),
                    "sha256": hashlib.sha256(transported_hmac).hexdigest(),
                },
            ],
        }
        archive = fake_repo / "journaled-restore.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr(f"files/{entry_path}", restored_payload)
            zf.writestr(
                f"files/{transported_hmac_path}",
                transported_hmac,
            )
            zf.writestr("manifest.json", json.dumps(manifest))

        result = restore_backup(archive)

        assert result.ok
        assert transported_hmac_path in result.skipped
        assert DataPersistenceManager._try_load_json(target) == {
            "value": "restored",
        }
        assert target.read_bytes() == restored_payload

    def test_uppercase_data_alias_uses_journal_and_skips_hmac(
        self,
        fake_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.core import backup as backup_module

        target = fake_repo / "app" / "data" / "devices.json"
        target.write_bytes(b'{"value":"existing"}')
        payload = b'{"value":"restored"}'
        transported_hmac = b"0" * 96
        json_path = "app/data/DEVICES.JSON"
        hmac_path = "app/data/DEVICES.HMAC"
        entries = [
            {
                "path": json_path,
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            },
            {
                "path": hmac_path,
                "size": len(transported_hmac),
                "sha256": hashlib.sha256(transported_hmac).hexdigest(),
            },
        ]
        archive = fake_repo / "uppercase-alias.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr(f"files/{json_path}", payload)
            zf.writestr(f"files/{hmac_path}", transported_hmac)
            zf.writestr("manifest.json", json.dumps({
                "schema": BUNDLE_SCHEMA,
                "entries": entries,
            }))

        pair_calls: list[tuple[str, Path, bytes, Path]] = []

        def replace_pair(
            rel_path: str,
            destination: Path,
            restored_payload: bytes,
            *,
            hmac_path: Path,
        ) -> None:
            pair_calls.append((
                rel_path,
                destination,
                restored_payload,
                hmac_path,
            ))

        monkeypatch.setattr(
            backup_module,
            "_restore_destination",
            lambda rel: (
                target.with_suffix(".hmac")
                if rel.casefold().endswith(".hmac")
                else target
            ),
        )
        monkeypatch.setattr(
            backup_module,
            "_replace_restored_authenticated_pair",
            replace_pair,
        )

        result = restore_backup(archive)

        assert result.ok
        assert result.restored == [json_path]
        assert result.skipped == [hmac_path]
        assert pair_calls == [
            (json_path, target, payload, target.with_suffix(".hmac"))
        ]
        assert target.read_bytes() == b'{"value":"existing"}'

    def test_case_variants_are_all_skipped_as_one_windows_destination(
        self,
        fake_repo: Path,
    ) -> None:
        paths = (
            "app/data/devices.json",
            "app/data/DEVICES.JSON",
        )
        payloads = (b'{"value":1}', b'{"value":2}')
        archive = fake_repo / "case-collision.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            entries = []
            for path, payload in zip(paths, payloads):
                zf.writestr(f"files/{path}", payload)
                entries.append({
                    "path": path,
                    "size": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                })
            zf.writestr("manifest.json", json.dumps({
                "schema": BUNDLE_SCHEMA,
                "entries": entries,
            }))

        target = fake_repo / "app" / "data" / "devices.json"
        target.write_bytes(b'{"value":"trusted"}')

        result = restore_backup(archive)

        assert result.ok
        assert result.restored == []
        assert result.skipped == list(paths)
        assert target.read_bytes() == b'{"value":"trusted"}'

    def test_filesystem_aliases_are_all_skipped_before_restore(
        self,
        fake_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.core import backup as backup_module

        paths = ("app/data/devices.json", "app/data/device-short-name.json")
        archive = fake_repo / "filesystem-alias.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            entries = []
            for index, path in enumerate(paths):
                payload = json.dumps({"value": index}).encode()
                zf.writestr(f"files/{path}", payload)
                entries.append({
                    "path": path,
                    "size": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                })
            zf.writestr("manifest.json", json.dumps({
                "schema": BUNDLE_SCHEMA,
                "entries": entries,
            }))

        target = fake_repo / "app" / "data" / "devices.json"
        target.write_bytes(b'{"value":"trusted"}')
        monkeypatch.setattr(
            backup_module,
            "_restore_destination",
            lambda _path: target,
        )

        result = restore_backup(archive)

        assert result.ok
        assert result.restored == []
        assert result.skipped == list(paths)
        assert target.read_bytes() == b'{"value":"trusted"}'

    @pytest.mark.parametrize(
        "entry_path",
        (
            "app/data/devices.json.",
            "app/data/devices.json ",
            "app/data/devices.json:alternate",
            "app/data/profiles./player.json",
        ),
    )
    def test_windows_ambiguous_components_are_blocked(
        self,
        fake_repo: Path,
        entry_path: str,
    ) -> None:
        payload = b"{}"
        archive = fake_repo / "ambiguous-component.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr(f"files/{entry_path}", payload)
            zf.writestr("manifest.json", json.dumps({
                "schema": BUNDLE_SCHEMA,
                "entries": [{
                    "path": entry_path,
                    "size": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }],
            }))

        result = restore_backup(archive)

        assert result.ok
        assert result.restored == []
        assert result.skipped == [entry_path]

    def test_valid_posix_nested_bundle_name_still_restores(
        self,
        fake_repo: Path,
    ) -> None:
        entry_path = "app/data/profiles/Player One-α.json"
        payload = b'{"valid":true}'
        archive = fake_repo / "valid-posix-name.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr(f"files/{entry_path}", payload)
            zf.writestr("manifest.json", json.dumps({
                "schema": BUNDLE_SCHEMA,
                "entries": [{
                    "path": entry_path,
                    "size": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }],
            }))

        result = restore_backup(archive)

        assert result.ok
        assert result.restored == [entry_path]
        assert (fake_repo / entry_path).read_bytes() == payload

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
                    tampered_payload = bytearray(data)
                    tampered_payload[len(tampered_payload) // 2] ^= 1
                    data = bytes(tampered_payload)
                dst.writestr(item, data)
        target = fake_repo / "app" / "config" / "settings.json"
        target.unlink()
        result = restore_backup(tampered)
        # The tampered file should NOT have been restored.
        assert any("settings.json" in m for m in result.hash_mismatches)
        # Other files still restore fine.
        assert (fake_repo / "app" / "data" / "dayz_accounts.json").exists()

    def test_legacy_archive_url_is_stripped_on_restore(
        self,
        fake_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        url = "https://discord.com/api/" + "webhooks/123/restore-test"
        payload = json.dumps({
            "theme": "dark",
            "audit_webhook": {"enabled": True, "url": url},
        }).encode()
        entry_path = "app/data/settings.json"
        manifest = {
            "schema": BUNDLE_SCHEMA,
            "created_at": "2026-08-12T00:00:00Z",
            "app_version": "legacy",
            "encrypted": False,
            "entries": [{
                "path": entry_path,
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }],
        }
        archive = fake_repo / "legacy-webhook.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr(f"files/{entry_path}", payload)
            zf.writestr("manifest.json", json.dumps(manifest))
        from app.core.data_persistence import DataPersistenceManager

        pair_calls: list[tuple[Path, Path, bytes]] = []

        def replace_pair(
            _cls,
            destination: Path,
            restored_payload: bytes,
            *,
            hmac_path: Path,
        ) -> None:
            pair_calls.append((destination, hmac_path, restored_payload))
            destination.write_bytes(restored_payload)
            hmac_path.write_bytes(b"a" * 96)

        monkeypatch.setattr(
            DataPersistenceManager,
            "_replace_authenticated_pair",
            classmethod(replace_pair),
        )

        result = restore_backup(archive)

        assert result.ok
        restored = (fake_repo / entry_path).read_text(encoding="utf-8")
        assert url not in restored
        assert json.loads(restored)["audit_webhook"]["enabled"] is False
        assert pair_calls == [
            (
                fake_repo / "app" / "data" / "settings.json",
                fake_repo / "app" / "data" / "settings.hmac",
                restored.encode("utf-8"),
            )
        ]
        assert (
            fake_repo / "app" / "data" / "settings.hmac"
        ).read_bytes() == b"a" * 96

    def test_parent_traversal_inside_allowlisted_prefix_is_blocked(
        self,
        fake_repo: Path,
    ) -> None:
        target = fake_repo / "dupez.py"
        target.write_text("# trusted\n", encoding="utf-8")
        payload = b"# replaced\n"
        malicious_path = "app/data/../../dupez.py"
        manifest = {
            "schema": BUNDLE_SCHEMA,
            "created_at": "2026-08-12T00:00:00Z",
            "app_version": "malicious",
            "encrypted": False,
            "entries": [{
                "path": malicious_path,
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }],
        }
        archive = fake_repo / "parent-traversal.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr(f"files/{malicious_path}", payload)
            zf.writestr("manifest.json", json.dumps(manifest))

        result = restore_backup(archive)

        assert malicious_path in result.skipped
        assert target.read_text(encoding="utf-8") == "# trusted\n"

    def test_declared_size_must_match_zip_directory_and_payload(
        self,
        fake_repo: Path,
    ) -> None:
        payload = b'{"trusted": true}'
        entry_path = "app/data/lying-size.json"
        manifest = {
            "schema": BUNDLE_SCHEMA,
            "created_at": "2026-08-12T00:00:00Z",
            "app_version": "malicious",
            "encrypted": False,
            "entries": [{
                "path": entry_path,
                "size": 0,
                "sha256": hashlib.sha256(payload).hexdigest(),
            }],
        }
        archive = fake_repo / "lying-size.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr(f"files/{entry_path}", payload)
            zf.writestr("manifest.json", json.dumps(manifest))

        result = restore_backup(archive)

        assert not result.ok
        assert "size mismatch" in result.error
        assert not (fake_repo / entry_path).exists()

    def test_actual_member_sizes_enforce_aggregate_restore_cap(
        self,
        fake_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.core import backup as backup_module

        monkeypatch.setattr(backup_module, "_MAX_TOTAL_RESTORE_BYTES", 3)
        entries = []
        payloads = {}
        for index in range(2):
            entry_path = f"app/data/capped-{index}.json"
            payload = b"{}"
            payloads[entry_path] = payload
            entries.append({
                "path": entry_path,
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            })
        archive = fake_repo / "aggregate-cap.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            for entry_path, payload in payloads.items():
                zf.writestr(f"files/{entry_path}", payload)
            zf.writestr("manifest.json", json.dumps({
                "schema": BUNDLE_SCHEMA,
                "created_at": "2026-08-12T00:00:00Z",
                "app_version": "malicious",
                "encrypted": False,
                "entries": entries,
            }))

        result = restore_backup(archive)

        assert not result.ok
        assert "total restore size cap" in result.error

    @pytest.mark.parametrize("invalid_size", (-1, True, "2"))
    def test_manifest_rejects_noncanonical_sizes(
        self,
        fake_repo: Path,
        invalid_size,
    ) -> None:
        payload = b"{}"
        entry_path = "app/data/invalid-size.json"
        archive = fake_repo / f"invalid-size-{invalid_size!s}.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr(f"files/{entry_path}", payload)
            zf.writestr("manifest.json", json.dumps({
                "schema": BUNDLE_SCHEMA,
                "entries": [{
                    "path": entry_path,
                    "size": invalid_size,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }],
            }))

        result = restore_backup(archive)

        assert not result.ok
        assert "invalid size" in result.error

    def test_restore_uses_exclusive_random_same_directory_stage(
        self,
        fake_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        out = fake_repo / "bundle.zip"
        create_backup(out, encrypt=False)
        target = (
            fake_repo
            / "app"
            / "data"
            / "episodes"
            / "episode_test.jsonl"
        )
        target.unlink()
        calls = []
        import tempfile

        real_mkstemp = tempfile.mkstemp

        def tracked_mkstemp(*args, **kwargs):
            calls.append(kwargs.copy())
            return real_mkstemp(*args, **kwargs)

        monkeypatch.setattr(tempfile, "mkstemp", tracked_mkstemp)

        result = restore_backup(out)

        assert result.ok
        assert calls
        target_calls = [
            call
            for call in calls
            if call.get("prefix") == f".{target.name}."
        ]
        assert target_calls
        assert all(Path(call["dir"]) == target.parent for call in target_calls)
        assert all(call["suffix"] == ".restoring" for call in calls)


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
