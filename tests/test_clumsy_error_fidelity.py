"""Ensure staged startup does not replace precise adapter failures."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.firewall import clumsy_network_disruptor as legacy
from app.firewall import direct_clumsy_runtime as runtime
from app.firewall.direct_clumsy_manager import ManagedClumsyEngine


def test_subcontrol_failure_keeps_named_control_error(monkeypatch, tmp_path):
    executable = tmp_path / "clumsy.exe"
    executable.write_bytes(b"clumsy-error-fidelity")
    engine = ManagedClumsyEngine(
        str(executable),
        str(tmp_path),
        "true",
        ["throttle"],
        {"direction": "both", "throttle_frame": 10, "throttle_chance": 0},
    )
    engine._proc = SimpleNamespace(pid=77, poll=MagicMock(return_value=None))
    cleanup = MagicMock()

    monkeypatch.setattr(legacy, "_find_window_by_pid", lambda *_a, **_k: 101)
    monkeypatch.setattr(legacy, "_get_window_text", lambda _hwnd: "clumsy")
    monkeypatch.setattr(runtime, "_wait_for_control_tree", lambda _engine: True)
    monkeypatch.setattr(engine, "_select_network_layer", lambda: True)
    monkeypatch.setattr(engine, "_enable_modules", lambda: True)

    def fail_subcontrol():
        engine._last_error = (
            "Clumsy sub-control 'Drop Throttled' did not confirm state=True"
        )
        return False

    monkeypatch.setattr(engine, "_click_sub_checkboxes", fail_subcontrol)
    monkeypatch.setattr(engine, "_cleanup", cleanup)

    assert runtime._staged_start_gui_automation(engine) is False
    assert engine._last_stage == "sub_checkboxes"
    assert engine._last_error == (
        "Clumsy sub-control 'Drop Throttled' did not confirm state=True"
    )
    cleanup.assert_called_once_with()
