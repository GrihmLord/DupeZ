"""Fail-open health policy for the God Mode extension."""

from __future__ import annotations

import threading

__all__ = ["HealthPolicy"]


class HealthPolicy:
    def __init__(self, maximum_send_failures: int = 25) -> None:
        self._maximum_send_failures = max(1, int(maximum_send_failures))
        self._send_failures = 0
        self._failed = False
        self._reason = ""
        self._lock = threading.RLock()

    def record_send(self, success: bool) -> None:
        if success:
            return
        with self._lock:
            self._send_failures += 1
            if self._send_failures >= self._maximum_send_failures:
                self._failed = True
                self._reason = "packet release repeatedly failed"

    def fail(self, reason: str) -> None:
        with self._lock:
            self._failed = True
            self._reason = str(reason)[:200]

    @property
    def healthy(self) -> bool:
        with self._lock:
            return not self._failed

    @property
    def reason(self) -> str:
        with self._lock:
            return self._reason
