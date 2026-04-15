# app/ai/flush_predictor.py — Hive-flush timing predictor (P5)
"""Answers "how much longer can I hold this cut before the hive flushes?"

Closes gap G10 from the competitive audit. The learning loop already
aggregates labeled episodes into direction/duration recommendations;
this module adds a *time-indexed* view of the same data so the operator
gets a live countdown while the cut is open.

Method
------
For a given ``(target_profile, goal, network_class)`` bucket we split
labeled episodes into two populations:

* **Successes** — ``outcome=True`` (``persisted=False`` in episode JSON):
  the hive did NOT flush. We took the cut down voluntarily; these
  durations are the "safe ceiling" evidence.
* **Failures** — ``outcome=False`` (``persisted=True``): the hive
  flushed. These durations tell us *when* flushes happen.

From those two populations we derive, per bucket:

    safe_ceiling_s     = P90 of successful-cut durations
    recommended_stop_s = P50 of successful-cut durations  (the engine's
                         auto-tune already emits this)
    danger_floor_s     = P10 of failed-cut durations
    p_flush_at(t)      = empirical CDF of failure durations at t

The live call ``predict(elapsed_s)`` returns all four plus a
``recommendation`` ∈ {``HOLD``, ``WARN``, ``STOP_NOW``}:

    elapsed < recommended_stop_s              → HOLD
    recommended_stop_s ≤ elapsed < danger_floor → WARN
    elapsed ≥ danger_floor                    → STOP_NOW

Below ``MIN_EPISODES_FOR_PREDICT`` labeled episodes the predictor
returns ``None`` and callers should fall back to the profile default
(dayz.json disconnect_duration_ms).

Design constraints
------------------
* **Pure Python, zero deps.** Uses stdlib ``statistics`` and the already
  built ``LearningLoop`` cache. No numpy, no scikit — this has to run
  alongside the packet hot path without adding import cost.
* **Cached.** ``predict()`` is called ~1 Hz during a cut. We compute
  the per-bucket stats once per LearningLoop refresh and memoize.
* **Read-only.** Predictor never mutates episodes or the cache.
"""

from __future__ import annotations

import statistics
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple

from app.ai.learning_loop import (
    LearningLoop,
    EpisodeSummary,
    MIN_EPISODES_FOR_RECS,
)
from app.logs.logger import log_info

__all__ = [
    "FlushPrediction",
    "FlushPredictor",
    "FlushAction",
    "MIN_EPISODES_FOR_PREDICT",
]

# Predictor can run with fewer samples than the recommender because a
# per-duration CDF tolerates noise better than a direction/method vote.
MIN_EPISODES_FOR_PREDICT: int = 3


class FlushAction(str, Enum):
    HOLD = "hold"             # Below recommended stop — keep cutting
    WARN = "warn"             # Past recommended, before danger — wrap it up
    STOP_NOW = "stop_now"     # Past danger floor — hive likely flushing
    UNKNOWN = "unknown"       # Not enough data


@dataclass(frozen=True)
class FlushPrediction:
    sample_size: int
    success_count: int
    fail_count: int
    safe_ceiling_s: Optional[float]         # P90 of successful cuts
    recommended_stop_s: Optional[float]     # P50 of successful cuts
    danger_floor_s: Optional[float]         # P10 of failed cuts
    p_flush_at_elapsed: Optional[float]     # empirical CDF at elapsed_s
    elapsed_s: float
    action: FlushAction
    reason: str
    bucket: Tuple[str, str, str]            # (profile, goal, network_class)


@dataclass(frozen=True)
class _BucketStats:
    success_durations: Tuple[float, ...]
    fail_durations: Tuple[float, ...]
    safe_ceiling_s: Optional[float]
    recommended_stop_s: Optional[float]
    danger_floor_s: Optional[float]


def _percentile(sorted_vals: List[float], pct: float) -> Optional[float]:
    """Nearest-rank percentile. ``sorted_vals`` must be sorted ascending.
    ``pct`` in [0, 100]."""
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    # Linear interpolation between ranks
    k = (len(sorted_vals) - 1) * (pct / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = k - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def _empirical_cdf(sorted_vals: List[float], x: float) -> float:
    """Fraction of ``sorted_vals`` that are ≤ ``x``. Binary search."""
    if not sorted_vals:
        return 0.0
    lo, hi = 0, len(sorted_vals)
    while lo < hi:
        mid = (lo + hi) // 2
        if sorted_vals[mid] <= x:
            lo = mid + 1
        else:
            hi = mid
    return lo / len(sorted_vals)


class FlushPredictor:
    """Time-indexed view of LearningLoop episodes.

    One instance per process; shares an underlying ``LearningLoop`` by
    default so both the recommender and predictor rescan disk at most
    once per cache cycle.
    """

    def __init__(self, loop: Optional[LearningLoop] = None) -> None:
        self._loop: LearningLoop = loop if loop is not None else LearningLoop()
        self._lock = threading.Lock()
        self._stats_cache: Dict[Tuple[str, str, str], _BucketStats] = {}
        self._cache_fingerprint: int = 0

    # ------------------------------------------------------------------
    def predict(
        self,
        target_profile: str,
        goal: str,
        elapsed_s: float,
        network_class: str = "unknown",
    ) -> Optional[FlushPrediction]:
        """Return a live prediction for the current cut, or None if the
        bucket has fewer than ``MIN_EPISODES_FOR_PREDICT`` labeled
        episodes."""
        bucket = (target_profile, goal, network_class)
        stats = self._get_stats(bucket)
        if stats is None:
            return None

        total = len(stats.success_durations) + len(stats.fail_durations)
        if total < MIN_EPISODES_FOR_PREDICT:
            return None

        # Empirical flush CDF evaluated at elapsed_s
        sorted_fails = list(stats.fail_durations)
        p_flush = _empirical_cdf(sorted_fails, float(elapsed_s)) if sorted_fails else None

        # Decide action
        rec_stop = stats.recommended_stop_s
        danger = stats.danger_floor_s

        if rec_stop is None and danger is None:
            action = FlushAction.UNKNOWN
            reason = "no duration signal available"
        elif danger is not None and elapsed_s >= danger:
            action = FlushAction.STOP_NOW
            reason = (f"elapsed {elapsed_s:.1f}s ≥ danger floor "
                      f"{danger:.1f}s (p10 of flush events)")
        elif rec_stop is not None and elapsed_s >= rec_stop:
            action = FlushAction.WARN
            reason = (f"elapsed {elapsed_s:.1f}s past recommended stop "
                      f"{rec_stop:.1f}s (median successful cut)")
        else:
            action = FlushAction.HOLD
            reason = (f"elapsed {elapsed_s:.1f}s under recommended stop "
                      f"{rec_stop:.1f}s" if rec_stop is not None
                      else f"elapsed {elapsed_s:.1f}s, no stop signal")

        return FlushPrediction(
            sample_size=total,
            success_count=len(stats.success_durations),
            fail_count=len(stats.fail_durations),
            safe_ceiling_s=stats.safe_ceiling_s,
            recommended_stop_s=stats.recommended_stop_s,
            danger_floor_s=stats.danger_floor_s,
            p_flush_at_elapsed=p_flush,
            elapsed_s=float(elapsed_s),
            action=action,
            reason=reason,
            bucket=bucket,
        )

    # ------------------------------------------------------------------
    def _get_stats(self, bucket: Tuple[str, str, str]) -> Optional[_BucketStats]:
        """Compute (or fetch cached) per-bucket duration stats. Rebuilds
        when the underlying episode set changes size."""
        episodes = self._loop.all_episodes()
        fingerprint = len(episodes)

        with self._lock:
            if fingerprint != self._cache_fingerprint:
                self._stats_cache.clear()
                self._cache_fingerprint = fingerprint
            cached = self._stats_cache.get(bucket)
            if cached is not None:
                return cached

        profile, goal, netclass = bucket
        matching: List[EpisodeSummary] = [
            e for e in episodes
            if e.target_profile == profile
            and e.goal == goal
            and (netclass == "unknown" or e.network_class == netclass)
            and e.outcome is not None
        ]

        if not matching:
            return None

        successes = sorted(
            e.duration_s for e in matching
            if e.outcome is True and e.duration_s > 0.0
        )
        failures = sorted(
            e.duration_s for e in matching
            if e.outcome is False and e.duration_s > 0.0
        )

        stats = _BucketStats(
            success_durations=tuple(successes),
            fail_durations=tuple(failures),
            safe_ceiling_s=_percentile(successes, 90.0),
            recommended_stop_s=(
                statistics.median(successes) if successes else None
            ),
            danger_floor_s=_percentile(failures, 10.0),
        )

        with self._lock:
            self._stats_cache[bucket] = stats

        log_info(
            f"[FLUSH] bucket {bucket} stats: "
            f"n_success={len(successes)} n_fail={len(failures)} "
            f"rec_stop={stats.recommended_stop_s} "
            f"danger={stats.danger_floor_s} "
            f"safe_ceil={stats.safe_ceiling_s}"
        )
        return stats

    # ------------------------------------------------------------------
    def bucket_size(
        self,
        target_profile: str,
        goal: str,
        network_class: str = "unknown",
    ) -> int:
        """Count labeled episodes in a bucket. Cheap; for gating."""
        stats = self._get_stats((target_profile, goal, network_class))
        if stats is None:
            return 0
        return len(stats.success_durations) + len(stats.fail_durations)
