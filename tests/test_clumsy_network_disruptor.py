"""
Tests for app.firewall.clumsy_network_disruptor — the orchestration
layer that wraps NativeWinDivertEngine (and the legacy ClumsyEngine
fallback) into a multi-target disruption manager.

We don't try to exercise the actual packet-engine startup (that requires
WinDivert/Npcap/admin), so the strategy is:

  1. Module-level constants and the EDIT_INDEX_MAP / MODULE_CHECKBOX_TEXT
     tables — these are the GUI-automation contract; any drift breaks
     the ClumsyEngine fallback silently.
  2. Path init — verify _init_paths attaches the three artefact paths
     to the manager without crashing when the files are missing.
  3. Manager state machine — start / stop / register / unregister and
     the associated dict bookkeeping, with a fake engine.
  4. get_status / get_device_status / get_all_engine_stats — wire the
     manager's dict into the expected GUI-facing shape.
  5. mark_cut_outcome — broadcast outcome label to the engines that
     accept it.
  6. clear_all_disruptions — must reconcile against the device dict
     even if individual engine stop() calls raise.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from app.firewall import clumsy_network_disruptor as cnd
from app.firewall.clumsy_network_disruptor import (
    BM_CLICK,
    BM_GETCHECK,
    BST_CHECKED,
    EDIT_INDEX_MAP,
    GWL_EXSTYLE,
    LWA_ALPHA,
    MODULE_CHECKBOX_TEXT,
    SW_HIDE,
    WS_EX_LAYERED,
    WS_EX_TOOLWINDOW,
    ClumsyEngine,
    ClumsyNetworkDisruptor,
    ENGINE_AUTO,
    ENGINE_CLUMSY,
    ENGINE_NATIVE,
)


# ── Module-level constants ───────────────────────────────────────────

class TestConstants:
    def test_module_checkbox_text_covers_known_methods(self):
        for name in ("lag", "drop", "disconnect", "bandwidth",
                     "throttle", "duplicate", "ood", "corrupt", "rst"):
            assert name in MODULE_CHECKBOX_TEXT, \
                f"method '{name}' missing from MODULE_CHECKBOX_TEXT"

    def test_module_checkbox_text_values_are_strings(self):
        for k, v in MODULE_CHECKBOX_TEXT.items():
            assert isinstance(v, str) and v, \
                f"empty/non-string checkbox label for {k!r}"

    def test_edit_index_map_no_holes(self):
        # Indices 1..11 must all be mapped (index 0 = filter, skipped)
        for i in range(1, 12):
            assert i in EDIT_INDEX_MAP, \
                f"EDIT index {i} missing — clumsy.exe edit-control " \
                f"ordering changed?"

    def test_edit_index_map_values_unique(self):
        values = list(EDIT_INDEX_MAP.values())
        assert len(values) == len(set(values)), \
            "duplicate param key in EDIT_INDEX_MAP"

    def test_edit_index_map_keys_consistent_with_modules(self):
        # Each EDIT_INDEX_MAP value should look like "<module>_<field>"
        for idx, key in EDIT_INDEX_MAP.items():
            assert isinstance(key, str) and "_" in key, \
                f"EDIT_INDEX_MAP[{idx}] = {key!r} not in <module>_<field> form"

    def test_win32_constants_match_documented_values(self):
        # These are the actual Windows API constants — they don't change,
        # and a copy-paste typo would silently break GUI automation.
        assert BM_CLICK == 0x00F5
        assert BM_GETCHECK == 0x00F0
        assert BST_CHECKED == 0x0001
        assert GWL_EXSTYLE == -20
        assert WS_EX_TOOLWINDOW == 0x80
        assert WS_EX_LAYERED == 0x00080000
        assert LWA_ALPHA == 0x02
        assert SW_HIDE == 0


class TestClumsyLayerSelection:
    @pytest.mark.parametrize(
        "want_local, expected_index, expected_text",
        [
            (True, 0, "(Local)_This_Device"),
            (False, 1, "(Remote)_Shared_Devices"),
        ],
    )
    def test_selects_and_verifies_requested_layer(
        self,
        monkeypatch,
        want_local,
        expected_index,
        expected_text,
    ):
        engine = ClumsyEngine(
            "clumsy.exe", ".", "true", ["lag"],
            {"_network_local": want_local},
        )
        engine._hwnd = 100
        selected = []
        monkeypatch.setattr(
            cnd, "_find_children_by_class", lambda _parent, _name: [200])
        monkeypatch.setattr(
            cnd,
            "_combobox_items",
            lambda _combo: [
                "(Local)_This_Device",
                "(Remote)_Shared_Devices",
            ],
        )
        monkeypatch.setattr(
            cnd,
            "_select_combobox_item",
            lambda combo, index: selected.append((combo, index)) or True,
        )
        monkeypatch.setattr(cnd, "_get_window_text", lambda _hwnd: expected_text)

        assert engine._select_network_layer() is True
        assert selected == [(200, expected_index)]

    def test_missing_network_combo_fails_closed(self, monkeypatch):
        engine = ClumsyEngine(
            "clumsy.exe", ".", "true", ["lag"],
            {"_network_local": True},
        )
        engine._hwnd = 100
        monkeypatch.setattr(
            cnd, "_find_children_by_class", lambda _parent, _name: [200])
        monkeypatch.setattr(
            cnd, "_combobox_items", lambda _combo: ["Preset 1", "Preset 2"])
        assert engine._select_network_layer() is False

    def test_gui_start_aborts_before_modules_when_layer_is_unverified(
        self, monkeypatch,
    ):
        engine = ClumsyEngine(
            "clumsy.exe", ".", "true", ["lag"],
            {"_network_local": True},
        )
        engine._proc = MagicMock(pid=123)
        engine._proc.poll.return_value = None
        monkeypatch.setattr(cnd, "_find_window_by_pid", lambda *_a, **_k: 100)
        monkeypatch.setattr(cnd, "_get_window_text", lambda _hwnd: "clumsy")
        engine._select_network_layer = MagicMock(return_value=False)
        engine._enable_modules = MagicMock(return_value=True)
        engine._cleanup = MagicMock()

        assert engine._start_gui_automation() is False
        engine._enable_modules.assert_not_called()
        engine._cleanup.assert_called_once()

    def test_combobox_selection_emits_iup_change_notification(self):
        class _FakeUser32:
            def __init__(self):
                self.selected = -1
                self.commands = []

            def SendMessageW(self, hwnd, message, wparam, lparam):
                if message == cnd.CB_SETCURSEL:
                    self.selected = int(wparam)
                    return self.selected
                if message == cnd.CB_GETCURSEL:
                    return self.selected
                if message == cnd.WM_COMMAND:
                    self.commands.append((hwnd, wparam, lparam))
                    return 0
                raise AssertionError(f"unexpected message {message:#x}")

            @staticmethod
            def GetParent(_hwnd):
                return 300

            @staticmethod
            def GetDlgCtrlID(_hwnd):
                return 7

        user32 = _FakeUser32()
        assert cnd._select_combobox_item(200, 1, user32=user32) is True
        assert user32.commands == [
            (300, (cnd.CBN_SELCHANGE << 16) | 7, 200)
        ]


class TestEnginePreference:
    @staticmethod
    def _manager_with_clumsy(tmp_path):
        exe = tmp_path / "clumsy.exe"
        exe.write_bytes(b"stub")
        manager = ClumsyNetworkDisruptor()
        manager.clumsy_exe = str(exe)
        return manager

    def test_auto_prefers_exact_clumsy_path(self, monkeypatch, tmp_path):
        manager = self._manager_with_clumsy(tmp_path)
        native = MagicMock()
        native.start.return_value = True
        native_ctor = MagicMock(return_value=native)
        clumsy = MagicMock()
        clumsy.start.return_value = True
        clumsy_ctor = MagicMock(return_value=clumsy)
        monkeypatch.setattr(cnd, "NATIVE_ENGINE_AVAILABLE", True)
        monkeypatch.setattr(cnd, "NativeWinDivertEngine", native_ctor)
        monkeypatch.setattr(cnd, "ClumsyEngine", clumsy_ctor)

        engine, actual, requested = manager._start_selected_engine(
            filter_str="true", methods=["lag"],
            params={"_engine_preference": ENGINE_AUTO},
        )
        assert engine is clumsy
        assert (actual, requested) == (ENGINE_CLUMSY, ENGINE_AUTO)
        clumsy_ctor.assert_called_once()
        native_ctor.assert_not_called()

    def test_auto_falls_back_to_native_equivalent(self, monkeypatch, tmp_path):
        manager = self._manager_with_clumsy(tmp_path)
        native = MagicMock()
        native.start.return_value = True
        clumsy = MagicMock()
        clumsy.start.return_value = False
        monkeypatch.setattr(cnd, "NATIVE_ENGINE_AVAILABLE", True)
        monkeypatch.setattr(
            cnd, "NativeWinDivertEngine", MagicMock(return_value=native))
        monkeypatch.setattr(
            cnd, "ClumsyEngine", MagicMock(return_value=clumsy))

        engine, actual, requested = manager._start_selected_engine(
            filter_str="true", methods=["lag"],
            params={"_engine_preference": ENGINE_AUTO},
        )
        assert engine is native
        assert (actual, requested) == (ENGINE_NATIVE, ENGINE_AUTO)
        clumsy.stop.assert_called_once()

    def test_explicit_clumsy_never_constructs_native(
        self, monkeypatch, tmp_path,
    ):
        manager = self._manager_with_clumsy(tmp_path)
        native_ctor = MagicMock()
        clumsy = MagicMock()
        clumsy.start.return_value = True
        monkeypatch.setattr(cnd, "NATIVE_ENGINE_AVAILABLE", True)
        monkeypatch.setattr(cnd, "NativeWinDivertEngine", native_ctor)
        monkeypatch.setattr(
            cnd, "ClumsyEngine", MagicMock(return_value=clumsy))

        engine, actual, requested = manager._start_selected_engine(
            filter_str="true", methods=["lag", "duplicate"],
            params={
                "_engine_preference": ENGINE_CLUMSY,
                "lag_passthrough": False,
                "lag_preserve_connection": False,
            },
        )
        assert engine is clumsy
        assert (actual, requested) == (ENGINE_CLUMSY, ENGINE_CLUMSY)
        native_ctor.assert_not_called()

    def test_explicit_native_does_not_fallback(
        self, monkeypatch, tmp_path,
    ):
        manager = self._manager_with_clumsy(tmp_path)
        native = MagicMock()
        native.start.return_value = False
        clumsy_ctor = MagicMock()
        monkeypatch.setattr(cnd, "NATIVE_ENGINE_AVAILABLE", True)
        monkeypatch.setattr(
            cnd, "NativeWinDivertEngine", MagicMock(return_value=native))
        monkeypatch.setattr(cnd, "ClumsyEngine", clumsy_ctor)

        engine, actual, requested = manager._start_selected_engine(
            filter_str="true", methods=["lag"],
            params={"_engine_preference": ENGINE_NATIVE},
        )
        assert engine is None
        assert actual == ""
        assert requested == ENGINE_NATIVE
        clumsy_ctor.assert_not_called()

    def test_clumsy_stats_are_explicitly_unverified(self):
        engine = ClumsyEngine(
            "clumsy.exe", ".", "true", ["lag", "duplicate"],
            {"_target_ip": "192.0.2.10"},
        )
        stats = engine.get_stats()
        assert stats["engine"] == "clumsy_compatibility"
        assert stats["telemetry_available"] is False
        assert stats["effective_methods"] == []
        assert stats["methods"] == ["lag", "duplicate"]


# ── ClumsyNetworkDisruptor construction ──────────────────────────────

class TestManagerConstruction:
    def test_starts_idle(self):
        mgr = ClumsyNetworkDisruptor()
        assert mgr.is_running is False
        assert mgr.disrupted_devices == {}
        assert mgr._initialized is False

    def test_init_paths_attaches_three_artefacts(self):
        mgr = ClumsyNetworkDisruptor()
        # Paths point inside app/firewall regardless of whether the
        # binary actually exists on this machine.
        assert mgr.clumsy_exe and "clumsy.exe" in mgr.clumsy_exe
        assert mgr.windivert_dll and "WinDivert.dll" in mgr.windivert_dll
        assert mgr.windivert_sys and "WinDivert64.sys" in mgr.windivert_sys

    def test_get_clumsy_dir_is_absolute(self):
        mgr = ClumsyNetworkDisruptor()
        # _get_clumsy_dir returns dirname of clumsy_exe → absolute path
        assert os.path.isabs(mgr._get_clumsy_dir())


# ── initialize() ─────────────────────────────────────────────────────

class TestInitialize:
    def test_initialize_requires_admin(self, monkeypatch):
        mgr = ClumsyNetworkDisruptor()
        monkeypatch.setattr(cnd, "is_admin", lambda: False)
        assert mgr.initialize() is False
        assert mgr._initialized is False

    def test_initialize_requires_windivert_dll(self, monkeypatch, tmp_path):
        mgr = ClumsyNetworkDisruptor()
        monkeypatch.setattr(cnd, "is_admin", lambda: True)
        mgr.windivert_dll = str(tmp_path / "does_not_exist.dll")
        assert mgr.initialize() is False

    def test_initialize_succeeds_with_native_available(self, monkeypatch,
                                                        tmp_path):
        mgr = ClumsyNetworkDisruptor()
        monkeypatch.setattr(cnd, "is_admin", lambda: True)
        # Create a fake WinDivert.dll file so the existence check passes
        fake_dll = tmp_path / "WinDivert.dll"
        fake_dll.write_bytes(b"\x00")
        mgr.windivert_dll = str(fake_dll)
        monkeypatch.setattr(cnd, "NATIVE_ENGINE_AVAILABLE", True)
        assert mgr.initialize() is True
        assert mgr._initialized is True

    def test_initialize_is_idempotent(self, monkeypatch, tmp_path):
        mgr = ClumsyNetworkDisruptor()
        mgr._initialized = True
        # No mocking needed — short-circuits on the first line
        assert mgr.initialize() is True

    def test_native_unavailable_requires_clumsy_exe(self, monkeypatch,
                                                     tmp_path):
        mgr = ClumsyNetworkDisruptor()
        monkeypatch.setattr(cnd, "is_admin", lambda: True)
        fake_dll = tmp_path / "WinDivert.dll"
        fake_dll.write_bytes(b"\x00")
        mgr.windivert_dll = str(fake_dll)
        mgr.clumsy_exe = str(tmp_path / "missing_clumsy.exe")
        monkeypatch.setattr(cnd, "NATIVE_ENGINE_AVAILABLE", False)
        assert mgr.initialize() is False


# ── Manager lifecycle ────────────────────────────────────────────────

class TestManagerLifecycle:
    def test_start_stop_toggles_is_running(self):
        mgr = ClumsyNetworkDisruptor()
        mgr.start_clumsy()
        assert mgr.is_running is True
        mgr.stop_clumsy()
        assert mgr.is_running is False

    def test_start_alias(self):
        mgr = ClumsyNetworkDisruptor()
        mgr.start()
        assert mgr.is_running is True
        mgr.stop()
        assert mgr.is_running is False

    def test_stop_clears_disrupted_devices(self):
        mgr = ClumsyNetworkDisruptor()
        mgr.is_running = True
        fake_engine = MagicMock()
        fake_engine.alive = True
        mgr.disrupted_devices["1.2.3.4"] = {
            "engine": fake_engine,
            "methods": ["drop"],
            "params": {},
            "start_time": time.time(),
        }
        mgr.stop_clumsy()
        assert mgr.disrupted_devices == {}
        fake_engine.stop.assert_called_once()


# ── Status reporting ─────────────────────────────────────────────────

class _FakeEngine:
    """Stand-in for NativeWinDivertEngine used by status / stats tests."""

    def __init__(self, alive: bool = True,
                 stats: Optional[Dict[str, int]] = None,
                 pid: int = 4242) -> None:
        self.alive = alive
        self._stats = stats or {
            "packets_processed": 0,
            "packets_dropped": 0,
            "packets_inbound": 0,
            "packets_outbound": 0,
            "packets_passed": 0,
            "alive": alive,
        }
        self.stop_called = False
        self.mark_calls: List[bool] = []

        class _Proc:
            pass

        proc = _Proc()
        proc.pid = pid
        self._proc = proc

    def get_stats(self) -> Dict:
        return dict(self._stats)

    def stop(self) -> None:
        self.stop_called = True
        self.alive = False

    def mark_last_cut_outcome(self, persisted: bool) -> None:
        self.mark_calls.append(bool(persisted))


class TestStatusReporting:
    def test_get_device_status_unknown_ip(self):
        mgr = ClumsyNetworkDisruptor()
        assert mgr.get_device_status_clumsy("1.2.3.4") == {"disrupted": False}

    def test_get_device_status_known_ip(self):
        mgr = ClumsyNetworkDisruptor()
        eng = _FakeEngine(alive=True, pid=999)
        mgr.disrupted_devices["1.2.3.4"] = {
            "engine": eng,
            "methods": ["drop"],
            "params": {"drop_chance": 50},
            "start_time": 1234567890.0,
        }
        status = mgr.get_device_status_clumsy("1.2.3.4")
        assert status["disrupted"] is True
        assert status["methods"] == ["drop"]
        assert status["params"] == {"drop_chance": 50}
        assert status["start_time"] == 1234567890.0
        assert status["process_running"] is True
        assert status["pid"] == 999

    def test_get_clumsy_status_shape(self, monkeypatch):
        mgr = ClumsyNetworkDisruptor()
        monkeypatch.setattr(cnd, "is_admin", lambda: True)
        eng = _FakeEngine()
        mgr.disrupted_devices["1.2.3.4"] = {"engine": eng}
        status = mgr.get_clumsy_status()
        assert status["is_running"] is False
        assert status["disrupted_devices_count"] == 1
        assert status["disrupted_devices"] == ["1.2.3.4"]
        assert status["is_admin"] is True

    def test_get_status_alias(self):
        mgr = ClumsyNetworkDisruptor()
        assert mgr.get_status() == mgr.get_clumsy_status()


# ── get_disrupted_devices reaper ─────────────────────────────────────

class TestGetDisruptedDevicesReaper:
    def test_alive_devices_returned(self):
        mgr = ClumsyNetworkDisruptor()
        eng = _FakeEngine(alive=True)
        mgr.disrupted_devices["1.1.1.1"] = {"engine": eng}
        assert mgr.get_disrupted_devices_clumsy() == ["1.1.1.1"]

    def test_dead_engines_reaped(self):
        mgr = ClumsyNetworkDisruptor()
        alive = _FakeEngine(alive=True)
        dead = _FakeEngine(alive=False)
        mgr.disrupted_devices["1.1.1.1"] = {"engine": alive}
        mgr.disrupted_devices["2.2.2.2"] = {"engine": dead}
        # Dead engine should be popped and its stop() called
        result = mgr.get_disrupted_devices_clumsy()
        assert "2.2.2.2" not in result
        assert "1.1.1.1" in result
        assert dead.stop_called is True

    def test_alias_get_disrupted_devices(self):
        mgr = ClumsyNetworkDisruptor()
        assert mgr.get_disrupted_devices() == []


# ── clear_all_disruptions ────────────────────────────────────────────

class TestClearAll:
    def test_clears_every_device(self):
        mgr = ClumsyNetworkDisruptor()
        engines = [_FakeEngine() for _ in range(3)]
        for i, e in enumerate(engines):
            mgr.disrupted_devices[f"10.0.0.{i}"] = {"engine": e}

        # Patch reconnect_device_clumsy to a known no-op so we don't
        # need to mock the entire engine teardown path (ArpSpoofer etc.)
        cleared: List[str] = []

        def _stub_reconnect(ip):
            cleared.append(ip)
            mgr.disrupted_devices.pop(ip)
            return True

        mgr.reconnect_device_clumsy = _stub_reconnect  # type: ignore[assignment]
        assert mgr.clear_all_disruptions_clumsy() is True
        assert sorted(cleared) == ["10.0.0.0", "10.0.0.1", "10.0.0.2"]

    def test_returns_false_when_any_reconnect_fails(self):
        mgr = ClumsyNetworkDisruptor()
        for ip in ("10.0.0.1", "10.0.0.2"):
            mgr.disrupted_devices[ip] = {"engine": _FakeEngine()}

        def _stub_reconnect(ip):
            mgr.disrupted_devices.pop(ip)
            return ip != "10.0.0.2"

        mgr.reconnect_device_clumsy = _stub_reconnect  # type: ignore[assignment]
        assert mgr.clear_all_disruptions_clumsy() is False
        assert mgr.disrupted_devices == {}

    def test_returns_false_when_registry_entry_remains(self):
        mgr = ClumsyNetworkDisruptor()
        mgr.disrupted_devices["10.0.0.1"] = {"engine": _FakeEngine()}
        mgr.reconnect_device_clumsy = lambda ip: True  # type: ignore[assignment]

        assert mgr.clear_all_disruptions_clumsy() is False
        assert list(mgr.disrupted_devices) == ["10.0.0.1"]

    def test_continues_after_unexpected_reconnect_error(self):
        mgr = ClumsyNetworkDisruptor()
        for ip in ("10.0.0.1", "10.0.0.2"):
            mgr.disrupted_devices[ip] = {"engine": _FakeEngine()}
        attempted: List[str] = []

        def _stub_reconnect(ip):
            attempted.append(ip)
            mgr.disrupted_devices.pop(ip)
            if ip == "10.0.0.1":
                raise RuntimeError("stop failed")
            return True

        mgr.reconnect_device_clumsy = _stub_reconnect  # type: ignore[assignment]
        assert mgr.clear_all_disruptions_clumsy() is False
        assert attempted == ["10.0.0.1", "10.0.0.2"]
        assert mgr.disrupted_devices == {}

    def test_stop_all_devices_alias(self):
        mgr = ClumsyNetworkDisruptor()
        mgr.reconnect_device_clumsy = lambda ip: True  # type: ignore[assignment]
        assert mgr.stop_all_devices() is True


# ── reconnect_device_clumsy ──────────────────────────────────────────

class TestReconnectDevice:
    def test_unknown_ip_returns_true(self):
        mgr = ClumsyNetworkDisruptor()
        assert mgr.reconnect_device_clumsy("9.9.9.9") is True

    def test_stops_engine(self):
        mgr = ClumsyNetworkDisruptor()
        eng = _FakeEngine()
        mgr.disrupted_devices["1.2.3.4"] = {"engine": eng}
        assert mgr.reconnect_device_clumsy("1.2.3.4") is True
        assert eng.stop_called is True
        assert "1.2.3.4" not in mgr.disrupted_devices

    def test_stops_arp_spoofer_if_present(self):
        mgr = ClumsyNetworkDisruptor()
        eng = _FakeEngine()
        spoofer = MagicMock()
        mgr.disrupted_devices["1.2.3.4"] = {
            "engine": eng, "arp_spoofer": spoofer,
        }
        assert mgr.reconnect_device_clumsy("1.2.3.4") is True
        spoofer.stop.assert_called_once()

    def test_cancels_wifi_watchdog(self):
        mgr = ClumsyNetworkDisruptor()
        eng = _FakeEngine()
        watchdog = MagicMock()
        mgr.disrupted_devices["1.2.3.4"] = {
            "engine": eng, "wifi_watchdog": watchdog,
        }
        assert mgr.reconnect_device_clumsy("1.2.3.4") is True
        watchdog.cancel.assert_called_once()

    def test_stop_device_alias(self):
        mgr = ClumsyNetworkDisruptor()
        eng = _FakeEngine()
        mgr.disrupted_devices["1.2.3.4"] = {"engine": eng}
        assert mgr.stop_device("1.2.3.4") is True

    def test_engine_stop_exception_still_pops_device(self):
        mgr = ClumsyNetworkDisruptor()
        eng = MagicMock()
        eng.stop.side_effect = RuntimeError("boom")
        mgr.disrupted_devices["1.2.3.4"] = {"engine": eng}
        # Function catches and pops; returns False to signal partial failure
        result = mgr.reconnect_device_clumsy("1.2.3.4")
        assert result is False
        assert "1.2.3.4" not in mgr.disrupted_devices


# ── get_all_engine_stats ─────────────────────────────────────────────

class TestGetAllEngineStats:
    def test_empty_returns_zeros(self):
        mgr = ClumsyNetworkDisruptor()
        stats = mgr.get_all_engine_stats()
        assert stats["active_engines"] == 0
        assert stats["packets_processed"] == 0
        assert stats["per_device"] == {}

    def test_aggregates_counters(self):
        mgr = ClumsyNetworkDisruptor()
        e1 = _FakeEngine(stats={
            "packets_processed": 100, "packets_dropped": 10,
            "packets_inbound": 60, "packets_outbound": 40,
            "packets_passed": 90, "alive": True,
        })
        e2 = _FakeEngine(stats={
            "packets_processed": 50, "packets_dropped": 5,
            "packets_inbound": 30, "packets_outbound": 20,
            "packets_passed": 45, "alive": True,
        })
        mgr.disrupted_devices["1.1.1.1"] = {"engine": e1}
        mgr.disrupted_devices["2.2.2.2"] = {"engine": e2}
        stats = mgr.get_all_engine_stats()
        assert stats["packets_processed"] == 150
        assert stats["packets_dropped"] == 15
        assert stats["packets_inbound"] == 90
        assert stats["active_engines"] == 2
        assert set(stats["per_device"].keys()) == {"1.1.1.1", "2.2.2.2"}

    def test_dead_engine_not_counted_active(self):
        mgr = ClumsyNetworkDisruptor()
        dead = _FakeEngine(alive=False, stats={
            "packets_processed": 100, "packets_dropped": 0,
            "packets_inbound": 0, "packets_outbound": 0,
            "packets_passed": 0, "alive": False,
        })
        mgr.disrupted_devices["1.1.1.1"] = {"engine": dead}
        stats = mgr.get_all_engine_stats()
        assert stats["active_engines"] == 0
        # Counters still accumulate even for dead engines (they may
        # have processed packets before exiting)
        assert stats["packets_processed"] == 100

    def test_attaches_arp_spoofer_state(self):
        mgr = ClumsyNetworkDisruptor()
        eng = _FakeEngine()
        spoofer = MagicMock()
        spoofer._running = True
        # packets_sent is a property in the real class — emulate via attr.
        spoofer.packets_sent = 42
        mgr.disrupted_devices["1.1.1.1"] = {
            "engine": eng, "arp_spoofer": spoofer,
        }
        stats = mgr.get_all_engine_stats()
        per = stats["per_device"]["1.1.1.1"]
        assert per["arp_spoof_active"] is True
        assert per["arp_packets_sent"] == 42

    def test_get_engine_stats_alias(self):
        mgr = ClumsyNetworkDisruptor()
        assert mgr.get_engine_stats() == mgr.get_all_engine_stats()


# ── mark_cut_outcome ─────────────────────────────────────────────────

class TestMarkCutOutcome:
    def test_no_engines_returns_zero(self):
        mgr = ClumsyNetworkDisruptor()
        assert mgr.mark_cut_outcome(True) == 0

    def test_broadcasts_to_all_engines(self):
        mgr = ClumsyNetworkDisruptor()
        e1 = _FakeEngine()
        e2 = _FakeEngine()
        mgr.disrupted_devices["1.1.1.1"] = {"engine": e1}
        mgr.disrupted_devices["2.2.2.2"] = {"engine": e2}
        assert mgr.mark_cut_outcome(True) == 2
        assert e1.mark_calls == [True]
        assert e2.mark_calls == [True]

    def test_targeted_to_specific_ip(self):
        mgr = ClumsyNetworkDisruptor()
        e1 = _FakeEngine()
        e2 = _FakeEngine()
        mgr.disrupted_devices["1.1.1.1"] = {"engine": e1}
        mgr.disrupted_devices["2.2.2.2"] = {"engine": e2}
        assert mgr.mark_cut_outcome(False, ip="1.1.1.1") == 1
        assert e1.mark_calls == [False]
        assert e2.mark_calls == []

    def test_unknown_ip_falls_back_to_broadcast(self):
        """When the supplied IP isn't in the device dict, the manager
        falls through to the broadcast path (current behavior — kept as
        a regression pin so a future refactor surfaces the choice).
        """
        mgr = ClumsyNetworkDisruptor()
        eng = _FakeEngine()
        mgr.disrupted_devices["1.1.1.1"] = {"engine": eng}
        assert mgr.mark_cut_outcome(True, ip="9.9.9.9") == 1
        assert eng.mark_calls == [True]

    def test_engine_without_mark_method_skipped(self):
        mgr = ClumsyNetworkDisruptor()
        eng = MagicMock(spec=[])  # no methods at all
        mgr.disrupted_devices["1.1.1.1"] = {"engine": eng}
        # No mark_last_cut_outcome → count stays 0
        assert mgr.mark_cut_outcome(True) == 0

    def test_engine_exception_doesnt_abort_loop(self):
        mgr = ClumsyNetworkDisruptor()
        bad = MagicMock()
        bad.mark_last_cut_outcome.side_effect = RuntimeError("x")
        good = _FakeEngine()
        mgr.disrupted_devices["1.1.1.1"] = {"engine": bad}
        mgr.disrupted_devices["2.2.2.2"] = {"engine": good}
        count = mgr.mark_cut_outcome(True)
        # Bad raised → count=1 (only good succeeded)
        assert count == 1
        assert good.mark_calls == [True]


# ── disrupt_device delegates to disconnect_device_clumsy ────────────

class TestDisruptDeviceAlias:
    def test_forwards_to_disconnect(self, monkeypatch):
        mgr = ClumsyNetworkDisruptor()
        seen: Dict[str, Any] = {}

        def _stub(target_ip, methods=None, params=None, **kwargs):
            seen["target_ip"] = target_ip
            seen["methods"] = methods
            seen["params"] = params
            seen["kwargs"] = kwargs
            return True

        mgr.disconnect_device_clumsy = _stub  # type: ignore[assignment]
        ok = mgr.disrupt_device("1.2.3.4", methods=["drop"],
                                 params={"drop_chance": 50},
                                 preset="pc_local")
        assert ok is True
        assert seen["target_ip"] == "1.2.3.4"
        assert seen["methods"] == ["drop"]
        assert seen["params"] == {"drop_chance": 50}
        assert seen["kwargs"]["preset"] == "pc_local"


# ── Thread safety: device dict iteration ─────────────────────────────

class TestDeviceLockConsistency:
    def test_device_lock_present(self):
        mgr = ClumsyNetworkDisruptor()
        # The lock should be a threading.Lock or RLock — both have
        # acquire/release.
        assert hasattr(mgr._device_lock, "acquire")
        assert hasattr(mgr._device_lock, "release")

    def test_concurrent_read_returns_consistent_snapshot(self):
        """Hammer the device list while a writer registers and unregisters.
        If the manager exposed the underlying dict directly, this would
        race; the lock + snapshot pattern should keep readers stable.
        """
        mgr = ClumsyNetworkDisruptor()
        stop = threading.Event()

        def _writer():
            i = 0
            while not stop.is_set():
                ip = f"10.0.0.{i % 250}"
                with mgr._device_lock:
                    mgr.disrupted_devices[ip] = {
                        "engine": _FakeEngine(alive=True),
                    }
                with mgr._device_lock:
                    mgr.disrupted_devices.pop(ip, None)
                i += 1

        def _reader():
            for _ in range(200):
                # get_disrupted_devices_clumsy snapshots under the lock
                _ = mgr.get_disrupted_devices_clumsy()

        w = threading.Thread(target=_writer)
        r = threading.Thread(target=_reader)
        w.start()
        r.start()
        r.join()
        stop.set()
        w.join()
        # No assertion needed — the test passes if no exception escapes.
        assert True
