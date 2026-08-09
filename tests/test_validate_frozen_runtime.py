from __future__ import annotations

import ctypes

import psutil

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

        def terminate(self) -> None:
            raise psutil.AccessDenied(pid=self.pid)

        def is_running(self) -> bool:
            raise psutil.AccessDenied(pid=self.pid)

        def kill(self) -> None:
            raise AssertionError("an inaccessible elevated helper must not be killed")

    helper = ElevatedHelper()
    monkeypatch.setattr(validator, "_tree", lambda _root_pid: [helper])
    monkeypatch.setattr(validator.psutil, "Process", lambda _pid: helper)

    validator._terminate_started_family(41001, {helper.pid})


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
