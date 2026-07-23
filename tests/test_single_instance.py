"""Focused tests for the pre-Qt GUI single-instance guard."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import uuid

import pytest

import dupez_single_instance as single_instance

_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _reset_guard(monkeypatch):
    monkeypatch.setattr(single_instance, "_instance_handle", None)
    monkeypatch.setattr(single_instance, "_instance_pid", None)
    monkeypatch.setattr(single_instance, "_release_registered", False)


@pytest.mark.parametrize(
    "argv",
    [
        ["dupez.exe", "--role", "helper", "--parent-pid", "123"],
        ["dupez.exe", "--reset-audit"],
        ["dupez.exe", "--verify-self"],
    ],
)
def test_helper_and_maintenance_launches_bypass_mutex(
    monkeypatch,
    argv,
) -> None:
    def unexpected_acquire():
        raise AssertionError("non-GUI launch tried to acquire GUI mutex")

    monkeypatch.setattr(
        single_instance,
        "_acquire_windows_mutex",
        unexpected_acquire,
    )

    assert single_instance.guard_gui_startup(argv, notify=False) is True


def test_guard_is_idempotent_inside_owner_process(monkeypatch) -> None:
    calls = []

    def acquire():
        calls.append(True)
        return single_instance._AcquireResult(
            single_instance._AcquireState.ACQUIRED,
            handle=321,
        )

    monkeypatch.setattr(single_instance, "_acquire_windows_mutex", acquire)
    monkeypatch.setattr(single_instance, "_close_windows_handle", lambda _h: None)

    assert single_instance.guard_gui_startup(["dupez.exe"], notify=False)
    assert single_instance.guard_gui_startup(["dupez.exe"], notify=False)
    assert calls == [True]


def test_second_launch_is_blocked_with_actionable_message(monkeypatch) -> None:
    messages = []
    monkeypatch.setattr(
        single_instance,
        "_acquire_windows_mutex",
        lambda: single_instance._AcquireResult(
            single_instance._AcquireState.ALREADY_RUNNING,
            error=183,
        ),
    )
    monkeypatch.setattr(
        single_instance,
        "_notify_startup_blocked",
        messages.append,
    )

    assert single_instance.guard_gui_startup(["dupez.exe"]) is False
    assert len(messages) == 1
    assert "already running" in messages[0].lower()
    assert "Task Manager" in messages[0]
    assert "launch DupeZ again" in messages[0]


def test_cross_integrity_descriptor_is_user_scoped() -> None:
    sddl = single_instance._security_descriptor_sddl("S-1-5-21-1-2-3-1001")

    assert "(A;;GA;;;S-1-5-21-1-2-3-1001)" in sddl
    assert "(A;;GA;;;SY)" in sddl
    assert ";;;WD" not in sddl
    assert ";;;AU" not in sddl
    assert "S:(ML;;NW;;;LW)" in sddl


def test_mutex_name_is_stable_per_user_without_exposing_sid() -> None:
    sid = "S-1-5-21-1-2-3-1001"

    first = single_instance._instance_name(sid)
    second = single_instance._instance_name(sid)

    assert first == second
    assert first.startswith(r"Local\DupeZ.GUI.")
    assert sid not in first


@pytest.mark.skipif(sys.platform != "win32", reason="Windows named mutex")
def test_named_mutex_blocks_another_process_and_is_os_released() -> None:
    name = rf"Local\DupeZ.GUI.Test.{uuid.uuid4().hex}"
    first = single_instance._acquire_windows_mutex(name)
    assert first.state is single_instance._AcquireState.ACQUIRED
    assert first.handle

    child_code = (
        "import dupez_single_instance as s;"
        f"r=s._acquire_windows_mutex({name!r});"
        "print(r.state.value, flush=True)"
    )
    try:
        child = subprocess.run(
            [sys.executable, "-c", child_code],
            cwd=_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert child.returncode == 0, child.stderr
        assert child.stdout.strip() == "already_running"
    finally:
        single_instance._close_windows_handle(first.handle)

    # os._exit bypasses Python cleanup/atexit. Windows must still close the
    # process handle so an abnormal exit cannot leave a stale startup lock.
    crash_code = (
        "import os;"
        "import dupez_single_instance as s;"
        f"r=s._acquire_windows_mutex({name!r});"
        "print(r.state.value, flush=True);"
        "os._exit(23)"
    )
    crashed = subprocess.run(
        [sys.executable, "-c", crash_code],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert crashed.returncode == 23, crashed.stderr
    assert crashed.stdout.strip() == "acquired"

    after_exit = single_instance._acquire_windows_mutex(name)
    try:
        assert after_exit.state is single_instance._AcquireState.ACQUIRED
    finally:
        if after_exit.handle:
            single_instance._close_windows_handle(after_exit.handle)


def test_launchers_guard_before_gui_bootstrap() -> None:
    launcher = (_ROOT / "dupez.py").read_text(encoding="utf-8")
    main_source = (_ROOT / "app" / "main.py").read_text(encoding="utf-8")

    acquire_pos = launcher.index("if not guard_gui_startup():")
    assert acquire_pos > launcher.index("_inproc_self_elevate_if_needed()")
    assert acquire_pos < launcher.index(
        "from app.gui.map_host.renderer_tier import apply_chromium_flags"
    )
    assert acquire_pos < launcher.index("from app.main import main")

    assert "if not guard_gui_startup():" in main_source
