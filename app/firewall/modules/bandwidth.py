"""Bandwidth module — limit throughput to X KB/s via token-bucket."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Callable

from app.firewall.native_divert_engine import DisruptionModule

if TYPE_CHECKING:
    from app.firewall.native_divert_engine import WINDIVERT_ADDRESS

__all__ = ["BandwidthModule"]

# Default bandwidth cap in KB/s.
DEFAULT_BANDWIDTH_LIMIT_KBPS: int = 1
# Sliding window length in seconds.
_WINDOW_SECONDS: float = 1.0
# Bytes per kilobyte for budget calculation.
_BYTES_PER_KB: int = 1024


class BandwidthModule(DisruptionModule):
    """Limit throughput to *bandwidth_limit* KB/s.

    Uses a simple 1-second sliding window: packets that would exceed the
    byte budget for the current window are dropped.  The window resets
    every second.

    Parameters (via *params* dict):
        bandwidth_limit (int): Maximum throughput in KB/s.
            Defaults to :data:`DEFAULT_BANDWIDTH_LIMIT_KBPS`.
    """

    _direction_key: str = "bandwidth"

    def __init__(self, params: dict) -> None:
        super().__init__(params)
        self._bytes_sent: int = 0
        self._window_start: float = time.time()

    def process(
        self,
        packet_data: bytearray,
        addr: WINDIVERT_ADDRESS,
        send_fn: Callable[[bytearray, WINDIVERT_ADDRESS], None],
    ) -> bool:
        """Drop the packet if forwarding it would exceed the byte budget."""
        limit_kbps: int = self.params.get(
            "bandwidth_limit", DEFAULT_BANDWIDTH_LIMIT_KBPS
        )
        limit_bytes: int = limit_kbps * _BYTES_PER_KB
        now: float = time.time()

        # Reset window every second
        if now - self._window_start >= _WINDOW_SECONDS:
            self._bytes_sent = 0
            self._window_start = now

        if self._bytes_sent + len(packet_data) > limit_bytes:
            return True  # over budget — drop

        self._bytes_sent += len(packet_data)
        return False
