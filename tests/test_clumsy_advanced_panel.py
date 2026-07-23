"""Qt wiring coverage for the full Clumsy advanced settings panel."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PyQt6 import sip
from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtWidgets import QApplication, QCheckBox, QDoubleSpinBox

from app.gui.panels.clumsy_advanced_panel import ClumsyAdvancedPanel


class MemorySettings:
    def __init__(self):
        self.values = {}

    def value(self, key, default=None):
        return self.values.get(key, default)

    def setValue(self, key, value):
        self.values[key] = value

    def sync(self):
        return None


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _view():
    inbound = QCheckBox()
    outbound = QCheckBox()
    outbound.setChecked(True)
    manager = SimpleNamespace(hotkey_trigger=MagicMock(return_value=True))
    controller = SimpleNamespace(
        disruption_manager=manager,
        _disruption_manager=manager,
    )
    view = SimpleNamespace(
        dir_inbound=inbound,
        dir_outbound=outbound,
        controller=controller,
        _collect_params=lambda: {"lag_delay": 170},
        _get_targets=lambda: ["192.168.137.2"],
    )
    return view, manager


def _flush_deferred_deletes(qapp) -> None:
    QCoreApplication.sendPostedEvents(
        None,
        QEvent.Type.DeferredDelete,
    )
    qapp.processEvents()


def test_panel_defaults_to_true_and_both_directions(qapp):
    view, _manager = _view()
    panel = ClumsyAdvancedPanel(view, settings=MemorySettings())

    assert panel.filter_predicate.text() == "true"
    assert view.dir_inbound.isChecked() is True
    assert view.dir_outbound.isChecked() is True

    params = panel.augment_params({"lag_delay": 170})
    assert params["_clumsy_filter_predicate"] == "true"
    assert params["lag_direction"] == "both"
    assert params["tamper_direction"] == "both"
    assert params["corrupt_direction"] == "both"
    assert params["bandwidth_size"] == "kb"
    assert params["_clumsy_trigger_mode"] == "toggle"

    panel.deleteLater()
    _flush_deferred_deletes(qapp)


def test_panel_wraps_manual_collect_params_and_persists_overrides(qapp):
    view, _manager = _view()
    settings = MemorySettings()
    panel = ClumsyAdvancedPanel(view, settings=settings)

    panel.filter_predicate.setText("udp and udp.DstPort == 3074")
    panel.filter_name.setText("Console Filter")
    panel.function_preset_name.setText("Freeze")
    panel.bandwidth_unit.setCurrentIndex(
        panel.bandwidth_unit.findData("mb")
    )
    lag_in, lag_out = panel._direction_checks["lag"]
    lag_in.setChecked(True)
    lag_out.setChecked(False)
    panel._persist_settings()

    params = view._collect_params()
    assert params["lag_delay"] == 170
    assert params["_clumsy_filter_predicate"] == (
        "udp and udp.DstPort == 3074"
    )
    assert params["_clumsy_filter_name"] == "Console Filter"
    assert params["_clumsy_function_preset_name"] == "Freeze"
    assert params["bandwidth_size"] == "mb"
    assert params["lag_direction"] == "inbound"
    assert settings.values["clumsy_advanced/filter_predicate"] == (
        "udp and udp.DstPort == 3074"
    )

    panel.deleteLater()
    _flush_deferred_deletes(qapp)


def test_param_adapter_restores_original_collector_on_qt_destroy(qapp):
    view, _manager = _view()
    original = view._collect_params
    panel = ClumsyAdvancedPanel(view, settings=MemorySettings())

    assert view._collect_params is not original
    assert view._collect_params()["_clumsy_filter_predicate"] == "true"

    panel.deleteLater()
    _flush_deferred_deletes(qapp)

    # Qt guarantees C++ destruction and signal disconnection here. PyQt may
    # retain a dead Python wrapper until a later collection cycle, so wrapper
    # identity is not the lifecycle contract we need to enforce.
    assert sip.isdeleted(panel) is True
    assert view._collect_params is original
    assert not hasattr(view, "_clumsy_advanced_param_adapter")


def test_timer_mode_keeps_event_duration_coherent(qapp):
    view, _manager = _view()
    panel = ClumsyAdvancedPanel(view, settings=MemorySettings())
    event_panel = SimpleNamespace(duration_spin=QDoubleSpinBox())
    event_panel.duration_spin.setRange(0.1, 3600.0)
    panel.bind_event_panel(event_panel)

    panel.trigger_mode.setCurrentIndex(
        panel.trigger_mode.findData("timer")
    )
    panel.timer_seconds.setValue(12)

    assert panel.timer_seconds.isEnabled() is True
    assert event_panel.duration_spin.value() == 12.0
    assert panel.augment_params({})["_clumsy_timer_seconds"] == 12

    panel.deleteLater()
    event_panel.duration_spin.deleteLater()
    _flush_deferred_deletes(qapp)


def test_live_rst_button_uses_authenticated_manager_action(qapp):
    view, manager = _view()
    panel = ClumsyAdvancedPanel(view, settings=MemorySettings())

    panel._trigger_rst_next_packet()

    manager.hotkey_trigger.assert_called_once_with(
        "clumsy_rst_next_packet",
        {"target_ip": "192.168.137.2"},
    )
    assert "one-shot armed" in panel.status_label.text().lower()

    panel.deleteLater()
    _flush_deferred_deletes(qapp)
