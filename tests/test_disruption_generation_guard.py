"""Race guards for asynchronous connection-test engine replacement."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.firewall import clumsy_network_disruptor as cnd
from app.firewall.clumsy_network_disruptor import (
    ClumsyEngine,
    ClumsyNetworkDisruptor,
    ENGINE_AUTO,
    ENGINE_NATIVE,
)
from app.network import wifi_probe


TARGET = "192.0.2.10"


class _Watchdog:
    instances: list[_Watchdog] = []

    def __init__(self, **kwargs) -> None:
        self.on_result = kwargs["on_result"]
        self.started = False
        self.cancelled = False
        self.instances.append(self)

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancelled = True


def _active_entry(engine, generation: int, **extra):
    return {
        "engine": engine,
        "generation": generation,
        "engine_name": ENGINE_NATIVE,
        "engine_preference": ENGINE_AUTO,
        "methods": ["lag"],
        "params": {"lag_delay": 25},
        "arp_spoofer": MagicMock(),
        **extra,
    }


def test_successful_registry_installs_receive_monotonic_generations(
    monkeypatch,
) -> None:
    manager = ClumsyNetworkDisruptor()
    manager._initialized = True
    first = MagicMock()
    second = MagicMock()
    first.alive = True
    second.alive = True
    starts = iter(
        [
            (first, ENGINE_NATIVE, ENGINE_AUTO),
            (second, ENGINE_NATIVE, ENGINE_AUTO),
        ]
    )
    monkeypatch.setattr(manager, "_start_selected_engine", lambda **_kw: next(starts))

    assert manager.disconnect_device_clumsy(
        TARGET,
        methods=["lag"],
        params={"_network_local": True, "_wifi_auto_fallback": False},
        preset="manual",
    )
    first_generation = manager.disrupted_devices[TARGET]["generation"]

    assert manager.disconnect_device_clumsy(
        TARGET,
        methods=["lag"],
        params={"_network_local": True, "_wifi_auto_fallback": False},
        preset="manual",
    )
    second_generation = manager.disrupted_devices[TARGET]["generation"]

    assert first_generation > 0
    assert second_generation > first_generation
    first.stop.assert_called_once()


def test_watchdog_callback_captures_generation_and_engine(monkeypatch) -> None:
    manager = ClumsyNetworkDisruptor()
    old_engine = MagicMock()
    newer_engine = MagicMock()
    spoofer = MagicMock()
    manager._disruption_generation = 1
    manager.disrupted_devices[TARGET] = _active_entry(
        old_engine,
        1,
        arp_spoofer=spoofer,
    )
    _Watchdog.instances.clear()
    monkeypatch.setattr(wifi_probe, "IsolationWatchdog", _Watchdog)
    replacement_ctor = MagicMock()
    monkeypatch.setattr(cnd, "NativeWinDivertEngine", replacement_ctor)

    manager._arm_wifi_isolation_watchdog(
        TARGET,
        old_engine,
        spoofer,
        ["lag"],
        {"lag_delay": 25},
    )
    watchdog = _Watchdog.instances[-1]
    assert watchdog.started

    manager._disruption_generation = 2
    manager.disrupted_devices[TARGET] = _active_entry(newer_engine, 2)
    watchdog.on_result(wifi_probe.IsolationResult.ISOLATION_DETECTED)

    assert manager.disrupted_devices[TARGET]["engine"] is newer_engine
    replacement_ctor.assert_not_called()
    old_engine.stop.assert_not_called()


def test_fallback_discards_replacement_if_registry_changes_during_start(
    monkeypatch,
) -> None:
    manager = ClumsyNetworkDisruptor()
    old_engine = MagicMock()
    old_spoofer = MagicMock()
    newer_engine = MagicMock()
    replacement = MagicMock()
    manager._disruption_generation = 7
    old_entry = _active_entry(
        old_engine,
        7,
        arp_spoofer=old_spoofer,
    )
    manager.disrupted_devices[TARGET] = old_entry

    def _replace_registry_while_starting() -> bool:
        with manager._device_lock:
            manager._disruption_generation += 1
            manager.disrupted_devices[TARGET] = _active_entry(
                newer_engine,
                manager._disruption_generation,
            )
        return True

    replacement.start.side_effect = _replace_registry_while_starting
    monkeypatch.setattr(cnd, "NATIVE_ENGINE_AVAILABLE", True)
    monkeypatch.setattr(
        cnd,
        "NativeWinDivertEngine",
        MagicMock(return_value=replacement),
    )

    manager._fallback_to_self_disrupt(
        TARGET,
        ["lag"],
        {"lag_delay": 25},
        expected_generation=7,
        expected_engine=old_engine,
    )

    assert manager.disrupted_devices[TARGET]["engine"] is newer_engine
    replacement.stop.assert_called_once()
    old_engine.stop.assert_called_once()
    old_spoofer.stop.assert_called_once()


def test_fallback_refuses_a_callback_after_registry_removal(monkeypatch) -> None:
    manager = ClumsyNetworkDisruptor()
    old_engine = MagicMock()
    manager._disruption_generation = 3
    manager.disrupted_devices[TARGET] = _active_entry(old_engine, 3)
    manager.disrupted_devices.pop(TARGET)
    replacement_ctor = MagicMock()
    monkeypatch.setattr(cnd, "NativeWinDivertEngine", replacement_ctor)

    manager._fallback_to_self_disrupt(
        TARGET,
        ["lag"],
        {"lag_delay": 25},
        expected_generation=3,
        expected_engine=old_engine,
    )

    replacement_ctor.assert_not_called()
    old_engine.stop.assert_not_called()


def test_successful_fallback_commits_with_a_new_generation(monkeypatch) -> None:
    manager = ClumsyNetworkDisruptor()
    old_engine = MagicMock()
    old_spoofer = MagicMock()
    replacement = MagicMock()
    replacement.start.return_value = True
    manager._disruption_generation = 11
    manager.disrupted_devices[TARGET] = _active_entry(
        old_engine,
        11,
        arp_spoofer=old_spoofer,
    )
    monkeypatch.setattr(cnd, "NATIVE_ENGINE_AVAILABLE", True)
    monkeypatch.setattr(
        cnd,
        "NativeWinDivertEngine",
        MagicMock(return_value=replacement),
    )

    manager._fallback_to_self_disrupt(
        TARGET,
        ["lag"],
        {"lag_delay": 25},
        expected_generation=11,
        expected_engine=old_engine,
    )

    current = manager.disrupted_devices[TARGET]
    assert current["engine"] is replacement
    assert current["generation"] == 12
    assert current["wifi_fallback_transition"] is False
    assert current["wifi_self_disrupt"] is True
    replacement.stop.assert_not_called()


def test_dead_entry_reaper_cleans_watchdog_engine_and_arp() -> None:
    manager = ClumsyNetworkDisruptor()
    engine = MagicMock()
    engine.alive = False
    engine.stop.side_effect = RuntimeError("already closed")
    watchdog = MagicMock()
    spoofer = MagicMock()
    manager.disrupted_devices[TARGET] = _active_entry(
        engine,
        1,
        wifi_watchdog=watchdog,
        arp_spoofer=spoofer,
    )

    assert manager.get_disrupted_devices_clumsy() == []
    watchdog.cancel.assert_called_once()
    engine.stop.assert_called_once()
    spoofer.stop.assert_called_once()


def test_clumsy_stats_make_runtime_observability_explicit() -> None:
    engine = ClumsyEngine(
        "clumsy.exe",
        ".",
        "true",
        ["lag"],
        {"_target_ip": TARGET},
    )

    inactive = engine.get_stats()
    assert inactive["runtime_verification_available"] is False
    assert inactive["local_effect_verified"] is False
    assert inactive["verification_state"] == "inactive"

    proc = MagicMock()
    proc.poll.return_value = None
    engine._proc = proc
    active = engine.get_stats()
    assert active["verification_state"] == "runtime_unobservable"
