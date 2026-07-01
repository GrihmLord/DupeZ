"""Tests for shipped JSON-backed diagnostic presets.

The DayZ profile is now an owned-lab diagnostic profile. These tests verify the
loader still works and that active presets do not re-expose quarantined legacy
method keys through JSON defaults.
"""

from __future__ import annotations

import pytest

from app.config.game_profiles import (
    PresetNotFoundError,
    get_disruption_defaults,
    get_disruption_preset,
    list_disruption_presets,
)


SHIPPED_PRESETS = ("pc_local", "ps5_hotspot", "xbox_hotspot")
FORWARD_LAYER_PRESETS = ("ps5_hotspot", "xbox_hotspot")
PUBLIC_METHODS = {
    "drop",
    "lag",
    "throttle",
    "duplicate",
    "ood",
    "corrupt",
    "rst",
    "disconnect",
    "bandwidth",
    "gilbert_elliott",
    "pareto_jitter",
    "correlated_drop",
    "token_bucket",
}
QUARANTINED_METHODS = {
    "godmode",
    "pulse",
    "tick_sync",
    "stealth_drop",
    "stealth_lag",
}
QUARANTINED_PARAM_PREFIXES = ("godmode_", "pulse_", "tick_sync_", "stealth_")


def test_list_presets_contains_shipped_presets():
    presets = list_disruption_presets("dayz")
    for name in SHIPPED_PRESETS:
        assert name in presets, f"{name} missing from disruption_presets"


def test_unknown_preset_raises():
    with pytest.raises(PresetNotFoundError):
        get_disruption_preset("dayz", "nonexistent_preset")


def test_preset_merges_over_defaults():
    defaults = get_disruption_defaults("dayz")
    preset = get_disruption_preset("dayz", "ps5_hotspot")
    for key in ("throttle_chance_pct", "bandwidth_queue"):
        if key in defaults:
            assert key in preset, f"{key} should be inherited from defaults"
    assert preset.get("_network_local") is False


@pytest.mark.parametrize("preset_name", SHIPPED_PRESETS)
def test_shipped_presets_only_use_public_methods(preset_name):
    preset = get_disruption_preset("dayz", preset_name)
    methods = set(preset.get("methods", []))
    assert methods
    assert methods <= PUBLIC_METHODS
    assert methods.isdisjoint(QUARANTINED_METHODS)


@pytest.mark.parametrize("preset_name", SHIPPED_PRESETS)
def test_shipped_presets_do_not_carry_quarantined_params(preset_name):
    preset = get_disruption_preset("dayz", preset_name)
    bad = [
        key for key in preset
        if any(key.startswith(prefix) for prefix in QUARANTINED_PARAM_PREFIXES)
    ]
    assert bad == []


def test_defaults_do_not_carry_quarantined_method_params():
    defaults = get_disruption_defaults("dayz")
    bad = [
        key for key in defaults
        if any(key.startswith(prefix) for prefix in QUARANTINED_PARAM_PREFIXES)
    ]
    assert bad == []


@pytest.mark.parametrize("preset_name", FORWARD_LAYER_PRESETS)
def test_forward_presets_force_forward_layer(preset_name):
    preset = get_disruption_preset("dayz", preset_name)
    assert preset.get("_network_local") is False


def test_pc_local_preset_forces_local_layer():
    preset = get_disruption_preset("dayz", "pc_local")
    assert preset.get("_network_local") is True
