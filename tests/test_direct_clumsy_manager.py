"""Regression coverage for the owned direct Clumsy integration."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.firewall import clumsy_network_disruptor as legacy
from app.firewall import direct_clumsy_manager as direct
from app.firewall.direct_clumsy_manager import (
    DirectClumsyNetworkDisruptor,
    ManagedClumsyEngine,
)


def _engine(tmp_path, methods=None, params=None):
    executable = tmp_path / "clumsy.exe"
    executable.write_bytes(b"direct-clumsy-test")
    effective_params = {"direction": "both", "lag_delay": 1500}
    effective_params.update(params or {})
    return ManagedClumsyEngine(
        str(executable),
        str(tmp_path),
        "true",
        list(methods or ["lag"]),
        effective_params,
    )


def test_direct_start_uses_visible_audited_launcher_and_never_global_taskkill(
    monkeypatch,
    tmp_path,
):
    engine = _engine(tmp_path)
    process = SimpleNamespace(pid=1234, poll=lambda: None, kill=MagicMock())
    visible_spawn = MagicMock(return_value=process)

    monkeypatch.setattr(direct, "_running_clumsy_pids", lambda: ())
    monkeypatch.setattr(direct, "spawn_managed_gui", visible_spawn)
    monkeypatch.setattr(legacy, "_safe_sp", SimpleNamespace())
    monkeypatch.setattr(
        legacy,
        "_kill_all_clumsy",
        MagicMock(side_effect=AssertionError("global taskkill must not run")),
    )
    monkeypatch.setattr(engine, "_detect_silent_support", lambda _path: False)
    monkeypatch.setattr(engine, "_start_gui_automation", lambda: True)

    assert engine.start() is True
    legacy._kill_all_clumsy.assert_not_called()
    visible_spawn.assert_called_once()
    assert visible_spawn.call_args.kwargs["intent"] == (
        "clumsy.direct_owned_visible_launch"
    )
    assert engine._proc is process
    assert engine.get_stats()["failure_stage"] == "running"


def test_external_clumsy_contention_fails_without_spawning(monkeypatch, tmp_path):
    engine = _engine(tmp_path)
    spawn = MagicMock()

    monkeypatch.setattr(direct, "_running_clumsy_pids", lambda: (41, 42))
    monkeypatch.setattr(direct, "spawn_managed_gui", spawn)
    monkeypatch.setattr(legacy, "_safe_sp", SimpleNamespace())

    assert engine.start() is False
    spawn.assert_not_called()
    stats = engine.get_stats()
    assert stats["contention_detected"] is True
    assert stats["contention_process_count"] == 2
    assert stats["failure_stage"] == "contention_check"
    assert "no process was killed" in stats["last_error"].lower()


def test_gui_failure_surfaces_stage_and_control_snapshot(monkeypatch, tmp_path):
    engine = _engine(tmp_path)
    process = SimpleNamespace(pid=321, poll=lambda: None, kill=MagicMock())
    monkeypatch.setattr(direct, "_running_clumsy_pids", lambda: ())
    monkeypatch.setattr(direct, "spawn_managed_gui", lambda *args, **kwargs: process)
    monkeypatch.setattr(legacy, "_safe_sp", SimpleNamespace())
    monkeypatch.setattr(engine, "_detect_silent_support", lambda _path: False)

    def fail_gui():
        engine._failure_diagnostics = [
            {
                "top_level": True,
                "class": "IupDialog",
                "text": "clumsy Keybind Edition",
                "control_id": 0,
                "visible": True,
                "enabled": True,
            }
        ]
        engine._proc = None
        return False

    monkeypatch.setattr(engine, "_start_gui_automation", fail_gui)

    assert engine.start() is False
    stats = engine.get_stats()
    assert stats["failure_stage"] == "gui_verification"
    assert "IupDialog" in stats["last_error"]
    assert stats["diagnostic_controls"][0]["visible"] is True


def test_stop_prefers_graceful_owned_process_exit(monkeypatch, tmp_path):
    engine = _engine(tmp_path)
    process = SimpleNamespace(pid=77, poll=MagicMock(return_value=None), kill=MagicMock())
    engine._proc = process
    engine._hwnd = 99

    monkeypatch.setattr(engine, "_request_graceful_stop", lambda: True)
    monkeypatch.setattr(engine, "_wait_for_exit", lambda _timeout: True)

    engine.stop()

    process.kill.assert_not_called()
    assert engine.get_stats()["stop_mode"] == "graceful"
    assert engine._proc is None


def test_stop_kills_only_owned_child_as_bounded_fallback(monkeypatch, tmp_path):
    engine = _engine(tmp_path)
    process = SimpleNamespace(pid=88, poll=MagicMock(return_value=None), kill=MagicMock())
    engine._proc = process
    engine._hwnd = 101

    monkeypatch.setattr(engine, "_request_graceful_stop", lambda: False)

    engine.stop()

    process.kill.assert_called_once_with()
    assert engine.get_stats()["stop_mode"] == "owned_pid_kill_fallback"
    assert engine._proc is None


def _active_clumsy_entry():
    active_engine = SimpleNamespace(alive=True)
    return {
        "engine": active_engine,
        "engine_name": legacy.ENGINE_CLUMSY,
        "methods": ["lag"],
        "params": {"direction": "both"},
    }


def test_explicit_clumsy_refuses_second_active_session(monkeypatch, tmp_path):
    manager = DirectClumsyNetworkDisruptor()
    manager.clumsy_exe = str(tmp_path / "clumsy.exe")
    (tmp_path / "clumsy.exe").write_bytes(b"stub")
    manager.disrupted_devices["192.168.1.10"] = _active_clumsy_entry()
    constructor = MagicMock()
    monkeypatch.setattr(direct, "ManagedClumsyEngine", constructor)

    engine, actual, requested = manager._start_selected_engine(
        filter_str="true",
        methods=["lag"],
        params={
            "_engine_preference": legacy.ENGINE_CLUMSY,
            "direction": "both",
            "lag_delay": 1000,
        },
    )

    assert engine is None
    assert actual == ""
    assert requested == legacy.ENGINE_CLUMSY
    constructor.assert_not_called()
    assert "one active event" in manager.get_status()["last_engine_error"]


def test_auto_uses_native_for_second_equivalent_event(monkeypatch, tmp_path):
    manager = DirectClumsyNetworkDisruptor()
    manager.clumsy_exe = str(tmp_path / "clumsy.exe")
    (tmp_path / "clumsy.exe").write_bytes(b"stub")
    manager.disrupted_devices["192.168.1.10"] = _active_clumsy_entry()

    native = MagicMock()
    native.start.return_value = True
    native_constructor = MagicMock(return_value=native)
    monkeypatch.setattr(legacy, "NATIVE_ENGINE_AVAILABLE", True)
    monkeypatch.setattr(legacy, "NativeWinDivertEngine", native_constructor)

    engine, actual, requested = manager._start_selected_engine(
        filter_str="true",
        methods=["lag"],
        params={
            "_engine_preference": legacy.ENGINE_AUTO,
            "direction": "both",
            "lag_delay": 1000,
        },
    )

    assert engine is native
    assert actual == legacy.ENGINE_NATIVE
    assert requested == legacy.ENGINE_AUTO
    native_constructor.assert_called_once()


def test_inproc_feature_flag_returns_direct_manager(monkeypatch):
    from app.firewall_helper import feature_flag

    monkeypatch.setattr(feature_flag, "is_split_mode", lambda: False)

    manager = feature_flag.get_disruption_manager()

    assert isinstance(manager, DirectClumsyNetworkDisruptor)
    assert manager.get_status()["direct_clumsy_integration"] is True


def test_helper_imports_same_direct_manager_source():
    source = open("dupez_helper.py", encoding="utf-8").read()

    assert (
        "from app.firewall.direct_clumsy_manager import disruption_manager"
        in source
    )
    assert (
        "from app.firewall.clumsy_network_disruptor import disruption_manager"
        not in source
    )
