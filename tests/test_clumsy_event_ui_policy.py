"""Coverage for dynamic exact-Clumsy slider and route policy."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.clumsy_controls import CLUMSY_NUMERIC_LIMITS
from app.core.disruption_events import ENGINE_CLUMSY, ENGINE_NATIVE
from app.gui.panels import clumsy_event_ui_policy as policy


class Slider:
    def __init__(self, minimum, maximum, value):
        self._minimum = minimum
        self._maximum = maximum
        self._value = value

    def minimum(self):
        return self._minimum

    def maximum(self):
        return self._maximum

    def value(self):
        return self._value

    def setRange(self, minimum, maximum):
        self._minimum = minimum
        self._maximum = maximum
        self._value = max(minimum, min(maximum, self._value))

    def setValue(self, value):
        self._value = max(self._minimum, min(self._maximum, int(value)))


class Check:
    def __init__(self, checked):
        self.checked = checked
        self.enabled = True
        self.blocked = []

    def isChecked(self):
        return self.checked

    def setChecked(self, value):
        self.checked = bool(value)

    def blockSignals(self, value):
        self.blocked.append(bool(value))

    def setEnabled(self, value):
        self.enabled = bool(value)


def test_explicit_clumsy_limits_stay_valid_when_route_changes():
    lag = Slider(0, 120_000, 20_000)
    duplicate = Slider(1, 50, 50)
    bandwidth = Slider(0, 1_000, 500)
    disconnect_chance = Slider(0, 100, 40)
    view = SimpleNamespace(
        sliders={
            "lag_delay": lag,
            "duplicate_count": duplicate,
            "bandwidth_limit": bandwidth,
            "disconnect_chance": disconnect_chance,
        }
    )
    panel = SimpleNamespace(
        engine_preference=ENGINE_CLUMSY,
        _clumsy_view=view,
    )

    policy._apply_clumsy_slider_policy(panel)

    assert (lag.minimum(), lag.maximum(), lag.value()) == (0, 15_000, 15_000)
    assert duplicate.maximum() == 49
    assert bandwidth.maximum() == 99_999
    assert disconnect_chance.minimum() == 100
    assert disconnect_chance.maximum() == 100
    assert disconnect_chance.value() == 100

    panel.engine_preference = ENGINE_NATIVE
    policy._apply_clumsy_slider_policy(panel)

    assert (lag.minimum(), lag.maximum(), lag.value()) == (0, 15_000, 15_000)
    assert duplicate.maximum() == 49
    assert duplicate.value() == 49
    assert bandwidth.maximum() == 99_999
    assert bandwidth.value() == 500
    assert disconnect_chance.minimum() == 0
    assert disconnect_chance.maximum() == 100
    assert disconnect_chance.value() == 40


@pytest.mark.parametrize("engine", ["auto", ENGINE_CLUMSY, ENGINE_NATIVE])
def test_all_routes_keep_shared_standard_module_limits(engine):
    sliders = {
        key: Slider(-1, maximum + 100, minimum)
        for key, (minimum, maximum) in CLUMSY_NUMERIC_LIMITS.items()
    }
    panel = SimpleNamespace(
        engine_preference=engine,
        _clumsy_view=SimpleNamespace(sliders=sliders),
    )

    policy._apply_clumsy_slider_policy(panel)

    for key, slider in sliders.items():
        assert (slider.minimum(), slider.maximum()) == CLUMSY_NUMERIC_LIMITS[key]


def test_auto_does_not_change_legacy_disconnect_values_or_ranges():
    slider = Slider(0, 60_000, 250)
    panel = SimpleNamespace(
        engine_preference="auto",
        _clumsy_view=SimpleNamespace(
            sliders={"disconnect_duration_ms": slider},
        ),
    )

    policy._apply_clumsy_slider_policy(panel)

    assert (slider.minimum(), slider.maximum(), slider.value()) == (0, 60_000, 250)


@pytest.mark.parametrize("engine", ["auto", ENGINE_NATIVE])
def test_route_copy_explains_capability_selection_without_fallback(monkeypatch, engine):
    messages = []
    panel = SimpleNamespace(
        engine_preference=engine,
        network_layer="auto",
        route_status=SimpleNamespace(setText=messages.append),
    )
    monkeypatch.setattr(policy, "_allow_verified_per_module_directions", lambda *_: None)
    monkeypatch.setattr(policy, "_apply_clumsy_slider_policy", lambda *_: None)

    policy._route_status(panel)

    assert "extensions" in messages[0]
    assert "substitut" in messages[0]
    assert "Mixed" in messages[0]


def test_direction_policy_keeps_one_direction_and_allows_editing():
    inbound = Check(False)
    outbound = Check(False)
    panel = SimpleNamespace(
        _clumsy_view=SimpleNamespace(
            dir_inbound=inbound,
            dir_outbound=outbound,
        )
    )

    policy._allow_verified_per_module_directions(panel)

    assert inbound.checked is False
    assert outbound.checked is True
    assert inbound.enabled is True
    assert outbound.enabled is True
    assert outbound.blocked == [True, False]
