"""Coverage for dynamic exact-Clumsy slider and route policy."""

from __future__ import annotations

from types import SimpleNamespace

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


def test_explicit_clumsy_applies_exact_limits_and_native_restores_values():
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

    assert (lag.minimum(), lag.maximum(), lag.value()) == (0, 120_000, 20_000)
    assert duplicate.maximum() == 50
    assert duplicate.value() == 50
    assert bandwidth.maximum() == 1_000
    assert bandwidth.value() == 500
    assert disconnect_chance.minimum() == 0
    assert disconnect_chance.maximum() == 100
    assert disconnect_chance.value() == 40


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
