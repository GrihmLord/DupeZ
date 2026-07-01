"""Backend-owned built-in preset definitions.

Preset data is consumed by both the GUI and headless orchestration. Keeping it
in ``app.core`` prevents backend services from importing the large Qt view
module merely to resolve a preset.
"""

from __future__ import annotations

from typing import Any, Dict

__all__ = ["BUILTIN_PRESETS", "get_builtin_preset"]


BUILTIN_PRESETS: Dict[str, Dict[str, Any]] = {
    "Red Disconnect": {
        "description": (
            "Full isolation diagnostic - 100% drop, 3s lag, zero bandwidth, "
            "throttle, and stateful timed disconnect"
        ),
        "methods": ["lag", "drop", "bandwidth", "throttle", "disconnect"],
        "params": {
            "lag_delay": 3000,
            "drop_chance": 100,
            "bandwidth_limit": 0,
            "bandwidth_queue": 0,
            "throttle_chance": 100,
            "throttle_frame": 600,
            "throttle_drop": True,
            "direction": "both",
            "disconnect_chance": 100,
            "disconnect_arm_delay_ms": 0,
            "disconnect_duration_ms": 0,
        },
    },
    "Lag": {
        "description": (
            "Heavy sustained lag + drop - tune sliders after selecting "
            "(Light ~800/60, Max ~5000/100)"
        ),
        "methods": ["lag", "drop", "bandwidth", "throttle"],
        "params": {
            "lag_delay": 2500,
            "drop_chance": 90,
            "bandwidth_limit": 1,
            "bandwidth_queue": 0,
            "throttle_chance": 80,
            "throttle_frame": 400,
            "throttle_drop": True,
            "direction": "both",
        },
    },
    "Custom": {
        "description": "Set your own parameters below",
        "methods": [],
        "params": {},
    },
}


def get_builtin_preset(name: str) -> Dict[str, Any]:
    """Return a defensive copy of a built-in preset, or an empty mapping."""
    preset = BUILTIN_PRESETS.get(name)
    if preset is None:
        return {}
    return {
        "description": preset.get("description", ""),
        "methods": list(preset.get("methods", [])),
        "params": dict(preset.get("params", {})),
    }
