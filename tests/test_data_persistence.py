"""Tests for app.core.data_persistence — CollectionManager and managers."""

import builtins
import concurrent.futures
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from app.core import data_persistence
from app.core.data_persistence import CollectionManager


class TestCollectionManager:
    """Test CollectionManager CRUD operations.

    CollectionManager uses AutoSaveMixin which delegates to a global
    persistence_manager. We mock save/load to isolate the logic.
    """

    def _make_cm(self):
        """Create a CollectionManager with mocked persistence."""
        with patch("app.core.data_persistence.persistence_manager") as mock_pm:
            mock_pm.load_data.return_value = []
            mock_pm.save_data.return_value = True
            mock_pm.mark_dirty.return_value = None
            cm = CollectionManager("test_data", key_field="id")
        # Replace the save method so subsequent calls don't need the patch active
        cm.save_changes = MagicMock(return_value=True)
        return cm

    def test_add(self):
        """Add an item and verify it's in the items list."""
        cm = self._make_cm()
        cm.add({"id": "1", "name": "alpha"})
        assert len(cm.items) == 1
        assert cm.items[0]["name"] == "alpha"

    def test_add_multiple(self):
        """Add multiple items."""
        cm = self._make_cm()
        cm.add({"id": "1", "name": "alpha"})
        cm.add({"id": "2", "name": "beta"})
        assert len(cm.items) == 2

    def test_remove(self):
        """Remove an item by key value."""
        cm = self._make_cm()
        cm.add({"id": "1", "name": "alpha"})
        cm.add({"id": "2", "name": "beta"})
        cm.remove("1")
        assert len(cm.items) == 1
        assert cm.items[0]["id"] == "2"

    def test_remove_nonexistent(self):
        """Remove with nonexistent key doesn't crash."""
        cm = self._make_cm()
        cm.add({"id": "1", "name": "alpha"})
        cm.remove("999")
        assert len(cm.items) == 1

    def test_update(self):
        """Update modifies matching item."""
        cm = self._make_cm()
        cm.add({"id": "1", "name": "alpha", "value": 10})
        cm.update("1", {"value": 42})
        assert cm.items[0]["value"] == 42

    def test_update_nonexistent(self):
        """Update with nonexistent key is a no-op."""
        cm = self._make_cm()
        cm.add({"id": "1", "name": "alpha"})
        cm.update("999", {"name": "ghost"})
        assert cm.items[0]["name"] == "alpha"

    def test_items_starts_empty(self):
        """New CollectionManager starts with empty items."""
        cm = self._make_cm()
        assert cm.items == []

    def test_save_called_on_add(self):
        """save_changes is called when adding an item."""
        cm = self._make_cm()
        cm.add({"id": "1"})
        cm.save_changes.assert_called()

    def test_save_called_on_remove(self):
        """save_changes is called when removing an item."""
        cm = self._make_cm()
        cm.add({"id": "1"})
        cm.save_changes.reset_mock()
        cm.remove("1")
        cm.save_changes.assert_called()


class TestPersistenceHmacFailClosed:
    """A present-but-unusable integrity sidecar must never be bypassed."""

    @staticmethod
    def _write_payload(tmp_path: Path) -> tuple[Path, Path]:
        path = tmp_path / "protected.json"
        sidecar = path.with_suffix(".hmac")
        path.write_text('{"trusted": true}', encoding="utf-8")
        sidecar.write_text("0" * 96, encoding="ascii")
        return path, sidecar

    def test_unreadable_sidecar_rejects_json(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        path, sidecar = self._write_payload(tmp_path)
        real_open = builtins.open

        def deny_sidecar(file, *args, **kwargs):
            if Path(file) == sidecar:
                raise PermissionError("sidecar access denied")
            return real_open(file, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", deny_sidecar)

        assert data_persistence.DataPersistenceManager._try_load_json(path) is None

    def test_undecodable_sidecar_rejects_json(
        self, tmp_path: Path,
    ) -> None:
        path, sidecar = self._write_payload(tmp_path)
        sidecar.write_bytes(b"\xff\xfe")

        assert data_persistence.DataPersistenceManager._try_load_json(path) is None

    def test_unverifiable_sidecar_rejects_json(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        path, _sidecar = self._write_payload(tmp_path)
        monkeypatch.setattr(data_persistence, "_verify_hmac", lambda *_: False)
        monkeypatch.setattr(
            data_persistence, "_verify_hmac_legacy", lambda *_: False,
        )

        assert data_persistence.DataPersistenceManager._try_load_json(path) is None

    def test_verifier_error_rejects_json(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        path, _sidecar = self._write_payload(tmp_path)

        def verifier_failed(_data: bytes, _expected: str) -> bool:
            raise RuntimeError("verification backend unavailable")

        monkeypatch.setattr(data_persistence, "_verify_hmac", verifier_failed)

        assert data_persistence.DataPersistenceManager._try_load_json(path) is None

    def test_secret_store_failure_never_uses_predictable_fallback(
        self,
        monkeypatch,
    ) -> None:
        from app.core import secret_store

        messages: list[str] = []
        canary = r"C:\Users\Sensitive\DupeZ\secrets"
        monkeypatch.setattr(data_persistence, "_KEY_CACHE", None)
        monkeypatch.setattr(data_persistence, "_KEY_DEGRADED", False)
        monkeypatch.setattr(data_persistence, "log_error", messages.append)
        monkeypatch.setattr(
            secret_store,
            "get_or_create_secret",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                PermissionError(canary)
            ),
        )

        with pytest.raises(RuntimeError, match="unavailable"):
            data_persistence._get_hmac_key()

        assert data_persistence._KEY_CACHE is None
        assert data_persistence._KEY_DEGRADED is True
        assert canary not in "\n".join(messages)


class TestAuthenticatedPairTransactions:
    """Authenticated generations must survive crashes and writer races."""

    @staticmethod
    def _manager(tmp_path: Path, *, backup_enabled: bool = False):
        return data_persistence.DataPersistenceManager(
            data_persistence.PersistenceConfig(
                data_directory=str(tmp_path),
                backup_enabled=backup_enabled,
            )
        )

    @staticmethod
    def _deterministic_hmac(payload: bytes) -> str:
        import hashlib

        return hashlib.sha384(payload).hexdigest()

    def test_hmac_compute_failure_leaves_previous_pair_unchanged(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        manager = self._manager(tmp_path)
        monkeypatch.setattr(
            data_persistence,
            "_compute_hmac",
            self._deterministic_hmac,
        )
        monkeypatch.setattr(
            data_persistence,
            "_verify_hmac",
            lambda payload, tag: self._deterministic_hmac(payload) == tag,
        )
        assert manager.save_data("protected", {"version": 1}, force=True)
        path = tmp_path / "protected.json"
        sidecar = tmp_path / "protected.hmac"
        before = path.read_bytes(), sidecar.read_bytes()

        monkeypatch.setattr(
            data_persistence,
            "_compute_hmac",
            lambda _payload: (_ for _ in ()).throw(
                RuntimeError("secret store unavailable")
            ),
        )

        assert not manager.save_data("protected", {"version": 2}, force=True)
        assert (path.read_bytes(), sidecar.read_bytes()) == before

    def test_pointer_commit_failure_leaves_previous_commit_authoritative(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        manager = self._manager(tmp_path)
        monkeypatch.setattr(
            data_persistence,
            "_compute_hmac",
            self._deterministic_hmac,
        )
        monkeypatch.setattr(
            data_persistence,
            "_verify_hmac",
            lambda payload, tag: self._deterministic_hmac(payload) == tag,
        )
        assert manager.save_data("protected", {"version": 1}, force=True)
        path = tmp_path / "protected.json"
        sidecar = tmp_path / "protected.hmac"
        before = path.read_bytes(), sidecar.read_bytes()
        manager_type = data_persistence.DataPersistenceManager
        pointer_path = manager_type._pointer_path(path)
        real_replace = manager_type._durable_replace

        def fail_pointer_once(
            cls,
            source: Path,
            destination: Path,
            *,
            replace: bool = True,
        ) -> None:
            if Path(destination) == pointer_path:
                raise PermissionError("commit pointer replacement denied")
            real_replace(source, destination, replace=replace)

        monkeypatch.setattr(
            manager_type,
            "_durable_replace",
            classmethod(fail_pointer_once),
        )

        assert not manager.save_data("protected", {"version": 2}, force=True)
        assert (path.read_bytes(), sidecar.read_bytes()) == before
        assert data_persistence.DataPersistenceManager._try_load_json(path) == {
            "version": 1,
        }

    @pytest.mark.parametrize(
        ("phase", "expected_version"),
        [
            ("generation-durable", 1),
            ("pointer-staged", 1),
            ("pointer-committed", 2),
            ("hmac-mirrored", 2),
            ("json-mirrored", 2),
        ],
    )
    def test_subprocess_exit_recovers_last_committed_generation(
        self,
        tmp_path: Path,
        monkeypatch,
        phase: str,
        expected_version: int,
    ) -> None:
        key = b"persistence-crash-test-key-32b".ljust(32, b"!")
        assert len(key) == 32
        monkeypatch.setattr(data_persistence, "_KEY_CACHE", key)
        manager = self._manager(tmp_path)
        assert manager.save_data("protected", {"version": 1}, force=True)

        script = r"""
import os
import sys
from pathlib import Path
from app.core import data_persistence as persistence

persistence._KEY_CACHE = b"persistence-crash-test-key-32b".ljust(32, b"!")
selected = sys.argv[2]

def crash(phase, _target):
    if phase == selected:
        os._exit(91)

persistence._persistence_fault_point = crash
manager = persistence.DataPersistenceManager(
    persistence.PersistenceConfig(
        data_directory=sys.argv[1],
        backup_enabled=False,
    )
)
manager.save_data("protected", {"version": 2}, force=True)
raise SystemExit(92)
"""
        completed = subprocess.run(
            [sys.executable, "-c", script, str(tmp_path), phase],
            cwd=Path.cwd(),
            check=False,
        )

        assert completed.returncode == 91
        assert manager.load_data("protected") == {"version": expected_version}
        generations = list(tmp_path.glob(".protected.json.auth-gen-*"))
        assert 1 <= len(generations) <= 2
        assert not list(tmp_path.glob(".protected.json.auth-stage-*"))

    def test_concurrent_managers_leave_one_valid_bounded_commit(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        monkeypatch.setattr(
            data_persistence,
            "_compute_hmac",
            self._deterministic_hmac,
        )
        monkeypatch.setattr(
            data_persistence,
            "_verify_hmac",
            lambda payload, tag: self._deterministic_hmac(payload) == tag,
        )

        def write(version: int) -> bool:
            manager = self._manager(tmp_path)
            return manager.save_data(
                "protected",
                {"version": version},
                force=True,
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(write, range(24)))

        assert all(results)
        loaded = self._manager(tmp_path).load_data("protected")
        assert loaded["version"] in range(24)
        assert len(list(tmp_path.glob(".protected.json.auth-gen-*"))) <= 2
        assert not list(tmp_path.glob(".protected.json.auth-stage-*"))

    def test_tampered_commit_pointer_never_falls_back_to_legacy_mirror(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        manager = self._manager(tmp_path)
        monkeypatch.setattr(
            data_persistence,
            "_compute_hmac",
            self._deterministic_hmac,
        )
        monkeypatch.setattr(
            data_persistence,
            "_verify_hmac",
            lambda payload, tag: self._deterministic_hmac(payload) == tag,
        )
        assert manager.save_data("protected", {"trusted": True}, force=True)
        path = tmp_path / "protected.json"
        pointer = data_persistence.DataPersistenceManager._pointer_path(path)
        raw = bytearray(pointer.read_bytes())
        raw[-2] = ord("0") if raw[-2] != ord("0") else ord("1")
        pointer.write_bytes(raw)

        # The still-valid compatibility JSON/HMAC pair is not a bypass once
        # a journal commit exists.
        assert manager.load_data("protected", {"safe": True}) == {"safe": True}

    def test_rotated_backup_has_required_valid_hmac(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        manager = self._manager(tmp_path, backup_enabled=True)
        monkeypatch.setattr(
            data_persistence,
            "_compute_hmac",
            self._deterministic_hmac,
        )
        monkeypatch.setattr(
            data_persistence,
            "_verify_hmac",
            lambda payload, tag: self._deterministic_hmac(payload) == tag,
        )

        assert manager.save_data("protected", {"version": 1}, force=True)
        assert manager.save_data("protected", {"version": 2}, force=True)

        backups = list(tmp_path.glob("protected.backup.*.json"))
        assert len(backups) == 1
        backup = backups[0]
        assert backup.with_suffix(".hmac").is_file()
        assert manager._try_load_json(backup, require_hmac=True) == {
            "version": 1,
        }

    def test_recovery_refuses_rotated_backup_without_hmac(
        self,
        tmp_path: Path,
    ) -> None:
        manager = self._manager(tmp_path)
        (tmp_path / "protected.json").write_text("not json", encoding="utf-8")
        (tmp_path / "protected.backup.1.json").write_text(
            '{"version": 1}',
            encoding="utf-8",
        )

        assert manager.load_data("protected", {"safe": True}) == {"safe": True}

    def test_live_file_sidecar_deletion_repairs_from_committed_generation(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        manager = self._manager(tmp_path)
        monkeypatch.setattr(
            data_persistence,
            "_compute_hmac",
            self._deterministic_hmac,
        )
        monkeypatch.setattr(
            data_persistence,
            "_verify_hmac",
            lambda payload, tag: self._deterministic_hmac(payload) == tag,
        )
        assert manager.save_data("protected", {"trusted": True}, force=True)
        (tmp_path / "protected.hmac").unlink()

        assert manager.load_data("protected", {"safe": True}) == {"trusted": True}
        assert (tmp_path / "protected.hmac").is_file()
