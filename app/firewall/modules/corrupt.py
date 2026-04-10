"""Corrupt module — flip random bits in packet payload.

NOTE: Limited effectiveness against DayZ's Enfusion engine.  Enfusion uses
snapshot-based replication with integrity checks.  Corrupted UDP game packets
are likely detected and silently discarded by the application layer, then
replaced by the next clean snapshot.  Corrupting TCP (BattlEye/Steam auth)
risks triggering a "client not responding" kick on yourself.

This module is most useful combined with other disruption methods (lag, OOD)
to add noise to an already degraded connection.  On its own, it produces
minimal visible effect against DayZ.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, Callable

from app.firewall.native_divert_engine import DisruptionModule

if TYPE_CHECKING:
    from app.firewall.native_divert_engine import WINDIVERT_ADDRESS

__all__ = ["CorruptModule"]

# Minimum byte offset for corruption — skip IP + TCP/UDP headers.
MIN_PAYLOAD_OFFSET: int = 40
DEFAULT_TAMPER_CHANCE: int = 60


class CorruptModule(DisruptionModule):
    """Flip random bits in packet payload, preserving protocol headers.

    Corruption starts at byte offset :data:`MIN_PAYLOAD_OFFSET` (past the
    combined IP + transport headers) to avoid breaking routing or checksum
    fields that would cause the OS to silently discard the packet before the
    application sees it.  The engine recalculates checksums after all modules
    run, so corrupted payload bytes reach the target application intact.

    **Effectiveness note:** Enfusion's replication layer uses integrity
    verification on state snapshots.  Corrupted packets are likely discarded
    and retransmitted.  This module adds connection noise but does not
    reliably cause persistent desync against DayZ.

    Parameters (via *params* dict):
        tamper_chance (int): Probability 0-100 that a given packet is
            corrupted.  Defaults to :data:`DEFAULT_TAMPER_CHANCE`.
    """

    _direction_key: str = "tamper"

    def process(
        self,
        packet_data: bytearray,
        addr: WINDIVERT_ADDRESS,
        send_fn: Callable[[bytearray, WINDIVERT_ADDRESS], None],
    ) -> bool:
        """Corrupt a random payload byte.  Always returns ``False`` (pass-through)."""
        if (
            self._roll(self.params.get("tamper_chance", DEFAULT_TAMPER_CHANCE))
            and len(packet_data) > MIN_PAYLOAD_OFFSET
        ):
            offset = random.randint(MIN_PAYLOAD_OFFSET, len(packet_data) - 1)
            packet_data[offset] ^= random.randint(1, 255)
        return False  # still needs to be sent by the engine
