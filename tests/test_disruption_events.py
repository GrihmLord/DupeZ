"""Tests for user-owned disruption events and the routing UI adapter."""

from __future__ import annotations

import time
from types import SimpleNamespace

from PyQt6.QtWidgets import QApplication

from app.core.disruption_events import (
    ENGINE_CLUMSY,
    FAILURE_CONTINUE,
    LAYER_LOCAL,
    LAYER_REMOTE,
    DisruptionEvent,
    EventSequence,
    EventSequenceRunner,
    EventSequenceStore,
)
from app.gui.panels.disruption_event_panel import DisruptionEventPanel


def _wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


def test_event_resolves_explicit_engine_and_layer_without_mutating_source():
    original = {"lag_delay": 900, "nested": {"value": 1}}
    event = DisruptionEvent(
        methods=["lag"],
        params=original,
        engine_preference=ENGINE_CLUMSY,
        network_layer=LAYER_REMOTE,
    )

    resolved = event.resolved_params()
    resolved["nested"]["value"] = 2

    assert resolved["_engine_preference"] == ENGINE_CLUMSY
    assert resolved["_network_local"] is False
    assert resolved["_network_layer_explicit"] is True
    assert original == {"lag_delay": 900, "nested": {"value": 1}}


def test_event_store_round_trip_preserves_enabled_order_and_routing(tmp_path):
    store = EventSequenceStore(str(tmp_path))
    sequence = EventSequence(
        name="Lab queue",
        events=[
            DisruptionEvent(
                name="First",
                enabled=False,
                methods=["lag"],
                engine_preference=ENGINE_CLUMSY,
                network_layer=LAYER_LOCAL,
            ),
            DisruptionEvent(
                name="Second",
                methods=["drop"],
                network_layer=LAYER_REMOTE,
            ),
        ],
    )

    sequence_id = store.save(sequence)
    reloaded = EventSequenceStore(str(tmp_path)).get(sequence_id)

    assert reloaded is not None
    assert [event.name for event in reloaded.events] == ["First", "Second"]
    assert reloaded.events[0].enabled is False
    assert reloaded.events[0].engine_preference == ENGINE_CLUMSY
    assert reloaded.events[1].network_layer == LAYER_REMOTE


class _FakeController:
    def __init__(self):
        self.calls = []
        self.stop_calls = []
        self.generation = 7
        self.active = False
        self.last_error = ""

    def disrupt_device(self, ip, methods, params, **kwargs):
        self.calls.append((ip, list(methods), dict(params), dict(kwargs)))
        self.active = True
        return True

    def get_disruption_status(self, _ip):
        if not self.active:
            return {"disrupted": False}
        return {
            "disrupted": True,
            "generation": self.generation,
            "engine": "clumsy",
        }

    def stop_disruption(self, ip):
        self.stop_calls.append(ip)
        self.active = False
        return True

    def get_clumsy_status(self):
        return {"last_engine_error": self.last_error}


def test_runner_skips_disabled_event_and_injects_per_event_routing():
    controller = _FakeController()
    statuses = []
    sequence = EventSequence(events=[
        DisruptionEvent(name="Disabled", enabled=False, methods=["drop"]),
        DisruptionEvent(
            name="Direct lag",
            methods=["lag"],
            params={"lag_delay": 1250},
            engine_preference=ENGINE_CLUMSY,
            network_layer=LAYER_LOCAL,
            duration_seconds=0.1,
        ),
    ])
    runner = EventSequenceRunner(
        sequence,
        controller,
        "192.168.1.50",
        on_status=statuses.append,
    )

    assert runner.start() is True
    assert _wait_until(lambda: not runner.running)

    assert len(controller.calls) == 1
    _ip, methods, params, kwargs = controller.calls[0]
    assert methods == ["lag"]
    assert params["_engine_preference"] == ENGINE_CLUMSY
    assert params["_network_local"] is True
    assert params["_network_layer_explicit"] is True
    assert kwargs["operation_timeout"] == 5.1
    assert controller.stop_calls == ["192.168.1.50"]
    assert any(status.kind == "skipped" for status in statuses)
    assert statuses[-1].kind == "complete"


def test_runner_does_not_stop_a_newer_generation():
    controller = _FakeController()
    sequence = EventSequence(events=[DisruptionEvent(
        methods=["lag"],
        duration_seconds=0.1,
    )])
    runner = EventSequenceRunner(sequence, controller, "192.168.1.51")

    assert runner.start() is True
    assert _wait_until(lambda: bool(controller.calls))
    controller.generation = 8
    assert _wait_until(lambda: not runner.running)

    assert controller.stop_calls == []


class _FailThenSucceedController(_FakeController):
    def disrupt_device(self, ip, methods, params, **kwargs):
        self.calls.append((ip, list(methods), dict(params), dict(kwargs)))
        if len(self.calls) == 1:
            self.last_error = "simulated direct Clumsy contention"
            return False
        self.active = True
        return True


def test_continue_failure_policy_advances_to_next_event():
    controller = _FailThenSucceedController()
    statuses = []
    sequence = EventSequence(events=[
        DisruptionEvent(
            name="May fail",
            methods=["lag"],
            failure_policy=FAILURE_CONTINUE,
        ),
        DisruptionEvent(
            name="Next",
            methods=["drop"],
            duration_seconds=0.1,
        ),
    ])
    runner = EventSequenceRunner(
        sequence,
        controller,
        "192.168.1.52",
        on_status=statuses.append,
    )

    assert runner.start() is True
    assert _wait_until(lambda: not runner.running)

    assert len(controller.calls) == 2
    assert any(
        status.kind == "error"
        and "contention" in status.detail
        for status in statuses
    )
    assert statuses[-1].kind == "complete"


def test_event_panel_adapter_restores_explicit_gui_routing(tmp_path):
    # Keep the Python wrapper alive until every QWidget created below has been
    # destroyed. Dropping the last QApplication reference first causes Qt to
    # abort the interpreter rather than raise a Python exception.
    _application = QApplication.instance() or QApplication([])
    fake_view = SimpleNamespace(
        _collect_params=lambda: {"lag_delay": 1000},
        _get_active_methods=lambda: ["lag"],
        _get_targets=lambda: [],
        _lookup_device_meta=lambda _ip: {},
        controller=None,
    )
    panel = DisruptionEventPanel(
        fake_view,
        store=EventSequenceStore(str(tmp_path)),
    )
    panel.engine_combo.setCurrentIndex(
        panel.engine_combo.findData(ENGINE_CLUMSY)
    )
    panel.layer_combo.setCurrentIndex(
        panel.layer_combo.findData(LAYER_REMOTE)
    )

    params = fake_view._collect_params()

    assert params["_engine_preference"] == ENGINE_CLUMSY
    assert params["_network_local"] is False
    assert params["_network_layer_explicit"] is True
    panel.deleteLater()
    _application.processEvents()
