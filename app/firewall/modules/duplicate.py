"""Duplicate module — send packets multiple times to flood the connection."""

from __future__ import annotations

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

    **Outbound duplication (primary use case — e.g. God Mode Aggressive):**
    Flooding the server with duplicate outbound packets (hit reports,
    position updates, inventory RPCs) can overwhelm the server's RPC
    processing.  The server may process the same client RPC multiple
    times if its deduplication layer doesn't catch the burst.  This is
    the main value: outbound-only duplication with ``duplicate_direction:
    "outbound"`` floods hit reports during God Mode flush.

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

    def process(
        self,
        packet_data: bytearray,
        addr: WINDIVERT_ADDRESS,
        send_fn: Callable[[bytearray, WINDIVERT_ADDRESS], None],
    ) -> bool:
        """Send original + *count* copies when the roll hits."""
        count: int = self.params.get("duplicate_count", DEFAULT_DUPLICATE_COUNT)

        if self._roll(self.params.get("duplicate_chance", DEFAULT_DUPLICATE_CHANCE)):
            # Send the original first, then extra copies
            send_fn(packet_data, addr)
            for _ in range(count):
                send_fn(packet_data, addr)
            return True  # we handled the send (original + copies)

        return False  # chance didn't hit — let packet pass through normally
