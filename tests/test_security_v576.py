"""v5.7.6 security hardening — regression coverage.

Items under test:
    1. Downgrade-replay protection in update_verify / update_state
    2. HMAC sidecars on settings.json (app/config/__init__.py)
    3. Audit log fail-closed tamper response (app/logs/audit.py)
    4. Subprocess hardening (STARTUPINFO + close_fds in safe_subprocess)
    5. Webhook host allowlist (app/core/audit_webhook.py)
    6. Self-verify helper sanity (app/core/self_verify.py)
    8. Cert-pinning helpers (app/core/cert_pinning.py)

Tests use the persistence HMAC key, which is provisioned via
:mod:`app.core.secret_store`. On CI / dev hosts that lack DPAPI the
secret store falls back to a 0o600 file under the user's data
directory — both work. The basetemp pin in conftest keeps test
artifacts inside the repo's ``.pytest-tmp``.
"""

from __future__ import annotations

import json
import os
import sys
import time
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

import pytest


# ── Item 1: downgrade-replay protection ─────────────────────────────

class TestDowngradeReplay:
    """app.core.update_state.enforce_monotonic_version + ledger I/O."""

    def test_compare_versions_strict_semver(self) -> None:
        from app.core.update_state import compare_versions
        assert compare_versions("5.7.6", "5.7.5") == 1
        assert compare_versions("5.7.5", "5.7.6") == -1
        assert compare_versions("5.7.5", "5.7.5") == 0
        assert compare_versions("6.0.0", "5.99.99") == 1
        assert compare_versions("5.8.0-beta", "5.8.0-rc") == -1
        assert compare_versions("5.8.0-rc.1", "5.8.0") == -1
        assert compare_versions("5.8.0-beta.2", "5.8.0-beta.11") == -1
        assert compare_versions("5.8.0-1", "5.8.0-alpha") == -1
        assert compare_versions("5.8.0-alpha", "5.8.0-alpha.1") == -1
        assert compare_versions("5.8.0+build.1", "5.8.0+build.2") == 0
        # Malformed inputs collapse to 0.0.0 — never let a junk version
        # win the ordering and trick us into accepting a downgrade.
        assert compare_versions("not-a-version", "0.0.1") == -1
        assert compare_versions("0.0.1", "not-a-version") == 1
        assert compare_versions("5.8.0-01", "0.0.1") == -1
        assert compare_versions(" 5.8.0", "0.0.1") == -1

    def test_stable_install_rejects_same_core_prerelease(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        from app.core import update_state
        monkeypatch.setattr(
            "app.core.data_persistence._resolve_data_directory",
            lambda: str(tmp_path),
        )

        with pytest.raises(update_state.DowngradeRefusedError, match="strictly newer"):
            update_state.enforce_update_version(
                "5.8.0-rc.1",
                installed_version="5.8.0",
            )
        with pytest.raises(update_state.DowngradeRefusedError, match="malformed"):
            update_state.enforce_update_version(
                " 5.8.1",
                installed_version="5.8.0",
            )

    def test_set_then_get_persists(self, tmp_path: Path, monkeypatch) -> None:
        from app.core import update_state
        monkeypatch.setattr(update_state, "CURRENT_VERSION", "5.7.0")
        monkeypatch.setattr(
            "app.core.data_persistence._resolve_data_directory",
            lambda: str(tmp_path),
        )
        update_state.set_last_seen_version("5.7.6")
        assert update_state.get_last_seen_version() == "5.7.6"

    def test_set_does_not_lower_floor(self, tmp_path: Path, monkeypatch) -> None:
        from app.core import update_state
        monkeypatch.setattr(update_state, "CURRENT_VERSION", "5.7.0")
        monkeypatch.setattr(
            "app.core.data_persistence._resolve_data_directory",
            lambda: str(tmp_path),
        )
        update_state.set_last_seen_version("5.7.6")
        # An attempt to lower the floor is silently ignored.
        update_state.set_last_seen_version("5.7.0")
        assert update_state.get_last_seen_version() == "5.7.6"

    def test_enforce_raises_on_downgrade(self, tmp_path: Path, monkeypatch) -> None:
        from app.core import update_state
        monkeypatch.setattr(update_state, "CURRENT_VERSION", "5.7.0")
        monkeypatch.setattr(
            "app.core.data_persistence._resolve_data_directory",
            lambda: str(tmp_path),
        )
        update_state.set_last_seen_version("5.7.6")
        with pytest.raises(update_state.DowngradeRefusedError):
            update_state.enforce_monotonic_version("5.7.5")
        # Floor unchanged.
        assert update_state.get_last_seen_version() == "5.7.6"

    def test_enforce_accepts_equal_or_greater(self, tmp_path: Path, monkeypatch) -> None:
        from app.core import update_state
        monkeypatch.setattr(update_state, "CURRENT_VERSION", "5.7.0")
        monkeypatch.setattr(
            "app.core.data_persistence._resolve_data_directory",
            lambda: str(tmp_path),
        )
        update_state.set_last_seen_version("5.7.5")
        update_state.enforce_monotonic_version("5.7.5")  # equal accepted
        update_state.enforce_monotonic_version("5.7.6")  # greater accepted
        assert update_state.get_last_seen_version() == "5.7.6"

    def test_ledger_mirror_tamper_recovers_authenticated_high_water_mark(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        """The non-authoritative JSON mirror cannot lower the committed floor."""
        from app.core import update_state
        monkeypatch.setattr(update_state, "CURRENT_VERSION", "5.8.0")
        monkeypatch.setattr(
            "app.core.data_persistence._resolve_data_directory",
            lambda: str(tmp_path),
        )
        update_state.set_last_seen_version("5.9.0")
        # Corrupt only the compatibility JSON body. The authenticated commit
        # remains authoritative and repairs the mirror on the next read.
        ledger = update_state.ledger_path()
        ledger.write_bytes(b'{"schema":"dupez.update-state.v1","last_seen_version":"99.0.0"}')
        assert update_state.get_last_seen_version() == "5.9.0"
        assert json.loads(ledger.read_text(encoding="utf-8"))[
            "last_seen_version"
        ] == "5.9.0"

    def test_concurrent_processes_preserve_highest_ledger_version(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        import subprocess

        from app.core import data_persistence, update_state

        key = b"update-ledger-concurrency-key".ljust(32, b"!")
        monkeypatch.setattr(data_persistence, "_KEY_CACHE", key)
        monkeypatch.setattr(
            data_persistence,
            "_resolve_data_directory",
            lambda: str(tmp_path),
        )
        script = r"""
import sys
from app.core import data_persistence

data_persistence._KEY_CACHE = b"update-ledger-concurrency-key".ljust(32, b"!")
data_persistence._resolve_data_directory = lambda: sys.argv[1]
from app.core import update_state
update_state.set_last_seen_version(sys.argv[2], installed_version="5.7.0")
"""
        versions = ["5.8.0", "5.11.0", "5.9.9", "5.10.4", "5.7.1"]
        processes = [
            subprocess.Popen(
                [sys.executable, "-c", script, str(tmp_path), version],
                cwd=Path.cwd(),
            )
            for version in versions
        ]
        assert [process.wait(timeout=30) for process in processes] == [0] * len(
            processes
        )
        assert update_state.get_last_seen_version("5.7.0") == "5.11.0"

    def test_signed_manifest_requires_authenticode_signer_binding(self) -> None:
        import hashlib

        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
        )

        from app.core import update_verify

        private = Ed25519PrivateKey.generate()
        public_pem = private.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")
        payload = json.dumps({
            "schema": update_verify.MANIFEST_SCHEMA,
            "version": "5.8.1",
            "installer": {
                "filename": "DupeZ_Setup.exe",
                "sha256": hashlib.sha256(b"installer").hexdigest(),
                "size": len(b"installer"),
            },
        }, separators=(",", ":"), sort_keys=True).encode("utf-8")
        envelope = (
            update_verify.pubkey_fingerprint(public_pem)
            + private.sign(payload)
        )

        with pytest.raises(
            update_verify.SigVerifyError,
            match="authenticode_signer_sha256",
        ):
            update_verify.verify_manifest(
                payload,
                envelope,
                trusted_pubkeys_pem=[public_pem],
            )
        parsed = update_verify.verify_manifest(
            payload,
            envelope,
            trusted_pubkeys_pem=[public_pem],
            allow_unsigned=True,
        )
        assert parsed.authenticode_signer_sha256 is None

    def test_installer_authenticode_must_match_signed_certificate(
        self, monkeypatch,
    ) -> None:
        from app.core import update_verify

        manifest = update_verify.UpdateManifest(
            version="5.8.1",
            released_at="",
            installer_filename="DupeZ_Setup.exe",
            installer_sha256="0" * 64,
            installer_size=1,
            authenticode_signer_sha256="a" * 64,
        )
        monkeypatch.setattr(
            update_verify,
            "authenticode_signer_sha256",
            lambda _path: "a" * 64,
        )
        update_verify.verify_installer_authenticode("fixture.exe", manifest)

        monkeypatch.setattr(
            update_verify,
            "authenticode_signer_sha256",
            lambda _path: "b" * 64,
        )
        with pytest.raises(update_verify.SigVerifyError, match="does not match"):
            update_verify.verify_installer_authenticode(
                "fixture.exe",
                manifest,
            )

    def test_missing_ledger_uses_installed_floor(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        from app.core import update_state
        monkeypatch.setattr(update_state, "CURRENT_VERSION", "5.8.0")
        monkeypatch.setattr(
            "app.core.data_persistence._resolve_data_directory",
            lambda: str(tmp_path),
        )
        assert update_state.get_last_seen_version() == "5.8.0"
        with pytest.raises(update_state.DowngradeRefusedError):
            update_state.enforce_monotonic_version("5.7.9")

    def test_authenticated_ledger_above_installed_wins(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        from app.core import update_state
        monkeypatch.setattr(update_state, "CURRENT_VERSION", "5.8.0")
        monkeypatch.setattr(
            "app.core.data_persistence._resolve_data_directory",
            lambda: str(tmp_path),
        )
        update_state.set_last_seen_version("5.9.0")
        assert update_state.get_last_seen_version() == "5.9.0"
        with pytest.raises(update_state.DowngradeRefusedError):
            update_state.enforce_monotonic_version("5.8.9")

    def test_update_path_requires_strictly_newer_than_installed(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        from app.core import update_state, update_verify
        manifest = update_verify.UpdateManifest(
            version="5.8.0",
            released_at="",
            installer_filename="DupeZ_Setup.exe",
            installer_sha256="0" * 64,
            installer_size=1,
        )
        monkeypatch.setattr(update_verify, "verify_manifest", lambda *_a, **_k: manifest)
        monkeypatch.setattr(
            "app.core.data_persistence._resolve_data_directory",
            lambda: str(tmp_path),
        )
        with pytest.raises(update_state.DowngradeRefusedError, match="strictly newer"):
            update_verify.verify_manifest_and_enforce_monotonic(
                b"manifest",
                b"signature",
                installed_version="5.8.0",
                expected_release_version="5.8.0",
                expected_installer_filename="DupeZ_Setup.exe",
            )

    def test_release_binding_fails_before_ledger_advances(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        from app.core import update_state, update_verify
        monkeypatch.setattr(update_state, "CURRENT_VERSION", "5.8.0")
        monkeypatch.setattr(
            "app.core.data_persistence._resolve_data_directory",
            lambda: str(tmp_path),
        )
        manifest = update_verify.UpdateManifest(
            version="9.0.0",
            released_at="",
            installer_filename="DupeZ_Setup.exe",
            installer_sha256="0" * 64,
            installer_size=1,
        )
        monkeypatch.setattr(update_verify, "verify_manifest", lambda *_a, **_k: manifest)
        with pytest.raises(update_verify.SigVerifyError, match="selected release"):
            update_verify.verify_manifest_and_enforce_monotonic(
                b"manifest",
                b"signature",
                installed_version="5.8.0",
                expected_release_version="5.8.1",
                expected_installer_filename="DupeZ_Setup.exe",
            )
        assert update_state.get_last_seen_version() == "5.8.0"


class TestUpdaterInstallerHandoff:
    """Private target, final rehash, and absolute System32 process tools."""

    def test_private_target_is_random_exclusive_and_restrictive(self) -> None:
        from app.core import updater

        private_dir, installer_path, fd = updater._create_private_installer_target(
            "DupeZ_Setup.exe"
        )
        try:
            os.write(fd, b"installer")
            os.close(fd)
            fd = -1
            assert Path(installer_path).parent == Path(private_dir)
            assert Path(private_dir).name.startswith("DupeZ-Update-")
            st = updater._assert_safe_installer_target(installer_path, private_dir)
            assert st.st_nlink == 1
            if os.name != "nt":
                assert updater.stat.S_IMODE(Path(private_dir).stat().st_mode) == 0o700
                assert updater.stat.S_IMODE(Path(installer_path).stat().st_mode) == 0o600
        finally:
            if fd >= 0:
                os.close(fd)
            updater._cleanup_private_installer_target(installer_path, private_dir)

    def test_safe_hash_rejects_target_changed_during_verification(
        self, monkeypatch,
    ) -> None:
        from app.core import updater
        from app.core.update_verify import UpdateManifest

        private_dir, installer_path, fd = updater._create_private_installer_target(
            "DupeZ_Setup.exe"
        )
        try:
            os.write(fd, b"signed")
            os.close(fd)
            fd = -1
            manifest = UpdateManifest(
                version="5.8.1",
                released_at="",
                installer_filename="DupeZ_Setup.exe",
                installer_sha256="0" * 64,
                installer_size=6,
            )

            def mutate_target(path: str, _manifest: UpdateManifest) -> None:
                Path(path).write_bytes(b"changed-size")

            monkeypatch.setattr(updater, "verify_installer_sha256", mutate_target)
            with pytest.raises(updater.SigVerifyError, match="changed while"):
                updater._verify_safe_installer(
                    installer_path,
                    private_dir,
                    manifest,
                )
        finally:
            if fd >= 0:
                os.close(fd)
            updater._cleanup_private_installer_target(installer_path, private_dir)

    def test_download_rehashes_after_process_cleanup_immediately_before_spawn(
        self, monkeypatch,
    ) -> None:
        import hashlib

        from app.core import updater
        from app.core.update_verify import UpdateManifest

        payload = b"signed installer bytes"
        manifest = UpdateManifest(
            version="5.8.1",
            released_at="",
            installer_filename="DupeZ_Setup.exe",
            installer_sha256=hashlib.sha256(payload).hexdigest(),
            installer_size=len(payload),
        )
        events: list[str] = []
        completed: list[tuple[bool, str]] = []

        class ImmediateThread:
            def __init__(self, *, target, **_kwargs) -> None:
                self._target = target

            def start(self) -> None:
                self._target()

        class Response:
            headers = {"Content-Length": str(len(payload))}

            def __init__(self) -> None:
                self._sent = False

            def read(self, _size: int) -> bytes:
                if self._sent:
                    return b""
                self._sent = True
                return payload

        monkeypatch.setattr(updater.threading, "Thread", ImmediateThread)
        monkeypatch.setattr(
            updater, "_read_updater_asset", lambda *_a, **_k: b"signed"
        )
        monkeypatch.setattr(
            updater,
            "verify_manifest_and_enforce_monotonic",
            lambda *_a, **_k: events.append("manifest") or manifest,
        )
        monkeypatch.setattr(
            updater, "_open_no_redirect", lambda *_a, **_k: Response()
        )
        monkeypatch.setattr(updater, "_get_tls_context", lambda: None)
        monkeypatch.setattr(updater.time, "sleep", lambda _seconds: None)
        monkeypatch.setattr(updater.os, "_exit", lambda _code: events.append("exit"))
        monkeypatch.setattr(
            updater,
            "_kill_dupez_processes",
            lambda **_kwargs: events.append("kill"),
        )

        real_verify = updater._verify_safe_installer

        def tracked_verify(*args, **kwargs) -> None:
            events.append("verify")
            real_verify(*args, **kwargs)

        monkeypatch.setattr(updater, "_verify_safe_installer", tracked_verify)
        monkeypatch.setattr(
            updater,
            "verify_installer_authenticode",
            lambda *_a, **_k: events.append("authenticode"),
        )
        monkeypatch.setattr(
            updater,
            "_windows_attachment_services_required",
            lambda: True,
        )
        monkeypatch.setattr(
            updater,
            "_apply_windows_attachment_evidence",
            lambda *_a, **_k: events.append("attachment"),
        )
        monkeypatch.setattr(
            updater,
            "_verify_windows_attachment_evidence",
            lambda *_a, **_k: events.append("attachment-evidence"),
        )

        def tracked_spawn(argv, **kwargs) -> int:
            events.append("spawn")
            assert Path(argv[0]).read_bytes() == payload
            assert kwargs["trusted_executable"] is False
            return 4242

        monkeypatch.setattr(updater.safe_subprocess, "spawn_detached", tracked_spawn)

        checker = updater.UpdateChecker()
        checker.latest_version = "5.8.1"
        checker.installer_url = updater.LATEST_INSTALLER_URL
        checker.download_and_install(on_done=lambda ok, msg: completed.append((ok, msg)))

        assert events == [
            "manifest",
            "verify",
            "authenticode",
            "attachment",
            "manifest",
            "verify",
            "authenticode",
            "kill",
            "verify",
            "attachment-evidence",
            "authenticode",
            "spawn",
            "exit",
        ]
        assert completed and completed[0][0] is True
        launched = Path(completed[0][1])
        updater._cleanup_private_installer_target(
            str(launched),
            str(launched.parent),
        )

    def test_attachment_scan_mutation_is_rejected_before_process_cleanup(
        self,
        monkeypatch,
    ) -> None:
        import hashlib

        from app.core import updater
        from app.core.update_verify import UpdateManifest

        payload = b"signed installer bytes"
        manifest = UpdateManifest(
            version="5.8.1",
            released_at="",
            installer_filename="DupeZ_Setup.exe",
            installer_sha256=hashlib.sha256(payload).hexdigest(),
            installer_size=len(payload),
        )
        events: list[str] = []
        completed: list[tuple[bool, str]] = []
        staged_paths: list[Path] = []

        class ImmediateThread:
            def __init__(self, *, target, **_kwargs) -> None:
                self._target = target

            def start(self) -> None:
                self._target()

        class Response:
            headers = {"Content-Length": str(len(payload))}

            def __init__(self) -> None:
                self._sent = False

            def read(self, _size: int) -> bytes:
                if self._sent:
                    return b""
                self._sent = True
                return payload

        def mutate_during_attachment(path: str, _source: str) -> None:
            staged = Path(path)
            staged_paths.append(staged)
            staged.write_bytes(b"X" * len(payload))
            events.append("attachment")

        monkeypatch.setattr(updater.threading, "Thread", ImmediateThread)
        monkeypatch.setattr(
            updater, "_read_updater_asset", lambda *_a, **_k: b"signed"
        )
        monkeypatch.setattr(
            updater,
            "verify_manifest_and_enforce_monotonic",
            lambda *_a, **_k: manifest,
        )
        monkeypatch.setattr(
            updater, "_open_no_redirect", lambda *_a, **_k: Response()
        )
        monkeypatch.setattr(updater, "_get_tls_context", lambda: None)
        monkeypatch.setattr(
            updater,
            "verify_installer_authenticode",
            lambda *_a, **_k: None,
        )
        monkeypatch.setattr(
            updater,
            "_windows_attachment_services_required",
            lambda: True,
        )
        monkeypatch.setattr(
            updater,
            "_apply_windows_attachment_evidence",
            mutate_during_attachment,
        )
        monkeypatch.setattr(
            updater,
            "_kill_dupez_processes",
            lambda **_kwargs: events.append("kill"),
        )
        monkeypatch.setattr(
            updater.safe_subprocess,
            "spawn_detached",
            lambda *_a, **_k: events.append("spawn"),
        )

        checker = updater.UpdateChecker()
        checker.latest_version = "5.8.1"
        checker.installer_url = updater.LATEST_INSTALLER_URL
        checker.download_and_install(
            on_done=lambda ok, msg: completed.append((ok, msg))
        )

        assert events == ["attachment"]
        assert completed and completed[0][0] is False
        assert staged_paths
        assert not staged_paths[0].exists()
        assert not staged_paths[0].parent.exists()

    def test_updater_establishes_attachment_evidence_before_cleanup(self) -> None:
        """The mutation boundary precedes post-scan crypto and process cleanup."""
        from app.core import updater

        source = Path(updater.__file__).read_text(encoding="utf-8")
        assert "Zone.Identifier" not in source
        attachment = source.index(
            "                    _apply_windows_attachment_evidence(dest, url)"
        )
        post_attachment = source[attachment:]
        assert post_attachment.index(
            "rescanned_manifest = verify_manifest_and_enforce_monotonic("
        ) < post_attachment.index(
            "_verify_safe_installer(dest, private_dir, manifest)"
        )
        assert post_attachment.index(
            "_verify_safe_installer(dest, private_dir, manifest)"
        ) < post_attachment.index(
            "verify_installer_authenticode(dest, manifest)"
        )
        assert post_attachment.index(
            "verify_installer_authenticode(dest, manifest)"
        ) < post_attachment.index("_kill_dupez_processes(")

    @pytest.mark.skipif(os.name != "nt", reason="Windows launch sharing lock")
    def test_launch_lock_denies_same_user_replacement_until_spawn(self) -> None:
        import hashlib

        from app.core import updater
        from app.core.update_verify import UpdateManifest

        payload = b"signed installer bytes"
        replacement = b"same-user replacement"
        manifest = UpdateManifest(
            version="5.8.1",
            released_at="",
            installer_filename="DupeZ_Setup.exe",
            installer_sha256=hashlib.sha256(payload).hexdigest(),
            installer_size=len(payload),
        )
        private_dir, installer_path, fd = updater._create_private_installer_target(
            manifest.installer_filename
        )
        try:
            os.write(fd, payload)
            os.close(fd)
            fd = -1

            with updater._locked_verified_installer(
                installer_path,
                private_dir,
                manifest,
            ):
                with pytest.raises(PermissionError):
                    Path(installer_path).write_bytes(replacement)
                replacement_path = Path(private_dir, "replacement.exe")
                replacement_path.write_bytes(replacement)
                with pytest.raises(PermissionError):
                    os.replace(replacement_path, installer_path)
                replacement_path.unlink()

            # The native handle is released only after the launch boundary.
            Path(installer_path).write_bytes(payload)
        finally:
            if fd >= 0:
                os.close(fd)
            updater._cleanup_private_installer_target(installer_path, private_dir)

    @pytest.mark.skipif(os.name != "nt", reason="Windows taskkill hardening")
    def test_elevated_taskkill_is_pid_scoped_and_holds_identity_handle(
        self, monkeypatch,
    ) -> None:
        from app.core import updater

        taskkill_path = os.path.join(
            os.environ.get("SystemRoot", r"C:\Windows"),
            "System32",
            "taskkill.exe",
        )
        shell_calls: list[tuple[str, str, str]] = []
        close_order: list[int] = []

        class Kernel32:
            @staticmethod
            def WaitForSingleObject(handle, timeout):
                assert handle == 202
                assert timeout == 30_000
                return 0

            @staticmethod
            def CloseHandle(handle):
                close_order.append(handle)
                return 1

        class Shell32:
            @staticmethod
            def ShellExecuteExW(info_ptr):
                info = info_ptr._obj
                shell_calls.append(
                    (info.lpFile, info.lpParameters, info.lpDirectory)
                )
                info.hProcess = 202
                return 1

        identity = updater._ProcessIdentity(
            pid=123,
            image_path=updater._normalize_windows_image_path(
                r"C:\Program Files\DupeZ\dupez.exe"
            ),
            creation_time=456,
        )
        monkeypatch.setattr(
            updater,
            "_open_matching_process",
            lambda *_args, **_kwargs: 101,
        )

        assert updater._dispatch_elevated_taskkill(
            Kernel32(),
            Shell32(),
            taskkill_path,
            identity,
        )

        assert shell_calls == [
            (
                taskkill_path,
                "/PID 123 /T /F",
                os.path.dirname(taskkill_path),
            )
        ]
        assert "/IM" not in shell_calls[0][1]
        assert os.path.isabs(shell_calls[0][0])
        # Elevated taskkill completes before either its process handle or the
        # pinned target identity handle is released.
        assert close_order == [202, 101]

    @pytest.mark.skipif(os.name != "nt", reason="Windows taskkill hardening")
    def test_cleanup_snapshots_same_variant_and_never_targets_new_processes(
        self, monkeypatch,
    ) -> None:
        from app.core import updater

        taskkill_path = os.path.join(
            os.environ.get("SystemRoot", r"C:\Windows"),
            "System32",
            "taskkill.exe",
        )
        tasklist_path = os.path.join(
            os.path.dirname(taskkill_path),
            "tasklist.exe",
        )
        captured: list[int] = []
        elevated: list[int] = []

        def resolve(name: str) -> str:
            return taskkill_path if name == "taskkill" else tasklist_path

        def fake_run(argv, **_kwargs):
            if "IMAGENAME eq dupez.exe" in argv:
                return SimpleNamespace(stdout=(
                    '"dupez.exe","999","Console","1","1,024 K"\n'
                    '"dupez.exe","123","Console","1","1,024 K"'
                ))
            return SimpleNamespace(stdout="")

        identity = updater._ProcessIdentity(
            pid=123,
            image_path=updater._normalize_windows_image_path(
                r"C:\Program Files\DupeZ\dupez.exe"
            ),
            creation_time=456,
        )

        def snapshot(_kernel32, pid, _trusted):
            captured.append(pid)
            return identity if pid == 123 else None

        def elevate(_kernel32, _shell32, path, expected):
            assert path == taskkill_path
            elevated.append(expected.pid)
            return True

        monkeypatch.setattr(updater.safe_subprocess, "resolve_system_binary", resolve)
        monkeypatch.setattr(updater.safe_subprocess, "run", fake_run)
        monkeypatch.setattr(
            updater.sys,
            "executable",
            r"C:\Program Files\DupeZ\dupez.exe",
        )
        monkeypatch.setattr(
            updater,
            "_trusted_dupez_image_paths",
            lambda _names: {identity.image_path},
        )
        monkeypatch.setattr(updater, "_snapshot_process_identity", snapshot)
        monkeypatch.setattr(
            updater,
            "_terminate_process_identity",
            lambda *_args: False,
        )
        monkeypatch.setattr(updater, "_dispatch_elevated_taskkill", elevate)
        monkeypatch.setattr(
            updater.ctypes,
            "windll",
            SimpleNamespace(kernel32=object(), shell32=object()),
        )

        updater._kill_dupez_processes(exclude_pid=999)

        # The other instance with the same image name is included; only this
        # updater's exact PID is excluded. PID 456 represents a process that
        # appeared after the enumeration snapshot and is never targeted.
        assert captured == [123]
        assert elevated == [123]
        assert 999 not in captured
        assert 456 not in elevated


# ── Item 2: settings.json HMAC sidecar ──────────────────────────────

class TestSettingsHmacSidecar:
    """app.config.load_config / save_config integrity."""

    @staticmethod
    def _isolate_marker(cfg, monkeypatch):
        state = {"initialized": False}
        monkeypatch.setattr(
            cfg,
            "_integrity_initialized",
            lambda: state["initialized"],
        )
        monkeypatch.setattr(
            cfg,
            "_mark_integrity_initialized",
            lambda: state.update(initialized=True),
        )
        return state

    def test_roundtrip_writes_sidecar(self, tmp_path: Path, monkeypatch) -> None:
        from app import config as cfg
        self._isolate_marker(cfg, monkeypatch)
        monkeypatch.setattr(cfg, "CONFIG_PATH", str(tmp_path / "settings.json"))
        monkeypatch.setattr(cfg, "HMAC_PATH", str(tmp_path / "settings.json.hmac"))
        cfg.save_config({"k": "v", "kill_switch": True})
        assert os.path.isfile(cfg.CONFIG_PATH)
        assert os.path.isfile(cfg.HMAC_PATH)
        loaded = cfg.load_config()
        assert loaded == {"k": "v", "kill_switch": True}

    def test_tampered_projection_is_repaired_from_authenticated_commit(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        from app import config as cfg
        self._isolate_marker(cfg, monkeypatch)
        monkeypatch.setattr(cfg, "CONFIG_PATH", str(tmp_path / "settings.json"))
        monkeypatch.setattr(cfg, "HMAC_PATH", str(tmp_path / "settings.json.hmac"))
        cfg.save_config({"kill_switch": True})
        # Attacker rewrites settings.json directly.
        Path(cfg.CONFIG_PATH).write_bytes(
            json.dumps({"kill_switch": False}, indent=4, sort_keys=True).encode("utf-8")
        )
        loaded = cfg.load_config()
        assert loaded == {"kill_switch": True}
        assert json.loads(Path(cfg.CONFIG_PATH).read_text(encoding="utf-8")) == {
            "kill_switch": True,
        }

    def test_first_run_no_sidecar_migrates(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        """v5.7.5 settings.json + no sidecar: load + re-sign once."""
        from app import config as cfg
        self._isolate_marker(cfg, monkeypatch)
        monkeypatch.setattr(cfg, "CONFIG_PATH", str(tmp_path / "settings.json"))
        monkeypatch.setattr(cfg, "HMAC_PATH", str(tmp_path / "settings.json.hmac"))
        Path(cfg.CONFIG_PATH).write_text(json.dumps({"legacy": True}))
        loaded = cfg.load_config()
        assert loaded == {"legacy": True}
        # Sidecar exists now.
        assert os.path.isfile(cfg.HMAC_PATH)
        # Subsequent load with a real sidecar still works.
        assert cfg.load_config() == {"legacy": True}

    def test_deleted_projection_sidecar_repairs_from_authenticated_commit(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        from app import config as cfg

        state = self._isolate_marker(cfg, monkeypatch)
        monkeypatch.setattr(cfg, "CONFIG_PATH", str(tmp_path / "settings.json"))
        monkeypatch.setattr(cfg, "HMAC_PATH", str(tmp_path / "settings.json.hmac"))
        cfg.save_config({"kill_switch": True})
        assert state["initialized"] is True
        Path(cfg.HMAC_PATH).unlink()

        assert cfg.load_config() == {"kill_switch": True}
        assert Path(cfg.HMAC_PATH).is_file()

    def test_config_pointer_commit_failure_preserves_previous_commit(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        from app import config as cfg
        from app.core import data_persistence

        self._isolate_marker(cfg, monkeypatch)
        monkeypatch.setattr(cfg, "CONFIG_PATH", str(tmp_path / "settings.json"))
        monkeypatch.setattr(cfg, "HMAC_PATH", str(tmp_path / "settings.json.hmac"))
        cfg.save_config({"version": 1})
        path = Path(cfg.CONFIG_PATH)
        sidecar = Path(cfg.HMAC_PATH)
        before = path.read_bytes(), sidecar.read_bytes()
        manager_type = data_persistence.DataPersistenceManager
        pointer_path = manager_type._pointer_path(path)
        real_replace = manager_type._durable_replace

        def fail_pointer(
            cls,
            source: Path,
            destination: Path,
            *,
            replace: bool = True,
        ) -> None:
            if Path(destination) == pointer_path:
                raise PermissionError("replace denied")
            real_replace(source, destination, replace=replace)

        monkeypatch.setattr(
            manager_type,
            "_durable_replace",
            classmethod(fail_pointer),
        )

        with pytest.raises(PermissionError, match="replace denied"):
            cfg.save_config({"version": 2})
        assert (path.read_bytes(), sidecar.read_bytes()) == before
        assert cfg.load_config() == {"version": 1}


# ── Item 3: audit log fail-closed tamper response ───────────────────

class TestAuditFailClosed:
    """app.logs.audit.AuditLogger seal / refuse / reset_after_tamper."""

    def test_clean_chain_logs_normally(self, tmp_path: Path) -> None:
        from app.logs.audit import AuditLogger
        logger = AuditLogger(audit_dir=str(tmp_path))
        logger.log("evt_a", {"x": 1})
        logger.log("evt_b", {"x": 2})
        assert not logger.is_sealed()
        valid, count, msg = logger.verify_chain()
        assert valid is True and count == 2, msg

    def test_tampered_terminal_entry_seals_logger(self, tmp_path: Path) -> None:
        from app.logs.audit import AuditLogger, TAMPER_SENTINEL_FILENAME
        logger = AuditLogger(audit_dir=str(tmp_path))
        logger.log("evt_a", {"x": 1})
        # Tamper: rewrite the audit file so the terminal hash is junk.
        path = tmp_path / "audit.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        bad = json.loads(lines[-1])
        bad["hash"] = "deadbeef" * 12  # right length, wrong value
        path.write_text(json.dumps(bad) + "\n", encoding="utf-8")
        # Reopen — chain resume must trip the seal.
        logger2 = AuditLogger(audit_dir=str(tmp_path))
        assert logger2.is_sealed(), "tampered terminal entry must seal"
        assert (tmp_path / TAMPER_SENTINEL_FILENAME).exists()

    def test_sealed_logger_drops_subsequent_writes(self, tmp_path: Path) -> None:
        from app.logs.audit import AuditLogger
        logger = AuditLogger(audit_dir=str(tmp_path))
        logger._seal(reason="manual test")
        # Should not raise; should not append.
        logger.log("evt_should_be_dropped", {})
        path = tmp_path / "audit.jsonl"
        # File may not exist yet, but if it does, no new line for the dropped event.
        if path.exists():
            assert "evt_should_be_dropped" not in path.read_text(encoding="utf-8")

    def test_reset_after_tamper_archives_and_unseals(self, tmp_path: Path) -> None:
        from app.logs.audit import AuditLogger
        logger = AuditLogger(audit_dir=str(tmp_path))
        logger.log("pre_seal", {})
        logger._seal(reason="manual test")
        assert logger.is_sealed()
        quarantine = logger.reset_after_tamper()
        assert quarantine.is_dir()
        assert not logger.is_sealed()
        # New events flow again under a fresh chain.
        logger.log("post_reset", {"new": True})
        valid, count, msg = logger.verify_chain()
        assert valid is True, msg


# ── Item 4: subprocess hardening ────────────────────────────────────

class TestSubprocessHardening:
    """Verify the safe_subprocess flags actually reach subprocess.run."""

    def test_run_sets_startupinfo_and_close_fds(self, monkeypatch) -> None:
        from app.core import safe_subprocess
        captured: dict = {}

        def fake_run(*args, **kwargs):
            captured.update(kwargs)
            class _Done:
                returncode = 0
                stdout = ""
                stderr = ""
            return _Done()

        monkeypatch.setattr(safe_subprocess.subprocess, "run", fake_run)
        # Use a known-good absolute path so _validate_argv passes.
        exe = sys.executable
        safe_subprocess.run(
            [exe, "-c", "pass"],
            trusted_executable=True,
            intent="test_v576",
            timeout=5,
        )
        assert captured.get("close_fds") is True, (
            "v5.7.6: subprocess.run must be called with close_fds=True"
        )
        if os.name == "nt":
            si = captured.get("startupinfo")
            assert si is not None, (
                "v5.7.6: Windows spawns must pass a STARTUPINFO with SW_HIDE"
            )

    def test_spawn_detached_uses_close_fds_true(self, monkeypatch) -> None:
        from app.core import safe_subprocess
        captured: dict = {}

        class _FakeProc:
            pid = 4242

        def fake_popen(*args, **kwargs):
            captured.update(kwargs)
            return _FakeProc()

        monkeypatch.setattr(safe_subprocess.subprocess, "Popen", fake_popen)
        exe = sys.executable
        pid = safe_subprocess.spawn_detached(
            [exe, "-c", "pass"],
            trusted_executable=True,
            intent="test_v576_detached",
        )
        assert pid == 4242
        assert captured.get("close_fds") is True, (
            "v5.7.6: spawn_detached must set close_fds=True on all platforms"
        )

    def test_spawn_managed_uses_close_fds_true_and_wraps_process(self, monkeypatch) -> None:
        from app.core import safe_subprocess
        captured: dict = {}

        class _FakeProc:
            pid = 4343
            returncode = None

            def poll(self):
                return self.returncode

            def kill(self):
                self.returncode = -9

        def fake_popen(*args, **kwargs):
            captured.update(kwargs)
            return _FakeProc()

        monkeypatch.setattr(safe_subprocess.subprocess, "Popen", fake_popen)
        exe = sys.executable
        proc = safe_subprocess.spawn_managed(
            [exe, "-c", "pass"],
            trusted_executable=True,
            intent="test_v576_managed",
        )
        assert proc.pid == 4343
        assert proc.poll() is None
        proc.kill()
        assert proc.returncode == -9
        assert captured.get("close_fds") is True, (
            "managed long-running spawns must inherit safe_subprocess handle policy"
        )
        if os.name == "nt":
            assert captured.get("startupinfo") is not None


# ── Item 5: webhook host allowlist ──────────────────────────────────

class TestWebhookHostAllowlist:
    """app.core.audit_webhook host allowlist enforcement."""

    def test_default_discord_host_accepted(self) -> None:
        from app.core.audit_webhook import _validate_webhook_url
        url = "https://discord.com/api/" + "webhooks/123/abc"
        assert _validate_webhook_url(url) == url

    def test_loopback_http_accepted(self) -> None:
        from app.core.audit_webhook import _validate_webhook_url
        # IPv6 literals need bracket form in URIs (RFC 3986 §3.2.2).
        for url in (
            "http://127.0.0.1:8080/hook",
            "http://localhost:8080/hook",
            "http://[::1]:8080/hook",
        ):
            assert _validate_webhook_url(url) == url

    def test_off_allowlist_https_rejected(self, monkeypatch) -> None:
        from app.core import audit_webhook
        with pytest.raises(audit_webhook.WebhookURLError):
            audit_webhook._validate_webhook_url("https://attacker.example.com/x")

    def test_environment_cannot_extend_allowlist(self, monkeypatch) -> None:
        from app.core import audit_webhook
        monkeypatch.setenv(
            "DUPEZ_TEST_WEBHOOK_HOSTS",
            "extra.example.com,another.example.com",
        )
        with pytest.raises(audit_webhook.WebhookURLError):
            audit_webhook._validate_webhook_url("https://extra.example.com/x")

    def test_authenticated_operator_allowlist_seam_is_accepted(
        self, monkeypatch,
    ) -> None:
        from app.core import audit_webhook

        monkeypatch.setattr(
            audit_webhook,
            "_load_operator_allowlist",
            lambda: frozenset({"relay.example.com"}),
        )
        url = "https://relay.example.com/x"
        assert audit_webhook._validate_webhook_url(url) == url

    def test_file_scheme_still_rejected(self) -> None:
        from app.core import audit_webhook
        with pytest.raises(audit_webhook.WebhookURLError):
            audit_webhook._validate_webhook_url(
                "file:///C:/Users/Foo/secrets.enc.json"
            )


# ── Item 6: self_verify behavior on source tree ─────────────────────

class TestSelfVerify:
    """In dev mode (not frozen) verify_self returns ok=True with 'skipped'."""

    def test_dev_mode_skipped(self) -> None:
        from app.core.self_verify import verify_self
        # We're not running from a PyInstaller bundle in tests.
        ok, msg = verify_self()
        assert ok is True
        assert "skipped" in msg.lower()


# ── Item 8: cert_pinning helpers (no network) ───────────────────────

class TestCertPinningHelpers:
    """Pure-function pieces of app.core.cert_pinning."""

    def test_enforce_pin_empty_set_is_audit_only(self) -> None:
        from app.core.cert_pinning import enforce_pin
        # Empty chain → empty observed list → empty PINS map ⇒ audit-only.
        # Don't pass junk DER; that would crash spki_hash().
        enforce_pin("unconfigured.example.com", [])

    def test_enforce_pin_raises_on_mismatch(self, monkeypatch) -> None:
        from app.core import cert_pinning
        # Make a synthetic SPKI hash and put it in PINS for the host.
        monkeypatch.setattr(cert_pinning, "PINS", {
            "api.github.com": frozenset({"a" * 64}),
        })
        # Stub spki_hash so we don't need real DER.
        monkeypatch.setattr(
            cert_pinning, "chain_spki_hashes",
            lambda chain: ["b" * 64],
        )
        with pytest.raises(cert_pinning.PinViolation):
            cert_pinning.enforce_pin("api.github.com", [b"dummy"])

    def test_enforce_pin_accepts_match(self, monkeypatch) -> None:
        from app.core import cert_pinning
        monkeypatch.setattr(cert_pinning, "PINS", {
            "api.github.com": frozenset({"c" * 64}),
        })
        monkeypatch.setattr(
            cert_pinning, "chain_spki_hashes",
            lambda chain: ["c" * 64],
        )
        cert_pinning.enforce_pin("api.github.com", [b"dummy"])  # no raise

    def test_env_disable_bypasses_enforcement(self, monkeypatch) -> None:
        from app.core import cert_pinning
        monkeypatch.setattr(cert_pinning, "PINS", {
            "api.github.com": frozenset({"d" * 64}),
        })
        monkeypatch.setattr(
            cert_pinning, "chain_spki_hashes",
            lambda chain: ["wrong" * 12 + "1234"],
        )
        monkeypatch.setenv("DUPEZ_DISABLE_CERT_PIN", "1")
        cert_pinning.enforce_pin("api.github.com", [b"dummy"])  # no raise
