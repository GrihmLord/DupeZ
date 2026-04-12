"""Shared packet classification and utility functions.

Extracted from godmode.py for reuse across dupe_engine_v2.py and other
modules that need direction detection, packet classification, keepalive
tracking, and WinDivert address handling.
"""

from __future__ import annotations

import ctypes
import socket
import time
from enum import Enum, auto
from typing import Tuple

from app.firewall.native_divert_engine import WINDIVERT_ADDRESS

__all__ = [
    "PktClass",
    "classify_packet",
    "ipv4_addrs_u32",
    "parse_ipv4_addrs",
    "ip_to_u32",
    "detect_direction",
    "copy_windivert_addr",
    "KeepaliveTracker",
    "PROTO_TCP",
    "PROTO_UDP",
    "GAME_PORT_MIN",
    "GAME_PORT_MAX",
    "STEAM_PORT_MIN",
    "STEAM_PORT_MAX",
    "KEEPALIVE_PAYLOAD_MAX",
    "GAME_SMALL_PAYLOAD_MAX",
    "GAME_STATE_PAYLOAD_MAX",
]

# ── Protocol constants ──────────────────────────────────────────────
PROTO_TCP = 6
PROTO_UDP = 17

# DayZ game server port range (Enfusion default + common configs)
GAME_PORT_MIN = 2300
GAME_PORT_MAX = 2410

# Steam port range
STEAM_PORT_MIN = 27015
STEAM_PORT_MAX = 27050

# UDP payload size thresholds
# DayZ smallest packets ~77B payload (105B total). 90B threshold captures
# heartbeat/ack packets while excluding game state.
KEEPALIVE_PAYLOAD_MAX = 90
GAME_SMALL_PAYLOAD_MAX = 200
GAME_STATE_PAYLOAD_MAX = 760


class PktClass(Enum):
    """Packet classification categories."""
    KEEPALIVE  = auto()   # Small UDP heartbeat/probe
    CONTROL    = auto()   # TCP (auth, BattlEye, Steam session)
    GAME_SMALL = auto()   # Small game UDP (acks, input echo)
    GAME_STATE = auto()   # Medium game UDP (position, entity state)
    GAME_BULK  = auto()   # Large game UDP (world/inventory sync)
    OTHER      = auto()   # Anything else (ICMP, unknown)


# ── IP parsing ──────────────────────────────────────────────────────

def parse_ipv4_addrs(packet_data: bytearray) -> Tuple[str, str]:
    """Extract (src_ip, dst_ip) strings from IPv4 header.

    Retained for diagnostics/logging. The hot path should use
    :func:`ipv4_addrs_u32` to avoid per-packet string allocations.
    """
    if len(packet_data) < 20:
        return ("", "")
    version = (packet_data[0] >> 4) & 0xF
    if version != 4:
        return ("", "")
    src = socket.inet_ntoa(packet_data[12:16])
    dst = socket.inet_ntoa(packet_data[16:20])
    return (src, dst)


def ipv4_addrs_u32(packet_data: bytearray) -> Tuple[int, int]:
    """Zero-allocation extraction of IPv4 (src, dst) as u32 ints.

    Returns ``(0, 0)`` for non-IPv4 or undersized packets.
    """
    if len(packet_data) < 20 or (packet_data[0] >> 4) & 0xF != 4:
        return (0, 0)
    src_u32 = (
        (packet_data[12] << 24)
        | (packet_data[13] << 16)
        | (packet_data[14] << 8)
        | packet_data[15]
    )
    dst_u32 = (
        (packet_data[16] << 24)
        | (packet_data[17] << 16)
        | (packet_data[18] << 8)
        | packet_data[19]
    )
    return (src_u32, dst_u32)


def ip_to_u32(ip_str: str) -> int:
    """Convert dotted IP string to u32 integer. Returns 0 on failure."""
    try:
        if ip_str:
            return int.from_bytes(socket.inet_aton(ip_str), "big")
    except OSError:
        pass
    return 0


def detect_direction(
    src_u32: int,
    dst_u32: int,
    target_u32: int,
    is_local: bool,
) -> Tuple[bool, bool]:
    """Determine (is_inbound, is_outbound) for a packet.

    Args:
        src_u32: Source IP as u32.
        dst_u32: Destination IP as u32.
        target_u32: Target device/server IP as u32.
        is_local: True for PC-local mode (target is game server IP).

    Returns:
        (is_inbound, is_outbound) tuple.
    """
    if target_u32 == 0:
        return (False, False)
    if is_local:
        # PC-local: target_ip is game SERVER IP
        return (src_u32 == target_u32, dst_u32 == target_u32)
    else:
        # Remote (console over hotspot): target_ip is DEVICE IP
        return (dst_u32 == target_u32, src_u32 == target_u32)


# ── Packet classification ──────────────────────────────────────────

def classify_packet(
    packet_data: bytearray,
    is_target: bool = False,
) -> Tuple[PktClass, int, int, int]:
    """Classify an IPv4 packet by protocol and payload size.

    When ``is_target`` is True, ALL UDP traffic is treated as game
    traffic (classified by payload size). This is correct for ICS/hotspot
    setups where the console's only traffic is DayZ.

    Returns (classification, protocol, src_port, dst_port).
    """
    if len(packet_data) < 20:
        return (PktClass.OTHER, 0, 0, 0)

    version = (packet_data[0] >> 4) & 0xF
    if version != 4:
        return (PktClass.OTHER, 0, 0, 0)

    ihl = (packet_data[0] & 0xF) * 4
    protocol = packet_data[9]
    total_len = len(packet_data)

    # TCP → CONTROL (BattlEye, Steam auth, session management)
    if protocol == PROTO_TCP:
        src_port = dst_port = 0
        if total_len >= ihl + 4:
            src_port = (packet_data[ihl] << 8) | packet_data[ihl + 1]
            dst_port = (packet_data[ihl + 2] << 8) | packet_data[ihl + 3]
        return (PktClass.CONTROL, protocol, src_port, dst_port)

    # UDP → classify by payload size
    if protocol == PROTO_UDP:
        if total_len < ihl + 8:
            return (PktClass.OTHER, protocol, 0, 0)

        src_port = (packet_data[ihl] << 8) | packet_data[ihl + 1]
        dst_port = (packet_data[ihl + 2] << 8) | packet_data[ihl + 3]
        udp_payload = total_len - ihl - 8

        if is_target:
            if udp_payload <= KEEPALIVE_PAYLOAD_MAX:
                return (PktClass.KEEPALIVE, protocol, src_port, dst_port)
            elif udp_payload <= GAME_SMALL_PAYLOAD_MAX:
                return (PktClass.GAME_SMALL, protocol, src_port, dst_port)
            elif udp_payload <= GAME_STATE_PAYLOAD_MAX:
                return (PktClass.GAME_STATE, protocol, src_port, dst_port)
            else:
                return (PktClass.GAME_BULK, protocol, src_port, dst_port)

        # Non-target UDP: use port heuristic
        is_game_port = (
            (GAME_PORT_MIN <= src_port <= GAME_PORT_MAX)
            or (GAME_PORT_MIN <= dst_port <= GAME_PORT_MAX)
            or (STEAM_PORT_MIN <= src_port <= STEAM_PORT_MAX)
            or (STEAM_PORT_MIN <= dst_port <= STEAM_PORT_MAX)
        )
        if is_game_port and udp_payload <= KEEPALIVE_PAYLOAD_MAX:
            return (PktClass.KEEPALIVE, protocol, src_port, dst_port)
        return (PktClass.OTHER, protocol, src_port, dst_port)

    return (PktClass.OTHER, protocol, 0, 0)


# ── WinDivert address copy ─────────────────────────────────────────

def copy_windivert_addr(addr: WINDIVERT_ADDRESS) -> WINDIVERT_ADDRESS:
    """Deep-copy a WinDivert address struct for deferred packet send."""
    addr_copy = WINDIVERT_ADDRESS()
    ctypes.memmove(
        ctypes.byref(addr_copy),
        ctypes.byref(addr),
        ctypes.sizeof(WINDIVERT_ADDRESS),
    )
    return addr_copy


# ── Keepalive tracker ──────────────────────────────────────────────

class KeepaliveTracker:
    """Tracks keepalive pass-through timing for both directions.

    Used by God Mode and Dupe Engine v2 to maintain connection health
    during packet blocking phases.
    """

    def __init__(self, interval_ms: int = 800) -> None:
        self._interval: float = max(0, interval_ms) / 1000.0
        self._last_in: float = 0.0
        self._last_out: float = 0.0
        self.passed_in: int = 0
        self.passed_out: int = 0

    @property
    def interval_s(self) -> float:
        return self._interval

    def should_pass_inbound(
        self, pkt_class: PktClass, now: float
    ) -> bool:
        """Check if an inbound packet should pass as a keepalive.

        Primary: pass KEEPALIVE-classified packets on schedule.
        Fallback: if 2x overdue, pass GAME_SMALL as emergency keepalive.
        """
        if self._interval <= 0:
            return False
        elapsed = now - self._last_in
        if pkt_class == PktClass.KEEPALIVE and elapsed >= self._interval:
            self._last_in = now
            self.passed_in += 1
            return True
        if pkt_class == PktClass.GAME_SMALL and elapsed >= self._interval * 2:
            self._last_in = now
            self.passed_in += 1
            return True
        return False

    def should_pass_outbound(
        self, pkt_class: PktClass, now: float
    ) -> bool:
        """Check if an outbound packet should pass as a keepalive."""
        if self._interval <= 0:
            return False
        elapsed = now - self._last_out
        if pkt_class == PktClass.KEEPALIVE and elapsed >= self._interval:
            self._last_out = now
            self.passed_out += 1
            return True
        if pkt_class == PktClass.GAME_SMALL and elapsed >= self._interval * 2:
            self._last_out = now
            self.passed_out += 1
            return True
        return False

    def reset(self) -> None:
        """Reset timestamps (e.g., on phase transition)."""
        self._last_in = 0.0
        self._last_out = 0.0
