"""Game profile loader — eliminates hardcoded game-specific assumptions.

Every game-specific constant (ports, tick rates, packet sizes, timing
defaults) lives in a JSON profile that can be updated without code changes.
Auto-calibration overrides these defaults with live traffic data when enabled.
"""

import json
import os
from typing import Any, Dict

from app.logs.logger import log_info, log_error

_PROFILES_DIR = os.path.dirname(os.path.abspath(__file__))

__all__ = [
    "load_profile",
    "get",
    "get_ports",
    "get_default_port",
    "get_disruption_defaults",
    "get_disruption_preset",
    "list_disruption_presets",
    "get_platform_config",
    "get_classification_config",
    "get_tick_model",
    "reload_profile",
]

class PresetNotFoundError(KeyError):
    """Raised when a named disruption preset is not defined in the game profile."""
_cache: Dict[str, Dict] = {}


def load_profile(game: str = "dayz") -> Dict[str, Any]:
    """Load a game profile from JSON.  Cached after first load."""
    if game in _cache:
        return _cache[game]

    path = os.path.join(_PROFILES_DIR, f"{game}.json")
    if not os.path.isfile(path):
        log_error(f"GameProfile: {game}.json not found at {path}")
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            profile = json.load(f)
        _cache[game] = profile
        log_info(f"GameProfile: loaded {game} profile "
                 f"({len(profile)} top-level keys)")
        return profile
    except Exception as e:
        log_error(f"GameProfile: failed to load {game}: {e}")
        return {}


def get(game: str, *keys: str, default: Any = None) -> Any:
    """Nested key lookup.  get("dayz", "network", "default_port") → 2302."""
    profile = load_profile(game)
    node = profile
    for key in keys:
        if isinstance(node, dict):
            node = node.get(key)
        else:
            return default
        if node is None:
            return default
    return node


def get_ports(game: str = "dayz") -> list:
    """Return all known game ports for this profile."""
    return get(game, "network", "all_known_ports", default=[2302])


def get_default_port(game: str = "dayz") -> int:
    """Return the primary game port."""
    return get(game, "network", "default_port", default=2302)


def get_disruption_defaults(game: str = "dayz") -> Dict[str, Any]:
    """Return the disruption parameter defaults for the game."""
    return dict(get(game, "disruption_defaults", default={}))


def list_disruption_presets(game: str = "dayz") -> list:
    """Return the names of all disruption presets defined in the profile.

    Returns an empty list if no ``disruption_presets`` section exists.
    """
    presets = get(game, "disruption_presets", default={})
    return list(presets.keys()) if isinstance(presets, dict) else []


def get_disruption_preset(game: str, preset: str) -> Dict[str, Any]:
    """Return a named disruption preset merged over ``disruption_defaults``.

    The merge order is::

        disruption_defaults  <  disruption_presets.<preset>

    so preset values override defaults but inherit anything the preset
    doesn't specify.

    Raises:
        PresetNotFoundError: the preset is not defined for this game.
    """
    defaults = get_disruption_defaults(game)
    presets = get(game, "disruption_presets", default={})
    if not isinstance(presets, dict) or preset not in presets:
        available = list(presets.keys()) if isinstance(presets, dict) else []
        raise PresetNotFoundError(
            f"preset {preset!r} not found in {game} profile "
            f"(available: {available})"
        )
    merged = dict(defaults)
    merged.update(presets[preset])
    return merged


def get_platform_config(game: str, platform: str) -> Dict[str, Any]:
    """Return platform-specific config (ps5, xbox_series, pc, etc.)."""
    return dict(get(game, "platform_support", platform, default={}))


def get_classification_config(game: str = "dayz") -> Dict[str, Any]:
    """Return packet classification config."""
    return dict(get(game, "packet_classification", default={}))


def get_tick_model(game: str = "dayz") -> Dict[str, Any]:
    """Return tick model config."""
    return dict(get(game, "tick_model", default={}))


def reload_profile(game: str = "dayz") -> Dict[str, Any]:
    """Force reload a profile (after user edits JSON)."""
    _cache.pop(game, None)
    return load_profile(game)
