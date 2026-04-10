#!/usr/bin/env python3
"""
Asymmetric Direction Engine — Phase 4 of DupeZ v5 Roadmap.

Provides preset configurations for direction-aware disruption where
inbound and outbound parameters are independently tuned. The existing
module architecture already supports per-module direction via
`{module}_direction` params — this module provides the preset library
and a builder API for constructing asymmetric configurations.

Key Insight:
  DayZ is a client-server game over UDP. On a hotspot/ICS setup,
  the target's traffic passes through your machine. The NETWORK_FORWARD
  layer gives us independent control over:
    - OUTBOUND (target → internet → server): target's inputs/actions
    - INBOUND (server → internet → gateway → target): server state updates

  By treating these independently, we can create effects impossible with
  symmetric disruption:

  God Mode:    lag inbound heavily, pass outbound → you move freely while
               the target sees a frozen world
  Ghost Mode:  drop outbound selectively, pass inbound → target can see
               the world but their inputs are lost (can't shoot, can't move)
  Desync Mode: lag inbound + duplicate outbound → target sees stale state
               while server receives conflicting duplicate inputs
  Phantom:     pulse inbound (burst/rest), normal outbound → target sees
               stuttering/teleporting world, connection stays alive

Presets:
  Each preset is a dict of params that can be passed directly to the
  NativeWinDivertEngine. The direction-aware module system handles
  routing packets to the correct modules automatically.
"""

from __future__ import annotations

from typing import Dict, List, Optional
from copy import deepcopy
from dataclasses import dataclass

__all__ = [
    "AsymmetricPreset",
    "GODMODE_STANDARD",
    "GODMODE_STEALTH",
    "GODMODE_AGGRESSIVE",
    "GHOST_MODE",
    "GHOST_SOFT",
    "DESYNC_STANDARD",
    "DESYNC_HEAVY",
    "PHANTOM_MODE",
    "PHANTOM_AGGRESSIVE",
    "BURSTY_LOSS",
    "JITTER_HELL",
    "THROTTLE_SHAPE",
    "COMBO_CHAOS",
    "COMBO_SURGICAL",
    "get_preset",
    "list_presets",
    "get_preset_names",
    "AsymmetricConfigBuilder",
]


@dataclass
class AsymmetricPreset:
    """A named asymmetric disruption configuration."""
    name: str
    description: str
    methods: List[str]
    params: Dict
    category: str = "general"       # general, stealth, aggressive, utility
    dayz_optimized: bool = False    # True if specifically tuned for DayZ
    effectiveness: float = 0.0      # 0-1 estimated effectiveness
    detectability: float = 0.5      # 0-1, lower = harder to detect

    def to_engine_config(self) -> Dict:
        """Return (methods, params) tuple for NativeWinDivertEngine."""
        return {"methods": list(self.methods), "params": deepcopy(self.params)}


# ═══════════════════════════════════════════════════════════════════════
# God Mode Variants
# ═══════════════════════════════════════════════════════════════════════

GODMODE_STANDARD = AsymmetricPreset(
    name="God Mode",
    description=(
        "Heavy inbound lag, full outbound pass. Target freezes while "
        "your actions register in real time. NAT keepalive maintains "
        "the connection."),
    methods=["godmode"],
    params={
        "godmode_lag_ms": 2000,
        "godmode_drop_inbound_pct": 0,
        "godmode_keepalive_interval_ms": 800,
    },
    category="aggressive",
    dayz_optimized=True,
    effectiveness=0.95,
    detectability=0.7,
)

GODMODE_STEALTH = AsymmetricPreset(
    name="God Mode (Stealth)",
    description=(
        "Moderate inbound lag with higher keepalive frequency. "
        "Less obvious than standard God Mode — target experiences "
        "stuttering rather than complete freeze."),
    methods=["godmode"],
    params={
        "godmode_lag_ms": 800,
        "godmode_drop_inbound_pct": 0,
        "godmode_keepalive_interval_ms": 400,
    },
    category="stealth",
    dayz_optimized=True,
    effectiveness=0.70,
    detectability=0.3,
)

GODMODE_AGGRESSIVE = AsymmetricPreset(
    name="God Mode (Aggressive)",
    description=(
        "Maximum inbound lag plus partial inbound drop. Complete "
        "freeze with some packets permanently lost. High impact "
        "but more likely to trigger DayZ's disconnect detection."),
    methods=["godmode"],
    params={
        "godmode_lag_ms": 5000,
        "godmode_drop_inbound_pct": 30,
        "godmode_keepalive_interval_ms": 1200,
    },
    category="aggressive",
    dayz_optimized=True,
    effectiveness=0.99,
    detectability=0.9,
)


# ═══════════════════════════════════════════════════════════════════════
# Ghost Mode — Target Can See But Can't Act
# ═══════════════════════════════════════════════════════════════════════

GHOST_MODE = AsymmetricPreset(
    name="Ghost Mode",
    description=(
        "Drop most outbound packets (target's inputs), pass inbound. "
        "Target sees the world updating but their actions don't register "
        "on the server — can't shoot, can't loot, can't move effectively."),
    methods=["drop"],
    params={
        "drop_chance": 90,
        "drop_direction": "outbound",
    },
    category="aggressive",
    dayz_optimized=True,
    effectiveness=0.85,
    detectability=0.6,
)

GHOST_SOFT = AsymmetricPreset(
    name="Ghost Mode (Soft)",
    description=(
        "Moderate outbound drop. Target's actions intermittently fail — "
        "shots don't register, movement stutters. Hard to distinguish "
        "from genuine packet loss."),
    methods=["drop"],
    params={
        "drop_chance": 50,
        "drop_direction": "outbound",
    },
    category="stealth",
    dayz_optimized=True,
    effectiveness=0.60,
    detectability=0.2,
)


# ═══════════════════════════════════════════════════════════════════════
# Desync Combos — Asymmetric Lag + Duplicate
# ═══════════════════════════════════════════════════════════════════════

DESYNC_STANDARD = AsymmetricPreset(
    name="Desync",
    description=(
        "Lag inbound + duplicate outbound. Target sees stale state "
        "while the server receives conflicting duplicate inputs. "
        "Causes inventory desync, position rubberbanding."),
    methods=["lag", "duplicate"],
    params={
        "lag_delay": 300,
        "lag_direction": "inbound",
        "lag_passthrough": True,
        "duplicate_count": 5,
        "duplicate_chance": 70,
        "duplicate_direction": "outbound",
    },
    category="aggressive",
    dayz_optimized=True,
    effectiveness=0.80,
    detectability=0.5,
)

DESYNC_HEAVY = AsymmetricPreset(
    name="Desync (Heavy)",
    description=(
        "Pareto jitter inbound + heavy duplicate outbound + OOD. "
        "Maximum state confusion — target receives delayed, reordered "
        "state while server sees input spam."),
    methods=["pareto_lag", "duplicate", "ood"],
    params={
        "pareto_base_ms": 100,
        "pareto_jitter_ms": 500,
        "pareto_alpha": 1.5,
        "pareto_lag_direction": "inbound",
        "duplicate_count": 10,
        "duplicate_chance": 80,
        "duplicate_direction": "outbound",
        "ood_chance": 60,
        "ood_direction": "inbound",
    },
    category="aggressive",
    dayz_optimized=True,
    effectiveness=0.90,
    detectability=0.7,
)


# ═══════════════════════════════════════════════════════════════════════
# Phantom Mode — Pulsed Disruption
# ═══════════════════════════════════════════════════════════════════════

PHANTOM_MODE = AsymmetricPreset(
    name="Phantom",
    description=(
        "Pulsed inbound disruption — 3 ticks burst, 5 ticks rest. "
        "Target sees stuttering/teleporting world. Connection stays "
        "alive during rest periods, bypassing DayZ freeze detection."),
    methods=["pulse"],
    params={
        "pulse_burst_ticks": 3,
        "pulse_rest_ticks": 5,
        "pulse_drop_chance": 95,
        "pulse_direction": "inbound",
    },
    category="stealth",
    dayz_optimized=True,
    effectiveness=0.75,
    detectability=0.25,
)

PHANTOM_AGGRESSIVE = AsymmetricPreset(
    name="Phantom (Aggressive)",
    description=(
        "Longer burst, shorter rest. More disruption but higher "
        "detection risk. 5 ticks burst, 3 ticks rest."),
    methods=["pulse"],
    params={
        "pulse_burst_ticks": 5,
        "pulse_rest_ticks": 3,
        "pulse_drop_chance": 95,
        "pulse_direction": "inbound",
    },
    category="aggressive",
    dayz_optimized=True,
    effectiveness=0.85,
    detectability=0.5,
)


# ═══════════════════════════════════════════════════════════════════════
# Statistical Model Presets
# ═══════════════════════════════════════════════════════════════════════

BURSTY_LOSS = AsymmetricPreset(
    name="Bursty Loss",
    description=(
        "Gilbert-Elliott bursty packet loss. Creates realistic "
        "loss bursts that overwhelm DayZ's ack redundancy. "
        "Indistinguishable from genuine bad WiFi."),
    methods=["ge_drop"],
    params={
        "ge_p_good_to_bad": 0.05,
        "ge_p_bad_to_good": 0.30,
        "ge_p_loss_good": 0.0,
        "ge_p_loss_bad": 1.0,
        "ge_drop_direction": "inbound",
    },
    category="stealth",
    dayz_optimized=True,
    effectiveness=0.70,
    detectability=0.1,
)

JITTER_HELL = AsymmetricPreset(
    name="Jitter Hell",
    description=(
        "Pareto heavy-tailed jitter on inbound. Most packets arrive "
        "~50ms late but occasional packets hit 500ms+. Causes "
        "rubberbanding and prediction failures."),
    methods=["pareto_lag"],
    params={
        "pareto_base_ms": 50,
        "pareto_jitter_ms": 200,
        "pareto_alpha": 1.5,
        "pareto_correlation": 0.25,
        "pareto_lag_direction": "inbound",
    },
    category="stealth",
    dayz_optimized=True,
    effectiveness=0.65,
    detectability=0.15,
)

THROTTLE_SHAPE = AsymmetricPreset(
    name="ISP Throttle",
    description=(
        "Token bucket rate limiting mimicking ISP traffic shaping. "
        "Allows burst, then starves. Looks like legitimate throttling."),
    methods=["token_bucket"],
    params={
        "tb_rate_bytes_sec": 5120,
        "tb_bucket_capacity": 8192,
        "token_bucket_direction": "inbound",
    },
    category="stealth",
    dayz_optimized=True,
    effectiveness=0.55,
    detectability=0.05,
)


# ═══════════════════════════════════════════════════════════════════════
# Combo Presets — Multi-Module Stacks
# ═══════════════════════════════════════════════════════════════════════

COMBO_CHAOS = AsymmetricPreset(
    name="Chaos",
    description=(
        "Everything at once — bursty drop + jitter + duplicate + OOD. "
        "Maximum disruption, maximum detection risk."),
    methods=["ge_drop", "pareto_lag", "duplicate", "ood"],
    params={
        "ge_p_good_to_bad": 0.10,
        "ge_p_bad_to_good": 0.20,
        "ge_p_loss_bad": 0.80,
        "pareto_base_ms": 30,
        "pareto_jitter_ms": 150,
        "pareto_alpha": 2.0,
        "duplicate_count": 3,
        "duplicate_chance": 50,
        "ood_chance": 40,
    },
    category="aggressive",
    dayz_optimized=True,
    effectiveness=0.95,
    detectability=0.9,
)

COMBO_SURGICAL = AsymmetricPreset(
    name="Surgical",
    description=(
        "Tick-synced drop on inbound + correlated drop on outbound. "
        "Precisely timed disruption that looks like natural network "
        "degradation. Minimal footprint."),
    methods=["tick_sync", "corr_drop"],
    params={
        "ts_drop_window_pct": 0.3,
        "ts_drop_chance": 80,
        "tick_sync_direction": "inbound",
        "corr_drop_chance": 15,
        "corr_correlation": 0.4,
        "corr_drop_direction": "outbound",
    },
    category="stealth",
    dayz_optimized=True,
    effectiveness=0.75,
    detectability=0.15,
)


# ═══════════════════════════════════════════════════════════════════════
# Preset Registry
# ═══════════════════════════════════════════════════════════════════════

ALL_PRESETS: Dict[str, AsymmetricPreset] = {
    # God Mode family
    "godmode":            GODMODE_STANDARD,
    "godmode_stealth":    GODMODE_STEALTH,
    "godmode_aggressive": GODMODE_AGGRESSIVE,
    # Ghost Mode family
    "ghost":              GHOST_MODE,
    "ghost_soft":         GHOST_SOFT,
    # Desync family
    "desync":             DESYNC_STANDARD,
    "desync_heavy":       DESYNC_HEAVY,
    # Phantom (pulsed) family
    "phantom":            PHANTOM_MODE,
    "phantom_aggressive": PHANTOM_AGGRESSIVE,
    # Statistical presets
    "bursty_loss":        BURSTY_LOSS,
    "jitter_hell":        JITTER_HELL,
    "isp_throttle":       THROTTLE_SHAPE,
    # Combos
    "chaos":              COMBO_CHAOS,
    "surgical":           COMBO_SURGICAL,
}


def get_preset(name: str) -> Optional[AsymmetricPreset]:
    """Look up a preset by name (case-insensitive)."""
    return ALL_PRESETS.get(name.lower())


def list_presets(category: Optional[str] = None) -> List[AsymmetricPreset]:
    """Return all presets, optionally filtered by category."""
    presets = list(ALL_PRESETS.values())
    if category:
        presets = [p for p in presets if p.category == category]
    return sorted(presets, key=lambda p: (-p.effectiveness, p.name))


def get_preset_names() -> List[str]:
    """Return all preset names."""
    return sorted(ALL_PRESETS.keys())


class AsymmetricConfigBuilder:
    """Fluent builder for constructing custom asymmetric configurations.

    Example:
        config = (AsymmetricConfigBuilder()
            .add_inbound("lag", lag_delay=500)
            .add_outbound("drop", drop_chance=30)
            .add_both("corrupt", tamper_chance=10)
            .build())
    """

    def __init__(self) -> None:
        self._methods: List[str] = []
        self._params: Dict = {}

    def add_inbound(self, method: str, **kwargs) -> "AsymmetricConfigBuilder":
        """Add a module targeting inbound packets only."""
        self._methods.append(method)
        self._params[f"{method}_direction"] = "inbound"
        self._params.update(kwargs)
        return self

    def add_outbound(self, method: str, **kwargs) -> "AsymmetricConfigBuilder":
        """Add a module targeting outbound packets only."""
        self._methods.append(method)
        self._params[f"{method}_direction"] = "outbound"
        self._params.update(kwargs)
        return self

    def add_both(self, method: str, **kwargs) -> "AsymmetricConfigBuilder":
        """Add a module targeting both directions."""
        self._methods.append(method)
        self._params[f"{method}_direction"] = "both"
        self._params.update(kwargs)
        return self

    def set_param(self, key: str, value) -> "AsymmetricConfigBuilder":
        """Set an arbitrary parameter."""
        self._params[key] = value
        return self

    def from_preset(self, preset_name: str) -> "AsymmetricConfigBuilder":
        """Start from an existing preset and customize."""
        preset = get_preset(preset_name)
        if preset:
            self._methods = list(preset.methods)
            self._params = deepcopy(preset.params)
        return self

    def build(self) -> Dict:
        """Return the final configuration dict."""
        return {
            "methods": list(self._methods),
            "params": deepcopy(self._params),
        }
