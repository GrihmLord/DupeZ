"""Throttle module — only allow packets through at certain intervals."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Callable

from app.firewall.native_divert_engine import DisruptionModule

if TYPE_CHECKING:
    from app.firewall.native_divert_engine import WINDIVERT_ADDRESS

__all__ = ["ThrottleModule"]

# Defaults — minimum inter-packet interval and activation probability.
DEFAULT_THROTTLE_FRAME_MS: int = 400
DEFAULT_THROTTLE_CHANCE: int = 100


class ThrottleModule(DisruptionModule):
    """Time-gated packet flow — drops packets arriving faster than *frame_ms*.

    Packets that arrive within *throttle_frame* milliseconds of the last
    forwarded packet are dropped.  ``throttle_chance`` controls the
    probability that throttling is applied to any given packet (100 = always).

    Parameters (via *params* dict):
        throttle_frame (int): Minimum interval in ms between forwarded
            packets.  Defaults to :data:`DEFAULT_THROTTLE_FRAME_MS`.
        throttle_chance (int): Probability 0-100 that throttling is
            evaluated for a packet.  Defaults to :data:`DEFAULT_THROTTLE_CHANCE`.
    """

    _direction_key: str = "throttle"

    def __init__(self, params: dict) -> None:
        super().__init__(params)
        self._last_send: float = 0.0

    def process(
        self,
        packet_data: bytearray,
        addr: WINDIVERT_ADDRESS,
        send_fn: Callable[[bytearray, WINDIVERT_ADDRESS], None],
    ) -> bool:
        """Return ``True`` to drop the packet when inside the throttle window."""
        frame_ms: int = max(1, self.params.get("throttle_frame", DEFAULT_THROTTLE_FRAME_MS))
        now: float = time.time()

        if self._roll(self.params.get("throttle_chance", DEFAULT_THROTTLE_CHANCE)):
            elapsed_ms = (now - self._last_send) * 1000.0
            if elapsed_ms < frame_ms:
                return True  # throttled — drop
            self._last_send = now

        return False
