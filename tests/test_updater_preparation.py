"""Verified updater preparation must precede cleanup-approved process launch."""

from __future__ import annotations

import gc
import hashlib
import io
import os
from dataclasses import replace

import pytest

from app.core import updater
from app.core.update_verify import SigVerifyError, UpdateManifest


@pytest.fixture
def preparation(monkeypatch, tmp_path):
    payload = b"MZ verified preparation fixture"
    manifest = UpdateManifest(
        version="9.0.0", released_at="2026-09-05T00:00:00Z",
        installer_filename="DupeZ_Setup.exe",
        installer_sha256=hashlib.sha256(payload).hexdigest(),
        installer_size=len(payload), authenticode_signer_sha256="a" * 64,
    )
    events = []
    completed = []
    prepared = []
    manifest_versions = []
    target = tmp_path / "private" / manifest.installer_filename

    class ImmediateThread:
        def __init__(self, *, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    def create_target(filename):
        assert filename == target.name
        target.parent.mkdir(mode=0o700)
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        return str(target.parent), str(target), fd

    def metadata(*_args, **kwargs):
        events.append("manifest")
        manifest_versions.append(kwargs["expected_release_version"])
        return manifest

    def response(*_args, **_kwargs):
        result = io.BytesIO(payload)
        result.headers = {"Content-Length": str(len(payload))}
        return result, updater.LATEST_INSTALLER_URL

    original_verify = updater._verify_safe_installer

    def verify(*args):
        events.append("hash")
        return original_verify(*args)

    monkeypatch.setattr(updater.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(updater, "_read_updater_asset", lambda *_a, **_k: b"signed fixture")
    monkeypatch.setattr(updater, "_open_updater_asset", response)
    monkeypatch.setattr(updater, "_create_private_installer_target", create_target)
    monkeypatch.setattr(updater, "verify_manifest_and_enforce_monotonic", metadata)
    monkeypatch.setattr(updater, "_verify_safe_installer", verify)
    monkeypatch.setattr(
        updater, "verify_installer_authenticode", lambda *_a: events.append("publisher"),
    )
    monkeypatch.setattr(updater, "_windows_attachment_services_required", lambda: True)
    monkeypatch.setattr(
        updater, "_apply_windows_attachment_evidence", lambda *_a: events.append("scan"),
    )
    monkeypatch.setattr(
        updater, "_verify_windows_attachment_evidence", lambda *_a: events.append("provenance"),
    )
    monkeypatch.setattr(updater, "_kill_dupez_processes", lambda **_k: events.append("kill"))
    monkeypatch.setattr(
        updater.safe_subprocess, "spawn_detached", lambda *_a, **_k: events.append("spawn"),
    )
    monkeypatch.setattr(updater.os, "_exit", lambda *_a: events.append("exit"))
    checker = updater.UpdateChecker()
    checker.latest_version = manifest.version
    checker.installer_url = updater.LATEST_INSTALLER_URL
    checker.download_and_install(
        on_prepared=prepared.append,
        on_done=lambda ok, message: completed.append((ok, message)),
    )
    yield checker, prepared, completed, events, target, manifest, manifest_versions
    for item in prepared:
        item.cancel()


def test_preparation_verifies_without_process_actions_and_cancel_removes_files(preparation):
    checker, prepared, done, events, target, _manifest, _versions = preparation
    assert events == ["manifest", "hash", "publisher", "scan", "manifest", "hash", "publisher"]
    assert target.is_file()
    assert done == []
    assert not checker.is_downloading
    assert prepared[0].cancel()
    assert not prepared[0].launch()
    assert not target.exists()
    assert not target.parent.exists()
    assert "kill" not in events and "spawn" not in events and "exit" not in events


def test_approved_launch_reverifies_after_cleanup_and_never_forces_exit(preparation):
    checker, prepared, done, events, target, _manifest, versions = preparation
    events.clear()
    events.append("cleanup approved")
    checker.latest_version = "10.0.0"  # Consent was for the captured 9.0.0 manifest.
    assert prepared[0].launch()

    assert events == [
        "cleanup approved", "manifest", "hash", "publisher", "kill", "hash",
        "provenance", "publisher", "spawn",
    ]
    assert done == [(True, str(target))]
    assert versions == ["9.0.0", "9.0.0", "9.0.0"]
    assert not prepared[0].launch()
    assert not prepared[0].cancel()
    assert target.exists()


def test_changed_installer_after_preparation_never_kills_or_launches(preparation):
    _checker, prepared, done, events, target, _manifest, _versions = preparation
    events.clear()
    target.write_bytes(b"MZ replaced after user consent")
    assert prepared[0].launch()

    assert done and done[0][0] is False
    assert "kill" not in events and "spawn" not in events and "exit" not in events
    assert not target.exists()


def test_changed_manifest_after_preparation_never_kills_or_launches(preparation, monkeypatch):
    _checker, prepared, done, events, target, manifest, _versions = preparation
    events.clear()
    monkeypatch.setattr(
        updater, "verify_manifest_and_enforce_monotonic",
        lambda *_a, **_k: replace(manifest, version="8.0.0"),
    )
    assert prepared[0].launch()

    assert done and done[0][0] is False
    assert "manifest changed" in done[0][1]
    assert not target.exists()
    assert "kill" not in events and "spawn" not in events and "exit" not in events


def test_failed_final_provenance_check_prevents_spawn_and_cleans_files(preparation, monkeypatch):
    _checker, prepared, done, events, target, _manifest, _versions = preparation

    def fail(_path):
        raise SigVerifyError("attachment provenance removed")

    monkeypatch.setattr(updater, "_verify_windows_attachment_evidence", fail)
    assert prepared[0].launch()

    assert done == [(False, "attachment provenance removed")]
    assert "spawn" not in events and "exit" not in events
    assert not target.exists()


def test_discarded_preparation_removes_owned_download(preparation):
    _checker, prepared, done, events, target, _manifest, _versions = preparation
    prepared.clear()
    gc.collect()

    assert not target.exists()
    assert done == []
    assert "kill" not in events and "spawn" not in events and "exit" not in events


def test_launch_claim_prevents_concurrent_cancel_or_duplicate_launch(preparation, monkeypatch):
    _checker, prepared, done, events, _target, _manifest, _versions = preparation
    pending = []

    class DeferredThread:
        def __init__(self, *, target, **_kwargs):
            self.target = target

        def start(self):
            pending.append(self.target)

    monkeypatch.setattr(updater.threading, "Thread", DeferredThread)
    assert prepared[0].launch()
    assert not prepared[0].launch()
    assert not prepared[0].cancel()
    assert "spawn" not in events
    pending[0]()
    assert done[0][0] is True
    assert events.count("spawn") == 1


def test_launch_thread_start_failure_cleans_prepared_files(preparation, monkeypatch):
    _checker, prepared, done, events, target, _manifest, _versions = preparation

    class BrokenThread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            raise RuntimeError("worker creation failed")

    monkeypatch.setattr(updater.threading, "Thread", BrokenThread)
    assert prepared[0].launch()
    assert done == [(False, "worker creation failed")]
    assert not target.exists()
    assert "kill" not in events and "spawn" not in events and "exit" not in events


def test_legacy_completion_is_notification_not_a_cleanup_approval(preparation, monkeypatch):
    checker, prepared, _done, events, _target, _manifest, _versions = preparation
    assert prepared[0].cancel()
    events.clear()
    monkeypatch.setattr(updater.time, "sleep", lambda _seconds: None)

    def cleanup_refused(_ok, _message):
        events.append("cleanup refused")
        return False

    # Reproduce the original ordering with process creation/exit mocked.
    # Legacy callers retain their API; the GUI must opt into preparation.
    checker.download_and_install(on_done=cleanup_refused)
    assert events.index("spawn") < events.index("cleanup refused") < events.index("exit")
