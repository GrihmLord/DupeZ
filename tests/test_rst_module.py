"""Focused tests for protocol-aware TCP RST telemetry."""

from __future__ import annotations

from types import SimpleNamespace

from app.firewall.modules.rst import RSTModule
from app.firewall.native_divert_engine import TCP_FLAG_RST


def _ipv4_packet(protocol: int, length: int = 40) -> bytearray:
    packet = bytearray(max(length, 20))
    packet[0] = 0x45  # IPv4, 20-byte header
    packet[9] = protocol
    return packet


def test_rst_marks_eligible_tcp_packet_and_sets_flag():
    module = RSTModule({"direction": "both", "rst_chance": 100})
    packet = _ipv4_packet(6)

    handled = module.process(packet, SimpleNamespace(), lambda *_args: True)

    assert handled is False
    assert packet[33] & TCP_FLAG_RST
    assert module.get_stats() == {"eligible": 1, "affected": 1}


def test_rst_does_not_claim_udp_packet_as_eligible():
    module = RSTModule({"direction": "both", "rst_chance": 100})
    packet = _ipv4_packet(17)

    module.process(packet, SimpleNamespace(), lambda *_args: True)

    assert packet[33] == 0
    assert module.get_stats() == {"eligible": 0, "affected": 0}


def test_rst_rejects_ipv6_and_malformed_ipv4_headers():
    module = RSTModule({"direction": "both", "rst_chance": 100})
    ipv6 = bytearray(40)
    ipv6[0] = 0x60
    ipv6[9] = 6
    malformed = _ipv4_packet(6)
    malformed[0] = 0x4F  # IHL=60 bytes, larger than packet

    module.process(ipv6, SimpleNamespace(), lambda *_args: True)
    module.process(malformed, SimpleNamespace(), lambda *_args: True)

    assert module.get_stats() == {"eligible": 0, "affected": 0}
