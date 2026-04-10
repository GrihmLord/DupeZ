"""Drop module — randomly drop packets based on chance percentage."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Dict

from app.firewall.native_divert_engine import DisruptionModule

if TYPE_CHECKING:
    from app.firewall.native_divert_engine import WINDIVERT_ADDRESS

__all__ = ["DropModule"]

# Default drop probability when no parameter is supplied (0-100).
DEFAULT_DROP_CHANCE: int = 95


class DropModule(DisruptionModule):
    """Randomly drop packets based on a configurable chance percentage.

    When *drop_chance* is 100, **all** packets are dropped with zero leakage.
    The underlying ``_roll`` uses ``>=`` comparison, so 100 % means 100 %.

    Parameters (via *params* dict):
        drop_chance (int): Probability 0-100 that any given packet is
            dropped.  Defaults to :data:`DEFAULT_DROP_CHANCE`.
    """

    _direction_key: str = "drop"

    def process(
        self,
        packet_data: bytearray,
        addr: WINDIVERT_ADDRESS,
        send_fn: Callable[[bytearray, WINDIVERT_ADDRESS], None],
    ) -> bool:
        """Return ``True`` to consume (drop) the packet."""
        return self._roll(self.params.get("drop_chance", DEFAULT_DROP_CHANCE))
