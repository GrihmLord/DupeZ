#!/usr/bin/env python3
"""Streaming TickEstimator equivalence tests.

Verifies the two-heap median + sum/sum_sq variance refactor produces
the same tick_hz and confidence as the previous statistics.median /
statistics.stdev implementation, including under sliding-window eviction.
"""

from __future__ import annotations

import math
import random
import statistics
import sys
import types
import unittest


# Mock native engine on non-Windows (must run before tick_sync import)
if sys.platform != "win32" and "app.firewall.native_divert_engine" not in sys.modules:
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


from app.firewall.tick_sync import TickEstimator  # noqa: E402


def _reference(iats):
    """Ground truth using the stdlib routines the old impl used."""
    if not iats:
        return 0.0, 0.0
    med = statistics.median(iats)
    if len(iats) >= 2:
        sd = statistics.stdev(iats)
    else:
        sd = 0.0
    cv = sd / med if med > 0 else 1.0
    confidence = max(0.0, min(1.0, 1.0 - cv))
    hz = (1.0 / med) if med > 0 else 0.0
    return hz, confidence


class TestStreamingMedian(unittest.TestCase):
    def test_median_matches_stdlib_exact(self):
        """Median from heap state must equal statistics.median() exactly."""
        est = TickEstimator(window_size=120, min_samples=20)
        rng = random.Random(0xC0FFEE)
        t = 1000.0
        for _ in range(250):
            iat = rng.uniform(0.005, 0.100)
            t += iat
            est.update(t)
            window = list(est._iats)  # noqa: SLF001
            if len(window) >= 2:
                expected = statistics.median(window)
                self.assertAlmostEqual(
                    est._median_value(), expected, places=12,  # noqa: SLF001
                    msg=f"median drift at window_size={len(window)}",
                )

    def test_confidence_matches_stdlib_within_tolerance(self):
        """CV-based confidence must match within float noise tolerance."""
        est = TickEstimator(window_size=120, min_samples=20)
        rng = random.Random(0xBEEF)
        t = 1000.0
        for _ in range(400):
            t += rng.uniform(0.020, 0.050)
            est.update(t)
        window = list(est._iats)  # noqa: SLF001
        hz_ref, conf_ref = _reference(window)
        self.assertAlmostEqual(est.estimated_tick_hz, hz_ref, places=9)
        self.assertAlmostEqual(est.confidence, conf_ref, places=9)

    def test_sliding_eviction_preserves_state(self):
        """After exceeding window_size, state must reflect only recent samples."""
        est = TickEstimator(window_size=50, min_samples=20)
        t = 1000.0
        # Phase 1: 30Hz traffic
        for _ in range(60):
            t += 1.0 / 30
            est.update(t)
        # Phase 2: 60Hz traffic — fully displaces phase 1
        for _ in range(60):
            t += 1.0 / 60
            est.update(t)
        # Should now estimate ~60Hz, not blended
        self.assertGreater(est.estimated_tick_hz, 50)
        self.assertLess(est.estimated_tick_hz, 70)

    def test_regular_intervals_high_confidence(self):
        est = TickEstimator(window_size=60, min_samples=20)
        t = 1000.0
        for _ in range(50):
            t += 1.0 / 30
            est.update(t)
        self.assertGreater(est.estimated_tick_hz, 25)
        self.assertLess(est.estimated_tick_hz, 35)
        self.assertGreater(est.confidence, 0.9)

    def test_noisy_intervals_low_confidence(self):
        est = TickEstimator(window_size=120, min_samples=20)
        rng = random.Random(42)
        t = 1000.0
        for _ in range(200):
            t += 0.033 + rng.uniform(-0.015, 0.015)
            est.update(t)
        self.assertLess(est.confidence, 0.75)

    def test_variance_never_negative(self):
        """Running sum_sq - n*mean^2 must never yield negative variance."""
        est = TickEstimator(window_size=60, min_samples=20)
        # Constant IAT — variance should be exactly 0
        t = 1000.0
        for _ in range(80):
            t += 0.033
            est.update(t)
        self.assertGreaterEqual(est.confidence, 0.0)
        self.assertLessEqual(est.confidence, 1.0)
        # Confidence should be very high (CV ≈ 0)
        self.assertGreater(est.confidence, 0.99)

    def test_outlier_rejection(self):
        """IATs outside [iat_min, iat_max] should not enter window."""
        est = TickEstimator(window_size=60, min_samples=20)
        t = 1000.0
        # Feed 30 normal + 10 huge gaps (keepalives)
        for i in range(40):
            if i % 4 == 3:
                t += 2.0  # outside iat_max
            else:
                t += 1.0 / 30
            est.update(t)
        # Window should only contain in-range IATs
        self.assertLessEqual(len(est._iats), 30)  # noqa: SLF001

    def test_empty_window_returns_zero_median(self):
        est = TickEstimator()
        self.assertEqual(est._median_value(), 0.0)  # noqa: SLF001

    def test_heap_sizes_match_window(self):
        """lo_size + hi_size must equal len(_iats) at all times."""
        est = TickEstimator(window_size=30, min_samples=10)
        rng = random.Random(7)
        t = 1000.0
        for _ in range(100):
            t += rng.uniform(0.010, 0.060)
            est.update(t)
            total = est._lo_size + est._hi_size  # noqa: SLF001
            self.assertEqual(total, len(est._iats))  # noqa: SLF001
            # Balance invariant
            diff = est._lo_size - est._hi_size  # noqa: SLF001
            self.assertIn(diff, (0, 1))

    def test_running_sum_matches_reconstructed(self):
        """Drift-check: running sum/sum_sq must match recomputed totals."""
        est = TickEstimator(window_size=40, min_samples=10)
        rng = random.Random(13)
        t = 1000.0
        for _ in range(150):
            t += rng.uniform(0.010, 0.080)
            est.update(t)
        iats = list(est._iats)  # noqa: SLF001
        expected_sum = sum(iats)
        expected_sum_sq = sum(x * x for x in iats)
        self.assertTrue(math.isclose(est._sum, expected_sum, rel_tol=1e-9, abs_tol=1e-12))  # noqa: SLF001
        self.assertTrue(math.isclose(est._sum_sq, expected_sum_sq, rel_tol=1e-9, abs_tol=1e-12))  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
