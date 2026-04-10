"""RST module — inject TCP RST flag to kill connections.

WARNING: This module kills YOUR connections (BattlEye, Steam auth) just
as much as it affects server-side TCP state.  Using this will likely kick
you from the server.  The Disconnect module (100% packet drop) achieves
the same hard-disconnect effect without corrupting TCP state.

Use cases:
  - Intentional hard disconnect with TCP teardown (cleaner than drop for
    some server configurations that hold TCP sessions open after packet loss)
  - Forcing immediate server-side session cleanup

For most combat/dupe scenarios, prefer Disconnect or Drop modules instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from app.firewall.native_divert_engine import DisruptionModule, TCP_FLAG_RST

if TYPE_CHECKING:
    from app.firewall.native_divert_engine import WINDIVERT_ADDRESS

__all__ = ["RSTModule"]

DEFAULT_RST_CHANCE: int = 90
# IP protocol number for TCP.
_IP_PROTO_TCP: int = 6
# Minimum packet length to safely access TCP flags (IP + TCP headers).
_MIN_TCP_PACKET_LEN: int = 40


class RSTModule(DisruptionModule):
    """Inject the TCP RST flag into transit packets to kill connections.

    Only operates on TCP packets (IP protocol 6).  The RST bit is set in
    the TCP flags byte; the engine recalculates checksums before forwarding
    so the modified packet is accepted by the target's network stack.

    **Self-kick risk:** Injecting RST on forwarded TCP packets will tear
    down BattlEye and Steam auth connections, causing a server kick.
    Use with caution — Disconnect module is usually a better choice.

    Parameters (via *params* dict):
        rst_chance (int): Probability 0-100 that RST is injected.
            Defaults to :data:`DEFAULT_RST_CHANCE`.
    """

    _direction_key: str = "rst"

    def process(
        self,
        packet_data: bytearray,
        addr: WINDIVERT_ADDRESS,
        send_fn: Callable[[bytearray, WINDIVERT_ADDRESS], None],
    ) -> bool:
        """Inject RST flag.  Always returns ``False`` (pass-through)."""
        if (
            self._roll(self.params.get("rst_chance", DEFAULT_RST_CHANCE))
            and len(packet_data) >= _MIN_TCP_PACKET_LEN
        ):
            # Verify TCP (protocol field at IP header byte 9)
            if packet_data[9] == _IP_PROTO_TCP:
                ihl: int = (packet_data[0] & 0x0F) * 4
                tcp_flags_offset: int = ihl + 13
                if tcp_flags_offset < len(packet_data):
                    packet_data[tcp_flags_offset] |= TCP_FLAG_RST
        return False
