"""Pure validation for the opt-in, single-action global shortcuts.

No keyboard hooks are installed here. Accepted definitions are single chords,
not key sequences, schedules, or macros; registration can still be refused by
the operating system or another application.
"""

from __future__ import annotations

import re
from typing import Any

__all__ = ["validate_hotkey_settings"]

_MODIFIERS = ("ctrl", "alt", "shift", "win")
_DEFAULTS = {
    "start": "ctrl+alt+f8",
    "stop": "ctrl+alt+f9",
    "panic": "ctrl+alt+x",
}

# Dashboard menu shortcuts and the separately registered tray shortcut. The
# local panic action is suspended only when its matching global action is live.
_RESERVED = frozenset({
    "ctrl+s", "ctrl+e", "ctrl+shift+e", "ctrl+q", "ctrl+,", "ctrl+d",
    "ctrl+shift+p", "ctrl+alt+a", "ctrl+alt+shift+a", "ctrl+shift+c",
    "ctrl+f2", "ctrl+alt+x", "ctrl+1", "ctrl+2", "ctrl+3", "ctrl+4",
    "ctrl+shift+d", "f1", "f2",
})


def _normalize_chord(value: Any, action: str) -> str:
    label = {"start": "Start", "stop": "Stop All", "panic": "Panic Stop"}[action]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} hotkey must be a non-empty single chord.")
    if len(value) > 64 or any(char in value for char in "\r\n\t,;"):
        raise ValueError(f"{label} hotkey must be one chord, not a key sequence.")
    tokens = [part.strip().lower() for part in value.strip().split("+")]
    modifiers, key = tokens[:-1], tokens[-1]
    if (
        not modifiers
        or any(modifier not in _MODIFIERS for modifier in modifiers)
        or len(set(modifiers)) != len(modifiers)
        or not set(modifiers).intersection({"ctrl", "alt", "win"})
    ):
        raise ValueError(
            f"{label} hotkey needs Ctrl, Alt, or Win before the key; "
            "Shift is optional and modifiers must not repeat."
        )
    if not re.fullmatch(r"[a-z0-9]|f(?:[1-9]|1[0-9]|2[0-4])", key):
        raise ValueError(f"{label} hotkey key must be A–Z, 0–9, or F1–F24.")
    if key == "f12":
        raise ValueError("F12 is reserved by Windows and cannot be a global hotkey.")
    chord = "+".join([modifier for modifier in _MODIFIERS if modifier in modifiers] + [key])
    if chord in _RESERVED and not (action == "panic" and chord == "ctrl+alt+x"):
        raise ValueError(f"{label} hotkey conflicts with an existing DupeZ shortcut: {chord}.")
    return chord


def validate_hotkey_settings(settings: Any) -> dict[str, str]:
    """Return normalized action chords, or raise ``ValueError``.

    Missing fields use safe defaults for older settings objects. Present enable
    flags must be actual booleans, not truthy strings or integers. Even disabled
    definitions are checked so enabling them later cannot reveal a hidden
    conflict. This does not mutate settings or claim successful registration.
    """
    for field in ("disruption_hotkeys_enabled", "disruption_start_hotkey_enabled"):
        if type(getattr(settings, field, False)) is not bool:
            raise ValueError(f"{field} must be a boolean.")
    chords = {
        action: _normalize_chord(
            getattr(settings, f"disruption_{action}_hotkey", default), action,
        )
        for action, default in _DEFAULTS.items()
    }
    if len(set(chords.values())) != len(chords):
        raise ValueError("Start, Stop All, and Panic Stop hotkeys must use different chords.")
    return chords
