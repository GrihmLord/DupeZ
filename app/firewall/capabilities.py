"""Canonical packet-effect capabilities for the unified DupeZ control plane.

Standard effects are owned by the pinned Kalirenegade Clumsy runtime. DupeZ
extensions are owned by the Native extension host. Legacy identifiers are
accepted only at this migration boundary and are immediately canonicalized.
"""

from __future__ import annotations

from typing import Iterable, Tuple

__all__ = [
    "CapabilityError",
    "KALIRENEGADE_CAPABILITIES",
    "NATIVE_EXTENSION_CAPABILITIES",
    "canonicalize_capability",
    "canonicalize_capabilities",
    "backend_method_for",
]


class CapabilityError(ValueError):
    """Raised when an effect identifier is unknown or malformed."""


KALIRENEGADE_CAPABILITIES = frozenset({
    "kali.lag",
    "kali.drop",
    "kali.disconnect",
    "kali.bandwidth",
    "kali.throttle",
    "kali.duplicate",
    "kali.ood",
    "kali.tamper",
    "kali.rst",
})

NATIVE_EXTENSION_CAPABILITIES = frozenset({
    "dupez.godmode",
    "dupez.custom_lag",
    # Existing statistical modules remain migration-time Native extensions.
    "dupez.gilbert_elliott",
    "dupez.pareto_jitter",
    "dupez.correlated_drop",
    "dupez.token_bucket",
})

_LEGACY_ALIASES = {
    "lag": "kali.lag",
    "drop": "kali.drop",
    "disconnect": "kali.disconnect",
    "bandwidth": "kali.bandwidth",
    "throttle": "kali.throttle",
    "duplicate": "kali.duplicate",
    "ood": "kali.ood",
    "corrupt": "kali.tamper",
    "tamper": "kali.tamper",
    "rst": "kali.rst",
    "godmode": "dupez.godmode",
    "custom_lag": "dupez.custom_lag",
    "gilbert_elliott": "dupez.gilbert_elliott",
    "pareto_jitter": "dupez.pareto_jitter",
    "correlated_drop": "dupez.correlated_drop",
    "token_bucket": "dupez.token_bucket",
}

_BACKEND_METHODS = {
    "kali.lag": "lag",
    "kali.drop": "drop",
    "kali.disconnect": "disconnect",
    "kali.bandwidth": "bandwidth",
    "kali.throttle": "throttle",
    "kali.duplicate": "duplicate",
    "kali.ood": "ood",
    "kali.tamper": "corrupt",
    "kali.rst": "rst",
    "dupez.godmode": "dupez.godmode",
    "dupez.custom_lag": "dupez.custom_lag",
    "dupez.gilbert_elliott": "gilbert_elliott",
    "dupez.pareto_jitter": "pareto_jitter",
    "dupez.correlated_drop": "correlated_drop",
    "dupez.token_bucket": "token_bucket",
}

_ALL_CAPABILITIES = KALIRENEGADE_CAPABILITIES | NATIVE_EXTENSION_CAPABILITIES


def canonicalize_capability(value: object) -> str:
    """Return one canonical capability ID or fail closed."""

    text = str(value or "").strip().lower()
    canonical = _LEGACY_ALIASES.get(text, text)
    if canonical not in _ALL_CAPABILITIES:
        raise CapabilityError(f"unknown packet capability: {value!r}")
    return canonical


def canonicalize_capabilities(values: Iterable[object]) -> Tuple[str, ...]:
    """Canonicalize and de-duplicate an ordered effect sequence."""

    if isinstance(values, (str, bytes)):
        raise CapabilityError("packet capabilities must be a sequence")
    result = []
    seen = set()
    for value in values:
        canonical = canonicalize_capability(value)
        if canonical not in seen:
            seen.add(canonical)
            result.append(canonical)
    if not result:
        raise CapabilityError("at least one packet capability is required")
    return tuple(result)


def backend_method_for(capability_id: str) -> str:
    """Translate a canonical ID to the selected backend's internal key."""

    try:
        return _BACKEND_METHODS[canonicalize_capability(capability_id)]
    except KeyError as exc:  # defensive: maps must remain total
        raise CapabilityError(
            f"capability has no backend mapping: {capability_id!r}"
        ) from exc
