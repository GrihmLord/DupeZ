"""Tests for explicit AppController dependency and lifecycle ownership."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from app.core.controller import AppController
from app.core.safety_policy import SafetyPolicy


class _DisruptionManager:
    def __init__(self) -> None:
        self.initialize_calls = 0
        self.start_calls = 0
        self.stop_calls = 0
        self.stop_all_calls = 0
        self.stop_device_calls = []
        self.disrupt_calls = []

    def initialize(self):
        self.initialize_calls += 1
        return True

    def start(self):
        self.start_calls += 1

    def stop(self):
        self.stop_calls += 1

    def disrupt_device(self, *args, **kwargs):
        self.disrupt_calls.append((args, kwargs))
        return True

    def stop_device(self, _ip):
        self.stop_device_calls.append(_ip)
        return True

    def stop_all_devices(self):
        self.stop_all_calls += 1
        return True

    def get_disrupted_devices(self):
        return []

    def mark_cut_outcome(self, _persisted, ip=None):
        return 1 if ip else 0

    def get_device_status(self, _ip):
        return {}

    def get_status(self):
        return {"running": True}

    def get_engine_stats(self):
        return {}


class _DeviceCache:
    def __init__(self) -> None:
        self.get_calls = 0
        self.updated = []

    def get_cached_devices(self):
        self.get_calls += 1
        return []

    def update_cache(self, devices):
        self.updated.append(devices)


class _Scheduler:
    def __init__(self, **_kwargs) -> None:
        self.start_calls = 0
        self.stop_calls = 0

    def start(self):
        self.start_calls += 1

    def stop(self):
        self.stop_calls += 1


class _Plugins:
    def __init__(self) -> None:
        self.discover_calls = 0
        self.load_calls = 0
        self.unload_calls = 0

    def discover(self):
        self.discover_calls += 1

    def load_all(self, _controller):
        self.load_calls += 1

    def unload_all(self):
        self.unload_calls += 1

    def get_active_plugins(self):
        return []

    def get_ui_panel_plugins(self):
        return []


class _State:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(
            auto_scan=False,
            scan_interval=3600,
            safety_dry_run=False,
            allowed_target_cidrs=[
                "10.0.0.0/8",
                "172.16.0.0/12",
                "192.168.0.0/16",
                "169.254.0.0/16",
            ],
            max_operation_seconds=300,
        )
        self.devices = []
        self.scan_in_progress = False
        self.save_calls = 0

    def update_devices(self, devices):
        self.devices = devices

    def save_settings(self):
        self.save_calls += 1


class _Journal:
    def __init__(self, pending=False, forwarding_original=None) -> None:
        self.pending = pending
        self.forwarding_original = forwarding_original
        self.marks = []
        self.clear_calls = 0

    def mark_pending(self, reason):
        self.pending = True
        self.marks.append(reason)

    def is_pending(self):
        return self.pending

    def clear(self):
        self.pending = False
        self.clear_calls += 1

    def forwarding_original_state(self):
        return self.forwarding_original


def _controller(
    auto_start: bool = False,
    safety_policy=None,
    recovery_journal=None,
    clear_firewall_blocks=lambda: True,
    restore_ip_forwarding=lambda _enabled: True,
):
    dm = _DisruptionManager()
    cache = _DeviceCache()
    scheduler = _Scheduler()
    plugins = _Plugins()
    saves = []
    controller = AppController(
        disruption_manager=dm,
        device_cache=cache,
        save_all=lambda: saves.append(True) or True,
        state=_State(),
        plugin_loader=plugins,
        scheduler_factory=lambda **_kwargs: scheduler,
        safety_policy=safety_policy,
        recovery_journal=recovery_journal or _Journal(),
        clear_firewall_blocks=clear_firewall_blocks,
        get_blocked_ips=lambda: [],
        restore_ip_forwarding=restore_ip_forwarding,
        auto_start=auto_start,
    )
    return controller, dm, cache, scheduler, plugins, saves


def test_controller_can_be_constructed_without_starting_services() -> None:
    controller, dm, cache, scheduler, plugins, saves = _controller()

    assert controller._started is False
    assert dm.initialize_calls == 0
    assert cache.get_calls == 0
    assert scheduler.start_calls == 0
    assert plugins.discover_calls == 0
    assert saves == []


def test_start_is_idempotent() -> None:
    controller, dm, cache, scheduler, plugins, _saves = _controller()

    controller.start()
    controller.start()

    assert controller._started is True
    assert dm.initialize_calls == 1
    assert dm.start_calls == 1
    assert cache.get_calls == 1
    assert scheduler.start_calls == 1
    assert plugins.discover_calls == 1
    assert plugins.load_calls == 1


def test_partial_start_failure_rolls_back_engine_and_scheduler() -> None:
    controller, dm, _cache, scheduler, _plugins, _saves = _controller()

    def failing_start():
        scheduler.start_calls += 1
        raise RuntimeError("scheduler failure")

    scheduler.start = failing_start

    try:
        controller.start()
    except RuntimeError as exc:
        assert "scheduler failure" in str(exc)
    else:
        raise AssertionError("controller.start() should propagate startup failure")

    assert controller._started is False
    assert scheduler.stop_calls == 1
    assert dm.stop_calls == 1


def test_shutdown_is_idempotent_and_stops_owned_services() -> None:
    controller, dm, _cache, scheduler, plugins, saves = _controller(
        auto_start=True
    )

    controller.shutdown()
    controller.shutdown()

    assert controller._started is False
    assert dm.stop_calls == 1
    assert scheduler.stop_calls == 1
    assert plugins.unload_calls == 1
    assert saves == [True]


def test_shutdown_continues_after_one_component_fails() -> None:
    controller, dm, _cache, scheduler, plugins, saves = _controller(
        auto_start=True
    )

    def failing_unload():
        plugins.unload_calls += 1
        raise RuntimeError("plugin failure")

    plugins.unload_all = failing_unload
    controller.shutdown()

    assert controller._started is False
    assert plugins.unload_calls == 1
    assert scheduler.stop_calls == 1
    assert dm.stop_calls == 1
    assert saves == [True]


def test_disruption_calls_use_injected_manager() -> None:
    controller, dm, *_rest = _controller()

    assert controller.disrupt_device(
        "192.168.1.10",
        ["drop"],
        {"drop_chance": 50},
        target_hostname="console",
    )
    args, kwargs = dm.disrupt_calls[0]
    assert args[0] == "192.168.1.10"
    assert args[1] == ["drop"]
    assert kwargs["target_hostname"] == "console"
    assert controller._recovery_journal.is_pending() is True


def test_disruption_refuses_public_target_before_engine_call() -> None:
    controller, dm, *_rest = _controller()

    assert controller.disrupt_device("8.8.8.8", ["drop"]) is False
    assert dm.disrupt_calls == []


def test_failed_start_keeps_journal_when_helper_state_is_unobservable() -> None:
    journal = _Journal()
    controller, dm, *_rest = _controller(recovery_journal=journal)
    dm.disrupt_device = lambda *_args, **_kwargs: False
    dm.get_disrupted_devices = lambda: (_ for _ in ()).throw(
        TimeoutError("helper unavailable")
    )

    assert controller.disrupt_device("192.168.1.20", ["drop"]) is False

    assert journal.pending is True
    assert "packet_disruption" in journal.marks


def test_dry_run_skips_engine_and_records_no_real_disruption() -> None:
    policy = SafetyPolicy(dry_run=True)
    controller, dm, *_rest = _controller(
        auto_start=True,
        safety_policy=policy,
    )

    assert dm.initialize_calls == 0
    assert controller.disrupt_device("192.168.1.20", ["drop"]) is True
    assert dm.disrupt_calls == []
    assert controller.plugin_loader.get_ui_panel_plugins() == []
    controller.shutdown()


def test_operation_deadline_stops_target() -> None:
    policy = SafetyPolicy(max_operation_seconds=1)
    controller, dm, *_rest = _controller(safety_policy=policy)

    assert controller.disrupt_device(
        "192.168.1.21",
        ["drop"],
        operation_timeout=0.05,
    )
    time.sleep(0.15)

    assert dm.stop_device_calls == ["192.168.1.21"]
    assert "192.168.1.21" not in controller._deadline_timers


def test_active_operation_snapshot_exposes_deadline_not_params() -> None:
    policy = SafetyPolicy(max_operation_seconds=60)
    controller, dm, *_rest = _controller(safety_policy=policy)
    dm.get_disrupted_devices = lambda: ["192.168.1.22"]
    dm.get_device_status = lambda _ip: {
        "methods": ["lag", "drop"],
        "params": {"lag_delay": 900, "private_note": "do not export"},
        "start_time": time.time() - 5,
        "process_running": True,
    }

    controller._arm_operation_deadline("192.168.1.22", 30)
    snapshot = controller.get_active_operations()
    controller._cancel_all_operation_deadlines()

    assert len(snapshot) == 1
    operation = snapshot[0]
    assert operation["target"] == "192.168.1.x"
    assert operation["methods"] == ["drop", "lag"]
    assert operation["automatic_stop_armed"] is True
    assert 0 <= operation["remaining_seconds"] <= 30
    assert "params" not in operation
    assert len(operation["params_fingerprint"]) == 16


def test_engine_initialization_failure_is_visible() -> None:
    controller, dm, *_rest = _controller()
    dm.initialize = lambda: False

    with pytest.raises(RuntimeError, match="engine init failed"):
        controller.start()

    assert controller._started is False
    assert dm.stop_calls == 0


def test_invalid_scope_update_rolls_back_setting() -> None:
    controller, *_rest = _controller()
    original = list(controller.state.settings.allowed_target_cidrs)

    with pytest.raises(ValueError, match="public target scope"):
        controller.update_setting("allowed_target_cidrs", ["0.0.0.0/0"])

    assert controller.state.settings.allowed_target_cidrs == original
    assert controller.state.save_calls == 0


def test_stale_journal_is_restored_before_services_start() -> None:
    journal = _Journal(pending=True)
    controller, dm, _cache, scheduler, *_rest = _controller(
        recovery_journal=journal,
    )

    controller.start()

    assert dm.stop_all_calls == 1
    assert journal.pending is False
    assert scheduler.start_calls == 1
    controller.shutdown()


def test_stale_journal_retained_when_firewall_restore_fails() -> None:
    journal = _Journal(pending=True)
    controller, dm, _cache, scheduler, *_rest = _controller(
        recovery_journal=journal,
        clear_firewall_blocks=lambda: False,
    )

    controller.start()

    assert dm.stop_all_calls == 1
    assert journal.pending is True
    assert "restore_firewall_incomplete" in journal.marks
    assert controller._started is True
    assert controller.network_operations_available is False
    health = controller.get_startup_health()
    assert health["recovery_blocked"] is True
    assert "could not be fully restored" in health["message"]
    assert scheduler.start_calls == 0
    assert controller.disrupt_device("192.168.1.20", ["drop"]) is False
    assert dm.disrupt_calls == []
    controller.shutdown()


def test_stale_journal_restores_original_forwarding_state() -> None:
    journal = _Journal(pending=True, forwarding_original=True)
    restored = []
    controller, *_rest = _controller(
        recovery_journal=journal,
        restore_ip_forwarding=lambda enabled: restored.append(enabled) or True,
    )

    controller.start()

    assert restored == [True]
    assert journal.pending is False
    controller.shutdown()


def test_auto_scan_stop_wakes_and_joins_sleeping_thread() -> None:
    controller, *_rest = _controller()
    scanned = threading.Event()
    controller.quick_scan_devices = lambda: scanned.set() or []

    controller.start_auto_scan()
    assert scanned.wait(timeout=1.0)

    controller.stop_auto_scan(join_timeout=1.0)

    assert controller._scan_stop_event.is_set()
    assert controller.scan_thread is not None
    assert not controller.scan_thread.is_alive()
