#!/usr/bin/env python3
"""Tests for v5 Phase 7: Stealth and Detection Avoidance."""

import sys
import unittest

# Mock native engine on non-Windows
if sys.platform != "win32":
    import types
    mock_nde = types.ModuleType("app.firewall.native_divert_engine")

    class _MockDisruptionModule:
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

    class _MockAddr:
        Outbound = False

    mock_nde.DisruptionModule = _MockDisruptionModule
    mock_nde.WINDIVERT_ADDRESS = _MockAddr
    mock_nde.DIR_BOTH = "both"
    mock_nde.DIR_INBOUND = "inbound"
    mock_nde.DIR_OUTBOUND = "outbound"
    sys.modules["app.firewall.native_divert_engine"] = mock_nde


from app.firewall.stealth import (
    TimingRandomizer,
    NaturalPatternGenerator,
    StealthDropModule,
    SessionFingerprintRotator,
    STEALTH_MODULE_MAP,
)


class _FakeAddr:
    Outbound = False


class TestTimingRandomizer(unittest.TestCase):
    def test_jitter_stays_positive(self):
        r = TimingRandomizer(jitter_pct=0.5)
        for _ in range(100):
            val = r.jitter(50.0)
            self.assertGreater(val, 0)

    def test_jitter_around_target(self):
        r = TimingRandomizer(jitter_pct=0.10)
        vals = [r.jitter(100.0) for _ in range(1000)]
        avg = sum(vals) / len(vals)
        # Average should be close to 100 (within 15% tolerance)
        self.assertGreater(avg, 85)
        self.assertLess(avg, 115)

    def test_zero_target_returns_zero(self):
        r = TimingRandomizer()
        self.assertEqual(r.jitter(0), 0.0)

    def test_jitter_chance_deterministic_edges(self):
        r = TimingRandomizer()
        self.assertEqual(r.jitter_chance(0.0), 0.0)
        self.assertEqual(r.jitter_chance(100.0), 100.0)

    def test_jitter_chance_varies(self):
        r = TimingRandomizer(jitter_pct=0.5)
        vals = set(r.jitter_chance(50.0) for _ in range(20))
        # Should produce different values
        self.assertGreater(len(vals), 1)


class TestNaturalPatternGenerator(unittest.TestCase):
    def test_wifi_pattern_varies(self):
        gen = NaturalPatternGenerator("wifi_interference", cycle_sec=0.1)
        vals = [gen.get_drop_chance(50) for _ in range(20)]
        # Should produce varying values
        self.assertGreater(max(vals) - min(vals), 1.0)

    def test_congestion_pattern(self):
        gen = NaturalPatternGenerator("congestion", cycle_sec=0.1)
        vals = [gen.get_delay_ms(100) for _ in range(20)]
        self.assertTrue(all(v >= 0 for v in vals))

    def test_distance_pattern(self):
        gen = NaturalPatternGenerator("distance", cycle_sec=0.1)
        vals = [gen.get_drop_chance(30) for _ in range(20)]
        self.assertTrue(all(0 <= v <= 100 for v in vals))

    def test_isp_throttle_pattern(self):
        gen = NaturalPatternGenerator("isp_throttle", cycle_sec=0.1)
        vals = [gen.get_delay_ms(50) for _ in range(20)]
        self.assertTrue(all(v >= 0 for v in vals))


class TestStealthDropModule(unittest.TestCase):
    def test_default_params(self):
        mod = StealthDropModule({})
        self.assertAlmostEqual(mod._base_drop, 30.0)

    def test_returns_bool(self):
        mod = StealthDropModule({"stealth_base_drop": 50})
        addr = _FakeAddr()
        result = mod.process(bytearray(100), addr, None)
        self.assertIsInstance(result, bool)

    def test_some_drops_occur(self):
        mod = StealthDropModule({"stealth_base_drop": 80})
        addr = _FakeAddr()
        drops = sum(mod.process(bytearray(100), addr, None) for _ in range(100))
        self.assertGreater(drops, 0)

    def test_stats(self):
        mod = StealthDropModule({})
        addr = _FakeAddr()
        for _ in range(10):
            mod.process(bytearray(100), addr, None)
        stats = mod.get_stats()
        self.assertEqual(stats["seen"], 10)


class TestSessionFingerprintRotator(unittest.TestCase):
    def test_deterministic_for_same_seed(self):
        r1 = SessionFingerprintRotator(seed="test_seed")
        r2 = SessionFingerprintRotator(seed="test_seed")
        self.assertAlmostEqual(
            r1.vary("delay", 100), r2.vary("delay", 100))

    def test_different_seeds_differ(self):
        r1 = SessionFingerprintRotator(seed="seed_a")
        r2 = SessionFingerprintRotator(seed="seed_b")
        # Different seeds should produce different variations
        # (extremely unlikely to be exactly equal)
        v1 = r1.vary("delay", 100)
        v2 = r2.vary("delay", 100)
        self.assertNotAlmostEqual(v1, v2, places=5)

    def test_variance_bounds(self):
        r = SessionFingerprintRotator(seed="bounds_test")
        for _ in range(100):
            v = r.vary("param", 100.0, variance_pct=0.20)
            self.assertGreater(v, 60)   # 100 * (1 - 0.20) = 80, but some margin
            self.assertLess(v, 140)     # 100 * (1 + 0.20) = 120, but some margin

    def test_get_pattern_returns_valid(self):
        r = SessionFingerprintRotator(seed="pattern_test")
        pattern = r.get_pattern()
        valid = {"wifi_interference", "congestion", "isp_throttle", "distance"}
        self.assertIn(pattern, valid)

    def test_vary_int(self):
        r = SessionFingerprintRotator(seed="int_test")
        result = r.vary_int("count", 10)
        self.assertIsInstance(result, int)
        self.assertGreater(result, 0)


class TestModuleMap(unittest.TestCase):
    def test_stealth_modules_in_map(self):
        self.assertIn("stealth_drop", STEALTH_MODULE_MAP)
        self.assertIn("stealth_lag", STEALTH_MODULE_MAP)


if __name__ == "__main__":
    unittest.main()
