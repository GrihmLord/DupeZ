"""Duplicate module — send packets multiple times to flood the connection."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Callable

from app.firewall.native_divert_engine import DisruptionModule

if TYPE_CHECKING:
    from app.firewall.native_divert_engine import WINDIVERT_ADDRESS

__all__ = ["DuplicateModule"]

# Default number of *extra* copies sent (total = 1 original + count).
DEFAULT_DUPLICATE_COUNT: int = 10
DEFAULT_DUPLICATE_CHANCE: int = 80


class DuplicateModule(DisruptionModule):
    """Send packets multiple times to flood the connection.

    **Outbound duplication (primary use case — e.g. Legacy pulse Aggressive):**
    Flooding the server with duplicate outbound packets (hit reports,
    position updates, inventory RPCs) can overwhelm the server's RPC
    processing.  The server may process the same client RPC multiple
    times if its deduplication layer doesn't catch the burst.  This is
    the main value: outbound-only duplication with ``duplicate_direction:
    "outbound"`` creates duplicate packet traces during release.

    **Inbound duplication (limited effectiveness):**
    Enfusion uses snapshot-based state replication with delta encoding.
    Duplicate inbound state snapshots are likely deduplicated or ignored
    by the client's replication layer (same sequence = already applied).
    Inbound duplication adds bandwidth pressure but is unlikely to cause
    visible desync on its own.  Use ``direction: "outbound"`` for combat.

    ``duplicate_count=10`` means 1 original + 10 copies = 11 total sends.

    Parameters (via *params* dict):
        duplicate_count (int): Extra copies to send.
            Defaults to :data:`DEFAULT_DUPLICATE_COUNT`.
        duplicate_chance (int): Probability 0-100.
            Defaults to :data:`DEFAULT_DUPLICATE_CHANCE`.
    """

    _direction_key: str = "duplicate"

    def __init__(self, params: dict) -> None:
        super().__init__(params)
        self._stats_lock = threading.Lock()
        self._attempts: int = 0
        self._sent: int = 0
        self._failed: int = 0

    def process(
        self,
        packet_data: bytearray,
        addr: WINDIVERT_ADDRESS,
        send_fn: Callable[[bytearray, WINDIVERT_ADDRESS], bool],
    ) -> bool:
        """Send original + *count* copies when the roll hits."""
        count: int = max(1, self.params.get("duplicate_count", DEFAULT_DUPLICATE_COUNT))

        if self._roll(self.params.get("duplicate_chance", DEFAULT_DUPLICATE_CHANCE)):
            attempts = count + 1
            sent = 0
            for _ in range(attempts):
                try:
                    if bool(send_fn(packet_data, addr)):
                        sent += 1
                except Exception:
                    # Continue the remaining copies, but expose the failure in
                    # module telemetry rather than silently claiming success.
                    pass
            with self._stats_lock:
                self._attempts += attempts
                self._sent += sent
                self._failed += attempts - sent
            return True

        return False

    def get_stats(self) -> dict:
        """Return verified duplicate-send counters."""
        with self._stats_lock:
            return {
                "attempts": self._attempts,
                "sent": self._sent,
                "failed": self._failed,
            }
