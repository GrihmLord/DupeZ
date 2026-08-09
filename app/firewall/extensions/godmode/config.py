"""Immutable validated configuration for the bounded God Mode extension."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

__all__ = ["GodModeConfig", "MAX_ACTIVE_MS"]

MAX_ACTIVE_MS = 29_000


def _bounded_int(
    value: object,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        parsed = float(default)
    if not math.isfinite(parsed):
        parsed = float(default)
    return max(minimum, min(maximum, int(parsed)))


@dataclass(frozen=True)
class GodModeConfig:
    active_ms: int = 25_000
    block_ms: int = 1_200
    release_ms: int = 250
    release_batch: int = 256
    queue_max: int = 4_096
    keepalive_interval_ms: int = 1_500
    preserve_connection: bool = True
    direction: str = "both"

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> "GodModeConfig":
        """Build from the new schema plus bounded legacy timing aliases."""

        return cls(
            active_ms=_bounded_int(
                params.get(
                    "extension_active_ms",
                    params.get("godmode_max_active_ms", 25_000),
                ),
                default=25_000,
                minimum=1_000,
                maximum=MAX_ACTIVE_MS,
            ),
            block_ms=_bounded_int(
                params.get(
                    "extension_block_ms",
                    params.get("godmode_pulse_block_ms", 1_200),
                ),
                default=1_200,
                minimum=50,
                maximum=5_000,
            ),
            release_ms=_bounded_int(
                params.get(
                    "extension_release_ms",
                    params.get("godmode_pulse_flush_ms", 250),
                ),
                default=250,
                minimum=10,
                maximum=2_000,
            ),
            release_batch=_bounded_int(
                params.get("extension_release_batch", 256),
                default=256,
                minimum=1,
                maximum=2_048,
            ),
            queue_max=_bounded_int(
                params.get("extension_queue_max", 4_096),
                default=4_096,
                minimum=128,
                maximum=10_000,
            ),
            keepalive_interval_ms=_bounded_int(
                params.get("extension_keepalive_interval_ms", 1_500),
                default=1_500,
                minimum=250,
                maximum=5_000,
            ),
            preserve_connection=bool(
                params.get("extension_preserve_connection", True)
            ),
            direction=(
                str(params.get("direction", "both")).strip().lower()
                if str(params.get("direction", "both")).strip().lower()
                in {"both", "inbound", "outbound"}
                else "both"
            ),
        )
