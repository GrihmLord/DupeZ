"""Focused contracts for the one-click automatic connection workflow."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.core.controller import AppController
from app.core.cut_chain import (
    ChainConfig,
    CutChainRunner,
    Gate,
    Stage,
    build_automatic_connection_test,
)
from app.core.safety_policy import SafetyPolicy


def _wait_for(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition did not become true")


def test_factory_builds_bounded_pure_stages_and_copies_inputs() -> None:
    common = {
        "lag_delay": 9000,
        "direction": "inbound",
        "_engine_preference": "clumsy",
        "_auto_tune_duration": True,
        "_network_local": True,
        "nested": {"value": 1},
    }
    metadata = {"target_mac": "AA:BB:CC:DD:EE:FF"}

    config = build_automatic_connection_test(
        "192.168.1.25",
        common_params=common,
        disrupt_kwargs=metadata,
    )
    common["nested"]["value"] = 99
    metadata["target_mac"] = "changed"

    assert [stage.methods for stage in config.stages] == [
        ["lag"],
        ["disconnect"],
    ]
    lag, disconnect = config.stages
    assert lag.params == {
        "lag_delay": 5000,
        "lag_passthrough": False,
        "lag_preserve_connection": False,
        "direction": "both",
    }
    assert lag.verify_method == "lag"
    assert lag.gate.seconds == 6.0
    assert disconnect.params == {
        "disconnect_chance": 100,
        "disconnect_arm_delay_ms": 0,
        "disconnect_duration_ms": 0,
        "direction": "both",
    }
    assert disconnect.verify_method == "disconnect"
    assert disconnect.gate.seconds == 5.0
    assert config.global_timeout_s == 20.0
    assert config.common_params["nested"] == {"value": 1}
    assert "_engine_preference" not in config.common_params
    assert "_auto_tune_duration" not in config.common_params
    assert "_network_local" not in config.common_params
    assert config.disrupt_kwargs["target_mac"] == "AA:BB:CC:DD:EE:FF"


def test_factory_accepts_absent_optional_device_metadata() -> None:
    config = build_automatic_connection_test(
        "192.168.1.25",
        disrupt_kwargs={
            "target_mac": None,
            "target_hostname": None,
            "target_device_type": None,
        },
    )

    assert config.disrupt_kwargs == {
        "target_mac": None,
        "target_hostname": None,
        "target_device_type": None,
    }


class _RecordingController:
    def __init__(self, fail_call: int = 0) -> None:
        self.calls: list[tuple] = []
        self.fail_call = fail_call
        self.disrupt_count = 0

    def disrupt_device(self, ip, methods, params, **kwargs):
        self.disrupt_count += 1
        self.calls.append(
            (
                "disrupt",
                ip,
                list(methods),
                dict(params),
                {k: v for k, v in kwargs.items() if k != "_cut_chain_runner"},
            )
        )
        return self.disrupt_count != self.fail_call

    def stop_disruption(self, ip, **_kwargs):
        self.calls.append(("stop", ip))
        return True


def test_runner_orders_calls_forwards_metadata_and_releases() -> None:
    controller = _RecordingController()
    config = build_automatic_connection_test(
        "192.168.1.25",
        common_params={"lag_delay": 1500, "direction": "outbound"},
        disrupt_kwargs={
            "target_mac": "AA:BB:CC:DD:EE:FF",
            "target_hostname": "console",
        },
    )
    for stage in config.stages:
        stage.gate = Gate("time", seconds=0.01)
    events = []
    finished = threading.Event()

    def _event(event) -> None:
        events.append(event)
        if event.kind in {"complete", "halt", "error"}:
            finished.set()

    runner = CutChainRunner(config, controller, on_event=_event)
    runner.start()
    assert finished.wait(2.0)

    assert [call[0] for call in controller.calls] == [
        "disrupt",
        "stop",
        "disrupt",
        "stop",
    ]
    first, _, second, _ = controller.calls
    assert first[2] == ["lag"]
    assert first[3]["lag_delay"] == 1500
    assert first[3]["direction"] == "both"
    assert second[3]["direction"] == "both"
    assert second[2] == ["disconnect"]
    assert second[3]["disconnect_duration_ms"] == 0
    assert first[4] == second[4] == {
        "target_mac": "AA:BB:CC:DD:EE:FF",
        "target_hostname": "console",
    }
    assert events[-1].kind == "complete"
    assert events[-1].detail == "connection released"


def test_runner_halts_on_stage_failure_without_starting_disconnect() -> None:
    controller = _RecordingController(fail_call=1)
    config = build_automatic_connection_test("192.168.1.25")
    for stage in config.stages:
        stage.gate = Gate("time", seconds=0.01)
    events = []
    finished = threading.Event()

    def _event(event) -> None:
        events.append(event)
        if event.kind in {"complete", "halt", "error"}:
            finished.set()

    CutChainRunner(config, controller, on_event=_event).start()
    assert finished.wait(2.0)
    assert [call[0] for call in controller.calls] == ["disrupt"]
    assert events[-1].kind == "error"


def test_runner_cancel_releases_and_never_starts_second_stage() -> None:
    controller = _RecordingController()
    config = build_automatic_connection_test("192.168.1.25")
    config.stages[0].gate = Gate("time", seconds=30.0)
    runner = CutChainRunner(config, controller)
    runner.start()
    _wait_for(lambda: controller.disrupt_count == 1)
    runner.stop()

    assert [call[0] for call in controller.calls] == ["disrupt", "stop"]
    assert not runner.running


class _TelemetryController(_RecordingController):
    def __init__(self, *, affected: int, telemetry_available: bool = True):
        super().__init__()
        self.affected = affected
        self.telemetry_available = telemetry_available

    def get_engine_stats(self):
        method = ""
        for call in reversed(self.calls):
            if call[0] == "disrupt":
                method = call[2][0]
                break
        device = {
            "telemetry_available": self.telemetry_available,
            "startup_verified": True,
        }
        if self.telemetry_available:
            device["module_activity"] = {
                method: {
                    "state": "effective" if self.affected else "reached",
                    "affected": self.affected,
                }
            }
        return {"per_device": {"192.168.1.25": device}}


def test_runner_requires_native_effect_before_advancing() -> None:
    controller = _TelemetryController(affected=0)
    config = build_automatic_connection_test("192.168.1.25")
    for stage in config.stages:
        stage.gate = Gate("time", seconds=0.01)
    events = []
    finished = threading.Event()

    def _event(event) -> None:
        events.append(event)
        if event.kind in {"complete", "halt", "error"}:
            finished.set()

    CutChainRunner(config, controller, on_event=_event).start()
    assert finished.wait(2.0)
    assert [call[0] for call in controller.calls] == ["disrupt", "stop"]
    assert events[-1].kind == "error"
    assert "lag produced no verified packet effect" in events[-1].detail


def test_runner_accepts_verified_native_effects() -> None:
    controller = _TelemetryController(affected=2)
    config = build_automatic_connection_test("192.168.1.25")
    for stage in config.stages:
        stage.gate = Gate("time", seconds=0.01)
    events = []
    finished = threading.Event()

    def _event(event) -> None:
        events.append(event)
        if event.kind in {"complete", "halt", "error"}:
            finished.set()

    CutChainRunner(config, controller, on_event=_event).start()
    assert finished.wait(2.0)
    assert events[-1].kind == "complete"
    verified = [event.detail for event in events if event.kind == "stage_end"]
    assert verified == [
        "lag verified (2 packet effects)",
        "disconnect verified (2 packet effects)",
    ]


def test_runner_labels_clumsy_runtime_as_unobservable_without_blocking() -> None:
    controller = _TelemetryController(
        affected=0,
        telemetry_available=False,
    )
    config = build_automatic_connection_test("192.168.1.25")
    for stage in config.stages:
        stage.gate = Gate("time", seconds=0.01)
    events = []
    finished = threading.Event()

    def _event(event) -> None:
        events.append(event)
        if event.kind in {"complete", "halt", "error"}:
            finished.set()

    CutChainRunner(config, controller, on_event=_event).start()
    assert finished.wait(2.0)
    assert events[-1].kind == "complete"
    details = [event.detail for event in events if event.kind == "stage_end"]
    assert all("runtime unobservable (startup verified)" in d for d in details)


def test_global_timeout_interrupts_a_long_stage_and_releases() -> None:
    controller = _RecordingController()
    config = ChainConfig(
        target_ip="192.168.1.25",
        stages=[Stage("Lag", gate=Gate("time", seconds=30.0))],
        global_timeout_s=0.1,
    )
    events = []
    finished = threading.Event()

    def _event(event) -> None:
        events.append(event)
        if event.kind in {"complete", "halt", "error"}:
            finished.set()

    started = time.monotonic()
    CutChainRunner(config, controller, on_event=_event).start()
    assert finished.wait(2.0)
    assert time.monotonic() - started < 1.0
    assert [call[0] for call in controller.calls] == ["disrupt", "stop"]
    assert events[-1].kind == "halt"
    assert "global timeout" in events[-1].detail


class _Manager:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def initialize(self):
        return True

    def start(self):
        return None

    def stop(self):
        self.calls.append(("manager_stop",))

    def disrupt_device(self, ip, methods, params, **kwargs):
        self.calls.append(("disrupt", ip, list(methods), dict(params), kwargs))
        return True

    def stop_device(self, ip):
        self.calls.append(("stop", ip))
        return True

    def stop_all_devices(self):
        self.calls.append(("stop_all",))
        return True

    def get_disrupted_devices(self):
        return []


class _Journal:
    def mark_pending(self, _reason):
        return None

    def is_pending(self):
        return False

    def clear(self):
        return None

    def forwarding_original_state(self):
        return None


class _IdleService:
    def start(self):
        return None

    def stop(self):
        return None

    def discover(self):
        return []

    def load_all(self, _controller):
        return []

    def unload_all(self):
        return None

    def get_active_plugins(self):
        return []


def _make_controller(manager: _Manager) -> AppController:
    state = SimpleNamespace(
        settings=SimpleNamespace(auto_scan=False),
        devices=[],
        scan_in_progress=False,
    )
    return AppController(
        disruption_manager=manager,
        device_cache=SimpleNamespace(get_cached_devices=lambda: []),
        save_all=lambda: True,
        state=state,
        plugin_loader=_IdleService(),
        scheduler_factory=lambda **_kwargs: _IdleService(),
        safety_policy=SafetyPolicy(max_operation_seconds=30),
        recovery_journal=_Journal(),
        clear_firewall_blocks=lambda: True,
        get_blocked_ips=lambda: [],
        restore_ip_forwarding=lambda _enabled: True,
        auto_start=False,
    )


def _long_workflow(target_ip, *, common_params=None, disrupt_kwargs=None):
    return ChainConfig(
        target_ip=target_ip,
        stages=[
            Stage(
                "Lag",
                methods=["lag"],
                gate=Gate("time", seconds=30.0),
            )
        ],
        common_params=common_params or {},
        disrupt_kwargs=disrupt_kwargs or {},
        global_timeout_s=60.0,
    )


def _fast_two_stage_workflow(
    target_ip, *, common_params=None, disrupt_kwargs=None
):
    return ChainConfig(
        target_ip=target_ip,
        stages=[
            Stage(
                "Lag",
                methods=["lag"],
                gate=Gate("time", seconds=0.01),
            ),
            Stage(
                "Red Disconnect",
                methods=["disconnect"],
                params={"disconnect_duration_ms": 10},
                gate=Gate("time", seconds=0.01),
            ),
        ],
        common_params=common_params or {},
        disrupt_kwargs=disrupt_kwargs or {},
        global_timeout_s=1.0,
    )


def test_controller_marker_allows_stage_two_and_completion(monkeypatch) -> None:
    manager = _Manager()
    controller = _make_controller(manager)
    monkeypatch.setattr(
        "app.core.controller.build_automatic_connection_test",
        _fast_two_stage_workflow,
    )
    events = []
    complete = threading.Event()

    def _event(event) -> None:
        events.append(event)
        if event.kind in {"complete", "halt", "error"}:
            complete.set()

    generation = controller.start_automatic_workflow(
        "192.168.1.25",
        disrupt_kwargs={"target_hostname": "authorized-test-device"},
        on_event=_event,
    )
    assert generation > 0
    assert complete.wait(2.0)

    disrupts = [call for call in manager.calls if call[0] == "disrupt"]
    assert [call[2] for call in disrupts] == [["lag"], ["disconnect"]]
    assert all(
        call[4] == {"target_hostname": "authorized-test-device"}
        for call in disrupts
    )
    assert events[-1].kind == "complete"
    assert not controller.is_automatic_workflow_running()


def test_controller_replaces_runner_and_manual_start_cancels_it(
    monkeypatch,
) -> None:
    manager = _Manager()
    controller = _make_controller(manager)
    monkeypatch.setattr(
        "app.core.controller.build_automatic_connection_test",
        _long_workflow,
    )

    first_events = []
    first = controller.start_automatic_workflow(
        "192.168.1.25", on_event=first_events.append
    )
    _wait_for(lambda: len([c for c in manager.calls if c[0] == "disrupt"]) == 1)
    second = controller.start_automatic_workflow("192.168.1.26")
    assert second > first > 0
    assert first_events[-1].kind == "halt"
    _wait_for(lambda: len([c for c in manager.calls if c[0] == "disrupt"]) == 2)
    assert controller.is_automatic_workflow_running()

    assert controller.disrupt_device(
        "192.168.1.30", ["lag"], {"lag_delay": 10}
    )
    assert not controller.is_automatic_workflow_running()
    disrupts = [call for call in manager.calls if call[0] == "disrupt"]
    assert [call[1] for call in disrupts] == [
        "192.168.1.25",
        "192.168.1.26",
        "192.168.1.30",
    ]
    controller.stop_all_disruptions()


def test_controller_stop_all_and_shutdown_cancel_owned_runner(monkeypatch) -> None:
    manager = _Manager()
    controller = _make_controller(manager)
    monkeypatch.setattr(
        "app.core.controller.build_automatic_connection_test",
        _long_workflow,
    )

    controller.start_automatic_workflow("192.168.1.25")
    _wait_for(controller.is_automatic_workflow_running)
    controller.stop_all_disruptions()
    assert not controller.is_automatic_workflow_running()

    controller.start_automatic_workflow("192.168.1.26")
    _wait_for(controller.is_automatic_workflow_running)
    controller.shutdown()
    assert not controller.is_automatic_workflow_running()


def test_controller_rejects_release_from_stale_runner(monkeypatch) -> None:
    manager = _Manager()
    controller = _make_controller(manager)
    monkeypatch.setattr(
        "app.core.controller.build_automatic_connection_test",
        _long_workflow,
    )

    controller.start_automatic_workflow("192.168.1.25")
    _wait_for(controller.is_automatic_workflow_running)
    stop_count = len([call for call in manager.calls if call[0] == "stop"])

    assert controller.stop_disruption(
        "192.168.1.25",
        _cut_chain_runner=object(),
    ) is False
    assert len([call for call in manager.calls if call[0] == "stop"]) == stop_count
    controller.stop_automatic_workflow()


def test_controller_starts_owned_configured_chain_and_caps_deadline(
    monkeypatch,
) -> None:
    manager = _Manager()
    controller = _make_controller(manager)
    captured = {}

    class _Runner:
        def __init__(self, config, owner, on_event=None) -> None:
            captured["config"] = config
            captured["owner"] = owner
            captured["callback"] = on_event
            self.running = False

        def start(self) -> None:
            self.running = True

        def stop(self) -> bool:
            self.running = False
            return True

        @property
        def release_confirmed(self) -> bool:
            return not self.running

        def confirm_external_release(self) -> bool:
            self.running = False
            return True

    monkeypatch.setattr("app.core.controller.CutChainRunner", _Runner)
    config = ChainConfig(
        target_ip="192.168.1.25",
        stages=[Stage("Lag", gate=Gate("time", seconds=1.0))],
        global_timeout_s=60.0,
    )

    generation = controller.start_cut_chain(config)

    assert generation > 0
    assert captured["owner"] is controller
    assert captured["config"] is not config
    assert captured["config"].target_ip == "192.168.1.25"
    assert captured["config"].global_timeout_s == 30.0
    assert config.global_timeout_s == 60.0
    assert controller.is_automatic_workflow_running()
    assert controller.stop_automatic_workflow()


def test_controller_refuses_configured_chain_outside_narrow_scope() -> None:
    manager = _Manager()
    controller = _make_controller(manager)
    controller.safety_policy = SafetyPolicy(
        allowed_cidrs=("192.168.1.0/24",),
        max_operation_seconds=30,
    )
    config = ChainConfig(
        target_ip="192.168.2.25",
        stages=[Stage("Lag", gate=Gate("time", seconds=0.01))],
        global_timeout_s=1.0,
    )

    assert controller.start_cut_chain(config) == 0
    assert manager.calls == []
    assert not controller.is_automatic_workflow_running()


def test_controller_refuses_mutated_chain_before_runner_ownership() -> None:
    manager = _Manager()
    controller = _make_controller(manager)
    config = ChainConfig(
        target_ip="192.168.1.25",
        stages=[Stage("Lag", gate=Gate("time", seconds=0.01))],
        global_timeout_s=1.0,
    )
    config.stages[0].action = "execute_program"

    assert controller.start_cut_chain(config) == 0
    assert manager.calls == []
    assert not controller.is_automatic_workflow_running()


def test_controller_blocks_replacement_until_global_restore_confirms_release(
    monkeypatch,
) -> None:
    manager = _Manager()
    controller = _make_controller(manager)
    runners = []

    class _UnconfirmedRunner:
        def __init__(self, _config, _owner, on_event=None) -> None:
            self.running = False
            self.release_confirmed = False
            self.on_event = on_event
            self.stop_calls = 0
            runners.append(self)

        def start(self) -> None:
            self.running = True

        def stop(self) -> bool:
            self.stop_calls += 1
            self.running = False
            return False

        def confirm_external_release(self) -> bool:
            if self.running:
                return False
            self.release_confirmed = True
            return True

    monkeypatch.setattr(
        "app.core.controller.CutChainRunner",
        _UnconfirmedRunner,
    )
    first = ChainConfig(
        target_ip="192.168.1.25",
        stages=[Stage("Lag", gate=Gate("time", seconds=1))],
        global_timeout_s=5,
    )
    second = ChainConfig(
        target_ip="192.168.1.26",
        stages=[Stage("Red Disconnect", gate=Gate("time", seconds=1))],
        global_timeout_s=5,
    )

    assert controller.start_cut_chain(first) > 0
    assert controller.start_cut_chain(second) == 0
    assert len(runners) == 1
    assert controller.is_automatic_workflow_running()
    assert controller.disrupt_device(
        "192.168.1.30",
        ["lag"],
        {"lag_delay": 10},
    ) is False
    assert not [call for call in manager.calls if call[0] == "disrupt"]

    assert controller.stop_all_disruptions() is True
    assert runners[0].release_confirmed
    assert controller.start_cut_chain(second) > 0
    assert len(runners) == 2


def test_external_stop_fails_closed_when_automatic_release_is_unconfirmed() -> None:
    manager = _Manager()
    controller = _make_controller(manager)
    target = "192.168.1.25"
    runner = SimpleNamespace(
        running=False,
        release_confirmed=False,
        stop=MagicMock(return_value=False),
    )
    controller._automatic_runner = runner
    controller._arm_operation_deadline(target, 30.0)
    owned_deadline = controller._deadline_timers[target]

    try:
        assert controller.stop_disruption(target) is False
        runner.stop.assert_called_once_with()
        assert manager.calls == []
        assert controller._automatic_runner is runner
        assert controller._deadline_timers[target] is owned_deadline
    finally:
        controller._cancel_all_operation_deadlines()


def test_macro_stop_retains_automatic_target_when_cleanup_is_unconfirmed() -> None:
    from app.gui.clumsy_control import ClumsyControlView

    stop_automatic = MagicMock(return_value=False)
    stop_macro = MagicMock(return_value=True)
    status = SimpleNamespace(
        setText=MagicMock(),
        setStyleSheet=MagicMock(),
    )
    view = SimpleNamespace(
        controller=SimpleNamespace(
            stop_automatic_workflow=stop_automatic,
            scheduler=SimpleNamespace(stop_macro=stop_macro),
        ),
        _automatic_target_ip="192.168.1.25",
        _automatic_ui_generation=4,
        sched_status=status,
        _MUTED_QSS="muted",
        _WARNING_QSS="warning",
    )

    ClumsyControlView._on_stop_macro(view)

    stop_automatic.assert_called_once_with()
    stop_macro.assert_called_once_with()
    assert view._automatic_target_ip == "192.168.1.25"
    assert view._automatic_ui_generation == 5
    status.setText.assert_called_once_with(
        "Automatic cleanup not confirmed — retry Stop"
    )
    status.setStyleSheet.assert_called_once_with("warning")


def test_gui_source_has_automatic_guard_and_no_engine_or_layer_widgets() -> None:
    source = (
        Path(__file__).parents[1] / "app" / "gui" / "clumsy_control.py"
    ).read_text(encoding="utf-8")
    assert "_automatic_event_ready = pyqtSignal(int, object)" in source
    assert "if generation != self._automatic_ui_generation" in source
    assert "self.engine_combo" not in source
    assert "self.pc_local_check" not in source
