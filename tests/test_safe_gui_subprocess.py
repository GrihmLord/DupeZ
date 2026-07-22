"""Tests for the audited hidden GUI subprocess launcher."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.core import safe_gui_subprocess as gui
from app.core import safe_subprocess as safe


def test_hidden_gui_launcher_uses_sw_hide_and_keeps_security_policy(
    monkeypatch,
    tmp_path,
):
    executable = tmp_path / "gui.exe"
    executable.write_bytes(b"stub")
    process = SimpleNamespace(
        pid=44,
        returncode=None,
        poll=lambda: None,
        kill=lambda: None,
    )
    popen = MagicMock(return_value=process)
    audit = MagicMock()
    startupinfo = object()

    monkeypatch.setattr(gui.subprocess, "Popen", popen)
    monkeypatch.setattr(safe, "_audit", audit)
    monkeypatch.setattr(safe, "_windows_creation_flags", lambda: 0x08000000)
    monkeypatch.setattr(safe, "_windows_startupinfo", lambda: startupinfo)

    managed = gui.spawn_managed_gui(
        [str(executable)],
        cwd=str(tmp_path),
        intent="test.hidden_gui",
    )

    assert managed.pid == 44
    kwargs = popen.call_args.kwargs
    assert kwargs["shell"] is False
    assert kwargs["stdin"] is gui.subprocess.DEVNULL
    assert kwargs["stdout"] is gui.subprocess.DEVNULL
    assert kwargs["stderr"] is gui.subprocess.DEVNULL
    assert kwargs["close_fds"] is True
    assert kwargs["creationflags"] == 0x08000000
    assert kwargs["startupinfo"] is startupinfo
    audit.assert_called_once()
    assert audit.call_args.args[1]["window_policy"] == (
        "hidden_during_verification"
    )


def test_hidden_gui_launcher_rejects_relative_executable(tmp_path):
    try:
        gui.spawn_managed_gui(["gui.exe"], cwd=str(tmp_path))
    except safe.SafeSubprocessError as exc:
        assert "absolute path" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("relative executable was accepted")
