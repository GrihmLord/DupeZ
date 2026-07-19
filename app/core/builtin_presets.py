"""Backend-owned built-in preset definitions.

Preset data is consumed by both the GUI and headless orchestration. Keeping it
in ``app.core`` prevents backend services from importing the large Qt view
module merely to resolve a preset.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

__all__ = [
    "AUTOMATIC_CONNECTION_TEST",
    "BUILTIN_PRESETS",
    "get_builtin_preset",
]


AUTOMATIC_CONNECTION_TEST = "Automatic Connection Test"


BUILTIN_PRESETS: Dict[str, Dict[str, Any]] = {
    AUTOMATIC_CONNECTION_TEST: {
        "description": (
            "One click: delay traffic long enough for delayed packets to "
            "mature, apply a five-second Red Disconnect, then release the "
            "connection automatically."
        ),
        # This preset is executed by the workflow factory.  It deliberately
        # has no simultaneous module list: each generated stage is pure.
        "methods": [],
        "params": {
            "lag_delay": 2500,
            # Keep the one-click recipe identical to standalone Clumsy.
            # Native-only echo/keepalive behavior must be explicitly selected
            # by an advanced preset, never inferred from the delay value.
            "lag_passthrough": False,
            "lag_preserve_connection": False,
            "direction": "both",
        },
        "workflow": {
            "factory": "automatic_connection_test",
            "lag_mature_window_ms": 1000,
            "max_lag_delay_ms": 5000,
            "disconnect_duration_ms": 5000,
            "global_timeout_s": 20.0,
        },
    },
    "Red Disconnect": {
        "description": (
            "Pure stateful disconnect - 100% cut with optional arm delay "
            "and duration"
        ),
        "methods": ["disconnect"],
        "params": {
            "direction": "both",
            "disconnect_chance": 100,
            "disconnect_arm_delay_ms": 0,
            "disconnect_duration_ms": 0,
        },
    },
    "Lag": {
        "description": (
            "Pure sustained packet delay - tune the delay slider after "
            "selecting (Light ~800ms, Max ~5000ms)"
        ),
        "methods": ["lag"],
        "params": {
            "lag_delay": 2500,
            "lag_passthrough": False,
            "lag_preserve_connection": False,
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
    return deepcopy(preset)
