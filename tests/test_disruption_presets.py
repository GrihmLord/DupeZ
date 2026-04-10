"""
Tests for JSON-backed disruption presets.

Covers the game profile preset loader (``get_disruption_preset``) and
asserts correctness of the values shipped in ``dayz.json``:

  1. Presets exist and load cleanly.
  2. Preset values override ``disruption_defaults`` (merge order).
  3. Any shipped preset using ``pulse`` defeats the 32-packet ack
     redundancy ceiling so bursts can actually cause state loss.
  4. Any shipped preset's burst/(burst+rest) ratio stays below the
     DayZ 1.27+ freeze-detection threshold (~15%).
  5. FORWARD-layer presets default to ``inbound`` direction — blocking
     outbound risks PS5/Xbox NAT teardown.
  6. PC-local preset forces ``_network_local=True``; FORWARD-layer
     presets force it to False.
"""

from __future__ import annotations

import pytest

from app.config.game_profiles import (
    get_disruption_defaults,
    get_disruption_preset,
    list_disruption_presets,
    PresetNotFoundError,
)


# Constants pulled from dayz.json — if these move, the profile moves too
ACK_REDUNDANCY_CEILING = 32          # reliable_udp.ack_redundancy_count
FREEZE_THRESHOLD_PCT = 15.0          # anti_cheat.freeze_threshold_pct
PULSE_CAPABLE_PRESETS = ("pc_local", "ps5_hotspot", "xbox_hotspot")
FORWARD_LAYER_PRESETS = ("ps5_hotspot", "xbox_hotspot")


# ── Loader smoke tests ──────────────────────────────────────────────

def test_list_presets_contains_shipped_presets():
    presets = list_disruption_presets("dayz")
    for name in PULSE_CAPABLE_PRESETS:
        assert name in presets, f"{name} missing from disruption_presets"


def test_unknown_preset_raises():
    with pytest.raises(PresetNotFoundError):
        get_disruption_preset("dayz", "nonexistent_preset")


def test_preset_merges_over_defaults():
    defaults = get_disruption_defaults("dayz")
    preset = get_disruption_preset("dayz", "ps5_hotspot")
    # Keys only in defaults survive (merge inheritance)
    for key in ("throttle_chance_pct", "bandwidth_queue"):
        if key in defaults:
            assert key in preset, f"{key} should be inherited from defaults"
    # Keys in the preset override defaults
    assert preset.get("pulse_direction") == "inbound"
    assert preset.get("_network_local") is False


# ── Correctness: ack redundancy ceiling ──────────────────────────────

@pytest.mark.parametrize("preset_name", PULSE_CAPABLE_PRESETS)
def test_pulse_burst_exceeds_ack_redundancy_ceiling(preset_name):
    """Any preset that ships 'pulse' in methods must burst >= 32 packets.

    DayZ's reliable UDP sends each ack through a 32-packet sliding
    bitfield. Burst sizes below 32 are absorbed silently — the client
    never sees the loss. burst_ticks must exceed 32 for the drop to
    actually cause state loss.
    """
    preset = get_disruption_preset("dayz", preset_name)
    if "pulse" not in preset.get("methods", []):
        pytest.skip(f"{preset_name} does not use pulse")
    burst = preset.get("pulse_burst_ticks", 0)
    assert burst > ACK_REDUNDANCY_CEILING, (
        f"{preset_name}: pulse_burst_ticks={burst} does not exceed "
        f"ack redundancy ceiling {ACK_REDUNDANCY_CEILING} — drops "
        f"will be absorbed by the 32-packet ack bitfield"
    )


# ── Correctness: freeze threshold ────────────────────────────────────

@pytest.mark.parametrize("preset_name", PULSE_CAPABLE_PRESETS)
def test_pulse_average_loss_below_freeze_threshold(preset_name):
    """Any pulse preset must keep windowed avg loss below the freeze
    threshold or DayZ 1.27+ will freeze the player (which desyncs the
    ghost and collapses the dupe).

    avg_loss = burst_ticks / (burst_ticks + rest_ticks)
    """
    preset = get_disruption_preset("dayz", preset_name)
    if "pulse" not in preset.get("methods", []):
        pytest.skip(f"{preset_name} does not use pulse")
    burst = preset.get("pulse_burst_ticks", 0)
    rest = preset.get("pulse_rest_ticks", 1)
    total = burst + rest
    assert total > 0, f"{preset_name}: invalid burst+rest total"
    avg_loss_pct = 100.0 * burst / total
    assert avg_loss_pct < FREEZE_THRESHOLD_PCT, (
        f"{preset_name}: avg loss {avg_loss_pct:.1f}% >= freeze "
        f"threshold {FREEZE_THRESHOLD_PCT}% — will trigger DayZ "
        f"player-freeze system"
    )


# ── Correctness: FORWARD-layer inbound-only default ──────────────────

@pytest.mark.parametrize("preset_name", FORWARD_LAYER_PRESETS)
def test_forward_layer_presets_default_inbound(preset_name):
    """FORWARD-layer (console) presets must default to inbound-only.

    Blocking outbound on a PS5 means the PS5's game socket goes silent,
    and the console's NAT keepalive fails in ~3-5s → session teardown.
    Inbound-only preserves the outbound NAT heartbeat.
    """
    preset = get_disruption_preset("dayz", preset_name)
    for direction_key in ("direction", "pulse_direction",
                          "tick_sync_direction", "stealth_drop_direction"):
        if direction_key in preset:
            assert preset[direction_key] == "inbound", (
                f"{preset_name}: {direction_key}="
                f"{preset[direction_key]!r} should be 'inbound'"
            )


# ── Correctness: layer lock ──────────────────────────────────────────

def test_pc_local_preset_forces_local_layer():
    preset = get_disruption_preset("dayz", "pc_local")
    assert preset.get("_network_local") is True, (
        "pc_local preset must force _network_local=True so the engine "
        "opens the NETWORK layer, not NETWORK_FORWARD"
    )


@pytest.mark.parametrize("preset_name", FORWARD_LAYER_PRESETS)
def test_forward_presets_force_forward_layer(preset_name):
    preset = get_disruption_preset("dayz", preset_name)
    assert preset.get("_network_local") is False, (
        f"{preset_name} must force _network_local=False so the engine "
        f"opens the NETWORK_FORWARD layer for ICS/hotspot traffic"
    )


# ── Correctness: confidence tolerance for hotspot jitter ─────────────

@pytest.mark.parametrize("preset_name", FORWARD_LAYER_PRESETS)
def test_forward_presets_loose_confidence(preset_name):
    """Hotspot double-hop adds 4-8ms jitter that crushes estimator
    confidence. FORWARD-layer presets must lower ts_min_confidence and
    pulse_min_confidence or the learning phase never completes."""
    preset = get_disruption_preset("dayz", preset_name)
    for key in ("ts_min_confidence", "pulse_min_confidence"):
        if key in preset:
            assert preset[key] <= 0.25, (
                f"{preset_name}: {key}={preset[key]} too high for "
                f"hotspot jitter; estimator won't lock"
            )


# ── Defaults carry per-module direction overrides ───────────────────

def test_disruption_defaults_carry_module_direction_overrides():
    """disruption_defaults must define per-module direction overrides
    so tick_sync/pulse/stealth_drop default to inbound even when no
    preset is selected."""
    defaults = get_disruption_defaults("dayz")
    for key in ("tick_sync_direction", "pulse_direction",
                "stealth_drop_direction"):
        assert defaults.get(key) == "inbound", (
            f"disruption_defaults.{key} should be 'inbound' so "
            f"existing users benefit from the safer default without "
            f"having to select a preset"
        )
