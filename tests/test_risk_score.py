"""Tests for app.core.risk_score (v5.7.0 feature #5).

Covers band classification, individual factor scaling, and the
guaranteed-non-raising contract of compute_risk_score.
"""

from __future__ import annotations

import pytest

from app.core.risk_score import (
    RiskBand,
    RiskScore,
    _classify_band,
    _compression_contribution,
    _failure_streak_contribution,
    _never_cut_contribution,
    _rate_contribution,
    _scale,
    _success_rate_contribution,
    compute_risk_score,
)


class TestBandClassification:
    """Boundary conditions for GREEN/AMBER/RED."""

    def test_zero_is_green(self) -> None:
        assert _classify_band(0) == RiskBand.GREEN

    def test_below_green_max_is_green(self) -> None:
        assert _classify_band(29) == RiskBand.GREEN

    def test_at_green_max_is_amber(self) -> None:
        # 30 is the band boundary — should be AMBER (excl. upper of GREEN).
        assert _classify_band(30) == RiskBand.AMBER

    def test_below_amber_max_is_amber(self) -> None:
        assert _classify_band(69) == RiskBand.AMBER

    def test_at_amber_max_is_red(self) -> None:
        assert _classify_band(70) == RiskBand.RED

    def test_max_is_red(self) -> None:
        assert _classify_band(100) == RiskBand.RED


class TestScale:
    """_scale clamps to [0, cap] and never divides by zero."""

    def test_zero_denominator_returns_zero(self) -> None:
        assert _scale(10, 0, 100) == 0

    def test_negative_denominator_returns_zero(self) -> None:
        assert _scale(10, -1, 100) == 0

    def test_basic_proportional(self) -> None:
        assert _scale(5, 10, 100) == 50

    def test_clamps_above_cap(self) -> None:
        # Even when ratio > 1, result clamps to cap.
        assert _scale(20, 10, 25) == 25

    def test_clamps_below_zero(self) -> None:
        assert _scale(-5, 10, 100) == 0


class TestRateContribution:
    """Recent cut rate — 30-min window, threshold 6, cap 25."""

    def test_no_recent_cuts_returns_zero(self) -> None:
        c = _rate_contribution([], 1000.0)
        assert c.value == 0

    def test_under_threshold_returns_zero(self) -> None:
        now = 1000.0
        # 5 cuts inside the 30m window — under threshold of 6.
        times = [now - i * 60 for i in range(5)]
        c = _rate_contribution(times, now)
        assert c.value == 0

    def test_at_threshold_returns_zero(self) -> None:
        now = 1000.0
        # Exactly 6 cuts — at threshold, no contribution yet.
        times = [now - i * 60 for i in range(6)]
        c = _rate_contribution(times, now)
        assert c.value == 0

    def test_over_threshold_scales(self) -> None:
        now = 1000.0
        # 12 cuts in window = 6 over threshold = full cap.
        times = [now - i * 60 for i in range(12)]
        c = _rate_contribution(times, now)
        assert c.value == c.cap

    def test_old_cuts_outside_window_ignored(self) -> None:
        now = 1000.0
        # All cuts more than 30m old — should not count.
        old = now - 60 * 60  # 60 minutes ago
        times = [old, old + 1, old + 2]
        c = _rate_contribution(times, now)
        assert c.value == 0


class TestFailureStreakContribution:
    """Failure streak — last 5 labeled outcomes."""

    def test_no_outcomes_returns_zero(self) -> None:
        c = _failure_streak_contribution([])
        assert c.value == 0

    def test_all_successes_returns_zero(self) -> None:
        c = _failure_streak_contribution([True, True, True])
        assert c.value == 0

    def test_all_failures_returns_cap(self) -> None:
        c = _failure_streak_contribution([False, False, False, False, False])
        assert c.value == c.cap

    def test_unlabeled_outcomes_skipped(self) -> None:
        # None means "not labeled" — should not count toward streak.
        c = _failure_streak_contribution([None, None, None])
        assert c.value == 0

    def test_only_first_five_labeled_count(self) -> None:
        # 5 most recent labeled failures = full cap regardless of older entries.
        outcomes = [False] * 5 + [True] * 100
        c = _failure_streak_contribution(outcomes)
        assert c.value == c.cap


class TestSuccessRateContribution:
    """Success rate shortfall vs 50% floor."""

    def test_too_few_labeled_returns_zero(self) -> None:
        # Need at least 3 labeled episodes to draw any conclusion.
        c = _success_rate_contribution({"labeled": 2, "success_rate": 0.0})
        assert c.value == 0

    def test_at_floor_returns_zero(self) -> None:
        c = _success_rate_contribution(
            {"labeled": 10, "success_rate": 0.5}
        )
        assert c.value == 0

    def test_above_floor_returns_zero(self) -> None:
        c = _success_rate_contribution(
            {"labeled": 10, "success_rate": 0.9}
        )
        assert c.value == 0

    def test_zero_success_rate_returns_cap(self) -> None:
        # Full shortfall — operator hasn't landed any cuts.
        c = _success_rate_contribution(
            {"labeled": 10, "success_rate": 0.0}
        )
        assert c.value == c.cap


class TestCompressionContribution:
    """Cuts <60s apart accrue points."""

    def test_too_few_cuts_returns_zero(self) -> None:
        c = _compression_contribution([1000.0])
        assert c.value == 0

    def test_widely_spaced_cuts_returns_zero(self) -> None:
        times = [1000.0, 2000.0, 3000.0]  # 1000s apart each
        c = _compression_contribution(times)
        assert c.value == 0

    def test_all_close_pairs_accrue(self) -> None:
        # 10 cuts back-to-back at 5s spacing — all pairs <60s apart.
        times = [1000.0 + i * 5 for i in range(10)]
        c = _compression_contribution(times)
        # 9 close pairs out of 10 cuts → 90% → close to cap
        assert c.value > 0


class TestNeverCutContribution:
    """High never-cut ratio means presets aren't landing."""

    def test_too_few_episodes_returns_zero(self) -> None:
        c = _never_cut_contribution({"total": 4, "never_cut": 4})
        assert c.value == 0

    def test_below_floor_returns_zero(self) -> None:
        # 25% never-cut is under the 30% floor.
        c = _never_cut_contribution({"total": 100, "never_cut": 25})
        assert c.value == 0

    def test_above_floor_scales(self) -> None:
        c = _never_cut_contribution({"total": 100, "never_cut": 100})
        # 100% never-cut → full cap
        assert c.value == c.cap


class TestComputeRiskScore:
    """End-to-end: never raises, returns valid RiskScore."""

    def test_returns_valid_riskscore(self) -> None:
        score = compute_risk_score()
        assert isinstance(score, RiskScore)
        assert 0 <= score.score <= 100
        assert score.band in (RiskBand.GREEN, RiskBand.AMBER, RiskBand.RED)
        assert score.contributions  # at least one factor reported
        assert score.advisory

    def test_score_within_bounds_on_repeated_calls(self) -> None:
        # Sanity: repeated calls produce a number in range.
        for _ in range(3):
            s = compute_risk_score()
            assert 0 <= s.score <= 100
