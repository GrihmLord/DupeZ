from __future__ import annotations

import ctypes
import io
import json
import os
from pathlib import Path

import psutil
import pytest

from scripts import validate_frozen_runtime as validator


def test_native_input_union_has_windows_abi_size() -> None:
    is_64_bit = ctypes.sizeof(ctypes.c_void_p) == 8
    expected_size = 40 if is_64_bit else 28
    expected_union_size = 32 if is_64_bit else 24

    assert ctypes.sizeof(validator.INPUT) == expected_size
    assert ctypes.sizeof(validator.INPUT_UNION) == expected_union_size


def test_access_denied_helper_does_not_mask_cleanup(monkeypatch) -> None:
    class ElevatedHelper:
        pid = 42001

        @staticmethod
        def create_time() -> float:
            return 1.0

        def terminate(self) -> None:
            raise psutil.AccessDenied(pid=self.pid)

        def is_running(self) -> bool:
            raise psutil.AccessDenied(pid=self.pid)

        def kill(self) -> None:
            raise AssertionError("an inaccessible elevated helper must not be killed")

    helper = ElevatedHelper()
    monkeypatch.setattr(validator, "_tree", lambda _root_pid: [helper])
    monkeypatch.setattr(validator.psutil, "Process", lambda _pid: helper)
    monkeypatch.setattr(validator.psutil, "pid_exists", lambda _pid: True)

    validator._terminate_started_family(41001, {(helper.pid, 1.0)})


def test_wait_for_dashboard_rebinds_after_handle_recreation(monkeypatch) -> None:
    replies = iter([(0, 0, []), (12345, 42002, ["current-process-tree"])])
    monkeypatch.setattr(validator, "_find_dashboard", lambda _root_pid: next(replies))
    monkeypatch.setattr(validator.time, "sleep", lambda _seconds: None)

    assert validator._wait_for_dashboard(41001, 1.0) == (
        12345,
        42002,
        ["current-process-tree"],
    )


def test_foreground_dashboard_attaches_input_queues(monkeypatch) -> None:
    class FakeUser32:
        foreground = 90001
        attach_calls: list[tuple[int, int, bool]] = []

        @staticmethod
        def ShowWindow(_hwnd, _mode):
            return 1

        @classmethod
        def GetForegroundWindow(cls):
            return cls.foreground

        @staticmethod
        def GetWindowThreadProcessId(hwnd, _pid):
            return {90001: 101, 90002: 202}[hwnd]

        @classmethod
        def AttachThreadInput(cls, source, target, attach):
            cls.attach_calls.append((source, target, bool(attach)))
            return 1

        @staticmethod
        def BringWindowToTop(_hwnd):
            return 1

        @classmethod
        def SetForegroundWindow(cls, hwnd):
            cls.foreground = hwnd
            return 1

        @staticmethod
        def SetActiveWindow(_hwnd):
            return 1

        @staticmethod
        def SetFocus(_hwnd):
            return 1

    class FakeKernel32:
        @staticmethod
        def GetCurrentThreadId():
            return 303

    monkeypatch.setattr(validator, "USER32", FakeUser32())
    monkeypatch.setattr(validator, "KERNEL32", FakeKernel32())
    monkeypatch.setattr(validator.time, "sleep", lambda _seconds: None)

    assert validator._foreground_dashboard(90002)
    assert FakeUser32.attach_calls == [
        (303, 101, True),
        (303, 202, True),
        (303, 202, False),
        (303, 101, False),
    ]


def test_release_sensitive_environment_rejection_never_exposes_values() -> None:
    secret = "do-not-print-this-value"  # pragma: allowlist secret

    with pytest.raises(RuntimeError) as raised:
        validator._assert_no_release_sensitive_environment(
            {
                "Path": "safe",
                "dupez_disable_webengine": secret,
                "QTWEBENGINE_CHROMIUM_FLAGS": secret,
            }
        )

    message = str(raised.value)
    assert "DUPEZ_DISABLE_WEBENGINE" in message
    assert "QTWEBENGINE_CHROMIUM_FLAGS" in message
    assert secret not in message


def test_validation_environment_scrubs_overrides_before_controlled_values(
    monkeypatch,
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    temp_root = runtime_root / "temp"
    monkeypatch.setattr(
        validator,
        "_windows_system_environment",
        lambda: {"PATH": "trusted-system-path", "SystemRoot": "trusted-system-root"},
    )
    environment = validator._validation_environment(
        runtime_root=runtime_root,
        temp_root=temp_root,
        inherited_environment={
            "PATH": "safe-path",
            "DUPEZ_DISABLE_WEBENGINE": "1",
            "DUPEZ_MAP_RENDERER": "software",
            "DUPEZ_USER_ROOT": "unsafe-root",
            "QTWEBENGINE_CHROMIUM_FLAGS": "unsafe-flags",
        },
        profile_environment={
            "DUPEZ_LOW_RESOURCE": "0",
            "DUPEZ_MAP_PREWARM": "1",
            "DUPEZ_STARTUP_TIMEOUT_MS": "180000",
        },
    )

    assert environment["PATH"] == "trusted-system-path"
    assert environment["SystemRoot"] == "trusted-system-root"
    assert environment["LOCALAPPDATA"] == str(runtime_root)
    assert environment["TEMP"] == str(temp_root)
    assert environment["TMPDIR"] == str(temp_root)
    assert environment["DUPEZ_RELEASE_VALIDATION"] == "1"
    assert environment["DUPEZ_LOW_RESOURCE"] == "0"
    assert "DUPEZ_DISABLE_WEBENGINE" not in environment
    assert "DUPEZ_MAP_RENDERER" not in environment
    assert "DUPEZ_USER_ROOT" not in environment
    assert "QTWEBENGINE_CHROMIUM_FLAGS" not in environment


def test_frozen_lifecycle_seeds_only_shipped_safety_dry_run_settings(
    tmp_path: Path,
) -> None:
    validator._write_safety_dry_run_settings(tmp_path)

    target = tmp_path / "DupeZ" / "config" / "settings.json"
    assert json.loads(target.read_text(encoding="utf-8")) == {
        "auto_scan": False,
        "safety_dry_run": True,
    }
    assert validator.NETWORK_VALIDATION_MODE == "production-safety-dry-run"
    assert "packet engine" in validator.NETWORK_VALIDATION_SIGNAL


def test_shutdown_diagnostics_emit_only_fixed_labels(
    monkeypatch,
    tmp_path: Path,
) -> None:
    secret = "must-not-leak-from-runtime-log"  # pragma: allowlist secret
    monkeypatch.setattr(
        validator,
        "_log_text",
        lambda _root: (
            f"{secret}\nController shutting down...\n"
            "Shutdown step failed (persistence): private detail\n"
            "Application close refused because cleanup failed"
        ),
    )

    summary = validator._shutdown_diagnostic_summary(tmp_path)

    assert summary == (
        "controller-started,shutdown-step-failed,dashboard-cleanup-refused"
    )
    assert secret not in summary


def test_unreviewed_dupez_qt_and_pyinstaller_environment_is_rejected() -> None:
    secret = "must-not-print-this-value"  # pragma: allowlist secret

    with pytest.raises(RuntimeError) as raised:
        validator._assert_no_release_sensitive_environment(
            {
                "DUPEZ_UNREVIEWED_SWITCH": secret,
                "QT_QUICK_BACKEND": secret,
                "QSG_RHI_BACKEND": secret,
                "_PYI_ARCHIVE_FILE": secret,
                "PYINSTALLER_STRICT_UNPACK_MODE": secret,
            }
        )

    message = str(raised.value)
    assert "DUPEZ_UNREVIEWED_SWITCH" in message
    assert "QT_QUICK_BACKEND" in message
    assert "_PYI_ARCHIVE_FILE" in message
    assert secret not in message


def test_validation_environment_silently_scrubs_signing_and_ci_secrets(
    monkeypatch,
    tmp_path: Path,
) -> None:
    sentinel = "must-not-reach-gui"
    secret_names = (
        "DUPEZ_SIGN_CERT",
        "GH_TOKEN",
        "OPENAI_API_KEY",
        "SERVICE_PRIVATE_KEY",
        "DATABASE_PASSWORD",
        "PROXY_PASSWD",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "DUPEZ_OFFSEC_OPERATOR_KEY",
        "HTTPS_PROXY",
        "REQUESTS_CA_BUNDLE",
        "SSL_CERT_FILE",
        "SSH_AUTH_SOCK",
        "GPG_AGENT_INFO",
        "AWS_PROFILE",
    )
    inherited = {
        "PATH": "safe-path",
        "SYSTEMROOT": "safe-system-root",
        **{name: sentinel for name in secret_names},
    }
    monkeypatch.setattr(
        validator,
        "_windows_system_environment",
        lambda: {"PATH": "trusted-system-path", "SystemRoot": "trusted-system-root"},
    )

    validator._assert_no_release_sensitive_environment(inherited)
    environment = validator._validation_environment(
        runtime_root=tmp_path / "runtime",
        temp_root=tmp_path / "runtime" / "temp",
        inherited_environment=inherited,
        profile_environment={
            "DUPEZ_LOW_RESOURCE": "0",
            "DUPEZ_MAP_PREWARM": "1",
            "DUPEZ_STARTUP_TIMEOUT_MS": "180000",
        },
    )

    assert environment["PATH"] == "trusted-system-path"
    assert environment["SystemRoot"] == "trusted-system-root"
    assert sentinel not in environment.values()
    assert all(name not in environment for name in secret_names)


def test_dirty_source_identity_is_explicit_and_release_gate_is_clean_only(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class Completed:
        def __init__(self, stdout: bytes) -> None:
            self.returncode = 0
            self.stdout = stdout

    monkeypatch.setattr(
        validator,
        "_force_hash_tracked_worktree",
        lambda _root: (False, "f" * 64),
    )
    monkeypatch.setattr(
        validator,
        "_assert_safe_git_configuration",
        lambda _root: None,
    )
    encoded_root = os.fsencode(os.path.abspath(tmp_path)) + b"\n"
    results = iter(
        (
            Completed(encoded_root),
            Completed(("a" * 40 + "\n").encode()),
            Completed(b""),
            Completed(b"H app/main.py\0"),
            Completed(b" M app/main.py\0"),
        )
    )
    monkeypatch.setattr(validator.subprocess, "run", lambda *args, **kwargs: next(results))

    with pytest.raises(RuntimeError, match="clean source tree"):
        validator._git_source_identity(tmp_path, allow_dirty=False)

    results = iter(
        (
            Completed(encoded_root),
            Completed(("b" * 40 + "\n").encode()),
            Completed(b""),
            Completed(b"H app/main.py\0"),
            Completed(b" M app/main.py\0"),
            Completed(b"binary diff"),
            Completed(b""),
        )
    )
    monkeypatch.setattr(validator.subprocess, "run", lambda *args, **kwargs: next(results))
    commit, source_state, fingerprint = validator._git_source_identity(
        tmp_path,
        allow_dirty=True,
    )
    assert commit == "b" * 40
    assert source_state == "dirty-validation"
    assert len(fingerprint) == 64


def test_git_provenance_rejects_ambient_repository_overrides_without_values() -> None:
    secret = "must-not-print-this-git-path"  # pragma: allowlist secret

    with pytest.raises(RuntimeError) as raised:
        validator._assert_no_git_override_environment(
            {
                "Path": "safe",
                "GIT_DIR": secret,
                "GIT_CONFIG_COUNT": secret,
            }
        )

    message = str(raised.value)
    assert "GIT_DIR" in message
    assert "GIT_CONFIG_COUNT" in message
    assert secret not in message


def test_git_command_environment_scrubs_overrides(
    monkeypatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "Temp").mkdir()
    monkeypatch.setattr(
        validator,
        "_windows_system_environment",
        lambda: {"PATH": "trusted-system-path", "SystemRoot": "trusted-system-root"},
    )
    monkeypatch.setattr(validator, "_windows_local_appdata", lambda: tmp_path)
    environment = validator._git_environment(
        {
            "PATH": "safe",
            "GIT_WORK_TREE": "unsafe",
            "GIT_CONFIG_KEY_0": "unsafe",
        }
    )

    assert environment["PATH"] == "trusted-system-path"
    assert "GIT_WORK_TREE" not in environment
    assert "GIT_CONFIG_KEY_0" not in environment
    assert environment["GIT_CONFIG_NOSYSTEM"] == "1"
    assert environment["GIT_CONFIG_GLOBAL"] == os.devnull
    assert environment["GIT_NO_REPLACE_OBJECTS"] == "1"
    assert environment["GIT_TERMINAL_PROMPT"] == "0"
    assert environment["TEMP"] == str(tmp_path / "Temp")


def test_git_commands_disable_replace_objects(monkeypatch, tmp_path: Path) -> None:
    git = tmp_path / "git.exe"
    git.write_bytes(b"fixture")
    observed: dict[str, object] = {}

    class Completed:
        returncode = 0
        stdout = b"result\n"

    def run(arguments, **kwargs):
        observed["arguments"] = arguments
        observed["environment"] = kwargs["env"]
        return Completed()

    monkeypatch.setattr(validator, "_trusted_git_executable", lambda: git)
    monkeypatch.setattr(
        validator,
        "_git_environment",
        lambda: {"GIT_NO_REPLACE_OBJECTS": "1"},
    )
    monkeypatch.setattr(validator.subprocess, "run", run)

    assert validator._git_run(tmp_path, ["rev-parse", "HEAD"]) == b"result\n"
    assert observed["arguments"][1] == "--no-replace-objects"
    assert observed["environment"] == {"GIT_NO_REPLACE_OBJECTS": "1"}


def test_git_source_identity_rejects_hidden_index_state(
    monkeypatch,
    tmp_path: Path,
) -> None:
    responses = iter(
        (
            os.fsencode(os.path.abspath(tmp_path)) + b"\n",
            ("a" * 40 + "\n").encode(),
            b"",
            b"S app/main.py\0",
        )
    )
    monkeypatch.setattr(validator, "_git_run", lambda *_args, **_kwargs: next(responses))
    monkeypatch.setattr(
        validator,
        "_assert_safe_git_configuration",
        lambda _root: None,
    )

    with pytest.raises(RuntimeError, match="skip-worktree or assume-unchanged"):
        validator._git_source_identity(tmp_path, allow_dirty=False)


def test_git_provenance_uses_known_program_files_location(
    monkeypatch,
    tmp_path: Path,
) -> None:
    git = tmp_path / "Git" / "cmd" / "git.exe"
    git.parent.mkdir(parents=True)
    git.write_bytes(b"trusted git fixture")
    monkeypatch.setattr(validator, "_windows_program_files", lambda: tmp_path)

    assert validator._trusted_git_executable() == git


def test_git_configuration_rejects_info_attributes(tmp_path: Path) -> None:
    info = tmp_path / ".git" / "info"
    info.mkdir(parents=True)
    (info / "attributes").write_text("* filter=unsafe\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="info attributes"):
        validator._assert_safe_git_configuration(tmp_path)


def test_git_configuration_rejects_local_filter_or_include(
    monkeypatch,
    tmp_path: Path,
) -> None:
    (tmp_path / ".git" / "info").mkdir(parents=True)
    monkeypatch.setattr(
        validator,
        "_git_run",
        lambda *_args, **_kwargs: b"filter.unsafe.clean\nexternal-command\0",
    )

    with pytest.raises(RuntimeError, match="filter/include"):
        validator._assert_safe_git_configuration(tmp_path)


def test_git_configuration_rejects_worktree_configuration(
    monkeypatch,
    tmp_path: Path,
) -> None:
    (tmp_path / ".git" / "info").mkdir(parents=True)
    monkeypatch.setattr(
        validator,
        "_git_run",
        lambda *_args, **_kwargs: b"extensions.worktreeConfig\ntrue\0",
    )

    with pytest.raises(RuntimeError, match="worktree configuration"):
        validator._assert_safe_git_configuration(tmp_path)


def test_tracked_worktree_is_force_hashed_against_head_and_index(
    monkeypatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "file.txt").write_text("content", encoding="utf-8")
    observed = b"a" * 40
    tree = b"100644 blob " + observed + b"\tfile.txt\0"
    index = b"100644 " + observed + b" 0\tfile.txt\0"

    def git_run(_root, arguments, **_kwargs):
        if arguments[0] == "ls-tree":
            return tree
        if arguments[:2] == ["ls-files", "-s"]:
            return index
        if arguments[0] == "check-attr":
            return b"file.txt\0filter\0unspecified\0"
        if arguments[0] == "hash-object":
            return observed + b"\n"
        raise AssertionError(arguments)

    monkeypatch.setattr(validator, "_git_run", git_run)
    clean, fingerprint = validator._force_hash_tracked_worktree(tmp_path)
    assert clean is True
    assert len(fingerprint) == 64

    def changed_git_run(_root, arguments, **kwargs):
        if arguments[0] == "hash-object":
            return b"b" * 40 + b"\n"
        return git_run(_root, arguments, **kwargs)

    monkeypatch.setattr(validator, "_git_run", changed_git_run)
    clean, _fingerprint = validator._force_hash_tracked_worktree(tmp_path)
    assert clean is False


def test_tracked_worktree_rejects_custom_clean_filters(
    monkeypatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "file.txt").write_text("content", encoding="utf-8")
    observed = b"a" * 40

    def git_run(_root, arguments, **_kwargs):
        if arguments[0] == "ls-tree":
            return b"100644 blob " + observed + b"\tfile.txt\0"
        if arguments[:2] == ["ls-files", "-s"]:
            return b"100644 " + observed + b" 0\tfile.txt\0"
        if arguments[0] == "check-attr":
            return b"file.txt\0filter\0custom-driver\0"
        raise AssertionError(arguments)

    monkeypatch.setattr(validator, "_git_run", git_run)
    with pytest.raises(RuntimeError, match="custom Git clean filters"):
        validator._force_hash_tracked_worktree(tmp_path)


def test_private_runtime_cleanup_rejects_paths_outside_smoke_root(
    monkeypatch,
    tmp_path: Path,
) -> None:
    smoke_root = tmp_path / "trusted-smoke"
    smoke_root.mkdir()
    monkeypatch.setattr(validator, "_release_validation_parent", lambda: smoke_root)
    outside = tmp_path / "must-remain"
    outside.mkdir()

    with pytest.raises(RuntimeError, match="outside the private smoke root"):
        validator._remove_private_runtime_root(outside)

    assert outside.is_dir()


def test_private_runtime_root_is_unique_private_and_fully_removed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    smoke_root = tmp_path / "trusted-smoke"
    smoke_root.mkdir()
    hardened: list[Path] = []
    monkeypatch.setattr(validator, "_release_validation_parent", lambda: smoke_root)
    monkeypatch.setattr(
        validator,
        "_harden_private_directory",
        lambda path: hardened.append(path),
    )
    monkeypatch.setattr(
        validator,
        "_private_directory_permissions_are_restricted",
        lambda _path: True,
    )

    runtime_root = validator._private_runtime_root(
        variant="GPU",
        profile="normal",
        cycle=1,
    )
    (runtime_root / "nested").mkdir()
    (runtime_root / "nested" / "payload.bin").write_bytes(b"payload")

    assert runtime_root.parent == smoke_root
    assert hardened == [runtime_root]
    validator._remove_private_runtime_root(runtime_root)
    assert not runtime_root.exists()


def test_release_artifact_rejects_hard_links(tmp_path: Path) -> None:
    artifact = tmp_path / "DupeZ-GPU.exe"
    alias = tmp_path / "alias.exe"
    artifact.write_bytes(b"artifact")
    os.link(artifact, alias)

    with pytest.raises(RuntimeError, match="hard-linked"):
        validator._sha256(artifact, require_single_link=True)


def test_locked_release_executable_denies_transient_replacement(tmp_path: Path) -> None:
    artifact = tmp_path / "DupeZ-GPU.exe"
    artifact.write_bytes(b"artifact")
    expected_hash = validator._sha256(artifact, require_single_link=True)
    locked = validator._locked_release_executable(
        artifact,
        expected_hash=expected_hash,
        expected_size=artifact.stat().st_size,
    )
    try:
        with pytest.raises(OSError):
            artifact.write_bytes(b"replacement")
    finally:
        locked.close()

    artifact.write_bytes(b"replacement")
    assert artifact.read_bytes() == b"replacement"


def test_legacy_runtime_inputs_are_rejected(tmp_path: Path) -> None:
    (tmp_path / "logs").mkdir()

    with pytest.raises(RuntimeError, match="legacy runtime inputs"):
        validator._assert_no_legacy_runtime_inputs(tmp_path)


def test_dirty_evidence_never_uses_canonical_release_filename(tmp_path: Path) -> None:
    clean = validator._evidence_path(tmp_path, "GPU", "clean")
    dirty = validator._evidence_path(tmp_path, "GPU", "dirty-validation")

    assert clean.name == "frozen-runtime-evidence-gpu.json"
    assert dirty.name == "frozen-runtime-evidence-gpu.dirty-validation.json"
    assert dirty != clean


def test_evidence_write_is_atomic_and_refuses_existing_leaf(tmp_path: Path) -> None:
    evidence_path = tmp_path / "evidence.json"
    validator._atomic_write_evidence(evidence_path, {"schema": validator.SCHEMA})
    assert json.loads(evidence_path.read_text(encoding="utf-8")) == {"schema": validator.SCHEMA}

    with pytest.raises(RuntimeError, match="unexpectedly reappeared"):
        validator._atomic_write_evidence(evidence_path, {"schema": "replacement"})
    assert json.loads(evidence_path.read_text(encoding="utf-8")) == {"schema": validator.SCHEMA}


def test_evidence_invalidation_refuses_non_file_leaf(tmp_path: Path) -> None:
    evidence_path = tmp_path / "evidence.json"
    evidence_path.mkdir()

    with pytest.raises(RuntimeError, match="unsafe pre-existing"):
        validator._invalidate_evidence(evidence_path)

    assert evidence_path.is_dir()


def test_process_evidence_excludes_command_line(monkeypatch) -> None:
    class Process:
        pid = 123

        @staticmethod
        def ppid() -> int:
            return 12

        @staticmethod
        def name() -> str:
            return "DupeZ-GPU.exe"

        @staticmethod
        def cmdline() -> list[str]:
            raise AssertionError("command lines must never enter evidence")

    assert validator._process_info(Process()) == {
        "pid": 123,
        "parent_pid": 12,
        "name": "DupeZ-GPU.exe",
    }


def _run_profile_kwargs(executable: Path) -> dict:
    return {
        "variant": "GPU",
        "executable": executable,
        "executable_hash": "a" * 64,
        "executable_size": executable.stat().st_size,
        "commit": "b" * 40,
        "source_state": "dirty-validation",
        "source_fingerprint": "c" * 64,
        "validation_session_id": "11111111-1111-4111-8111-111111111111",
        "profile_name": "normal",
        "profile_environment": {
            "DUPEZ_LOW_RESOURCE": "0",
            "DUPEZ_MAP_PREWARM": "1",
            "DUPEZ_STARTUP_TIMEOUT_MS": "180000",
        },
        "cycle": 1,
        "startup_timeout": 1,
        "map_timeout": 1,
        "shutdown_timeout": 1,
        "is_admin": False,
    }


def test_popen_failure_still_removes_private_runtime_root(
    monkeypatch,
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    executable = tmp_path / "DupeZ-GPU.exe"
    executable.write_bytes(b"artifact")
    removed: list[Path] = []

    monkeypatch.setattr(validator, "_private_runtime_root", lambda **_kwargs: runtime_root)
    monkeypatch.setattr(validator, "_write_acknowledgement", lambda _root: None)
    monkeypatch.setattr(validator, "_write_safety_dry_run_settings", lambda _root: None)
    monkeypatch.setattr(validator, "_baseline_webengine_identities", lambda: set())
    monkeypatch.setattr(
        validator,
        "_locked_release_executable",
        lambda *_args, **_kwargs: io.BytesIO(b"locked"),
    )

    def fail_launch(*_args, **_kwargs):
        raise OSError("launch failed")

    def remove(root: Path) -> None:
        (root / "temp").rmdir()
        root.rmdir()
        removed.append(root)

    monkeypatch.setattr(validator.subprocess, "Popen", fail_launch)
    monkeypatch.setattr(validator, "_remove_private_runtime_root", remove)

    with pytest.raises(OSError, match="launch failed"):
        validator._run_profile(**_run_profile_kwargs(executable))

    assert removed == [runtime_root]
    assert not runtime_root.exists()


def test_keyboard_interrupt_runs_process_and_private_root_cleanup(
    monkeypatch,
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    executable = tmp_path / "DupeZ-GPU.exe"
    executable.write_bytes(b"artifact")
    cleaned: list[str] = []

    class Process:
        pid = 45001

        @staticmethod
        def poll() -> int:
            return 0

    monkeypatch.setattr(validator, "_private_runtime_root", lambda **_kwargs: runtime_root)
    monkeypatch.setattr(validator, "_write_acknowledgement", lambda _root: None)
    monkeypatch.setattr(validator, "_write_safety_dry_run_settings", lambda _root: None)
    monkeypatch.setattr(validator, "_baseline_webengine_identities", lambda: set())
    monkeypatch.setattr(
        validator,
        "_locked_release_executable",
        lambda *_args, **_kwargs: io.BytesIO(b"locked"),
    )
    monkeypatch.setattr(validator.subprocess, "Popen", lambda *_args, **_kwargs: Process())
    monkeypatch.setattr(validator.psutil, "Process", lambda _pid: object())
    monkeypatch.setattr(validator, "_process_identity", lambda _process: (45001, 1.0))
    monkeypatch.setattr(
        validator,
        "_find_dashboard",
        lambda _pid: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    monkeypatch.setattr(
        validator,
        "_terminate_started_family",
        lambda _pid, _identities: cleaned.append("processes"),
    )
    monkeypatch.setattr(
        validator,
        "_wait_for_process_identities_gone",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        validator,
        "_wait_for_no_new_webengine_processes",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        validator,
        "_wait_for_no_dupez_processes",
        lambda *_args, **_kwargs: cleaned.append("global-processes"),
    )

    def remove(root: Path) -> None:
        (root / "temp").rmdir()
        root.rmdir()
        cleaned.append("root")

    monkeypatch.setattr(validator, "_remove_private_runtime_root", remove)

    with pytest.raises(KeyboardInterrupt):
        validator._run_profile(**_run_profile_kwargs(executable))

    assert cleaned == ["processes", "global-processes", "root"]


def test_initial_identity_failure_stops_popen_before_private_root_cleanup(
    monkeypatch,
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    executable = tmp_path / "DupeZ-GPU.exe"
    executable.write_bytes(b"artifact")
    events: list[str] = []

    class Process:
        pid = 45002
        returncode = None

        def poll(self):
            return self.returncode

        def terminate(self) -> None:
            events.append("popen-terminate")
            self.returncode = -15

        def wait(self, timeout=None):
            del timeout
            events.append("popen-wait")
            return self.returncode

    process = Process()
    monkeypatch.setattr(validator, "_private_runtime_root", lambda **_kwargs: runtime_root)
    monkeypatch.setattr(validator, "_write_acknowledgement", lambda _root: None)
    monkeypatch.setattr(validator, "_write_safety_dry_run_settings", lambda _root: None)
    monkeypatch.setattr(validator, "_baseline_webengine_identities", lambda: set())
    monkeypatch.setattr(
        validator,
        "_locked_release_executable",
        lambda *_args, **_kwargs: io.BytesIO(b"locked"),
    )
    monkeypatch.setattr(validator.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(
        validator.psutil,
        "Process",
        lambda _pid: (_ for _ in ()).throw(RuntimeError("identity capture failed")),
    )
    monkeypatch.setattr(
        validator,
        "_terminate_started_family",
        lambda *_args, **_kwargs: events.append("family-cleanup"),
    )
    monkeypatch.setattr(validator, "_wait_for_process_identities_gone", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(validator, "_wait_for_no_dupez_processes", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        validator,
        "_wait_for_no_new_webengine_processes",
        lambda *_args, **_kwargs: None,
    )

    def remove(root: Path) -> None:
        assert process.poll() is not None
        (root / "temp").rmdir()
        root.rmdir()
        events.append("root-cleanup")

    monkeypatch.setattr(validator, "_remove_private_runtime_root", remove)

    with pytest.raises(RuntimeError, match="identity capture failed"):
        validator._run_profile(**_run_profile_kwargs(executable))

    assert events == [
        "family-cleanup",
        "popen-terminate",
        "popen-wait",
        "root-cleanup",
    ]


def test_cleanup_failure_preserves_primary_error_and_reports_cleanup_kind(
    monkeypatch,
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    executable = tmp_path / "DupeZ-GPU.exe"
    executable.write_bytes(b"artifact")
    monkeypatch.setattr(validator, "_private_runtime_root", lambda **_kwargs: runtime_root)
    monkeypatch.setattr(validator, "_write_acknowledgement", lambda _root: None)
    monkeypatch.setattr(validator, "_write_safety_dry_run_settings", lambda _root: None)
    monkeypatch.setattr(validator, "_baseline_webengine_identities", lambda: set())
    monkeypatch.setattr(
        validator,
        "_locked_release_executable",
        lambda *_args, **_kwargs: io.BytesIO(b"locked"),
    )
    monkeypatch.setattr(
        validator.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("primary")),
    )
    monkeypatch.setattr(
        validator,
        "_remove_private_runtime_root",
        lambda _root: (_ for _ in ()).throw(PermissionError("cleanup")),
    )

    with pytest.raises(RuntimeError, match="PermissionError") as raised:
        validator._run_profile(**_run_profile_kwargs(executable))

    assert isinstance(raised.value.__cause__, ValueError)


def test_release_inputs_are_rechecked_before_evidence(
    monkeypatch,
    tmp_path: Path,
) -> None:
    executable = tmp_path / "DupeZ-GPU.exe"
    executable.write_bytes(b"artifact")
    expected_source = ("a" * 40, "clean", "b" * 64)
    expected_executable = ("c" * 64, executable.stat().st_size)
    monkeypatch.setattr(
        validator,
        "_git_source_identity",
        lambda *_args, **_kwargs: ("d" * 40, "clean", "e" * 64),
    )

    with pytest.raises(RuntimeError, match="Source provenance changed"):
        validator._assert_release_inputs_unchanged(
            repo_root=tmp_path,
            executable=executable,
            allow_dirty=False,
            expected_source=expected_source,
            expected_executable=expected_executable,
        )

    monkeypatch.setattr(
        validator,
        "_git_source_identity",
        lambda *_args, **_kwargs: expected_source,
    )
    monkeypatch.setattr(validator, "_sha256", lambda *_args, **_kwargs: "f" * 64)
    with pytest.raises(RuntimeError, match="executable changed"):
        validator._assert_release_inputs_unchanged(
            repo_root=tmp_path,
            executable=executable,
            allow_dirty=False,
            expected_source=expected_source,
            expected_executable=expected_executable,
        )


def test_started_family_identity_leak_fails_closed(monkeypatch) -> None:
    ticks = iter((0.0, 0.5, 2.0))
    monkeypatch.setattr(validator.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(validator.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(validator, "_identity_process", lambda _identity: object())

    with pytest.raises(RuntimeError, match="leaked processes"):
        validator._wait_for_process_identities_gone({(50001, 1.0)}, timeout=1.0)


def test_new_global_webengine_helper_after_baseline_fails_closed(monkeypatch) -> None:
    baseline = {(51001, 1.0)}
    replies = iter(
        (
            baseline | {(51002, 2.0)},
            baseline | {(51002, 2.0)},
            baseline | {(51002, 2.0)},
        )
    )
    ticks = iter((0.0, 0.5, 2.0))
    monkeypatch.setattr(
        validator,
        "_matching_webengine_identities",
        lambda: next(replies),
    )
    monkeypatch.setattr(validator.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(validator.time, "sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError, match="QtWebEngine helper"):
        validator._wait_for_no_new_webengine_processes(baseline, timeout=1.0)


def test_stale_dupez_webengine_helper_is_not_grandfathered(
    monkeypatch,
    tmp_path: Path,
) -> None:
    helper_path = tmp_path / "DupeZ" / "release-validation" / "old" / "QtWebEngineProcess.exe"
    helper_path.parent.mkdir(parents=True)
    helper_path.write_bytes(b"helper")

    class Process:
        pid = 52001
        info = {"pid": pid, "name": "QtWebEngineProcess.exe"}

        @staticmethod
        def create_time() -> float:
            return 1.0

        @staticmethod
        def exe() -> str:
            return str(helper_path)

    monkeypatch.setattr(validator, "_windows_local_appdata", lambda: tmp_path)
    monkeypatch.setattr(
        validator.psutil,
        "process_iter",
        lambda _attributes: [Process()],
    )

    with pytest.raises(RuntimeError, match="stale DupeZ"):
        validator._baseline_webengine_identities()


def test_post_action_map_gate_does_not_reuse_pre_action_marker(
    monkeypatch,
    tmp_path: Path,
) -> None:
    log_root = tmp_path / "DupeZ" / "logs"
    log_root.mkdir(parents=True)
    log_path = log_root / "dupez.log"
    log_path.write_text(
        "\n".join(
            (
                validator.WEBENGINE_INITIALIZED_SIGNAL,
                validator.MAP_LOAD_FINISHED_SIGNAL,
                validator.MAP_DASHBOARD_ACTIVE_SIGNAL,
            )
        ),
        encoding="utf-8",
    )
    pre_action_text, cursor = validator._log_snapshot(tmp_path)
    ticks = iter((0.0, 0.5, 2.0))
    monkeypatch.setattr(validator.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(validator.time, "sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError, match="post-action state"):
        validator._wait_for_post_action_map_ready(
            tmp_path,
            cursor,
            initialized_before_action=(validator.WEBENGINE_INITIALIZED_SIGNAL in pre_action_text),
            load_finished_before_action=(validator.MAP_LOAD_FINISHED_SIGNAL in pre_action_text),
            timeout=1,
        )


def test_post_action_map_gate_accepts_only_new_dashboard_marker(tmp_path: Path) -> None:
    log_root = tmp_path / "DupeZ" / "logs"
    log_root.mkdir(parents=True)
    log_path = log_root / "dupez.log"
    log_path.write_text(
        validator.WEBENGINE_INITIALIZED_SIGNAL + "\n" + validator.MAP_LOAD_FINISHED_SIGNAL + "\n",
        encoding="utf-8",
    )
    pre_action_text, cursor = validator._log_snapshot(tmp_path)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(validator.MAP_DASHBOARD_ACTIVE_SIGNAL + "\n")

    assert (
        validator._wait_for_post_action_map_ready(
            tmp_path,
            cursor,
            initialized_before_action=(validator.WEBENGINE_INITIALIZED_SIGNAL in pre_action_text),
            load_finished_before_action=(validator.MAP_LOAD_FINISHED_SIGNAL in pre_action_text),
            timeout=1,
        )
        == validator.MAP_DASHBOARD_ACTIVE_SIGNAL
    )


def test_post_ready_stability_rejects_late_renderer_failure(tmp_path: Path) -> None:
    log_root = tmp_path / "DupeZ" / "logs"
    log_root.mkdir(parents=True)
    log_path = log_root / "dupez.log"
    log_path.write_text(
        validator.WEBENGINE_INITIALIZED_SIGNAL + "\n" + validator.MAP_LOAD_FINISHED_SIGNAL + "\n",
        encoding="utf-8",
    )
    _text, cursor = validator._log_snapshot(tmp_path)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(validator.MAP_DASHBOARD_ACTIVE_SIGNAL + "\n")
        handle.write("Map: renderer terminated unexpectedly\n")

    with pytest.raises(RuntimeError, match="failure marker observed"):
        validator._assert_post_ready_stability(tmp_path, cursor, duration=0)


def test_log_cursor_does_not_replay_rotated_pre_action_file(tmp_path: Path) -> None:
    log_root = tmp_path / "DupeZ" / "logs"
    log_root.mkdir(parents=True)
    current = log_root / "dupez.log"
    current.write_text(validator.MAP_DASHBOARD_ACTIVE_SIGNAL + "\n", encoding="utf-8")
    _text, cursor = validator._log_snapshot(tmp_path)

    current.rename(log_root / "dupez.log.1")
    current.write_text("new log without action marker\n", encoding="utf-8")

    suffix = validator._log_text_since(tmp_path, cursor)
    assert validator.MAP_DASHBOARD_ACTIVE_SIGNAL not in suffix
    assert "new log without action marker" in suffix


def test_log_cursor_fails_closed_on_same_file_truncation(tmp_path: Path) -> None:
    log_root = tmp_path / "DupeZ" / "logs"
    log_root.mkdir(parents=True)
    current = log_root / "dupez.log"
    current.write_text("a sufficiently long pre-action record\n", encoding="utf-8")
    _text, cursor = validator._log_snapshot(tmp_path)
    current.write_text("short\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="truncated"):
        validator._log_text_since(tmp_path, cursor)


@pytest.mark.parametrize(
    "message",
    (
        "QtWebEngine disabled; DayZ map will show a safe placeholder",
        "Map unavailable — placeholder",
        "Map: load_map — map_view is None, cannot navigate",
        "Map: WebEngine initialization failed (RuntimeError)",
        "Map: dashboard view active without WebEngine",
        "Map: renderer terminated unexpectedly",
        "Map: navigation failed",
        "Lazy map initialization failed",
    ),
)
def test_map_failure_markers_fail_closed(message: str) -> None:
    with pytest.raises(RuntimeError, match="failure marker observed"):
        validator._raise_for_map_failure(message)
