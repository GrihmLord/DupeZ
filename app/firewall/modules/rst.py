"""RST module — inject TCP RST flag to kill connections.

WARNING: This module kills YOUR connections (BattlEye, Steam auth) just as much
as it affects server-side TCP state. Using this will likely kick you from the
server. The Disconnect module (100% packet drop) achieves the same hard-cut
effect without corrupting TCP state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from app.firewall.native_divert_engine import DisruptionModule, TCP_FLAG_RST

if TYPE_CHECKING:
    from app.firewall.native_divert_engine import WINDIVERT_ADDRESS

__all__ = ["RSTModule"]

DEFAULT_RST_CHANCE: int = 90
_IP_PROTO_TCP: int = 6
_IPV4_VERSION: int = 4
_MIN_IPV4_HEADER_LEN: int = 20
_MIN_TCP_HEADER_LEN: int = 20


class RSTModule(DisruptionModule):
    """Inject TCP RST into eligible IPv4 TCP packets.

    ``eligible`` telemetry distinguishes an inactive implementation from a
    target that simply produced UDP-only traffic during a short hardware test.
    """

    _direction_key: str = "rst"

    def __init__(self, params: dict) -> None:
        super().__init__(params)
        self._eligible: int = 0
        self._affected: int = 0

    def process(
        self,
        packet_data: bytearray,
        addr: WINDIVERT_ADDRESS,
        send_fn: Callable[[bytearray, WINDIVERT_ADDRESS], None],
    ) -> bool:
        """Set the TCP RST flag and always continue the packet chain."""

        if len(packet_data) < _MIN_IPV4_HEADER_LEN:
            return False
        if (packet_data[0] >> 4) != _IPV4_VERSION:
            return False
        if packet_data[9] != _IP_PROTO_TCP:
            return False

        ihl = (packet_data[0] & 0x0F) * 4
        if ihl < _MIN_IPV4_HEADER_LEN:
            return False
        if len(packet_data) < ihl + _MIN_TCP_HEADER_LEN:
            return False

        tcp_flags_offset = ihl + 13
        if tcp_flags_offset >= len(packet_data):
            return False

        self._eligible += 1
        if self._roll(self.params.get("rst_chance", DEFAULT_RST_CHANCE)):
            packet_data[tcp_flags_offset] |= TCP_FLAG_RST
            self._affected += 1
        return False

    def get_stats(self) -> dict:
        return {
            "eligible": self._eligible,
            "affected": self._affected,
        }
