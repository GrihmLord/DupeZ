"""Disconnect module — hard disconnect via configurable drop rate."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from app.firewall.native_divert_engine import DisruptionModule

if TYPE_CHECKING:
    from app.firewall.native_divert_engine import WINDIVERT_ADDRESS

__all__ = ["DisconnectModule"]

# Default disconnect probability — true 100 % with zero leakage.
DEFAULT_DISCONNECT_CHANCE: int = 100


class DisconnectModule(DisruptionModule):
    """Hard disconnect — configurable drop rate, defaults to TRUE 100 %.

    When *disconnect_chance* is 100 (default), every single packet is dropped.
    No ``random.random()`` call, no probability leak, no 1-in-100 slip-through.

    Set *disconnect_chance* < 100 for a softer disconnect (e.g. 95 for the
    legacy clumsy behaviour).

    Parameters (via *params* dict):
        disconnect_chance (int): Drop probability 0-100.
            Defaults to :data:`DEFAULT_DISCONNECT_CHANCE`.
    """

    _direction_key: str = "disconnect"

    def process(
        self,
        packet_data: bytearray,
        addr: WINDIVERT_ADDRESS,
        send_fn: Callable[[bytearray, WINDIVERT_ADDRESS], None],
    ) -> bool:
        """Return ``True`` to consume (drop) the packet."""
        return self._roll(
            self.params.get("disconnect_chance", DEFAULT_DISCONNECT_CHANCE)
        )
