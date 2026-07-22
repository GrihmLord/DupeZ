"""Tests for the staged hardware-backed Clumsy GUI runtime."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.firewall import clumsy_network_disruptor as legacy
from app.firewall import direct_clumsy_runtime as runtime
from app.firewall.direct_clumsy_manager import ManagedClumsyEngine


def _engine(tmp_path):
    executable = tmp_path / "clumsy.exe"
    executable.write_bytes(b"direct-runtime-test")
    return ManagedClumsyEngine(
        str(executable),
        str(tmp_path),
        "true",
        ["lag"],
        {"direction": "both", "lag_delay": 100},
    )


def test_control_tree_ready_requires_every_boundary():
    ready = {
        "start_button": True,
        "network_combo": True,
        "missing_modules": (),
        "edit_count": 2,
        "required_edit_count": 2,
    }

    assert runtime._control_tree_ready(ready) is True
    for key, value in (
        ("start_button", False),
        ("network_combo", False),
        ("missing_modules", ("Lag",)),
        ("edit_count", 1),
    ):
        candidate = dict(ready)
        candidate[key] = value
        assert runtime._control_tree_ready(candidate) is False


def test_staged_runtime_verifies_in_order_and_hides_window(monkeypatch, tmp_path):
    engine = _engine(tmp_path)
    process = SimpleNamespace(pid=77, poll=MagicMock(return_value=None))
    engine._proc = process
    calls = []

    monkeypatch.setattr(legacy, "_find_window_by_pid", lambda *_a, **_k: 101)
    monkeypatch.setattr(legacy, "_get_window_text", lambda _hwnd: "clumsy")
    monkeypatch.setattr(runtime, "_wait_for_control_tree", lambda _engine: True)
    monkeypatch.setattr(
        engine,
        "_select_network_layer",
        lambda: calls.append("network") or True,
    )
    monkeypatch.setattr(
        engine,
        "_enable_modules",
        lambda: calls.append("modules") or True,
    )
    monkeypatch.setattr(
        engine,
        "_click_sub_checkboxes",
        lambda: calls.append("subchecks") or True,
    )
    monkeypatch.setattr(
        engine,
        "_set_input_values",
        lambda: calls.append("inputs") or True,
    )
    monkeypatch.setattr(
        engine,
        "_click_start_button",
        lambda: calls.append("start") or True,
    )
    hide = MagicMock(return_value=True)
    monkeypatch.setattr(legacy, "_hide_window", hide)
    monkeypatch.setattr(runtime.time, "sleep", lambda _seconds: None)

    assert runtime._staged_start_gui_automation(engine) is True
    assert calls == ["network", "modules", "subchecks", "inputs", "start"]
    assert engine._startup_verified is True
    assert engine._last_stage == "running"
    assert engine._hwnd == 101
    hide.assert_called_once_with(101)


def test_control_tree_timeout_fails_closed_with_stage(monkeypatch, tmp_path):
    engine = _engine(tmp_path)
    engine._proc = SimpleNamespace(pid=88, poll=MagicMock(return_value=None))
    cleanup = MagicMock()

    monkeypatch.setattr(legacy, "_find_window_by_pid", lambda *_a, **_k: 202)
    monkeypatch.setattr(legacy, "_get_window_text", lambda _hwnd: "clumsy")

    def fail_readiness(candidate):
        candidate._last_error = "Functions control tree timeout"
        return False

    monkeypatch.setattr(runtime, "_wait_for_control_tree", fail_readiness)
    monkeypatch.setattr(engine, "_cleanup", cleanup)

    assert runtime._staged_start_gui_automation(engine) is False
    assert engine._startup_verified is False
    assert engine._last_stage == "control_tree_readiness"
    assert "control tree" in engine._last_error.lower()
    cleanup.assert_called_once_with()


def test_runtime_installer_replaces_only_managed_subclass_method(monkeypatch):
    original = ManagedClumsyEngine._start_gui_automation
    monkeypatch.delattr(
        ManagedClumsyEngine,
        "_staged_runtime_installed",
        raising=False,
    )

    runtime.install_direct_clumsy_runtime()

    assert (
        ManagedClumsyEngine._start_gui_automation
        is runtime._staged_start_gui_automation
    )
    assert (
        legacy.ClumsyEngine._start_gui_automation
        is not runtime._staged_start_gui_automation
    )
    ManagedClumsyEngine._start_gui_automation = original
