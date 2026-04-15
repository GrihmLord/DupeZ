"""Out-of-order module — buffer packets and release in random order."""

from __future__ import annotations

import ctypes
import random
from typing import Callable, List, Optional, Tuple

from app.firewall.native_divert_engine import DisruptionModule, WINDIVERT_ADDRESS
from app.logs.logger import log_error

__all__ = ["OODModule"]

DEFAULT_OOD_CHANCE: int = 80
# Number of buffered packets before a shuffle-and-flush cycle.
_FLUSH_THRESHOLD: int = 4
# Hard cap on buffer size to prevent unbounded growth under heavy traffic.
MAX_BUFFER: int = 64


class OODModule(DisruptionModule):
    """Out-of-order — buffer packets and release in random order.

    Packets are buffered until :data:`_FLUSH_THRESHOLD` are collected, then
    the buffer is shuffled and all packets are flushed.  If the buffer
    reaches :data:`MAX_BUFFER` it is flushed immediately **without** shuffling
    to act as a safety valve.

    Parameters (via *params* dict):
        ood_chance (int): Probability 0-100 that a packet enters the
            reorder buffer.  Defaults to :data:`DEFAULT_OOD_CHANCE`.
    """

    _direction_key: str = "ood"

    def __init__(self, params: dict) -> None:
        super().__init__(params)
        self._buffer: List[Tuple[bytearray, WINDIVERT_ADDRESS]] = []

    def process(
        self,
        packet_data: bytearray,
        addr: WINDIVERT_ADDRESS,
        send_fn: Callable[[bytearray, WINDIVERT_ADDRESS], None],
    ) -> bool:
        """Buffer and reorder packets.  Returns ``True`` when consumed."""
        if self._roll(self.params.get("ood_chance", DEFAULT_OOD_CHANCE)):
            # Deep-copy address struct for deferred send
            addr_copy = WINDIVERT_ADDRESS()
            ctypes.memmove(
                ctypes.byref(addr_copy),
                ctypes.byref(addr),
                ctypes.sizeof(WINDIVERT_ADDRESS),
            )
            self._buffer.append((bytearray(packet_data), addr_copy))

            if len(self._buffer) >= _FLUSH_THRESHOLD:
                if len(self._buffer) < MAX_BUFFER:
                    random.shuffle(self._buffer)  # skip shuffle on safety flush
                for pkt, a in self._buffer:
                    send_fn(pkt, a)
                self._buffer.clear()

            return True

        return False

    def stop(
        self,
        send_fn: Optional[Callable[[bytearray, WINDIVERT_ADDRESS], None]] = None,
    ) -> None:
        """Flush remaining buffered packets on shutdown.

        If *send_fn* is provided, buffered packets are sent **in order**
        (no shuffle) so in-flight data is not silently dropped.
        """
        if send_fn and self._buffer:
            for pkt, a in self._buffer:
                try:
                    send_fn(pkt, a)
                except Exception as exc:
                    log_error(f"OODModule: flush-on-stop failed ({len(pkt)}B): {exc}")
        self._buffer.clear()
