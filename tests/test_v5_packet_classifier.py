#!/usr/bin/env python3
"""Tests for v5 Phase 2: Packet Classification Engine."""

import struct
import time
import unittest

from app.firewall.packet_classifier import (
    PacketCategory,
    PacketClassifier,
    FlowTracker,
    SelectiveDisruptionFilter,
)


def _make_udp_packet(src_port: int, dst_port: int,
                     payload_size: int = 50,
                     src_ip: str = "192.168.1.100",
                     dst_ip: str = "1.2.3.4") -> bytearray:
    """Construct a minimal valid UDP/IP packet for testing."""
    # IP header (20 bytes)
    ip_header = bytearray(20)
    ip_header[0] = 0x45  # version=4, IHL=5
    total_len = 20 + 8 + payload_size  # IP + UDP + payload
    struct.pack_into("!H", ip_header, 2, total_len)
    ip_header[9] = 17  # protocol = UDP

    # Pack IP addresses
    src_parts = [int(x) for x in src_ip.split(".")]
    dst_parts = [int(x) for x in dst_ip.split(".")]
    struct.pack_into("!4B", ip_header, 12, *src_parts)
    struct.pack_into("!4B", ip_header, 16, *dst_parts)

    # UDP header (8 bytes)
    udp_header = bytearray(8)
    struct.pack_into("!H", udp_header, 0, src_port)
    struct.pack_into("!H", udp_header, 2, dst_port)
    struct.pack_into("!H", udp_header, 4, 8 + payload_size)

    # Payload
    payload = bytearray(payload_size)

    return ip_header + udp_header + payload


def _make_tcp_packet(src_port: int, dst_port: int,
                     flags: int = 0, payload_size: int = 50) -> bytearray:
    """Construct a minimal valid TCP/IP packet for testing."""
    ip_header = bytearray(20)
    ip_header[0] = 0x45
    total_len = 20 + 20 + payload_size
    struct.pack_into("!H", ip_header, 2, total_len)
    ip_header[9] = 6  # TCP
    struct.pack_into("!I", ip_header, 12, 0xC0A80164)  # 192.168.1.100
    struct.pack_into("!I", ip_header, 16, 0x01020304)  # 1.2.3.4

    tcp_header = bytearray(20)
    struct.pack_into("!H", tcp_header, 0, src_port)
    struct.pack_into("!H", tcp_header, 2, dst_port)
    tcp_header[12] = 0x50  # data offset = 5 (20 bytes)
    tcp_header[13] = flags

    payload = bytearray(payload_size)
    return ip_header + tcp_header + payload


class TestPacketCategory(unittest.TestCase):
    def test_label(self):
        self.assertEqual(PacketCategory.KEEPALIVE.label, "keepalive")
        self.assertEqual(PacketCategory.MOVEMENT.label, "movement")
        self.assertEqual(PacketCategory.STATE.label, "state")
        self.assertEqual(PacketCategory.BULK.label, "bulk")


class TestFlowTracker(unittest.TestCase):
    def test_record_and_rate(self):
        tracker = FlowTracker(window_sec=1.0)
        now = time.monotonic()
        for i in range(10):
            tracker.record(now + i * 0.1, 100)
        rate = tracker.get_rate(now + 1.0)
        self.assertGreater(rate, 0)

    def test_avg_size(self):
        tracker = FlowTracker()
        now = time.monotonic()
        tracker.record(now, 100)
        tracker.record(now + 0.1, 200)
        tracker.record(now + 0.2, 300)
        self.assertAlmostEqual(tracker.get_avg_size(), 200.0)


class TestPacketClassifier(unittest.TestCase):
    def setUp(self):
        self.classifier = PacketClassifier(game_port=2302, enable_frequency=False, auto_calibrate=False)

    def test_tiny_udp_is_keepalive(self):
        pkt = _make_udp_packet(2302, 12345, payload_size=10)
        cat = self.classifier.classify(pkt)
        self.assertEqual(cat, PacketCategory.KEEPALIVE)

    def test_small_udp_is_movement(self):
        pkt = _make_udp_packet(2302, 12345, payload_size=80)
        cat = self.classifier.classify(pkt)
        self.assertEqual(cat, PacketCategory.MOVEMENT)

    def test_medium_udp_is_state(self):
        pkt = _make_udp_packet(2302, 12345, payload_size=300)
        cat = self.classifier.classify(pkt)
        self.assertEqual(cat, PacketCategory.STATE)

    def test_large_udp_is_bulk(self):
        pkt = _make_udp_packet(2302, 12345, payload_size=600)
        cat = self.classifier.classify(pkt)
        self.assertEqual(cat, PacketCategory.BULK)

    def test_tcp_syn_is_connection(self):
        pkt = _make_tcp_packet(12345, 443, flags=0x02)  # SYN
        cat = self.classifier.classify(pkt)
        self.assertEqual(cat, PacketCategory.CONNECTION)

    def test_tcp_rst_is_connection(self):
        pkt = _make_tcp_packet(12345, 443, flags=0x04)  # RST
        cat = self.classifier.classify(pkt)
        self.assertEqual(cat, PacketCategory.CONNECTION)

    def test_too_small_is_unknown(self):
        pkt = bytearray(10)  # too small for IP header
        cat = self.classifier.classify(pkt)
        self.assertEqual(cat, PacketCategory.UNKNOWN)

    def test_non_dayz_port_generic_classification(self):
        pkt = _make_udp_packet(9999, 8888, payload_size=80)
        cat = self.classifier.classify(pkt)
        self.assertIn(cat, (PacketCategory.MOVEMENT, PacketCategory.STATE))

    def test_stats_accumulated(self):
        for size in [10, 80, 300, 600]:
            pkt = _make_udp_packet(2302, 12345, payload_size=size)
            self.classifier.classify(pkt)
        stats = self.classifier.get_stats()
        self.assertGreater(sum(stats.values()), 0)


class TestSelectiveDisruptionFilter(unittest.TestCase):
    def test_bypass_keepalive(self):
        mock_module = type("MockModule", (), {
            "direction": "both",
            "matches_direction": lambda self, addr: True,
            "process": lambda self, pkt, addr, fn: True,  # always drops
        })()

        classifier = PacketClassifier(enable_frequency=False)
        filt = SelectiveDisruptionFilter(
            mock_module, classifier,
            target_categories={PacketCategory.MOVEMENT, PacketCategory.STATE},
            bypass_categories={PacketCategory.KEEPALIVE},
        )

        # Keepalive packet should bypass
        pkt = _make_udp_packet(2302, 12345, payload_size=10)
        result = filt.process(pkt, None, None)
        self.assertFalse(result)  # bypassed, not dropped

        # State packet should be processed (and dropped by mock)
        pkt = _make_udp_packet(2302, 12345, payload_size=300)
        result = filt.process(pkt, None, None)
        self.assertTrue(result)  # processed and dropped


if __name__ == "__main__":
    unittest.main()
