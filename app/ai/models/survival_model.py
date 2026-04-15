"""Survival model for red-disconnect cut duration.

Replaces point-estimate duration regression with a survival curve
``S(t) = P(cut still needs to stay open at time t)``. The operational
question for DupeZ is not "how long will this cut be?" but "how long
must I hold the cut before the hive-flush window has passed?" — that's
a survival problem.

Two estimators live here:

    * :class:`KaplanMeier`  — non-parametric baseline. No features.
      Uses the empirical survival curve of observed cuts where
      ``persisted == False`` is the event of interest (dupe succeeded).
      Right-censored cuts (persisted=True, operator released too early)
      contribute to the risk set without triggering the event, which is
      exactly the behavior the research brief recommended.

    * :class:`KNNSurvival` — feature-conditional. For each prediction
      query we pull the k nearest pre-cut feature vectors from the
      training set and fit a weighted KM over their observed durations.
      With N=26 samples and 28 features this beats any parametric Cox
      fit and keeps the model honest about what it's seen.

Both models expose :meth:`quantile_duration` — the seconds at which the
survival curve drops below ``1 - p``. That's the number the GUI and
smart engine actually want: "cut for this long to dupe at p90 success."

The artefact is still a single pickle so it can drop in behind the
:class:`BaseModel` contract used elsewhere:

    >>> from app.ai.models.survival_model import load_default
    >>> model = load_default()
    >>> if model.ready:
    ...     secs = model.quantile_duration(feat, p=0.9)   # p90 success
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from app.ai.models.base import BaseModel, NullModel, Prediction
from app.logs.logger import log_info, log_warning

__all__ = [
    "KaplanMeier",
    "KNNSurvival",
    "SurvivalDurationModel",
    "load_default",
    "DEFAULT_ARTEFACT",
    "HIVE_FLUSH_FLOOR_S",
    "HARD_KICK_FLOOR_S",
]

# Empirical DayZ combat-log floor — the server holds the character in
# world for ~15 s after disconnect before flushing. Any suggested cut
# shorter than this is a training-data artifact, not a useful prediction.
HIVE_FLUSH_FLOOR_S: float = 15.0

# Practical floor for forcing a BattlEye query-timeout eviction instead
# of a clean combat-log logout. BE's default query cadence means the
# session typically isn't marked unresponsive until ~25–30 s of silence;
# cuts below this value let the server complete a clean save even when
# they clear HIVE_FLUSH_FLOOR_S. Use this as the minimum for any cut
# intended to produce a dupe.
HARD_KICK_FLOOR_S: float = 30.0

DEFAULT_ARTEFACT: Path = Path("app/data/models/survival_model.pkl")


@dataclass
class _KMCurve:
    """Kaplan-Meier survival curve stored as step times and S(t) values."""

    times: np.ndarray        # ascending event times (seconds)
    survival: np.ndarray     # S(t) at each event time, same length as times

    def S(self, t: float) -> float:
        """Evaluate S(t) — survival probability at time t."""
        if self.times.size == 0:
            return 1.0
        if t < self.times[0]:
            return 1.0
        # rightmost index where times[idx] <= t
        idx = int(np.searchsorted(self.times, t, side="right") - 1)
        return float(self.survival[idx])

    def quantile(self, p: float) -> float:
        """Smallest t with S(t) <= 1 - p.

        I.e. "time at which the cumulative failure-of-persistence
        probability reaches p." For p=0.9, returns the duration where
        90% of cuts have already tipped into dupe success.
        """
        if self.times.size == 0:
            return HIVE_FLUSH_FLOOR_S
        threshold = 1.0 - p
        below = np.where(self.survival <= threshold)[0]
        if below.size == 0:
            # Curve never drops that low — return the longest observed cut
            # so the engine doesn't under-cut. Not ideal but honest.
            return float(self.times[-1])
        return float(self.times[below[0]])


def _fit_km(
    durations: Sequence[float],
    events: Sequence[bool],
    weights: Optional[Sequence[float]] = None,
) -> _KMCurve:
    """Fit a (weighted) Kaplan-Meier curve.

    Args:
        durations: observed cut lengths in seconds.
        events:    True if the cut led to a successful dupe (event
                   occurred = persistence was prevented), False if the
                   operator released without a confirmed outcome
                   (right-censored).
        weights:   optional per-sample weights (used by kNN-KM).
    """
    if len(durations) == 0:
        return _KMCurve(times=np.empty(0), survival=np.empty(0))

    d = np.asarray(durations, dtype=np.float64)
    e = np.asarray(events, dtype=bool)
    w = (
        np.ones_like(d)
        if weights is None
        else np.asarray(weights, dtype=np.float64)
    )

    order = np.argsort(d)
    d, e, w = d[order], e[order], w[order]

    unique_times: List[float] = []
    survival: List[float] = []
    S = 1.0
    i = 0
    n = len(d)
    while i < n:
        t = d[i]
        j = i
        events_at_t = 0.0
        weight_at_t = 0.0
        while j < n and d[j] == t:
            weight_at_t += w[j]
            if e[j]:
                events_at_t += w[j]
            j += 1
        # Risk set weight = total weight of samples with duration >= t
        at_risk = float(w[i:].sum())
        if at_risk > 0 and events_at_t > 0:
            S *= max(0.0, 1.0 - events_at_t / at_risk)
        unique_times.append(t)
        survival.append(S)
        i = j

    return _KMCurve(
        times=np.asarray(unique_times, dtype=np.float64),
        survival=np.asarray(survival, dtype=np.float64),
    )


class KaplanMeier(BaseModel):
    """Feature-free KM baseline — the marginal survival curve."""

    def __init__(self, curve: _KMCurve, n_samples: int, n_events: int) -> None:
        self._curve = curve
        self._n_samples = n_samples
        self._n_events = n_events

    @property
    def name(self) -> str:
        return "survival_km"

    @property
    def ready(self) -> bool:
        return self._curve.times.size > 0

    @property
    def curve(self) -> _KMCurve:
        return self._curve

    def predict(self, x: Sequence[float]) -> Prediction:
        # Base contract: return the median survival time.
        return self.quantile_duration(x, p=0.5)

    def quantile_duration(self, x: Sequence[float], p: float = 0.9) -> float:
        t = self._curve.quantile(p)
        return max(HIVE_FLUSH_FLOOR_S, t)

    def meta(self) -> Dict[str, Any]:
        return {
            "n_samples": self._n_samples,
            "n_events":  self._n_events,
            "floor_s":   HIVE_FLUSH_FLOOR_S,
        }


class KNNSurvival(BaseModel):
    """Feature-conditional survival via weighted KM over k neighbors.

    The training set is just a feature matrix plus ``(duration, event)``
    per row. At inference we score the query against every row using an
    inverse-distance kernel on standardized features, fit a weighted KM
    over the top-k, and read off the requested quantile.

    This is intentionally lightweight — no parametric assumptions, no
    sklearn dep beyond numpy. At N=26 that's the right trade. When N
    grows past ~100 a Cox PH or DeepSurv swap becomes worthwhile.
    """

    def __init__(
        self,
        features: np.ndarray,
        durations: np.ndarray,
        events: np.ndarray,
        feature_names: Sequence[str],
        k: int = 8,
    ) -> None:
        self._features = features.astype(np.float64, copy=False)
        self._durations = durations.astype(np.float64, copy=False)
        self._events = events.astype(bool, copy=False)
        self._feature_names = list(feature_names)
        self._k = max(1, min(int(k), len(features)))

        # Standardize per feature. Degenerate (zero-variance) cols get
        # zero'd so they don't dominate the distance.
        self._mean = self._features.mean(axis=0)
        self._std = self._features.std(axis=0)
        self._std = np.where(self._std < 1e-9, 1.0, self._std)

    @property
    def name(self) -> str:
        return "survival_knn"

    @property
    def ready(self) -> bool:
        return len(self._features) > 0

    def _neighbors(self, x: Sequence[float]) -> Tuple[np.ndarray, np.ndarray]:
        q = (np.asarray(x, dtype=np.float64) - self._mean) / self._std
        X = (self._features - self._mean) / self._std
        d = np.linalg.norm(X - q, axis=1)
        idx = np.argsort(d)[: self._k]
        # Inverse-distance weights with +1 to avoid div-by-zero on exact
        # match (test-mode replay).
        weights = 1.0 / (1.0 + d[idx])
        return idx, weights

    def predict(self, x: Sequence[float]) -> Prediction:
        return self.quantile_duration(x, p=0.5)

    def quantile_duration(self, x: Sequence[float], p: float = 0.9) -> float:
        if len(self._features) == 0:
            return HIVE_FLUSH_FLOOR_S
        idx, w = self._neighbors(x)
        curve = _fit_km(
            durations=self._durations[idx],
            events=self._events[idx],
            weights=w,
        )
        return max(HIVE_FLUSH_FLOOR_S, curve.quantile(p))

    def interval(
        self,
        x: Sequence[float],
        lo_p: float = 0.5,
        hi_p: float = 0.95,
    ) -> Tuple[float, float, float]:
        """(lo, median, hi) duration for a range of success probabilities."""
        return (
            self.quantile_duration(x, lo_p),
            self.quantile_duration(x, 0.75),
            self.quantile_duration(x, hi_p),
        )


class SurvivalDurationModel(BaseModel):
    """Wrapper that prefers the kNN model and falls back to marginal KM."""

    def __init__(
        self,
        knn: Optional[KNNSurvival],
        km: KaplanMeier,
        meta: Dict[str, Any],
    ) -> None:
        self._knn = knn
        self._km = km
        self._meta = meta

    @property
    def name(self) -> str:
        return "duration_regressor"  # preserves GUI wiring key

    @property
    def ready(self) -> bool:
        return (self._knn is not None and self._knn.ready) or self._km.ready

    @property
    def meta(self) -> Dict[str, Any]:
        return dict(self._meta)

    def predict(self, x: Sequence[float]) -> Prediction:
        return self.quantile_duration(x, p=0.5)

    def quantile_duration(self, x: Sequence[float], p: float = 0.9) -> float:
        if self._knn is not None and self._knn.ready:
            return self._knn.quantile_duration(x, p)
        return self._km.quantile_duration(x, p)

    # GUI compat — old "Suggest Duration" button called predict_interval.
    def predict_interval(
        self,
        x: Sequence[float],
        lo_q: float = 0.1,
        hi_q: float = 0.9,
    ) -> Tuple[float, float, float]:
        # lo_q/hi_q are quantiles on the survival axis, i.e. success
        # probabilities. Remap to the wrapper's contract.
        return (
            self.quantile_duration(x, lo_q),
            self.quantile_duration(x, 0.5),
            self.quantile_duration(x, hi_q),
        )


def load_default(path: Path = DEFAULT_ARTEFACT) -> BaseModel:
    """Load the survival model or fall back to a NullModel.

    Falls back to the legacy QRF regressor when the survival artefact is
    missing but the QRF pickle is still around — this keeps the GUI
    "Suggest Duration" button working through the transition.
    """
    if path.exists():
        try:
            with open(path, "rb") as fp:
                artefact = pickle.load(fp)
            knn = artefact.get("knn")
            km = artefact["km"]
            meta = artefact.get("meta", {})
            model = SurvivalDurationModel(knn=knn, km=km, meta=meta)
            log_info(
                f"[MODEL] survival_model loaded "
                f"(n={meta.get('n_samples')}, events={meta.get('n_events')}, "
                f"trained_at={meta.get('trained_at')})"
            )
            return model
        except Exception as exc:  # pragma: no cover
            log_warning(f"[MODEL] survival_model load failed: {exc}")

    # Legacy fallback — try the QRF pickle so the button still works.
    try:
        from app.ai.models.duration_regressor import load_default as _legacy
        legacy = _legacy()
        if legacy.ready:
            log_info("[MODEL] survival_model missing — using legacy QRF")
            return legacy
    except Exception:
        pass

    return NullModel(name="duration_regressor", default=HIVE_FLUSH_FLOOR_S)
