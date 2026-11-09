"""Non-operational Qt coverage for the shared Clumsy numeric contract."""

from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import sip
from PyQt6.QtWidgets import QApplication, QLabel, QWidget

from app.core.clumsy_controls import CLUMSY_NUMERIC_LIMITS
from app.gui import clumsy_control as controls
from app.gui.panels import clumsy_event_ui_policy as policy


_UNCHANGED_DEFAULTS = {
    "lag_delay": 500,
    "drop_chance": 100,
    "bandwidth_limit": 5,
    "bandwidth_queue": 0,
    "throttle_chance": 80,
    "throttle_frame": 100,
    "duplicate_chance": 50,
    "duplicate_count": 5,
    "ood_chance": 50,
    "tamper_chance": 30,
    "rst_chance": 100,
}


class _PassivePanel(QWidget):
    """Exclude unrelated optional panels, persistence, and device services."""

    available = False

    def __init__(self, *args, **kwargs):
        super().__init__()


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def view(qapp, monkeypatch):
    from app.gui.panels import lan_cut_panel

    for name in (
        "SmartModePanel", "StatsPanel", "VoicePanel", "GPCPanel", "AIPanel",
    ):
        monkeypatch.setattr(controls, name, _PassivePanel)
    monkeypatch.setattr(lan_cut_panel, "LanCutPanel", _PassivePanel)
    monkeypatch.setattr(controls, "PROFILES_AVAILABLE", False)
    # Observe the actual module widgets before a saved preset changes values.
    monkeypatch.setattr(
        controls.ClumsyControlView, "_on_preset_changed", lambda *_args: None,
    )
    panel = controls.ClumsyControlView(controller=None)
    panel.stop_background_refresh()
    try:
        yield panel
    finally:
        # Several normally reparented panels are not children in this harness.
        for name in (
            "_smart_panel", "_stats_panel", "_voice_panel", "_gpc_panel",
            "_lan_cut_panel", "_ai_panel", "_ml_group",
        ):
            child = getattr(panel, name, None)
            if child is not None and not sip.isdeleted(child):
                sip.delete(child)
        sip.delete(panel)


def test_module_definitions_share_all_numeric_bounds_and_keep_defaults():
    params = {
        item[1]: item
        for module in controls.MODULE_DEFS
        for item in module["params"]
    }
    assert set(CLUMSY_NUMERIC_LIMITS) <= params.keys()
    for key, bounds in CLUMSY_NUMERIC_LIMITS.items():
        _label, _key, minimum, maximum, default = params[key]
        assert (minimum, maximum) == bounds
        assert default == _UNCHANGED_DEFAULTS[key]


@pytest.mark.parametrize("key", sorted(CLUMSY_NUMERIC_LIMITS))
def test_actual_numeric_widgets_obey_shared_bounds(view, key):
    slider = view.sliders[key]
    minimum, maximum = CLUMSY_NUMERIC_LIMITS[key]
    assert (slider.minimum(), slider.maximum()) == (minimum, maximum)
    assert slider.value() == _UNCHANGED_DEFAULTS[key]

    slider.setValue(maximum + 1)
    assert slider.value() == maximum
    assert view.slider_labels[key].text() == str(maximum)
    slider.setValue(minimum - 1)
    assert slider.value() == minimum
    assert view.slider_labels[key].text() == str(minimum)


def test_duplicate_widget_describes_additional_packet_copies(view):
    labels = {label.text() for label in view.findChildren(QLabel)}
    assert "Extra copies" in labels
    assert "Duplicate network packets" in labels
    assert view.sliders["duplicate_count"].maximum() == 49


def test_actual_widgets_retain_contract_when_route_policy_changes(view):
    panel = SimpleNamespace(_clumsy_view=view, engine_preference="auto")
    for engine in ("auto", "clumsy", "native", "auto"):
        panel.engine_preference = engine
        policy._apply_clumsy_slider_policy(panel)
        for key, bounds in CLUMSY_NUMERIC_LIMITS.items():
            slider = view.sliders[key]
            assert (slider.minimum(), slider.maximum()) == bounds
            assert slider.value() == _UNCHANGED_DEFAULTS[key]
