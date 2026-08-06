"""Immutable backend-neutral packet-disruption request contract."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Tuple

from app.firewall.capabilities import canonicalize_capabilities

__all__ = [
    "CaptureLayer",
    "DurationConfiguration",
    "EffectRequest",
    "EnginePolicy",
    "DisruptionRequest",
    "freeze_mapping",
    "thaw_value",
]


class CaptureLayer(str, Enum):
    NETWORK = "network"
    NETWORK_FORWARD = "network_forward"


class EnginePolicy(str, Enum):
    AUTO = "auto"
    KALIRENEGADE = "clumsy"
    NATIVE_EXTENSION = "native"


@dataclass(frozen=True)
class EffectRequest:
    capability_id: str
    direction: str = "both"


@dataclass(frozen=True)
class DurationConfiguration:
    max_active_ms: int = 0
    termination: str = "explicit_stop"


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(k): _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze(item) for item in value)
    return value


def freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return _freeze(dict(value))


def thaw_value(value: Any) -> Any:
    """Return ordinary mutable containers for a backend adapter."""

    if isinstance(value, Mapping):
        return {str(k): thaw_value(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [thaw_value(item) for item in value]
    if isinstance(value, frozenset):
        return [thaw_value(item) for item in value]
    return value


@dataclass(frozen=True)
class DisruptionRequest:
    target_id: str
    capture_layer: CaptureLayer
    effects: Tuple[EffectRequest, ...]
    duration: DurationConfiguration
    engine_policy: EnginePolicy
    request_id: str
    parameters: Mapping[str, Any] = field(repr=False, compare=False)
    filter_hash: str = ""

    @classmethod
    def from_legacy(
        cls,
        *,
        target_id: object,
        filter_string: str,
        methods: list[str] | tuple[str, ...],
        params: Mapping[str, Any],
    ) -> "DisruptionRequest":
        canonical = canonicalize_capabilities(methods)
        direction = str(params.get("direction", "both") or "both")
        effects = tuple(EffectRequest(item, direction) for item in canonical)
        layer = (
            CaptureLayer.NETWORK
            if bool(params.get("_network_local", False))
            else CaptureLayer.NETWORK_FORWARD
        )
        try:
            policy = EnginePolicy(
                str(params.get("_engine_preference", "auto") or "auto")
                .strip()
                .lower()
            )
        except ValueError as exc:
            raise ValueError("unknown engine policy") from exc
        raw_max = params.get("lag_max_active_ms", 0) or 0
        try:
            max_active = max(0, int(float(raw_max)))
        except (TypeError, ValueError, OverflowError):
            max_active = 0
        target = str(target_id or "").strip() or "unresolved"
        digest = hashlib.sha256(str(filter_string).encode("utf-8")).hexdigest()
        return cls(
            target_id=target,
            capture_layer=layer,
            effects=effects,
            duration=DurationConfiguration(max_active_ms=max_active),
            engine_policy=policy,
            request_id=str(uuid.uuid4()),
            parameters=freeze_mapping(params),
            filter_hash=digest,
        )

    def public_fingerprint(self) -> str:
        """Stable request fingerprint without raw target/filter/packet data."""

        payload = {
            "capture_layer": self.capture_layer.value,
            "effects": [effect.capability_id for effect in self.effects],
            "duration": self.duration.max_active_ms,
            "engine_policy": self.engine_policy.value,
            "filter_hash": self.filter_hash,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()
