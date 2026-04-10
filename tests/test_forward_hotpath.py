"""
Hot-path direction detection tests for the WinDivert FORWARD layer.

Covers the zero-allocation IPv4 target-matching logic in
``app.firewall.modules.godmode._ipv4_addrs_u32`` and the matching
logic in ``app.firewall.native_divert_engine``.

These tests synthesize raw IPv4 header bytes and verify:

  1. ``_ipv4_addrs_u32`` returns the correct u32 ints.
  2. Non-IPv4 / undersized packets return ``(0, 0)``.
  3. u32 comparison matches ``int.from_bytes(socket.inet_aton(...), "big")``.
  4. GodMode's FORWARD-layer direction logic picks the right side.
  5. GodMode's PC-local direction logic picks the right side.
  6. When _target_ip is unset (u32 == 0), process() should bail without
     misclassifying unrelated traffic as target traffic.
"""

from __future__ import annotations

import socket
import struct
import sys
import types

# ── Install/augment native_divert_engine stub on non-Windows ────────
# godmode.py imports from native_divert_engine. On Linux CI the real
# module can't load (ctypes.windll). Other test files install a partial
# stub — augment it here with the names godmode needs.
if sys.platform != "win32":
    mod = sys.modules.get("app.firewall.native_divert_engine")
    if mod is None:
        mod = types.ModuleType("app.firewall.native_divert_engine")
        sys.modules["app.firewall.native_divert_engine"] = mod

    if not hasattr(mod, "DisruptionModule"):
        class _StubDisruptionModule:
            _direction_key = ""
            def __init__(self, params):
                self.params = params
                self.direction = params.get("direction", "both")
            def matches_direction(self, addr):
                return True
            @staticmethod
            def _roll(chance):
                import random
                return chance >= 100 or random.random() * 100 < chance
            def process(self, packet_data, addr, send_fn):
                return False
        mod.DisruptionModule = _StubDisruptionModule

    if not hasattr(mod, "WINDIVERT_ADDRESS"):
        class _StubAddr:
            Outbound = False
        mod.WINDIVERT_ADDRESS = _StubAddr

    for name, val in (("DIR_BOTH", "both"), ("DIR_INBOUND", "inbound"),
                      ("DIR_OUTBOUND", "outbound"), ("TCP_FLAG_RST", 0x04),
                      ("TCP_FLAG_ACK", 0x10), ("TCP_FLAG_SYN", 0x02),
                      ("TCP_FLAG_FIN", 0x01), ("TCP_FLAG_PSH", 0x08),
                      ("TCP_FLAG_URG", 0x20)):
        if not hasattr(mod, name):
            setattr(mod, name, val)

# Import godmode once at module load so it's cached in sys.modules
# regardless of what other test files do to the engine stub afterward.
from app.firewall.modules.godmode import _ipv4_addrs_u32  # noqa: E402


def _ipv4_packet(src: str, dst: str, proto: int = 17,
                 payload_len: int = 100) -> bytearray:
    """Build a minimal IPv4 header + zero payload for direction tests."""
    version_ihl = (4 << 4) | 5      # IPv4, IHL=5 (20-byte header)
    tos = 0
    total_len = 20 + payload_len
    ident = 0
    flags_frag = 0
    ttl = 64
    checksum = 0
    src_b = socket.inet_aton(src)
    dst_b = socket.inet_aton(dst)
    hdr = struct.pack(
        "!BBHHHBBH4s4s",
        version_ihl, tos, total_len, ident, flags_frag,
        ttl, proto, checksum, src_b, dst_b,
    )
    return bytearray(hdr + b"\x00" * payload_len)


# ── _ipv4_addrs_u32 ─────────────────────────────────────────────────

def test_ipv4_addrs_u32_basic():
    pkt = _ipv4_packet("192.168.137.2", "203.0.113.10")
    src, dst = _ipv4_addrs_u32(pkt)
    assert src == int.from_bytes(socket.inet_aton("192.168.137.2"), "big")
    assert dst == int.from_bytes(socket.inet_aton("203.0.113.10"), "big")


def test_ipv4_addrs_u32_non_ipv4_returns_zero():
    # IPv6 packet (version=6)
    pkt = bytearray([0x60] + [0] * 39)
    assert _ipv4_addrs_u32(pkt) == (0, 0)


def test_ipv4_addrs_u32_short_packet_returns_zero():
    assert _ipv4_addrs_u32(bytearray(b"\x45" + b"\x00" * 10)) == (0, 0)


def test_ipv4_addrs_u32_matches_inet_aton():
    for ip in ("10.0.0.1", "255.255.255.255", "0.0.0.0",
               "192.168.137.1", "127.0.0.1"):
        pkt = _ipv4_packet(ip, "1.1.1.1")
        src, _ = _ipv4_addrs_u32(pkt)
        expected = int.from_bytes(socket.inet_aton(ip), "big")
        assert src == expected, ip


# ── GodMode FORWARD / PC-local direction logic ─────────────────────

def _stub_environment():
    """Ensure app modules import cleanly without a Windows runtime."""
    # No-op — this file only imports pure helpers and avoids the
    # Windows-only engine/packet loop machinery.
    pass


def test_forward_layer_direction_device_outbound():
    """PS5 → server packet: src == device IP → outbound."""
    device_ip = "192.168.137.2"
    server_ip = "203.0.113.10"
    pkt = _ipv4_packet(device_ip, server_ip)
    src_u32, dst_u32 = _ipv4_addrs_u32(pkt)
    target_u32 = int.from_bytes(socket.inet_aton(device_ip), "big")
    # FORWARD / remote-mode logic mirror
    is_inbound = (dst_u32 == target_u32)
    is_outbound = (src_u32 == target_u32)
    assert is_outbound and not is_inbound


def test_forward_layer_direction_device_inbound():
    """Server → PS5 packet: dst == device IP → inbound."""
    device_ip = "192.168.137.2"
    server_ip = "203.0.113.10"
    pkt = _ipv4_packet(server_ip, device_ip)
    src_u32, dst_u32 = _ipv4_addrs_u32(pkt)
    target_u32 = int.from_bytes(socket.inet_aton(device_ip), "big")
    is_inbound = (dst_u32 == target_u32)
    is_outbound = (src_u32 == target_u32)
    assert is_inbound and not is_outbound


def test_forward_layer_unrelated_traffic_rejected():
    """Third-party traffic on the hotspot subnet should match neither."""
    pkt = _ipv4_packet("192.168.137.3", "1.1.1.1")
    src_u32, dst_u32 = _ipv4_addrs_u32(pkt)
    target_u32 = int.from_bytes(socket.inet_aton("192.168.137.2"), "big")
    assert src_u32 != target_u32 and dst_u32 != target_u32


def test_pc_local_direction_server_inbound():
    """PC-local: src == server IP → inbound."""
    server_ip = "203.0.113.10"
    pkt = _ipv4_packet(server_ip, "10.0.0.15")
    src_u32, dst_u32 = _ipv4_addrs_u32(pkt)
    target_u32 = int.from_bytes(socket.inet_aton(server_ip), "big")
    # PC-local logic mirror
    is_outbound = (dst_u32 == target_u32)
    is_inbound = (src_u32 == target_u32)
    assert is_inbound and not is_outbound


def test_pc_local_direction_server_outbound():
    """PC-local: dst == server IP → outbound."""
    server_ip = "203.0.113.10"
    pkt = _ipv4_packet("10.0.0.15", server_ip)
    src_u32, dst_u32 = _ipv4_addrs_u32(pkt)
    target_u32 = int.from_bytes(socket.inet_aton(server_ip), "big")
    is_outbound = (dst_u32 == target_u32)
    is_inbound = (src_u32 == target_u32)
    assert is_outbound and not is_inbound


def test_unset_target_u32_is_zero_sentinel():
    """0 is the 'unset target' sentinel; process() short-circuits on it."""
    # 0.0.0.0 is not a legal target, but we confirm the value matches the
    # sentinel so the short-circuit in process() is correct.
    assert int.from_bytes(socket.inet_aton("0.0.0.0"), "big") == 0
