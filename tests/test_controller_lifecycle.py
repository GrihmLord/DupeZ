"""Tests for explicit AppController dependency and lifecycle ownership."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from app.core.controller import AppController
from app.core.kill_switch import KillSwitchConfigurationError
from app.core.safety_policy import SafetyPolicy


class _DisruptionManager:
    def __init__(self) -> None:
        self.initialize_calls = 0
        self.start_calls = 0
        self.stop_calls = 0
        self.stop_all_calls = 0
        self.stop_device_calls = []
        self.disrupt_calls = []
        self.engine_stats = {}

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
        return self.engine_stats


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
            kill_switch_enabled=False,
            kill_switch_process_watch_enabled=True,
            kill_switch_process_names=[],
            kill_switch_risk_threshold=80,
            kill_switch_packet_drop_ceiling=5000,
            kill_switch_packet_sustain_seconds=5.0,
            kill_switch_poll_interval_seconds=1.0,
            kill_switch_cooldown_seconds=30.0,
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
    state=None,
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
        state=state or _State(),
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
    controller.shutdown()


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

    assert controller.shutdown() is True
    assert controller.shutdown() is True

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
    assert controller.shutdown() is False

    assert controller._started is True
    assert plugins.unload_calls == 1
    assert scheduler.stop_calls == 1
    assert dm.stop_calls == 1
    assert saves == [True]


def test_shutdown_retries_after_explicit_cleanup_refusal() -> None:
    controller, dm, _cache, scheduler, plugins, saves = _controller(
        auto_start=True
    )
    results = iter((False, True))
    plugins.unload_all = lambda: next(results)

    assert controller.shutdown() is False
    assert controller._started is True
    assert controller.shutdown() is True
    assert controller._started is False
    assert scheduler.stop_calls == 2
    assert dm.stop_calls == 1
    assert saves == [True, True]


def test_plugin_reload_aborts_when_live_plugin_refuses_release() -> None:
    controller, _dm, _cache, _scheduler, plugins, _saves = _controller()
    plugins.unload_all = lambda: False

    assert controller.reload_plugins() is False
    assert plugins.discover_calls == 0
    assert plugins.load_calls == 0


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


def test_failed_explicit_stop_retains_operation_deadline() -> None:
    controller, dm, *_rest = _controller()
    target = "192.168.1.23"
    controller._arm_operation_deadline(target, 30)
    owned_deadline = controller._deadline_timers[target]

    def fail_stop(ip):
        dm.stop_device_calls.append(ip)
        return False

    dm.stop_device = fail_stop
    try:
        assert controller.stop_disruption(target) is False
        assert controller._deadline_timers[target] is owned_deadline
        assert dm.stop_device_calls == [target]
    finally:
        controller._cancel_all_operation_deadlines()


def test_raised_explicit_stop_retains_operation_deadline() -> None:
    controller, dm, *_rest = _controller()
    target = "192.168.1.24"
    controller._arm_operation_deadline(target, 30)
    owned_deadline = controller._deadline_timers[target]

    def raise_stop(_ip):
        raise RuntimeError("backend unavailable")

    dm.stop_device = raise_stop
    try:
        with pytest.raises(RuntimeError, match="backend unavailable"):
            controller.stop_disruption(target)
        assert controller._deadline_timers[target] is owned_deadline
    finally:
        controller._cancel_all_operation_deadlines()


def test_failed_deadline_stop_rearms_same_owned_generation() -> None:
    controller, dm, *_rest = _controller()
    target = "192.168.1.25"
    controller._DEADLINE_RELEASE_RETRY_SECONDS = 60.0
    controller._arm_operation_deadline(target, 30)
    original = controller._deadline_timers[target]

    def fail_stop(ip):
        dm.stop_device_calls.append(ip)
        return False

    dm.stop_device = fail_stop
    try:
        controller._expire_operation(target, original.generation)
        retained = controller._deadline_timers[target]
        assert retained.generation == original.generation
        assert retained.timer is not original.timer
        assert retained.expires_unix == original.expires_unix
        assert dm.stop_device_calls == [target]

        dm.stop_device = lambda _ip: True
        controller._expire_operation(target, original.generation)
        assert target not in controller._deadline_timers
    finally:
        controller._cancel_all_operation_deadlines()


def test_failed_stop_all_retains_operation_deadlines() -> None:
    controller, _dm, *_rest = _controller(
        clear_firewall_blocks=lambda: False,
    )
    target = "192.168.1.26"
    controller._arm_operation_deadline(target, 30)
    owned_deadline = controller._deadline_timers[target]
    try:
        assert controller.stop_all_disruptions() is False
        assert controller._deadline_timers[target] is owned_deadline
    finally:
        controller._cancel_all_operation_deadlines()


def test_failed_shutdown_restoration_retains_operation_deadline() -> None:
    controller, _dm, *_rest = _controller(
        auto_start=True,
        clear_firewall_blocks=lambda: False,
    )
    target = "192.168.1.27"
    controller._arm_operation_deadline(target, 30)
    owned_deadline = controller._deadline_timers[target]
    try:
        controller.shutdown()
        assert controller._deadline_timers[target] is owned_deadline
    finally:
        controller._cancel_all_operation_deadlines()


def test_safety_policy_update_is_refused_when_release_is_unconfirmed() -> None:
    controller, _dm, *_rest = _controller(
        clear_firewall_blocks=lambda: False,
    )
    original_settings = controller.state.settings
    original_policy = controller.safety_policy

    with pytest.raises(RuntimeError, match="could not be restored"):
        controller.update_setting("max_operation_seconds", 120)

    assert controller.state.settings is original_settings
    assert controller.safety_policy is original_policy
    assert controller.state.save_calls == 0


@pytest.mark.parametrize("mode", ["false", "raise"])
def test_failed_engine_stop_retains_engine_ownership(mode) -> None:
    controller, dm, *_rest = _controller()
    controller._engine_initialized = True

    if mode == "false":
        dm.stop = lambda: False
    else:
        dm.stop = lambda: (_ for _ in ()).throw(RuntimeError("stop failed"))

    with pytest.raises(RuntimeError):
        controller._stop_engine()

    assert controller._engine_initialized is True


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


def test_kill_switch_uses_only_aggregate_packet_drop_count() -> None:
    controller, dm, *_rest = _controller()
    dm.engine_stats = {
        "packets_dropped": 17,
        "packets_processed": 99,
        "per_device": {"192.168.1.44": {"packets_dropped": 17}},
    }

    assert controller._get_kill_switch_drop_counters() == {
        "packets_dropped": 17
    }


@pytest.mark.parametrize("value", [True, -1, 1.5, "7"])
def test_kill_switch_rejects_invalid_aggregate_drop_count(value) -> None:
    controller, dm, *_rest = _controller()
    dm.engine_stats = {"packets_dropped": value}

    with pytest.raises(ValueError, match="aggregate packet drop count"):
        controller._get_kill_switch_drop_counters()


def test_invalid_kill_switch_update_keeps_settings_and_worker() -> None:
    controller, *_rest = _controller(auto_start=True)
    old_settings = controller.state.settings
    old_switch = controller._kill_switch

    with pytest.raises(KillSwitchConfigurationError):
        controller.update_setting("kill_switch_risk_threshold", 101)

    try:
        assert controller.state.settings is old_settings
        assert controller._kill_switch is old_switch
        assert old_switch.is_running is True
        assert controller.state.save_calls == 0
    finally:
        controller.shutdown()


def test_valid_kill_switch_update_sanitizes_and_replaces_without_overlap() -> None:
    controller, *_rest = _controller(auto_start=True)
    old_switch = controller._kill_switch

    controller.update_setting(
        "kill_switch_process_names",
        [r"C:\Program Files\Vendor\GUARD.EXE", "guard.exe"],
    )

    try:
        assert controller._kill_switch is not old_switch
        assert old_switch.is_running is False
        assert controller._kill_switch.is_running is True
        assert controller.state.settings.kill_switch_process_names == [
            "guard.exe"
        ]
        assert controller.state.save_calls == 1
    finally:
        controller.shutdown()


def test_malformed_persisted_kill_switch_settings_block_mutations() -> None:
    state = _State()
    state.settings.kill_switch_poll_interval_seconds = 0
    controller, dm, *_rest = _controller(state=state)

    assert controller.network_operations_available is False
    assert controller.disrupt_device("192.168.1.20", ["drop"]) is False
    assert dm.disrupt_calls == []
    health = controller.get_startup_health()
    assert health["recovery_blocked"] is False
    assert health["kill_switch_blocked"] is True
    assert health["message"] == "automatic kill-switch settings are invalid"

    controller.update_setting("kill_switch_poll_interval_seconds", 1.0)

    assert controller.network_operations_available is True
    assert controller.get_startup_health()["kill_switch_blocked"] is False
    assert state.save_calls == 1


def test_manual_panic_stop_remains_available_when_automation_is_disabled() -> None:
    controller, dm, *_rest = _controller()

    controller.fire_manual_kill_switch()

    assert dm.stop_all_calls == 1
