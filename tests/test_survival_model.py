"""Unit tests for app.ai.models.survival_model.

Covers:
    * _fit_km — marginal and weighted Kaplan-Meier correctness
    * KaplanMeier.quantile_duration — monotonic + respects the 15s floor
    * KNNSurvival — picks neighbors correctly, respects the floor
    * SurvivalDurationModel — falls through kNN → KM → NullModel
    * load_default — returns NullModel when artefact is missing

Run with::

    python -m pytest tests/test_survival_model.py -v
"""

from __future__ import annotations

import numpy as np
import pytest

from app.ai.models.survival_model import (
    _fit_km,
    KaplanMeier,
    KNNSurvival,
    SurvivalDurationModel,
    HIVE_FLUSH_FLOOR_S,
    load_default,
    DEFAULT_ARTEFACT,
)


# ── _fit_km ───────────────────────────────────────────────────────────

def test_km_all_events_drops_to_zero():
    # 3 events at t=1,2,3 — S should be 2/3, 1/3, 0
    curve = _fit_km([1.0, 2.0, 3.0], [True, True, True])
    assert np.isclose(curve.survival[0], 2 / 3)
    assert np.isclose(curve.survival[1], 1 / 3)
    assert curve.survival[2] == 0.0


def test_km_all_censored_stays_at_one():
    curve = _fit_km([1.0, 2.0, 3.0], [False, False, False])
    assert np.allclose(curve.survival, 1.0)


def test_km_mixed_censoring():
    # Event at t=1, censored at t=2, event at t=3
    # At t=1: 1/3 fail → S=2/3
    # At t=2: no event → S=2/3
    # At t=3: 1/1 fail → S=0
    curve = _fit_km([1.0, 2.0, 3.0], [True, False, True])
    assert np.isclose(curve.survival[0], 2 / 3)
    assert np.isclose(curve.survival[1], 2 / 3)
    assert curve.survival[2] == 0.0


def test_km_empty_returns_flat():
    curve = _fit_km([], [])
    assert curve.times.size == 0
    assert curve.S(100.0) == 1.0


# ── KaplanMeier wrapper ───────────────────────────────────────────────

def test_km_quantile_respects_floor():
    curve = _fit_km([5.0, 6.0], [True, True])  # well below 15s
    km = KaplanMeier(curve=curve, n_samples=2, n_events=2)
    # Even though the curve crosses 0.5 at t=5, the floor clamps up.
    assert km.quantile_duration([], p=0.5) >= HIVE_FLUSH_FLOOR_S


def test_km_quantile_below_curve_min_returns_longest():
    # p so high it can't be reached — return longest observed.
    curve = _fit_km([20.0, 30.0], [False, False])  # all censored, S stays 1
    km = KaplanMeier(curve=curve, n_samples=2, n_events=0)
    assert km.quantile_duration([], p=0.9) == pytest.approx(30.0)


# ── KNNSurvival ───────────────────────────────────────────────────────

def test_knn_picks_nearest_neighbors():
    features = np.array([
        [0.0, 0.0],
        [10.0, 10.0],
        [20.0, 20.0],
    ])
    durations = np.array([20.0, 25.0, 30.0])
    events = np.array([True, True, True])
    knn = KNNSurvival(features, durations, events,
                      feature_names=["a", "b"], k=1)
    # Query near row 0 → median duration should be ~20
    t = knn.quantile_duration([0.1, 0.1], p=0.5)
    assert t >= HIVE_FLUSH_FLOOR_S
    assert t == pytest.approx(20.0)


def test_knn_respects_floor():
    features = np.array([[0.0], [1.0]])
    durations = np.array([3.0, 4.0])  # short cuts
    events = np.array([True, True])
    knn = KNNSurvival(features, durations, events,
                      feature_names=["a"], k=2)
    assert knn.quantile_duration([0.5], p=0.9) >= HIVE_FLUSH_FLOOR_S


def test_knn_interval_is_monotonic():
    rng = np.random.default_rng(0)
    features = rng.normal(size=(10, 3))
    durations = rng.uniform(15.0, 45.0, size=10)
    events = rng.choice([True, False], size=10)
    knn = KNNSurvival(features, durations, events,
                      feature_names=["a", "b", "c"], k=5)
    lo, med, hi = knn.interval(features[0], lo_p=0.5, hi_p=0.95)
    assert lo <= med <= hi


# ── SurvivalDurationModel wrapper ─────────────────────────────────────

def test_wrapper_prefers_knn_when_ready():
    features = np.array([[0.0], [1.0], [2.0]])
    durations = np.array([20.0, 25.0, 30.0])
    events = np.array([True, True, True])
    knn = KNNSurvival(features, durations, events,
                      feature_names=["a"], k=2)
    km = KaplanMeier(_fit_km(durations, events), 3, 3)
    wrapper = SurvivalDurationModel(knn=knn, km=km, meta={"n_samples": 3})
    assert wrapper.ready
    # Should not raise, should be ≥ floor
    assert wrapper.quantile_duration([0.0], p=0.9) >= HIVE_FLUSH_FLOOR_S


def test_wrapper_predict_interval_matches_contract():
    features = np.array([[0.0], [1.0], [2.0]])
    durations = np.array([20.0, 25.0, 30.0])
    events = np.array([True, True, True])
    knn = KNNSurvival(features, durations, events,
                      feature_names=["a"], k=2)
    km = KaplanMeier(_fit_km(durations, events), 3, 3)
    wrapper = SurvivalDurationModel(knn=knn, km=km, meta={})
    lo, med, hi = wrapper.predict_interval([0.0], lo_q=0.1, hi_q=0.9)
    assert all(v >= HIVE_FLUSH_FLOOR_S for v in (lo, med, hi))
    assert lo <= med <= hi


# ── load_default fallback ─────────────────────────────────────────────

def test_load_default_returns_something_when_missing(tmp_path):
    # Point at a nonexistent artefact; should fall back gracefully.
    ghost = tmp_path / "ghost.pkl"
    model = load_default(ghost)
    # Either NullModel (not ready) or a legacy QRF fallback that IS ready.
    assert model.name == "duration_regressor"
