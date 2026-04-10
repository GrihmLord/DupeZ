#!/usr/bin/env python3
"""Tests for v5 Phase 1: Statistical Disruption Models."""

import sys
import time
import unittest
from unittest.mock import MagicMock

# Skip on non-Windows (ctypes.windll not available)
if sys.platform != "win32":
    # Mock the native_divert_engine imports for testing
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


from app.firewall.statistical_models import (
    GilbertElliottDropModule,
    ParetoLagModule,
    TokenBucketDropModule,
    CorrelatedDropModule,
    STATISTICAL_MODULE_MAP,
)


class _FakeAddr:
    Outbound = False


class TestGilbertElliottDropModule(unittest.TestCase):
    """Tests for the Gilbert-Elliott two-state Markov chain drop module."""

    def test_default_params(self):
        mod = GilbertElliottDropModule({})
        self.assertEqual(mod._p_good_to_bad, 0.05)
        self.assertEqual(mod._p_bad_to_good, 0.30)
        self.assertEqual(mod._state, mod._STATE_GOOD)

    def test_custom_params(self):
        mod = GilbertElliottDropModule({
            "ge_p_good_to_bad": 0.10,
            "ge_p_bad_to_good": 0.50,
            "ge_p_loss_good": 0.02,
            "ge_p_loss_bad": 0.90,
        })
        self.assertAlmostEqual(mod._p_good_to_bad, 0.10)
        self.assertAlmostEqual(mod._p_bad_to_good, 0.50)

    def test_params_clamped(self):
        mod = GilbertElliottDropModule({
            "ge_p_good_to_bad": 5.0,  # should clamp to 1.0
            "ge_p_bad_to_good": -1.0,  # should clamp to 0.0
        })
        self.assertEqual(mod._p_good_to_bad, 1.0)
        self.assertEqual(mod._p_bad_to_good, 0.0)

    def test_process_returns_bool(self):
        mod = GilbertElliottDropModule({})
        addr = _FakeAddr()
        result = mod.process(bytearray(100), addr, None)
        self.assertIsInstance(result, bool)

    def test_statistical_behavior(self):
        """Run many packets and verify loss rate is in reasonable range."""
        mod = GilbertElliottDropModule({
            "ge_p_good_to_bad": 0.05,
            "ge_p_bad_to_good": 0.30,
            "ge_p_loss_good": 0.0,
            "ge_p_loss_bad": 1.0,
        })
        addr = _FakeAddr()
        drops = sum(mod.process(bytearray(100), addr, None) for _ in range(10000))
        rate = drops / 10000
        # Theoretical: ~14.3% (0.05 / (0.05 + 0.30))
        # Allow wide tolerance for randomness
        self.assertGreater(rate, 0.02)
        self.assertLess(rate, 0.40)

    def test_all_bad_state(self):
        """100% transition to bad, 0% back = permanent bad state."""
        mod = GilbertElliottDropModule({
            "ge_p_good_to_bad": 1.0,
            "ge_p_bad_to_good": 0.0,
            "ge_p_loss_bad": 1.0,
        })
        addr = _FakeAddr()
        # After first packet transitions to bad, all should drop
        _ = mod.process(bytearray(100), addr, None)  # triggers transition
        drops = sum(mod.process(bytearray(100), addr, None) for _ in range(100))
        self.assertEqual(drops, 100)

    def test_get_stats(self):
        mod = GilbertElliottDropModule({})
        addr = _FakeAddr()
        for _ in range(50):
            mod.process(bytearray(100), addr, None)
        stats = mod.get_stats()
        self.assertIn("state", stats)
        self.assertIn("packets_seen", stats)
        self.assertEqual(stats["packets_seen"], 50)

    def test_steady_state_loss_calculation(self):
        mod = GilbertElliottDropModule({
            "ge_p_good_to_bad": 0.10,
            "ge_p_bad_to_good": 0.40,
            "ge_p_loss_bad": 1.0,
            "ge_p_loss_good": 0.0,
        })
        # Theoretical: 0.10 / (0.10 + 0.40) = 0.20
        self.assertAlmostEqual(mod._steady_state_loss(), 0.20, places=2)


class TestTokenBucketDropModule(unittest.TestCase):
    """Tests for the token bucket rate limiter."""

    def test_default_params(self):
        mod = TokenBucketDropModule({})
        self.assertEqual(mod._rate, 5120)
        self.assertEqual(mod._capacity, 8192)

    def test_full_bucket_passes(self):
        """Packets should pass when bucket is full."""
        mod = TokenBucketDropModule({"tb_bucket_capacity": 10000, "tb_rate_bytes_sec": 10000})
        addr = _FakeAddr()
        result = mod.process(bytearray(100), addr, None)
        self.assertFalse(result)  # should pass

    def test_empty_bucket_drops(self):
        """Packets should drop when bucket is empty."""
        mod = TokenBucketDropModule({
            "tb_bucket_capacity": 50,
            "tb_rate_bytes_sec": 1,
            "tb_initial_tokens": 0,
        })
        addr = _FakeAddr()
        result = mod.process(bytearray(100), addr, None)
        self.assertTrue(result)  # should drop — not enough tokens

    def test_bucket_drains(self):
        """Bucket should drain as packets pass."""
        mod = TokenBucketDropModule({
            "tb_bucket_capacity": 500,
            "tb_rate_bytes_sec": 1,  # very slow refill
            "tb_initial_tokens": 500,
        })
        addr = _FakeAddr()
        passed = 0
        for _ in range(20):
            if not mod.process(bytearray(100), addr, None):
                passed += 1
        # Should pass first 5 (500/100=5 tokens), then drop
        self.assertEqual(passed, 5)

    def test_get_stats(self):
        mod = TokenBucketDropModule({})
        stats = mod.get_stats()
        self.assertIn("tokens_remaining", stats)
        self.assertIn("capacity", stats)


class TestCorrelatedDropModule(unittest.TestCase):
    """Tests for the correlated drop module."""

    def test_default_params(self):
        mod = CorrelatedDropModule({})
        self.assertAlmostEqual(mod._base_chance, 20.0)
        self.assertAlmostEqual(mod._correlation, 0.50)

    def test_zero_correlation_is_uniform(self):
        """With zero correlation, should behave like uniform random."""
        mod = CorrelatedDropModule({
            "corr_drop_chance": 50,
            "corr_correlation": 0.0,
        })
        addr = _FakeAddr()
        drops = sum(mod.process(bytearray(100), addr, None) for _ in range(10000))
        rate = drops / 10000
        # Should be ~50% ± tolerance
        self.assertGreater(rate, 0.40)
        self.assertLess(rate, 0.60)

    def test_high_correlation_produces_bursts(self):
        """High correlation should produce longer runs of drops/passes."""
        mod = CorrelatedDropModule({
            "corr_drop_chance": 50,
            "corr_correlation": 0.95,
        })
        addr = _FakeAddr()
        results = [mod.process(bytearray(100), addr, None) for _ in range(1000)]
        # Count state changes
        changes = sum(1 for i in range(1, len(results)) if results[i] != results[i-1])
        # High correlation = fewer changes
        # Low correlation (uniform) would give ~500 changes
        self.assertLess(changes, 250)


class TestParetoLagModule(unittest.TestCase):
    """Tests for the Pareto jitter lag module."""

    def test_default_params(self):
        mod = ParetoLagModule({})
        self.assertEqual(mod._base_ms, 50)
        self.assertEqual(mod._jitter_ms, 200)

    def test_sample_pareto_positive(self):
        mod = ParetoLagModule({})
        for _ in range(100):
            sample = mod._sample_pareto()
            self.assertGreaterEqual(sample, 0)

    def test_sample_delay_within_cap(self):
        mod = ParetoLagModule({"pareto_cap_ms": 500})
        for _ in range(100):
            delay = mod._sample_delay()
            self.assertLessEqual(delay, 500)
            self.assertGreaterEqual(delay, 0)

    def test_delay_distribution_has_heavy_tail(self):
        """Most delays should be small, but some should be large."""
        mod = ParetoLagModule({
            "pareto_base_ms": 0,
            "pareto_jitter_ms": 100,
            "pareto_alpha": 1.5,
            "pareto_cap_ms": 10000,
        })
        delays = [mod._sample_delay() for _ in range(1000)]
        median = sorted(delays)[500]
        p95 = sorted(delays)[950]
        # Heavy tail: p95 should be much larger than median
        self.assertGreater(p95, median * 2)


class TestModuleMap(unittest.TestCase):
    """Verify statistical modules are properly registered."""

    def test_all_modules_in_map(self):
        self.assertIn("ge_drop", STATISTICAL_MODULE_MAP)
        self.assertIn("pareto_lag", STATISTICAL_MODULE_MAP)
        self.assertIn("token_bucket", STATISTICAL_MODULE_MAP)
        self.assertIn("corr_drop", STATISTICAL_MODULE_MAP)

    def test_module_classes_are_correct(self):
        self.assertEqual(STATISTICAL_MODULE_MAP["ge_drop"], GilbertElliottDropModule)
        self.assertEqual(STATISTICAL_MODULE_MAP["token_bucket"], TokenBucketDropModule)


if __name__ == "__main__":
    unittest.main()
