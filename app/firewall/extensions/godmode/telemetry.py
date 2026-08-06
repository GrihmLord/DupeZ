"""Bounded counters for God Mode; never stores packet contents."""

from __future__ import annotations

import threading
from dataclasses import dataclass, asdict

__all__ = ["GodModeTelemetry"]


@dataclass
class _Counters:
    queued: int = 0
    released: int = 0
    release_failed: int = 0
    overflow_passed: int = 0
    keepalive_passed: int = 0
    ordinary_passed: int = 0
    phase_releases: int = 0
    expirations: int = 0


class GodModeTelemetry:
    def __init__(self) -> None:
        self._counters = _Counters()
        self._lock = threading.RLock()

    def increment(self, name: str, amount: int = 1) -> None:
        with self._lock:
            if hasattr(self._counters, name):
                setattr(
                    self._counters,
                    name,
                    int(getattr(self._counters, name)) + int(amount),
                )

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return asdict(self._counters)
