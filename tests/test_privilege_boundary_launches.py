"""Adversarial regressions for Windows privilege-boundary launches."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import subprocess
import sys
import time

import psutil
import pytest

import dupez_helper
from app.core import safe_subprocess, updater
from app.firewall_helper import auth as helper_auth
from app.firewall_helper import elevation, transport


def test_app_main_source_elevation_has_fixed_module_and_crt_quoting(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app import main as app_main

    interpreter = tmp_path / "python executable.exe"
    interpreter.write_bytes(b"test")
    adversarial = ["contains-app", 'quote"then\\tail', "plain"]
    monkeypatch.setattr(app_main.sys, "executable", str(interpreter))
    monkeypatch.setattr(app_main.sys, "argv", ["app/main.py", *adversarial])
    monkeypatch.delattr(app_main.sys, "frozen", raising=False)

    executable, parameters, working_dir = app_main._self_elevation_command()

    assert executable == str(interpreter)
    assert parameters == subprocess.list2cmdline(
        ["-m", "app.main", *adversarial]
    )
    assert Path(working_dir) == Path(app_main.__file__).resolve().parents[1]


def test_root_launcher_uses_fixed_absolute_source_entrypoint() -> None:
    source = (Path(__file__).resolve().parents[1] / "dupez.py").read_text(
        encoding="utf-8"
    )
    assert "[os.path.abspath(__file__), *passthrough]" in source
    assert "subprocess.list2cmdline(launch_argv)" in source
    assert '"app" not in' not in source


def test_helper_runas_uses_crt_quoting(monkeypatch, tmp_path: Path) -> None:
    interpreter = tmp_path / "python executable.exe"
    script = tmp_path / "helper script.py"
    interpreter.write_bytes(b"test")
    script.write_text("# test", encoding="utf-8")
    adversarial = 'value"with\\trailing\\'
    captured: dict[str, object] = {}

    monkeypatch.setattr(elevation.sys, "platform", "win32")
    monkeypatch.setattr(
        elevation,
        "_build_helper_argv",
        lambda *_args: [str(script), "--fixed", adversarial],
    )
    monkeypatch.setattr(elevation, "_python_exe", lambda: str(interpreter))

    class Shell32:
        @staticmethod
        def ShellExecuteExW(info_ptr):
            info = ctypes.cast(
                info_ptr,
                ctypes.POINTER(elevation._SHELLEXECUTEINFOW),
            ).contents
            captured["file"] = info.lpFile
            captured["params"] = info.lpParameters
            captured["show"] = info.nShow
            info.hProcess = 123
            return 1

    class Kernel32:
        @staticmethod
        def GetProcessId(_handle):
            return 456

        @staticmethod
        def CloseHandle(_handle):
            return 1

    monkeypatch.setattr(
        elevation.ctypes,
        "windll",
        type("Windll", (), {"shell32": Shell32(), "kernel32": Kernel32()})(),
        raising=False,
    )

    assert elevation.launch_helper_runas(os.getpid()) == 456
    assert captured["file"] == str(interpreter)
    assert captured["params"] == subprocess.list2cmdline(
        [str(script), "--fixed", adversarial]
    )
    assert captured["show"] == elevation._SW_SHOWNORMAL


def test_failed_helper_launch_securely_discards_sentinel(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        elevation,
        "probe_second_factor_boundary",
        lambda: calls.append("probe"),
    )
    monkeypatch.setattr(
        helper_auth,
        "write_token_sentinel",
        lambda _secret: calls.append("write"),
    )
    monkeypatch.setattr(
        helper_auth,
        "discard_token_sentinel",
        lambda: calls.append("discard") or True,
    )
    monkeypatch.setattr(
        elevation,
        "launch_helper_runas",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError(r"SENSITIVE C:\Users\operator\helper.exe")
        ),
    )

    with pytest.raises(elevation.ElevationError) as caught:
        elevation.ensure_helper_running(shared_secret=b"s" * 32)

    assert str(caught.value) == "helper launch failed"
    assert "SENSITIVE" not in str(caught.value)
    assert calls == ["probe", "write", "discard"]


def test_persistent_scheduled_task_paths_are_fail_closed(monkeypatch) -> None:
    monkeypatch.setenv("DUPEZ_ELEVATION", "scheduled_task")
    assert elevation.resolve_elevation_mode() == "scheduled_task"
    assert elevation.is_helper_task_registered() is False
    with pytest.raises(elevation.ElevationError, match="disabled"):
        elevation.register_helper_task()
    with pytest.raises(elevation.ElevationError, match="disabled"):
        elevation.launch_helper_via_task(os.getpid())
    with pytest.raises(elevation.ElevationError, match="disabled"):
        elevation.ensure_helper_running(
            mode="scheduled_task",
            shared_secret=b"x" * 32,
        )


class _ParentProcess:
    def __init__(self, created: float, running: bool = True) -> None:
        self._created = created
        self._running = running

    def create_time(self) -> float:
        return self._created

    def is_running(self) -> bool:
        return self._running


def test_helper_parent_identity_accepts_exact_live_process(monkeypatch) -> None:
    monkeypatch.setattr(psutil, "Process", lambda _pid: _ParentProcess(123.25))
    monkeypatch.setattr(dupez_helper.os, "getpid", lambda: 9999)

    assert dupez_helper._validate_parent_identity(1234, 123.25) == 123.25


@pytest.mark.parametrize(
    ("created", "running", "expected"),
    [(200.0, True, 100.0), (100.0, False, 100.0)],
)
def test_helper_parent_identity_rejects_stale_or_dead_process(
    monkeypatch,
    created: float,
    running: bool,
    expected: float,
) -> None:
    monkeypatch.setattr(
        psutil,
        "Process",
        lambda _pid: _ParentProcess(created, running),
    )
    monkeypatch.setattr(dupez_helper.os, "getpid", lambda: 9999)

    with pytest.raises(RuntimeError, match="parent"):
        dupez_helper._validate_parent_identity(1234, expected)


def test_helper_parent_identity_rejects_missing_pid() -> None:
    with pytest.raises(RuntimeError, match="parent"):
        dupez_helper._validate_parent_identity(0, 100.0)


class _PipeKernel32:
    def __init__(self, client_pid: int, succeeds: bool = True) -> None:
        self.client_pid = client_pid
        self.succeeds = succeeds

    def GetNamedPipeClientProcessId(self, _handle, pid_ptr):
        if not self.succeeds:
            return 0
        ctypes.cast(
            pid_ptr,
            ctypes.POINTER(transport.wintypes.ULONG),
        ).contents.value = self.client_pid
        return 1


def test_pipe_accepts_only_the_exact_launching_gui_pid() -> None:
    assert transport._client_matches_expected_parent(
        77,
        1234,
        kernel32=_PipeKernel32(1234),
    )


def test_sibling_with_stolen_token_cannot_connect_first() -> None:
    # Possession of the sentinel token is deliberately irrelevant here: the
    # OS-reported named-pipe client PID must still be the launching GUI.
    assert not transport._client_matches_expected_parent(
        77,
        1234,
        kernel32=_PipeKernel32(5678),
    )
    assert not transport._client_matches_expected_parent(
        77,
        1234,
        kernel32=_PipeKernel32(0, succeeds=False),
    )


def test_trusted_executable_cannot_reenable_path_search() -> None:
    with pytest.raises(safe_subprocess.SafeSubprocessError, match="absolute"):
        safe_subprocess._validate_argv(
            ["attacker-controlled.exe", "--flag"],
            trusted_executable=True,
        )


def test_system_binary_resolution_ignores_attacker_systemroot(
    monkeypatch,
) -> None:
    trusted = os.path.join("C:\\", "Windows", "System32")
    monkeypatch.setenv("SystemRoot", r"C:\attacker")
    monkeypatch.setattr(
        safe_subprocess,
        "_windows_system_directory",
        lambda: trusted,
    )
    monkeypatch.setattr(safe_subprocess.os, "name", "nt")
    monkeypatch.setattr(safe_subprocess.os.path, "isfile", lambda _path: True)

    resolved = safe_subprocess.resolve_system_binary("taskkill")
    nested = safe_subprocess.resolve_system_binary(
        "powershell",
        subdirectory=("WindowsPowerShell", "v1.0"),
    )

    assert resolved == os.path.join(trusted, "taskkill.exe")
    assert nested == os.path.join(
        trusted,
        "WindowsPowerShell",
        "v1.0",
        "powershell.exe",
    )
    assert "attacker" not in resolved.casefold()
    assert "attacker" not in nested.casefold()


@pytest.mark.parametrize("name", [r"..\evil", r"sub\evil", "..", ""])
def test_system_binary_resolution_rejects_path_components(name: str) -> None:
    with pytest.raises(safe_subprocess.SafeSubprocessError, match="unsafe"):
        safe_subprocess.resolve_system_binary(name)


@pytest.mark.parametrize(
    "relative_path",
    [
        "app/core/defender_posture.py",
        "app/core/gpu_probe.py",
        "app/core/network_health.py",
        "app/core/pktmon_capture.py",
        "app/firewall_helper/feature_flag.py",
        "app/gpc/device_bridge.py",
    ],
)
def test_system_executable_callsites_use_trusted_resolver(
    relative_path: str,
) -> None:
    source = (
        Path(__file__).resolve().parents[1] / relative_path
    ).read_text(encoding="utf-8")

    assert "resolve_system_binary" in source


def test_renderer_policy_has_no_system_process_fallback() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "app/gui/map_host/renderer_tier.py"
    ).read_text(encoding="utf-8")

    assert "subprocess" not in source
    assert "wmic" not in source.casefold()
    assert 'environ.get("SystemRoot"' not in source
    assert 'getenv("SystemRoot"' not in source


def test_module_trust_roots_use_os_derived_system_directory() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "app/offsec/recon.py"
    ).read_text(encoding="utf-8")

    assert "_windows_system_directory" in source
    assert 'environ.get("SystemRoot"' not in source
    assert 'getenv("SystemRoot"' not in source


class _ProcessKernel32:
    def __init__(self, image: str, creation_time: int = 12345) -> None:
        self.image = image
        self.creation_time = creation_time
        self.terminated = False
        self.closed = False
        self.opened: list[tuple[int, int]] = []

    def OpenProcess(self, access, _inherit, pid):
        self.opened.append((access, pid))
        return 101

    def QueryFullProcessImageNameW(self, _handle, _flags, buffer, size_ptr):
        del size_ptr
        buffer.value = self.image
        return 1

    def GetProcessTimes(
        self,
        _handle,
        creation_ptr,
        _exit_ptr,
        _kernel_ptr,
        _user_ptr,
    ):
        creation_ptr._obj.dwLowDateTime = self.creation_time & 0xFFFFFFFF
        creation_ptr._obj.dwHighDateTime = self.creation_time >> 32
        return 1

    def TerminateProcess(self, _handle, _code):
        self.terminated = True
        return 1

    def CloseHandle(self, _handle):
        self.closed = True
        return 1


def test_trusted_dupez_images_are_limited_to_current_and_installed_roots(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        updater.sys,
        "executable",
        r"C:\Portable\DupeZ\DupeZ-GPU.exe",
    )
    monkeypatch.setattr(
        updater,
        "_get_install_dir",
        lambda: Path(r"C:\Program Files\DupeZ"),
    )

    paths = updater._trusted_dupez_image_paths({
        "dupez.exe",
        "dupez-gpu.exe",
    })

    assert updater._normalize_windows_image_path(
        r"C:\Portable\DupeZ\dupez.exe"
    ) in paths
    assert updater._normalize_windows_image_path(
        r"C:\Program Files\DupeZ\dupez-gpu.exe"
    ) in paths
    assert updater._normalize_windows_image_path(
        r"C:\Temp\dupez.exe"
    ) not in paths


def test_name_collision_outside_trusted_dupez_paths_is_not_snapshotted() -> None:
    kernel32 = _ProcessKernel32(r"C:\Temp\DupeZ.exe")
    trusted = {
        updater._normalize_windows_image_path(
            r"C:\Program Files\DupeZ\DupeZ.exe"
        )
    }

    assert updater._snapshot_process_identity(kernel32, 1234, trusted) is None
    assert kernel32.terminated is False
    assert kernel32.closed is True


def test_pid_reuse_with_same_image_path_but_new_creation_time_is_refused() -> None:
    kernel32 = _ProcessKernel32(r"C:\Program Files\DupeZ\DupeZ.exe")
    trusted = {
        updater._normalize_windows_image_path(
            r"C:\Program Files\DupeZ\DupeZ.exe"
        )
    }
    captured = updater._snapshot_process_identity(kernel32, 1234, trusted)
    assert captured is not None
    kernel32.creation_time += 1

    assert not updater._terminate_process_identity(kernel32, captured)
    assert kernel32.terminated is False


def test_verified_dupez_identity_can_be_terminated() -> None:
    kernel32 = _ProcessKernel32(r"C:\Program Files\DupeZ\DupeZ.exe")
    trusted = {
        updater._normalize_windows_image_path(
            r"C:\Program Files\DupeZ\DupeZ.exe"
        )
    }
    captured = updater._snapshot_process_identity(kernel32, 1234, trusted)
    assert captured is not None

    assert updater._terminate_process_identity(kernel32, captured)
    assert kernel32.terminated is True
    assert kernel32.closed is True


def test_map_host_launch_validation_preserves_argument_boundaries(
    tmp_path: Path,
) -> None:
    from app.gui.map_host import launcher

    executable = tmp_path / "python with spaces.exe"
    executable.write_bytes(b"test")
    argv = ["-m", "app.gui.map_host.host", 'quote"and\\tail']

    resolved, clean = launcher._validated_spawn(str(executable), argv)

    assert resolved == str(executable)
    assert clean == argv
    assert subprocess.list2cmdline(clean) == subprocess.list2cmdline(argv)
    with pytest.raises(ValueError, match="absolute"):
        launcher._validated_spawn("python.exe", argv)


def test_map_host_shell_token_spawn_retains_real_process_identity(
    tmp_path: Path,
) -> None:
    from app.gui.map_host import launcher

    executable = tmp_path / "python.exe"
    executable.write_bytes(b"test")
    closed: list[int] = []

    class FakeApi:
        def open_shell_token(self) -> int:
            return 70

        def token_is_elevated(self, token_handle: int) -> bool:
            assert token_handle == 70
            return False

        def create_process(
            self,
            token_handle: int,
            requested_executable: str,
            argv,
            cwd: str,
        ):
            assert token_handle == 70
            assert requested_executable == str(executable)
            assert argv == ["-m", "app.gui.map_host.host"]
            assert cwd == launcher._REPO_ROOT
            return launcher._SpawnedChild(
                pid=4242,
                process_handle=80,
                close_handle=closed.append,
                terminate_callback=lambda: None,
                wait_callback=lambda _timeout_ms: True,
            )

        def close_handle(self, handle: int) -> None:
            closed.append(handle)

    child = launcher._spawn_with_shell_token(
        str(executable),
        ["-m", "app.gui.map_host.host"],
        api=FakeApi(),
    )

    assert child.pid == 4242
    assert closed == [70]
    child.close()
    child.close()
    assert closed == [70, 80]


def test_map_host_windows_spawn_failure_never_uses_elevated_fallback(
    monkeypatch,
) -> None:
    from app.gui.map_host import launcher

    class ElevatedApi:
        @staticmethod
        def current_process_is_elevated() -> bool:
            return True

    monkeypatch.setattr(launcher.sys, "platform", "win32")
    monkeypatch.setattr(
        launcher,
        "_spawn_with_shell_token",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("shell token unavailable")
        ),
    )
    monkeypatch.setattr(
        launcher,
        "_spawn_popen",
        lambda *_args, **_kwargs: pytest.fail(
            "Windows failure fell back to inherited-token Popen"
        ),
    )

    assert launcher._spawn_unelevated(
        sys.executable,
        [],
        api=ElevatedApi(),
    ) is None


def test_map_host_verified_unelevated_windows_parent_can_spawn_directly(
    monkeypatch,
) -> None:
    from app.gui.map_host import launcher

    class UnelevatedApi:
        @staticmethod
        def current_process_is_elevated() -> bool:
            return False

    expected = launcher._SpawnedChild(
        pid=4242,
        terminate_callback=lambda: None,
        wait_callback=lambda _timeout_ms: True,
    )
    monkeypatch.setattr(launcher.sys, "platform", "win32")
    monkeypatch.setattr(
        launcher,
        "_spawn_popen",
        lambda *_args, **_kwargs: expected,
    )
    monkeypatch.setattr(
        launcher,
        "_spawn_with_shell_token",
        lambda *_args, **_kwargs: pytest.fail(
            "unelevated Windows parent unnecessarily used token relaunch"
        ),
    )

    assert launcher._spawn_unelevated(
        sys.executable,
        [],
        api=UnelevatedApi(),
    ) is expected


def test_map_host_managed_spawn_receives_sanitized_webengine_environment(
    monkeypatch,
    tmp_path,
) -> None:
    from app.core import safe_subprocess
    from app.gui.map_host import launcher

    executable = tmp_path / "python.exe"
    executable.write_bytes(b"test")
    captured: dict[str, object] = {}

    class _Managed:
        pid = 4242

        @staticmethod
        def kill() -> None:
            return None

        @staticmethod
        def wait(_timeout: float) -> bool:
            return True

    def _spawn_managed(_argv, **kwargs):
        captured.update(kwargs)
        return _Managed()

    monkeypatch.setenv("QTWEBENGINE_DISABLE_SANDBOX", "1")
    monkeypatch.setenv("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")
    monkeypatch.setenv("QT_OPENGL", "software")
    monkeypatch.setattr(safe_subprocess, "spawn_managed", _spawn_managed)

    child = launcher._spawn_popen(str(executable), [])

    assert child is not None
    environment = captured["env"]
    assert isinstance(environment, dict)
    assert "QTWEBENGINE_DISABLE_SANDBOX" not in environment
    assert "QT_OPENGL" not in environment
    assert environment["QTWEBENGINE_CHROMIUM_FLAGS"] == (
        launcher.child_webengine_environment({})[
            "QTWEBENGINE_CHROMIUM_FLAGS"
        ]
    )


def test_map_host_spawned_child_termination_is_idempotent() -> None:
    from app.gui.map_host import launcher

    terminated: list[str] = []
    closed: list[int] = []
    child = launcher._SpawnedChild(
        pid=4242,
        process_handle=80,
        close_handle=closed.append,
        terminate_callback=lambda: terminated.append("terminated"),
    )

    child.terminate()
    child.terminate()

    assert terminated == ["terminated"]
    assert closed == [80]


def test_managed_process_wait_is_bounded_and_reports_exit() -> None:
    waits: list[float] = []

    class FakeProcess:
        returncode = None

        def wait(self, timeout: float) -> int:
            waits.append(timeout)
            if len(waits) == 1:
                raise subprocess.TimeoutExpired("map-host", timeout)
            self.returncode = 0
            return 0

    managed = safe_subprocess.ManagedProcess(
        FakeProcess(),
        intent="map_host.wait_test",
        started_at=time.monotonic(),
    )

    assert not managed.wait(0.01)
    assert managed.wait(0.02)
    assert waits == [0.01, 0.02]


def test_map_host_accepts_authenticated_hello_from_hwnd_owner() -> None:
    from app.gui.map_host import launcher

    nonce = "a5" * 32
    message = {
        "type": "hello",
        "session_nonce": nonce,
        "pid": 4242,
        "hwnd": 0x1234,
    }
    lookups: list[int] = []

    def owner_pid(hwnd: int) -> int:
        lookups.append(hwnd)
        return 4242

    assert launcher._validate_child_hello(
        message,
        nonce,
        4242,
        current_platform="win32",
        window_pid_lookup=owner_pid,
    ) == (0x1234, 4242)
    assert lookups == [0x1234]


def test_map_host_rejects_hello_with_wrong_nonce_before_hwnd_lookup() -> None:
    from app.gui.map_host import launcher

    message = {
        "type": "hello",
        "session_nonce": "00" * 32,
        "pid": 4242,
        "hwnd": 0x1234,
    }

    def unexpected_lookup(_hwnd: int) -> int:
        pytest.fail("unauthenticated hello reached HWND owner lookup")

    with pytest.raises(ValueError, match="authentication failed"):
        launcher._validate_child_hello(
            message,
            "ff" * 32,
            4242,
            current_platform="win32",
            window_pid_lookup=unexpected_lookup,
        )


def test_map_host_rejects_claimed_pid_that_differs_from_spawned_pid() -> None:
    from app.gui.map_host import launcher

    nonce = "b4" * 32
    message = {
        "type": "hello",
        "session_nonce": nonce,
        "pid": 9001,
        "hwnd": 0x1234,
    }

    def unexpected_lookup(_hwnd: int) -> int:
        pytest.fail("PID-mismatched hello reached HWND owner lookup")

    with pytest.raises(ValueError, match="does not match spawned child pid"):
        launcher._validate_child_hello(
            message,
            nonce,
            4242,
            current_platform="win32",
            window_pid_lookup=unexpected_lookup,
        )


def test_map_host_rejects_hello_when_hwnd_has_different_owner() -> None:
    from app.gui.map_host import launcher

    nonce = "c3" * 32
    message = {
        "type": "hello",
        "session_nonce": nonce,
        "pid": 4242,
        "hwnd": 0x1234,
    }

    with pytest.raises(ValueError, match="owner does not match spawned child pid"):
        launcher._validate_child_hello(
            message,
            nonce,
            4242,
            current_platform="win32",
            window_pid_lookup=lambda _hwnd: 9001,
        )


def test_map_host_rejects_oversized_unauthenticated_frame() -> None:
    from app.gui.map_host import launcher

    allowed = b"x" * launcher._MAX_CHILD_FRAME_BYTES
    assert launcher._append_child_frame_bytes(b"", allowed) == allowed
    with pytest.raises(ValueError, match="child hello exceeds"):
        launcher._append_child_frame_bytes(allowed, b"x")


def test_map_host_tcp_owner_match_uses_exact_reverse_four_tuple() -> None:
    from app.gui.map_host import launcher

    rows = (
        launcher._TcpOwnerRow("127.0.0.1", 55000, "127.0.0.1", 43123, 4242),
        launcher._TcpOwnerRow("127.0.0.1", 43123, "127.0.0.1", 55000, 1111),
    )

    assert launcher._peer_pid_from_rows(
        rows,
        "127.0.0.1",
        55000,
        "127.0.0.1",
        43123,
    ) == 4242


def test_map_host_tcp_owner_match_fails_on_ambiguity() -> None:
    from app.gui.map_host import launcher

    row = launcher._TcpOwnerRow(
        "127.0.0.1",
        55000,
        "127.0.0.1",
        43123,
        4242,
    )
    with pytest.raises(RuntimeError, match="ambiguous"):
        launcher._peer_pid_from_rows(
            (row, row),
            "127.0.0.1",
            55000,
            "127.0.0.1",
            43123,
        )


def test_map_host_non_windows_peer_validation_is_explicit_noop() -> None:
    from app.gui.map_host import launcher

    assert launcher._validate_child_socket_peer(
        object(),
        4242,
        current_platform="linux",
        peer_pid_lookup=lambda *_endpoint: pytest.fail(
            "non-Windows peer validation invoked the Windows owner lookup"
        ),
    ) == 4242


@pytest.mark.parametrize(
    ("previous_parent", "last_error", "expected"),
    [(0, 0, True), (0, 5, False), (123, 0, True)],
)
def test_set_parent_zero_result_uses_error_and_actual_parent(
    previous_parent: int,
    last_error: int,
    expected: bool,
) -> None:
    from app.gui.map_host import launcher

    assert launcher._set_parent_result_is_successful(
        previous_parent,
        last_error,
        456,
        456,
    ) is expected
    assert not launcher._set_parent_result_is_successful(
        previous_parent,
        last_error,
        999,
        456,
    )


@pytest.mark.parametrize(
    ("value", "last_error", "expected"),
    [(0, 0, True), (0, 5, False), (123, 5, True)],
)
def test_window_long_zero_result_uses_last_error(
    value: int,
    last_error: int,
    expected: bool,
) -> None:
    from app.gui.map_host import launcher

    assert launcher._window_long_result_is_successful(
        value,
        last_error,
    ) is expected


class _FakeReparentApi:
    ORIGINAL_STYLE = 0x90CF0000

    def __init__(
        self,
        *,
        fail_on_calls: dict[str, set[int]] | None = None,
    ) -> None:
        self.parent = 0
        self.style = self.ORIGINAL_STYLE
        self.size: tuple[int, int] | None = None
        self.shown = False
        self.calls: list[tuple] = []
        self._call_counts: dict[str, int] = {}
        self._fail_on_calls = fail_on_calls or {}

    def _fail_if_requested(self, operation: str) -> None:
        call_number = self._call_counts.get(operation, 0) + 1
        self._call_counts[operation] = call_number
        if call_number in self._fail_on_calls.get(operation, set()):
            raise OSError(5, f"forced {operation} failure")

    def get_parent(self, hwnd: int) -> int:
        self.calls.append(("get_parent", hwnd))
        self._fail_if_requested("get_parent")
        return self.parent

    def get_style(self, hwnd: int) -> int:
        self.calls.append(("get_style", hwnd))
        self._fail_if_requested("get_style")
        return self.style

    def set_parent(
        self,
        hwnd: int,
        parent_hwnd: int,
        *,
        verify_actual: bool = True,
    ) -> None:
        self.calls.append(("set_parent", hwnd, parent_hwnd, verify_actual))
        self._fail_if_requested("set_parent")
        self.parent = parent_hwnd

    def set_style(self, hwnd: int, style: int) -> None:
        self.calls.append(("set_style", hwnd, style))
        self._fail_if_requested("set_style")
        self.style = style

    def resize_and_refresh(self, hwnd: int, width: int, height: int) -> None:
        self.calls.append(("resize_and_refresh", hwnd, width, height))
        self._fail_if_requested("resize_and_refresh")
        self.size = (width, height)

    def refresh_frame(self, hwnd: int) -> None:
        self.calls.append(("refresh_frame", hwnd))
        self._fail_if_requested("refresh_frame")

    def show(self, hwnd: int) -> None:
        self.calls.append(("show", hwnd))
        self._fail_if_requested("show")
        self.shown = True


def test_map_host_reparent_transaction_checks_every_required_step() -> None:
    from app.gui.map_host import launcher

    api = _FakeReparentApi()

    assert launcher._reparent_hwnd_with_api(100, 200, 800, 600, api)
    expected_style = (
        _FakeReparentApi.ORIGINAL_STYLE & ~0x80CF0000
    ) | 0x40000000
    assert api.style == expected_style
    assert api.parent == 200
    assert api.size == (800, 600)
    assert api.shown


@pytest.mark.parametrize("operation", ["get_parent", "get_style"])
def test_map_host_reparent_capture_failure_does_not_mutate(
    operation: str,
) -> None:
    from app.gui.map_host import launcher

    api = _FakeReparentApi(fail_on_calls={operation: {1}})

    assert not launcher._reparent_hwnd_with_api(100, 200, 800, 600, api)
    assert api.parent == 0
    assert api.style == _FakeReparentApi.ORIGINAL_STYLE
    assert not any(call[0].startswith("set_") for call in api.calls)
    assert not api.shown


def test_map_host_reparent_set_style_failure_never_reports_success() -> None:
    from app.gui.map_host import launcher

    api = _FakeReparentApi(fail_on_calls={"set_style": {1}})

    assert not launcher._reparent_hwnd_with_api(100, 200, 800, 600, api)
    assert api.parent == 0
    assert api.style == _FakeReparentApi.ORIGINAL_STYLE
    assert not api.shown


def test_map_host_reparent_set_parent_failure_restores_original_style() -> None:
    from app.gui.map_host import launcher

    api = _FakeReparentApi(fail_on_calls={"set_parent": {1}})

    assert not launcher._reparent_hwnd_with_api(100, 200, 800, 600, api)
    assert api.parent == 0
    assert api.style == _FakeReparentApi.ORIGINAL_STYLE
    assert ("refresh_frame", 100) in api.calls
    assert not api.shown


def test_map_host_reparent_set_window_pos_failure_restores_all_state() -> None:
    from app.gui.map_host import launcher

    api = _FakeReparentApi(fail_on_calls={"resize_and_refresh": {1}})

    assert not launcher._reparent_hwnd_with_api(100, 200, 800, 600, api)
    assert api.parent == 0
    assert api.style == _FakeReparentApi.ORIGINAL_STYLE
    assert ("set_parent", 100, 0, False) in api.calls
    assert ("refresh_frame", 100) in api.calls
    assert not api.shown


def test_map_host_reparent_rollback_failure_cannot_be_false_success() -> None:
    from app.gui.map_host import launcher

    api = _FakeReparentApi(
        fail_on_calls={
            "resize_and_refresh": {1},
            "set_parent": {2},
        }
    )

    assert not launcher._reparent_hwnd_with_api(100, 200, 800, 600, api)
    assert api.parent == 200
    assert api.style == _FakeReparentApi.ORIGINAL_STYLE
    assert not api.shown


def _pump_qt_until(application, predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        application.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    application.processEvents()
    return bool(predicate())


def _map_host_hello_payload(nonce: str, pid: int, hwnd: int) -> bytes:
    import json

    return json.dumps({
        "type": "hello",
        "session_nonce": nonce,
        "pid": pid,
        "hwnd": hwnd,
    }).encode("utf-8") + b"\n"


def _send_map_host_hello(
    socket,
    nonce: str,
    pid: int,
    hwnd: int,
    *,
    suffix: bytes = b"",
) -> None:
    payload = _map_host_hello_payload(nonce, pid, hwnd) + suffix
    assert socket.write(payload) == len(payload)
    socket.flush()


def _owned_map_child(
    launcher,
    *,
    pid: int = 4242,
    wait_callback=None,
    terminate_callback=None,
):
    return launcher._SpawnedChild(
        pid=pid,
        wait_callback=wait_callback or (lambda _timeout_ms: True),
        terminate_callback=terminate_callback or (lambda: None),
    )


def test_map_host_frozen_runtime_fails_before_listen_or_spawn(monkeypatch) -> None:
    from PyQt6.QtCore import QCoreApplication

    from app.gui.map_host import launcher

    QCoreApplication.instance() or QCoreApplication([])
    monkeypatch.setattr(launcher.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        launcher,
        "_spawn_unelevated",
        lambda *_args: pytest.fail("frozen map host attempted to spawn"),
    )
    client = launcher.MapHostClient()
    failures: list[str] = []
    client.connectionFailed.connect(failures.append)

    assert not client.start()
    assert not client._server.isListening()
    assert failures and "frozen builds" in failures[0]


def test_map_host_windows_requires_owned_child_lifecycle(monkeypatch) -> None:
    from PyQt6.QtCore import QCoreApplication

    from app.gui.map_host import launcher

    QCoreApplication.instance() or QCoreApplication([])
    monkeypatch.setattr(launcher.sys, "platform", "win32")
    monkeypatch.setattr(launcher.sys, "frozen", False, raising=False)
    monkeypatch.setattr(
        launcher,
        "_spawn_unelevated",
        lambda *_args: launcher._SpawnedChild(pid=4242),
    )
    client = launcher.MapHostClient()
    failures: list[str] = []
    client.connectionFailed.connect(failures.append)

    assert not client.start()
    assert not client._server.isListening()
    assert failures == ["map-host child lifecycle ownership is unavailable"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows TCP owner table only")
def test_map_host_real_windows_tcp_owner_lookup_on_loopback() -> None:
    from PyQt6.QtCore import QCoreApplication
    from PyQt6.QtNetwork import QHostAddress, QTcpServer, QTcpSocket

    from app.gui.map_host import launcher

    application = QCoreApplication.instance() or QCoreApplication([])
    server = QTcpServer()
    assert server.listen(QHostAddress.SpecialAddress.LocalHost, 0)
    client = QTcpSocket()
    client.connectToHost("127.0.0.1", server.serverPort())
    assert client.waitForConnected(1000)
    assert _pump_qt_until(application, server.hasPendingConnections)
    accepted = server.nextPendingConnection()
    assert accepted is not None

    assert launcher._windows_tcp_peer_process_id(
        accepted.peerAddress().toString(),
        accepted.peerPort(),
        accepted.localAddress().toString(),
        accepted.localPort(),
    ) == os.getpid()

    accepted.abort()
    client.abort()
    server.close()


def test_map_host_bad_first_connector_does_not_consume_listener(
    monkeypatch,
) -> None:
    from PyQt6.QtCore import QCoreApplication
    from PyQt6.QtNetwork import QTcpSocket

    from app.gui.map_host import launcher

    application = QCoreApplication.instance() or QCoreApplication([])
    monkeypatch.setattr(
        launcher,
        "_spawn_unelevated",
        lambda *_args: _owned_map_child(launcher),
    )
    monkeypatch.setattr(launcher, "_window_process_id", lambda _hwnd: 4242)
    client = launcher.MapHostClient(
        peer_pid_lookup=lambda *_endpoint: 4242,
    )
    received: list[int] = []
    failures: list[str] = []
    client.hwndReceived.connect(received.append)
    client.connectionFailed.connect(failures.append)
    assert client.start()
    nonce = client._session_nonce
    assert nonce is not None
    port = client._server.serverPort()

    bad = QTcpSocket()
    bad.connectToHost("127.0.0.1", port)
    assert bad.waitForConnected(1000)
    assert _pump_qt_until(application, lambda: bool(client._candidate_buffers))
    candidate = next(iter(client._candidate_buffers))
    assert candidate.readBufferSize() == launcher._MAX_CHILD_FRAME_BYTES + 1
    _send_map_host_hello(bad, "00" * 32, 9001, 0x9999)
    assert _pump_qt_until(
        application,
        lambda: not client._candidate_buffers,
    )
    assert client._server.isListening()
    assert client._session_nonce == nonce
    assert client._expected_pid == 4242
    assert failures == []

    expected = QTcpSocket()
    expected.connectToHost("127.0.0.1", port)
    assert expected.waitForConnected(1000)
    _send_map_host_hello(expected, nonce, 4242, 0x1234)
    assert _pump_qt_until(application, lambda: received == [0x1234])
    assert not client._server.isListening()
    assert client._sock is not bad
    assert client._sock is not None
    client.stop()
    expected.abort()
    bad.abort()


def test_map_host_idle_first_connector_times_out_then_child_authenticates(
    monkeypatch,
) -> None:
    from PyQt6.QtCore import QCoreApplication
    from PyQt6.QtNetwork import QTcpSocket

    from app.gui.map_host import launcher

    application = QCoreApplication.instance() or QCoreApplication([])
    monkeypatch.setattr(launcher, "_CHILD_HELLO_TIMEOUT_MS", 25)
    monkeypatch.setattr(
        launcher,
        "_spawn_unelevated",
        lambda *_args: _owned_map_child(launcher),
    )
    monkeypatch.setattr(launcher, "_window_process_id", lambda _hwnd: 4242)
    client = launcher.MapHostClient(
        peer_pid_lookup=lambda *_endpoint: 4242,
    )
    received: list[int] = []
    failures: list[str] = []
    client.hwndReceived.connect(received.append)
    client.connectionFailed.connect(failures.append)
    assert client.start()
    nonce = client._session_nonce
    assert nonce is not None
    port = client._server.serverPort()

    idle = QTcpSocket()
    idle.connectToHost("127.0.0.1", port)
    assert idle.waitForConnected(1000)
    assert _pump_qt_until(application, lambda: bool(client._candidate_buffers))
    assert _pump_qt_until(
        application,
        lambda: not client._candidate_buffers,
    )
    assert client._server.isListening()
    assert client._session_nonce == nonce
    assert client._expected_pid == 4242
    assert failures == []

    expected = QTcpSocket()
    expected.connectToHost("127.0.0.1", port)
    assert expected.waitForConnected(1000)
    _send_map_host_hello(expected, nonce, 4242, 0x5678)
    assert _pump_qt_until(application, lambda: received == [0x5678])
    client.stop()
    expected.abort()
    idle.abort()


def test_map_host_launch_deadline_terminates_unauthenticated_child(
    monkeypatch,
) -> None:
    from PyQt6.QtCore import QCoreApplication

    from app.gui.map_host import launcher

    application = QCoreApplication.instance() or QCoreApplication([])
    terminated: list[int] = []
    monkeypatch.setattr(launcher, "_CHILD_LAUNCH_TIMEOUT_MS", 25)
    monkeypatch.setattr(
        launcher,
        "_spawn_unelevated",
        lambda *_args: launcher._SpawnedChild(
            pid=4242,
            terminate_callback=lambda: terminated.append(4242),
            wait_callback=lambda _timeout_ms: False,
        ),
    )
    client = launcher.MapHostClient()
    failures: list[str] = []
    client.connectionFailed.connect(failures.append)

    assert client.start()
    assert _pump_qt_until(application, lambda: bool(failures))

    assert failures == ["map-host launch authentication deadline exceeded"]
    assert terminated == [4242]
    assert client._spawned_child is None
    assert client._expected_pid is None
    assert client._session_nonce is None
    assert not client._server.isListening()
    client.stop()
    assert terminated == [4242]


def test_map_host_peer_pid_binds_valid_hello_to_actual_connector(
    monkeypatch,
) -> None:
    from PyQt6.QtCore import QCoreApplication
    from PyQt6.QtNetwork import QAbstractSocket, QTcpSocket

    from app.gui.map_host import launcher

    application = QCoreApplication.instance() or QCoreApplication([])
    monkeypatch.setattr(
        launcher,
        "_spawn_unelevated",
        lambda *_args: _owned_map_child(launcher),
    )
    monkeypatch.setattr(launcher, "_window_process_id", lambda _hwnd: 4242)
    actual_peer_pid = [9001]
    client = launcher.MapHostClient(
        peer_pid_lookup=lambda *_endpoint: actual_peer_pid[0],
    )
    received: list[int] = []
    client.hwndReceived.connect(received.append)
    assert client.start()
    nonce = client._session_nonce
    assert nonce is not None
    port = client._server.serverPort()

    attacker = QTcpSocket()
    attacker.connectToHost("127.0.0.1", port)
    assert attacker.waitForConnected(1000)
    _send_map_host_hello(attacker, nonce, 4242, 0x1234)
    assert _pump_qt_until(
        application,
        lambda: attacker.state()
        == QAbstractSocket.SocketState.UnconnectedState,
    )
    assert received == []
    assert client._candidate_buffers == {}
    assert client._server.isListening()

    actual_peer_pid[0] = 4242
    expected = QTcpSocket()
    expected.connectToHost("127.0.0.1", port)
    assert expected.waitForConnected(1000)
    _send_map_host_hello(expected, nonce, 4242, 0x1234)
    assert _pump_qt_until(application, lambda: received == [0x1234])

    client.stop()
    expected.abort()
    attacker.abort()


def test_map_host_transport_rejects_same_read_hello_remainder(
    monkeypatch,
) -> None:
    from PyQt6.QtCore import QCoreApplication
    from PyQt6.QtNetwork import QTcpSocket

    from app.gui.map_host import launcher

    application = QCoreApplication.instance() or QCoreApplication([])
    monkeypatch.setattr(
        launcher,
        "_spawn_unelevated",
        lambda *_args: _owned_map_child(launcher),
    )
    monkeypatch.setattr(launcher, "_window_process_id", lambda _hwnd: 4242)
    client = launcher.MapHostClient(peer_pid_lookup=lambda *_endpoint: 4242)
    received: list[int] = []
    client.hwndReceived.connect(received.append)
    assert client.start()
    nonce = client._session_nonce
    assert nonce is not None

    connector = QTcpSocket()
    connector.connectToHost("127.0.0.1", client._server.serverPort())
    assert connector.waitForConnected(1000)
    _send_map_host_hello(
        connector,
        nonce,
        4242,
        0x1234,
        suffix=b"unexpected",
    )
    assert _pump_qt_until(
        application,
        lambda: not client._candidate_buffers,
    )
    assert received == []
    assert client._server.isListening()

    client.stop()
    connector.abort()


def test_map_host_transport_cap_rejects_oversized_socket_input(
    monkeypatch,
) -> None:
    from PyQt6.QtCore import QCoreApplication
    from PyQt6.QtNetwork import QTcpSocket

    from app.gui.map_host import launcher

    application = QCoreApplication.instance() or QCoreApplication([])
    monkeypatch.setattr(
        launcher,
        "_spawn_unelevated",
        lambda *_args: _owned_map_child(launcher),
    )
    client = launcher.MapHostClient(peer_pid_lookup=lambda *_endpoint: 4242)
    assert client.start()

    connector = QTcpSocket()
    connector.connectToHost("127.0.0.1", client._server.serverPort())
    assert connector.waitForConnected(1000)
    oversized = b"x" * (launcher._MAX_CHILD_FRAME_BYTES + 1)
    assert connector.write(oversized) == len(oversized)
    connector.flush()
    assert _pump_qt_until(
        application,
        lambda: not client._candidate_buffers,
    )
    assert client._server.isListening()

    client.stop()
    connector.abort()


def test_map_host_aborts_on_unreviewed_authenticated_child_input(monkeypatch) -> None:
    from PyQt6.QtCore import QCoreApplication
    from PyQt6.QtNetwork import QTcpSocket

    from app.gui.map_host import launcher

    application = QCoreApplication.instance() or QCoreApplication([])
    terminated: list[int] = []
    monkeypatch.setattr(
        launcher,
        "_spawn_unelevated",
        lambda *_args: _owned_map_child(
            launcher,
            wait_callback=lambda _timeout_ms: False,
            terminate_callback=lambda: terminated.append(4242),
        ),
    )
    monkeypatch.setattr(launcher, "_window_process_id", lambda _hwnd: 4242)
    client = launcher.MapHostClient(peer_pid_lookup=lambda *_endpoint: 4242)
    disconnected: list[bool] = []
    client.disconnected.connect(lambda: disconnected.append(True))
    assert client.start()
    nonce = client._session_nonce
    assert nonce is not None

    connector = QTcpSocket()
    connector.connectToHost("127.0.0.1", client._server.serverPort())
    assert connector.waitForConnected(1000)
    _send_map_host_hello(connector, nonce, 4242, 0x1234)
    assert _pump_qt_until(application, lambda: client.hwnd == 0x1234)

    unexpected = b'{"type":"unexpected"}\n'
    assert connector.write(unexpected) == len(unexpected)
    connector.flush()
    assert _pump_qt_until(application, lambda: client._sock is None)
    assert terminated == [4242]
    assert disconnected == [True]

    client.stop()
    connector.abort()
    assert terminated == [4242]


def test_map_host_accepts_bounded_operational_status_frames(monkeypatch) -> None:
    from PyQt6.QtCore import QCoreApplication
    from PyQt6.QtNetwork import QTcpSocket

    from app.gui.map_host import launcher

    application = QCoreApplication.instance() or QCoreApplication(["map-host-test"])
    monkeypatch.setattr(
        launcher,
        "_spawn_unelevated",
        lambda *_args: _owned_map_child(launcher),
    )
    monkeypatch.setattr(launcher, "_window_process_id", lambda _hwnd: 4242)
    client = launcher.MapHostClient(peer_pid_lookup=lambda *_endpoint: 4242)
    started: list[bool] = []
    finished: list[bool] = []
    terminated: list[tuple[str, int]] = []
    client.loadStarted.connect(lambda: started.append(True))
    client.loadFinished.connect(finished.append)
    client.renderProcessTerminated.connect(
        lambda status, code: terminated.append((status, code))
    )
    assert client.start()
    nonce = client._session_nonce
    assert nonce is not None

    connector = QTcpSocket()
    connector.connectToHost("127.0.0.1", client._server.serverPort())
    assert connector.waitForConnected(1000)
    _send_map_host_hello(connector, nonce, 4242, 0x1234)
    assert _pump_qt_until(application, lambda: client.hwnd == 0x1234)

    frames = (
        b'{"type":"load-started"}\n'
        b'{"type":"load-finished","ok":true}\n'
        b'{"type":"renderer-terminated","status":"Crashed",'
        b'"exit_code":-1}\n'
    )
    assert connector.write(frames) == len(frames)
    connector.flush()
    assert _pump_qt_until(application, lambda: bool(terminated))

    assert started == [True]
    assert finished == [True]
    assert terminated == [("Crashed", -1)]
    assert client.webengine_ready is False

    client.stop()
    connector.abort()


def test_map_host_authenticated_hung_child_is_terminated_after_quit(
    monkeypatch,
) -> None:
    from PyQt6.QtCore import QCoreApplication
    from PyQt6.QtNetwork import QTcpSocket

    from app.gui.map_host import launcher

    application = QCoreApplication.instance() or QCoreApplication([])
    waited: list[int] = []
    terminated: list[int] = []

    def _wait(timeout_ms: int) -> bool:
        waited.append(timeout_ms)
        return False

    monkeypatch.setattr(
        launcher,
        "_spawn_unelevated",
        lambda *_args: _owned_map_child(
            launcher,
            wait_callback=_wait,
            terminate_callback=lambda: terminated.append(4242),
        ),
    )
    monkeypatch.setattr(launcher, "_window_process_id", lambda _hwnd: 4242)
    client = launcher.MapHostClient(peer_pid_lookup=lambda *_endpoint: 4242)
    assert client.start()
    nonce = client._session_nonce
    assert nonce is not None

    connector = QTcpSocket()
    connector.connectToHost("127.0.0.1", client._server.serverPort())
    assert connector.waitForConnected(1000)
    _send_map_host_hello(connector, nonce, 4242, 0x1234)
    assert _pump_qt_until(application, lambda: client.hwnd == 0x1234)

    client.stop()
    application.processEvents()
    assert b'"type": "quit"' in bytes(connector.readAll())
    assert waited == [launcher._CHILD_GRACEFUL_EXIT_TIMEOUT_MS]
    assert terminated == [4242]

    connector.abort()
    client.stop()
    assert terminated == [4242]
