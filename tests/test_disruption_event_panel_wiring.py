"""Focused non-Qt wiring tests for DisruptionEventPanel helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.core.disruption_events import ENGINE_AUTO, ENGINE_CLUMSY
from app.gui.panels.disruption_event_panel import DisruptionEventPanel


class _CheckBox:
    def __init__(self, checked=False):
        self.checked = checked
        self.enabled = True
        self.blocked = []

    def blockSignals(self, value):
        self.blocked.append(bool(value))

    def setChecked(self, value):
        self.checked = bool(value)

    def setEnabled(self, value):
        self.enabled = bool(value)


class _Widget:
    def __init__(self):
        self.enabled = True

    def setEnabled(self, value):
        self.enabled = bool(value)


class _Signal:
    def __init__(self):
        self.connections = []

    def connect(self, callback):
        self.connections.append(callback)


def test_explicit_clumsy_forces_and_locks_bidirectional_controls():
    inbound = _CheckBox(False)
    outbound = _CheckBox(True)
    panel = SimpleNamespace(
        engine_preference=ENGINE_CLUMSY,
        _clumsy_view=SimpleNamespace(
            dir_inbound=inbound,
            dir_outbound=outbound,
        ),
    )

    DisruptionEventPanel._enforce_clumsy_direction(panel)

    assert inbound.checked is True
    assert outbound.checked is True
    assert inbound.enabled is False
    assert outbound.enabled is False
    assert inbound.blocked == [True, False]
    assert outbound.blocked == [True, False]


def test_auto_reenables_direction_controls_without_rewriting_them():
    inbound = _CheckBox(True)
    outbound = _CheckBox(False)
    panel = SimpleNamespace(
        engine_preference=ENGINE_AUTO,
        _clumsy_view=SimpleNamespace(
            dir_inbound=inbound,
            dir_outbound=outbound,
        ),
    )

    DisruptionEventPanel._enforce_clumsy_direction(panel)

    assert inbound.checked is True
    assert outbound.checked is False
    assert inbound.enabled is True
    assert outbound.enabled is True
    assert inbound.blocked == []
    assert outbound.blocked == []


def test_active_queue_disables_competing_start_paths_but_not_stop_paths():
    controlled_widgets = [_Widget() for _ in range(10)]
    manual_disrupt = _Widget()
    timed_disrupt = _Widget()
    macro_start = _Widget()
    manual_stop = _Widget()
    panel = SimpleNamespace(
        run_button=controlled_widgets[0],
        stop_button=controlled_widgets[1],
        engine_combo=controlled_widgets[2],
        layer_combo=controlled_widgets[3],
        delay_spin=controlled_widgets[4],
        duration_spin=controlled_widgets[5],
        failure_combo=controlled_widgets[6],
        add_button=controlled_widgets[7],
        remove_button=controlled_widgets[8],
        up_button=controlled_widgets[9],
        down_button=_Widget(),
        event_list=_Widget(),
        _clumsy_view=SimpleNamespace(
            btn_disrupt=manual_disrupt,
            btn_sched_once=timed_disrupt,
            btn_run_macro=macro_start,
            btn_stop=manual_stop,
        ),
    )

    DisruptionEventPanel._set_queue_running(panel, True)

    assert panel.run_button.enabled is False
    assert panel.stop_button.enabled is True
    assert manual_disrupt.enabled is False
    assert timed_disrupt.enabled is False
    assert macro_start.enabled is False
    assert manual_stop.enabled is True

    DisruptionEventPanel._set_queue_running(panel, False)
    assert panel.run_button.enabled is True
    assert panel.stop_button.enabled is False
    assert manual_disrupt.enabled is True


def test_existing_stop_buttons_are_wired_to_stop_panel_queue():
    stop_signal = _Signal()
    stop_all_signal = _Signal()
    callback = MagicMock()
    panel = SimpleNamespace(
        stop_runner=callback,
        _clumsy_view=SimpleNamespace(
            btn_stop=SimpleNamespace(clicked=stop_signal),
            btn_stop_all=SimpleNamespace(clicked=stop_all_signal),
        ),
    )

    DisruptionEventPanel._wire_emergency_controls(panel)

    assert stop_signal.connections == [callback]
    assert stop_all_signal.connections == [callback]


def test_pending_stop_keeps_competing_controls_locked():
    runner = SimpleNamespace(
        running=True,
        stop=MagicMock(),
    )
    stop_button = _Widget()
    status = SimpleNamespace(setText=MagicMock())
    set_running = MagicMock()
    panel = SimpleNamespace(
        _runner=runner,
        _set_queue_running=set_running,
        stop_button=stop_button,
        queue_status=status,
    )

    DisruptionEventPanel.stop_runner(panel)

    runner.stop.assert_called_once_with()
    assert panel._runner is runner
    set_running.assert_called_once_with(True)
    assert stop_button.enabled is False
    status.setText.assert_called_with(
        "Queue stopping… waiting for the current engine operation"
    )


def test_completed_stop_releases_runner_and_controls():
    runner = SimpleNamespace(
        running=False,
        stop=MagicMock(),
    )
    status = SimpleNamespace(setText=MagicMock())
    set_running = MagicMock()
    panel = SimpleNamespace(
        _runner=runner,
        _set_queue_running=set_running,
        stop_button=_Widget(),
        queue_status=status,
    )

    DisruptionEventPanel.stop_runner(panel)

    runner.stop.assert_called_once_with()
    assert panel._runner is None
    set_running.assert_called_once_with(False)
    status.setText.assert_called_with("Queue stopped")


def test_diagnostic_action_falls_back_to_controller_private_manager():
    show = MagicMock(return_value=True)
    status_label = SimpleNamespace(setText=MagicMock())
    manager = SimpleNamespace(show_clumsy_diagnostic_window=show)
    panel = SimpleNamespace(
        _clumsy_view=SimpleNamespace(
            _get_targets=lambda: ["192.168.1.20"],
            controller=SimpleNamespace(_disruption_manager=manager),
        ),
        queue_status=status_label,
    )

    DisruptionEventPanel.show_diagnostic_window(panel)

    show.assert_called_once_with("192.168.1.20")
    status_label.setText.assert_called_with(
        "Clumsy diagnostic window restored"
    )
