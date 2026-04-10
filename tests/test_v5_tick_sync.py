#!/usr/bin/env python3
"""Tests for v5 Phase 3: Tick-Synchronized Disruption."""

import sys
import time
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


from app.firewall.tick_sync import (
    TickEstimator,
    TickSyncDropModule,
    PulseDisruptionModule,
    TICK_SYNC_MODULE_MAP,
)


class _FakeAddr:
    Outbound = False


class TestTickEstimator(unittest.TestCase):
    def test_no_data_returns_zero(self):
        est = TickEstimator()
        self.assertEqual(est.estimated_tick_hz, 0.0)
        self.assertEqual(est.confidence, 0.0)

    def test_regular_intervals_detected(self):
        """Feed packets at ~30Hz and verify tick rate estimation."""
        est = TickEstimator(window_size=60, min_samples=20)
        base = time.monotonic()
        interval = 1.0 / 30  # 30 Hz = ~33.3ms

        for i in range(50):
            est.update(base + i * interval)

        # Should estimate ~30 Hz
        self.assertGreater(est.estimated_tick_hz, 20)
        self.assertLess(est.estimated_tick_hz, 45)
        self.assertGreater(est.confidence, 0.3)

    def test_irregular_intervals_low_confidence(self):
        """Irregular timing should produce lower confidence."""
        import random
        est = TickEstimator(window_size=60, min_samples=20)
        base = time.monotonic()

        for i in range(50):
            # Very noisy timestamps
            est.update(base + i * 0.033 + random.uniform(-0.02, 0.02))

        # Confidence should be lower than regular
        # (still might estimate something, but less confident)
        self.assertLess(est.confidence, 0.9)

    def test_get_stats(self):
        est = TickEstimator()
        stats = est.get_stats()
        self.assertIn("tick_hz", stats)
        self.assertIn("confidence", stats)
        self.assertIn("samples", stats)

    def test_next_tick_time_without_data(self):
        est = TickEstimator()
        now = time.monotonic()
        result = est.get_next_tick_time(now)
        self.assertEqual(result, now)


class TestTickSyncDropModule(unittest.TestCase):
    def test_default_params(self):
        mod = TickSyncDropModule({})
        self.assertTrue(mod._learning)
        self.assertEqual(mod._learning_packets, 100)

    def test_learning_phase_passes_all(self):
        """During learning phase, no packets should be dropped."""
        mod = TickSyncDropModule({"ts_learning_packets": 1000})
        addr = _FakeAddr()
        drops = sum(mod.process(bytearray(100), addr, None) for _ in range(50))
        self.assertEqual(drops, 0)

    def test_get_stats(self):
        mod = TickSyncDropModule({})
        stats = mod.get_stats()
        self.assertTrue(stats["learning"])


class TestPulseDisruptionModule(unittest.TestCase):
    def test_default_params(self):
        mod = PulseDisruptionModule({})
        self.assertEqual(mod._burst_ticks, 3)
        self.assertEqual(mod._rest_ticks, 5)
        self.assertTrue(mod._learning)

    def test_learning_phase_passes_all(self):
        mod = PulseDisruptionModule({"pulse_learning": 500})
        addr = _FakeAddr()
        drops = sum(mod.process(bytearray(100), addr, None) for _ in range(50))
        self.assertEqual(drops, 0)

    def test_get_stats(self):
        mod = PulseDisruptionModule({})
        stats = mod.get_stats()
        self.assertIn("cycle", stats)
        self.assertEqual(stats["cycle"], "3B/5R")


class TestModuleMap(unittest.TestCase):
    def test_tick_sync_in_map(self):
        self.assertIn("tick_sync", TICK_SYNC_MODULE_MAP)
        self.assertIn("pulse", TICK_SYNC_MODULE_MAP)


if __name__ == "__main__":
    unittest.main()
