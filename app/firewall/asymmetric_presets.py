#!/usr/bin/env python3
"""Directional diagnostic presets for authorized lab traffic.

This module intentionally exposes only public, bounded network-condition
methods. Older asymmetric presets used legacy timing keys that are now
compatibility-only internals; keeping them out of this registry prevents GUI,
advisor, and scripting surfaces from rediscovering them.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Dict, List, Optional

__all__ = [
    "AsymmetricPreset",
    "INBOUND_JITTER",
    "OUTBOUND_LOSS",
    "BIDIRECTIONAL_DEGRADE",
    "BURSTY_LOSS",
    "HEAVY_TAIL_JITTER",
    "TOKEN_BUCKET_SHAPE",
    "CORRELATED_LOSS",
    "get_preset",
    "list_presets",
    "get_preset_names",
    "AsymmetricConfigBuilder",
]

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


@dataclass(frozen=True)
class AsymmetricPreset:
    """Named directional diagnostic configuration."""

    name: str
    description: str
    methods: List[str]
    params: Dict
    category: str = "general"
    dayz_optimized: bool = False
    effectiveness: float = 0.0
    detectability: float = 0.0

    def to_engine_config(self) -> Dict:
        """Return an engine config with copied methods and params."""
        return {"methods": list(self.methods), "params": deepcopy(self.params)}


INBOUND_JITTER = AsymmetricPreset(
    name="Inbound Jitter Diagnostic",
    description="Adds bounded inbound latency for private-server reachability testing.",
    methods=["lag"],
    params={"lag_delay": 250, "lag_direction": "inbound", "direction": "inbound"},
    category="diagnostic",
    dayz_optimized=True,
    effectiveness=0.55,
    detectability=0.0,
)

OUTBOUND_LOSS = AsymmetricPreset(
    name="Outbound Loss Diagnostic",
    description="Adds mild outbound loss to reproduce client uplink instability.",
    methods=["drop"],
    params={"drop_chance": 2, "drop_direction": "outbound", "direction": "outbound"},
    category="diagnostic",
    dayz_optimized=True,
    effectiveness=0.45,
    detectability=0.0,
)

BIDIRECTIONAL_DEGRADE = AsymmetricPreset(
    name="Bidirectional Degrade",
    description="Combines mild loss and latency for controlled poor-network testing.",
    methods=["drop", "lag"],
    params={
        "drop_chance": 2,
        "lag_delay": 250,
        "direction": "both",
    },
    category="diagnostic",
    dayz_optimized=True,
    effectiveness=0.60,
    detectability=0.0,
)

BURSTY_LOSS = AsymmetricPreset(
    name="Bursty Loss",
    description="Gilbert-Elliott burst-loss model for realistic lab impairment.",
    methods=["gilbert_elliott"],
    params={
        "ge_p_good_to_bad": 0.05,
        "ge_p_bad_to_good": 0.30,
        "ge_p_loss_good": 0.0,
        "ge_p_loss_bad": 1.0,
        "direction": "inbound",
    },
    category="statistical",
    dayz_optimized=True,
    effectiveness=0.60,
    detectability=0.0,
)

HEAVY_TAIL_JITTER = AsymmetricPreset(
    name="Heavy-Tail Jitter",
    description="Pareto jitter model for reproducing occasional latency spikes.",
    methods=["pareto_jitter"],
    params={
        "pareto_base_ms": 50,
        "pareto_jitter_ms": 200,
        "pareto_alpha": 1.5,
        "pareto_correlation": 0.25,
        "direction": "inbound",
    },
    category="statistical",
    dayz_optimized=True,
    effectiveness=0.55,
    detectability=0.0,
)

TOKEN_BUCKET_SHAPE = AsymmetricPreset(
    name="Token Bucket Shape",
    description="Token-bucket rate limiting for bandwidth-pressure reproduction.",
    methods=["token_bucket"],
    params={
        "tb_rate_bytes_sec": 5120,
        "tb_bucket_capacity": 8192,
        "direction": "inbound",
    },
    category="statistical",
    dayz_optimized=True,
    effectiveness=0.50,
    detectability=0.0,
)

CORRELATED_LOSS = AsymmetricPreset(
    name="Correlated Loss",
    description="Correlated low-rate loss for repeatable private-lab regression tests.",
    methods=["correlated_drop"],
    params={
        "corr_drop_chance": 5,
        "corr_correlation": 0.4,
        "direction": "both",
    },
    category="statistical",
    dayz_optimized=True,
    effectiveness=0.50,
    detectability=0.0,
)


ALL_PRESETS: Dict[str, AsymmetricPreset] = {
    "inbound_jitter": INBOUND_JITTER,
    "outbound_loss": OUTBOUND_LOSS,
    "bidirectional_degrade": BIDIRECTIONAL_DEGRADE,
    "bursty_loss": BURSTY_LOSS,
    "heavy_tail_jitter": HEAVY_TAIL_JITTER,
    "token_bucket_shape": TOKEN_BUCKET_SHAPE,
    "correlated_loss": CORRELATED_LOSS,
}


def _validate_public_methods(methods: List[str]) -> List[str]:
    return [method for method in methods if method in PUBLIC_METHODS]


def get_preset(name: str) -> Optional[AsymmetricPreset]:
    """Look up a public diagnostic preset by name."""
    return ALL_PRESETS.get(name.lower())


def list_presets(category: Optional[str] = None) -> List[AsymmetricPreset]:
    """Return public diagnostic presets, optionally filtered by category."""
    presets = list(ALL_PRESETS.values())
    if category:
        presets = [p for p in presets if p.category == category]
    return sorted(presets, key=lambda p: (-p.effectiveness, p.name))


def get_preset_names() -> List[str]:
    """Return all public preset registry keys."""
    return sorted(ALL_PRESETS.keys())


class AsymmetricConfigBuilder:
    """Fluent builder for public directional diagnostic configurations."""

    def __init__(self) -> None:
        self.methods: List[str] = []
        self.params: Dict = {}

    def from_preset(self, preset_name: str) -> "AsymmetricConfigBuilder":
        preset = get_preset(preset_name)
        if not preset:
            raise ValueError(f"Unknown public diagnostic preset: {preset_name}")
        self.methods = _validate_public_methods(list(preset.methods))
        self.params = deepcopy(preset.params)
        return self

    def add_method(
        self,
        method: str,
        direction: str = "both",
        **params,
    ) -> "AsymmetricConfigBuilder":
        if method not in PUBLIC_METHODS:
            raise ValueError(f"Method is not public-selectable: {method}")
        if method not in self.methods:
            self.methods.append(method)
        self.params[f"{method}_direction"] = direction
        self.params.update(params)
        return self

    def add_inbound(self, method: str, **params) -> "AsymmetricConfigBuilder":
        return self.add_method(method, "inbound", **params)

    def add_outbound(self, method: str, **params) -> "AsymmetricConfigBuilder":
        return self.add_method(method, "outbound", **params)

    def add_both(self, method: str, **params) -> "AsymmetricConfigBuilder":
        return self.add_method(method, "both", **params)

    def set_direction(self, method: str, direction: str) -> "AsymmetricConfigBuilder":
        if method not in PUBLIC_METHODS:
            raise ValueError(f"Method is not public-selectable: {method}")
        self.params[f"{method}_direction"] = direction
        return self

    def set_param(self, key: str, value) -> "AsymmetricConfigBuilder":
        if key.startswith(("godmode_", "pulse_", "tick_sync_", "stealth_")):
            raise ValueError(f"Parameter is not public-selectable: {key}")
        self.params[key] = value
        return self

    def build(self) -> Dict:
        methods = _validate_public_methods(self.methods)
        if not methods:
            raise ValueError("At least one public diagnostic method is required")
        return {"methods": methods, "params": deepcopy(self.params)}
