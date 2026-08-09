"""Protocol-neutral packet classes used only for resilience cadence."""

from __future__ import annotations

from enum import Enum

__all__ = ["PacketClass", "PacketClassifier"]


class PacketClass(str, Enum):
    CONTROL = "control"
    KEEPALIVE_CANDIDATE = "keepalive_candidate"
    DATA = "data"
    UNKNOWN = "unknown"


class PacketClassifier:
    """Classify by IPv4 protocol and payload size without game assumptions."""

    def classify(self, packet: bytearray) -> PacketClass:
        if len(packet) < 20 or ((packet[0] >> 4) & 0xF) != 4:
            return PacketClass.UNKNOWN
        ihl = (packet[0] & 0x0F) * 4
        if ihl < 20 or len(packet) < ihl:
            return PacketClass.UNKNOWN
        protocol = packet[9]
        if protocol == 6:
            if len(packet) < ihl + 20:
                return PacketClass.UNKNOWN
            tcp_header = ((packet[ihl + 12] >> 4) & 0x0F) * 4
            if tcp_header < 20 or len(packet) < ihl + tcp_header:
                return PacketClass.UNKNOWN
            flags = packet[ihl + 13]
            payload_size = len(packet) - ihl - tcp_header
            # ACK-only packets and connection lifecycle flags are control.
            # TCP packets carrying application payload are data and must not
            # bypass the bounded phase merely because their protocol is TCP.
            if payload_size == 0 or flags & 0x07:  # FIN, SYN, or RST
                return PacketClass.CONTROL
            return PacketClass.DATA
        if protocol == 17 and len(packet) >= ihl + 8:
            payload_size = len(packet) - ihl - 8
            if payload_size <= 96:
                return PacketClass.KEEPALIVE_CANDIDATE
            return PacketClass.DATA
        return PacketClass.UNKNOWN
