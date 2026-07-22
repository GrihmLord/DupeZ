# app/core/clumsy_controls.py — validated Clumsy 0.3.4 control contract
"""Pure validation helpers shared by GUI, event, helper, and frozen runtimes.

The user-editable filter is deliberately an *additional* predicate.  It is
never accepted as the complete WinDivert expression; the firewall adapter
always combines it with DupeZ's validated exact-target scope.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

__all__ = [
    "BANDWIDTH_KB",
    "BANDWIDTH_MB",
    "CLUMSY_NUMERIC_LIMITS",
    "CLUMSY_DIRECTION_KEYS",
    "CLUMSY_METHOD_LABELS",
    "TRIGGER_TOGGLE",
    "TRIGGER_TIMER",
    "normalize_additional_filter",
    "normalize_bandwidth_unit",
    "normalize_clumsy_label",
    "normalize_direction",
    "normalize_timer_seconds",
    "normalize_trigger_mode",
    "validate_clumsy_control_params",
]

TRIGGER_TOGGLE = "toggle"
TRIGGER_TIMER = "timer"
BANDWIDTH_KB = "kb"
BANDWIDTH_MB = "mb"

CLUMSY_METHOD_LABELS = {
    "lag": "Lag",
    "drop": "Drop",
    "disconnect": "Disconnect",
    "bandwidth": "Bandwidth Limiter",
    "throttle": "Throttle",
    "duplicate": "Duplicate",
    "ood": "Out of order",
    "corrupt": "Tamper",
    "rst": "Set TCP RST",
}

CLUMSY_DIRECTION_KEYS = {
    "lag": "lag_direction",
    "drop": "drop_direction",
    "disconnect": "disconnect_direction",
    "bandwidth": "bandwidth_direction",
    "throttle": "throttle_direction",
    "duplicate": "duplicate_direction",
    "ood": "ood_direction",
    "corrupt": "tamper_direction",
    "rst": "rst_direction",
}

# Exact limits in the bundled Kalirenegade 0.3.4 source.  DupeZ's public
# duplicate_count means *additional* copies, while Clumsy's EDIT contains the
# total number of copies, so 1..49 maps to Clumsy 2..50.
CLUMSY_NUMERIC_LIMITS = {
    "lag_delay": (0, 15_000),
    "drop_chance": (0, 100),
    "bandwidth_queue": (0, 99_999),
    "bandwidth_limit": (0, 99_999),
    "throttle_frame": (0, 1_000),
    "throttle_chance": (0, 100),
    "duplicate_count": (1, 49),
    "duplicate_chance": (0, 100),
    "ood_chance": (0, 100),
    "tamper_chance": (0, 100),
    "rst_chance": (0, 100),
}

_VALID_DIRECTIONS = frozenset({"both", "inbound", "outbound"})
_VALID_TRIGGER_MODES = frozenset({TRIGGER_TOGGLE, TRIGGER_TIMER})
_VALID_BANDWIDTH_UNITS = frozenset({BANDWIDTH_KB, BANDWIDTH_MB})

# No quotes, comments, semicolons, slashes, or line controls.  Parentheses are
# separately checked for a non-negative balanced expression so a user cannot
# close DupeZ's mandatory target-scope wrapper.
_FILTER_CHARS = re.compile(r"^[A-Za-z0-9_.<>=!&|()\s:-]+$")
_LABEL_CHARS = re.compile(r"[^A-Za-z0-9 _.-]+")


def normalize_additional_filter(value: Any) -> str:
    """Return a bounded extra WinDivert predicate, defaulting to ``true``.

    The returned expression is safe to place inside one additional pair of
    parentheses.  This is intentionally not a general WinDivert parser; it
    rejects syntax that could escape, comment out, or add records to the
    generated configuration file.
    """

    text = str(value if value is not None else "true").strip() or "true"
    if len(text) > 512:
        raise ValueError("Additional filter must be 512 characters or fewer")
    if any(character in text for character in ("\x00", "\r", "\n")):
        raise ValueError("Additional filter must be a single line")
    if not _FILTER_CHARS.fullmatch(text):
        raise ValueError(
            "Additional filter contains unsupported characters; quotes, "
            "comments, slashes, commas, and semicolons are not allowed"
        )

    depth = 0
    for character in text:
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth < 0:
                raise ValueError("Additional filter closes an outer scope")
    if depth:
        raise ValueError("Additional filter parentheses are unbalanced")
    return text


def normalize_clumsy_label(value: Any, *, default: str = "DupeZ") -> str:
    """Return a config/preset label that cannot alter INI or filter records."""

    text = str(value or default).strip()
    text = _LABEL_CHARS.sub("", text)[:48].strip(" .")
    return text or default


def normalize_direction(value: Any, *, default: str = "both") -> str:
    normalized = str(value or default).strip().lower()
    if normalized not in _VALID_DIRECTIONS:
        raise ValueError(
            "Direction must be one of: both, inbound, outbound"
        )
    return normalized


def normalize_trigger_mode(value: Any) -> str:
    normalized = str(value or TRIGGER_TOGGLE).strip().lower()
    if normalized not in _VALID_TRIGGER_MODES:
        raise ValueError("Trigger mode must be toggle or timer")
    return normalized


def normalize_timer_seconds(value: Any) -> int:
    try:
        seconds = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Clumsy timer must be an integer from 1 to 60") from exc
    if not 1 <= seconds <= 60:
        raise ValueError("Clumsy timer must be from 1 to 60 seconds")
    return seconds


def normalize_bandwidth_unit(value: Any) -> str:
    normalized = str(value or BANDWIDTH_KB).strip().lower()
    if normalized not in _VALID_BANDWIDTH_UNITS:
        raise ValueError("Bandwidth unit must be kb or mb")
    return normalized


def _bounded_integer(name: str, value: Any) -> int:
    minimum, maximum = CLUMSY_NUMERIC_LIMITS[name]
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{name} must be from {minimum} to {maximum}")
    return parsed


def validate_clumsy_control_params(
    methods: Iterable[str],
    params: dict[str, Any],
) -> tuple[str, ...]:
    """Return all advanced-control incompatibilities without mutating input."""

    method_list = tuple(dict.fromkeys(str(item) for item in methods))
    reasons: list[str] = []

    try:
        normalize_additional_filter(params.get("_clumsy_filter_predicate", "true"))
    except ValueError as exc:
        reasons.append(str(exc))

    try:
        mode = normalize_trigger_mode(params.get("_clumsy_trigger_mode"))
        if mode == TRIGGER_TIMER:
            normalize_timer_seconds(params.get("_clumsy_timer_seconds", 1))
    except ValueError as exc:
        reasons.append(str(exc))

    try:
        normalize_bandwidth_unit(params.get("bandwidth_size", BANDWIDTH_KB))
    except ValueError as exc:
        reasons.append(str(exc))

    try:
        normalize_direction(params.get("direction", "both"))
    except ValueError as exc:
        reasons.append(str(exc))

    for method in method_list:
        key = CLUMSY_DIRECTION_KEYS.get(method)
        if not key:
            continue
        try:
            normalize_direction(params.get(key, params.get("direction", "both")))
        except ValueError as exc:
            reasons.append(f"{key}: {exc}")

    method_for_param = {
        "lag_delay": "lag",
        "drop_chance": "drop",
        "bandwidth_queue": "bandwidth",
        "bandwidth_limit": "bandwidth",
        "throttle_frame": "throttle",
        "throttle_chance": "throttle",
        "duplicate_count": "duplicate",
        "duplicate_chance": "duplicate",
        "ood_chance": "ood",
        "tamper_chance": "corrupt",
        "rst_chance": "rst",
    }
    active = set(method_list)
    for name, method in method_for_param.items():
        if method not in active:
            continue
        try:
            _bounded_integer(name, params.get(name, CLUMSY_NUMERIC_LIMITS[name][0]))
        except ValueError as exc:
            reasons.append(str(exc))

    if params.get("_clumsy_rst_next_packet") and "rst" not in active:
        reasons.append("RST next packet requires the Set TCP RST module")

    return tuple(reasons)
