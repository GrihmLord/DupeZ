#!/usr/bin/env python3
"""Tests for app.firewall.target_profile.resolve_target_profile.

Covers the detection ladder:
  1. Subnet → layer decision (local vs forward)
  2. MAC OUI → platform (Sony → ps5, Microsoft → xbox)
  3. Hostname regex fallback
  4. device_type hint fallback
  5. Unknown-forward default → ps5_hotspot (most conservative)
"""

from __future__ import annotations

import unittest

from app.firewall.target_profile import (
    DetectionResult,
    HOTSPOT_SUBNET,
    resolve_target_profile,
    _normalize_mac,
    _oui_prefix,
)


class TestLayerDetection(unittest.TestCase):
    def test_hotspot_subnet_is_forward(self):
        r = resolve_target_profile("192.168.137.42")
        self.assertEqual(r.layer, "forward")

    def test_non_hotspot_subnet_is_local(self):
        r = resolve_target_profile("192.168.1.50")
        self.assertEqual(r.layer, "local")
        self.assertEqual(r.profile, "pc_local")
        self.assertEqual(r.platform, "pc")

    def test_local_ignores_platform_signals(self):
        # Even with a PS5 MAC, a local-subnet target must resolve to pc_local
        r = resolve_target_profile(
            "10.0.0.15", mac="b4:0a:d8:11:22:33",
            hostname="PS5-livingroom",
        )
        self.assertEqual(r.profile, "pc_local")
        self.assertEqual(r.platform, "pc")

    def test_invalid_ip_falls_through_to_local(self):
        r = resolve_target_profile("not-an-ip")
        self.assertEqual(r.layer, "local")
        self.assertEqual(r.profile, "pc_local")

    def test_hotspot_constant_exposed(self):
        self.assertEqual(str(HOTSPOT_SUBNET), "192.168.137.0/24")


class TestPlatformByMAC(unittest.TestCase):
    def test_sony_oui_resolves_ps5(self):
        r = resolve_target_profile("192.168.137.5", mac="b4:0a:d8:aa:bb:cc")
        self.assertEqual(r.platform, "ps5")
        self.assertEqual(r.profile, "ps5_hotspot")
        self.assertEqual(r.layer, "forward")

    def test_microsoft_oui_resolves_xbox(self):
        r = resolve_target_profile("192.168.137.6", mac="7c:ed:8d:11:22:33")
        self.assertEqual(r.platform, "xbox")
        self.assertEqual(r.profile, "xbox_hotspot")

    def test_dashed_mac_normalized(self):
        r = resolve_target_profile("192.168.137.7", mac="B4-0A-D9-DE-AD-BE")
        self.assertEqual(r.platform, "ps5")

    def test_raw_hex_mac_normalized(self):
        r = resolve_target_profile("192.168.137.8", mac="7ced8d112233")
        self.assertEqual(r.platform, "xbox")

    def test_unknown_oui_falls_through_to_hostname(self):
        r = resolve_target_profile(
            "192.168.137.9", mac="12:34:56:78:9a:bc",
            hostname="ps5-guest",
        )
        self.assertEqual(r.platform, "ps5")


class TestPlatformByHostname(unittest.TestCase):
    def test_ps5_hostname(self):
        r = resolve_target_profile("192.168.137.10", hostname="PS5-livingroom")
        self.assertEqual(r.platform, "ps5")
        self.assertEqual(r.profile, "ps5_hotspot")

    def test_playstation_hostname(self):
        r = resolve_target_profile("192.168.137.11", hostname="playstation-5")
        self.assertEqual(r.platform, "ps5")

    def test_xbox_hostname(self):
        r = resolve_target_profile("192.168.137.12", hostname="XBOX-main")
        self.assertEqual(r.platform, "xbox")

    def test_xboxone_hostname(self):
        r = resolve_target_profile("192.168.137.13", hostname="xboxone-kids")
        self.assertEqual(r.platform, "xbox")

    def test_bare_word_no_match(self):
        r = resolve_target_profile("192.168.137.14", hostname="randomhost")
        self.assertEqual(r.platform, "unknown")
        self.assertEqual(r.profile, "ps5_hotspot")  # conservative default


class TestPlatformByDeviceType(unittest.TestCase):
    def test_playstation_device_type(self):
        r = resolve_target_profile(
            "192.168.137.20", device_type="PlayStation",
        )
        self.assertEqual(r.platform, "ps5")

    def test_xbox_device_type(self):
        r = resolve_target_profile(
            "192.168.137.21", device_type="Xbox Series X",
        )
        self.assertEqual(r.platform, "xbox")


class TestDetectionLadderPriority(unittest.TestCase):
    def test_mac_beats_hostname(self):
        # Sony MAC + xbox hostname → MAC wins
        r = resolve_target_profile(
            "192.168.137.30",
            mac="b4:0a:d8:11:22:33",
            hostname="xbox-living",
        )
        self.assertEqual(r.platform, "ps5")

    def test_hostname_beats_device_type(self):
        # Unknown MAC + ps5 hostname + xbox device_type → hostname wins
        r = resolve_target_profile(
            "192.168.137.31",
            mac="aa:bb:cc:dd:ee:ff",
            hostname="PS5-pro",
            device_type="Xbox",
        )
        self.assertEqual(r.platform, "ps5")


class TestUnknownDefault(unittest.TestCase):
    def test_forward_no_signals_defaults_ps5(self):
        r = resolve_target_profile("192.168.137.99")
        self.assertEqual(r.profile, "ps5_hotspot")
        self.assertEqual(r.platform, "unknown")
        self.assertEqual(r.layer, "forward")
        # Reason trace must explain the default
        self.assertTrue(any("default" in x for x in r.reasons))


class TestDetectionResult(unittest.TestCase):
    def test_as_dict_roundtrip(self):
        r = resolve_target_profile("192.168.137.5", mac="b4:0a:d8:11:22:33")
        d = r.as_dict()
        self.assertEqual(d["profile"], "ps5_hotspot")
        self.assertEqual(d["layer"], "forward")
        self.assertEqual(d["platform"], "ps5")
        self.assertIsInstance(d["reasons"], list)

    def test_repr_readable(self):
        r = DetectionResult("ps5_hotspot", "forward", "ps5", ["x"])
        s = repr(r)
        self.assertIn("ps5_hotspot", s)
        self.assertIn("forward", s)


class TestNormalizationHelpers(unittest.TestCase):
    def test_normalize_mac_colon(self):
        self.assertEqual(_normalize_mac("AA:BB:CC:DD:EE:FF"), "aa:bb:cc:dd:ee:ff")

    def test_normalize_mac_dash(self):
        self.assertEqual(_normalize_mac("AA-BB-CC-DD-EE-FF"), "aa:bb:cc:dd:ee:ff")

    def test_normalize_mac_raw(self):
        self.assertEqual(_normalize_mac("aabbccddeeff"), "aa:bb:cc:dd:ee:ff")

    def test_normalize_mac_cisco(self):
        self.assertEqual(_normalize_mac("aabb.ccdd.eeff"), "aa:bb:cc:dd:ee:ff")

    def test_normalize_mac_empty(self):
        self.assertEqual(_normalize_mac(""), "")
        self.assertEqual(_normalize_mac(None), "")

    def test_oui_prefix(self):
        self.assertEqual(_oui_prefix("aa:bb:cc:dd:ee:ff"), "aa:bb:cc")
        self.assertEqual(_oui_prefix("invalid"), "")


if __name__ == "__main__":
    unittest.main()
