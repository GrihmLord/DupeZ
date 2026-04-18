"""Inference-side wrapper for the trained cut-duration regressor.

Online callers (GUI "suggest duration" button, smart engine, voice
control) import :func:`load_default` and get either the real model or a
:class:`NullModel` fallback when the artefact is missing, so the app
still boots on a clean checkout.

Usage::

    from app.ai.models.duration_regressor import load_default
    model = load_default()
    if model.ready:
        suggestion = model.predict(feature_vector)   # median seconds
        lo, med, hi = model.predict_interval(feature_vector, 0.1, 0.9)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from app.ai.models.base import BaseModel, NullModel, Prediction
from app.core.model_integrity import (
    ModelIntegrityError,
    load_artefact as _load_signed_artefact,
)
from app.logs.logger import log_info, log_warning

__all__ = ["DurationRegressor", "load_default", "DEFAULT_ARTEFACT"]

DEFAULT_ARTEFACT: Path = Path("app/data/models/duration_regressor.pkl")


class DurationRegressor(BaseModel):
    """Quantile-capable random forest regressor for cut duration (seconds).

    Quantiles are computed from the distribution of per-tree predictions
    on the input sample — no extra dependency on ``quantile-forest``.
    """

    def __init__(self, artefact: Dict[str, Any]) -> None:
        self._artefact = artefact
        self._model = artefact["model"]
        self._feature_names: List[str] = artefact.get("feature_names", [])
        self._median_fallback: float = float(artefact.get("median_s", 5.0))

    @property
    def name(self) -> str:
        return "duration_regressor"

    @property
    def ready(self) -> bool:
        return self._model is not None

    @property
    def meta(self) -> Dict[str, Any]:
        return {
            "n_samples":  self._artefact.get("n_samples"),
            "cv_mae_s":   self._artefact.get("cv_mae_s"),
            "trained_at": self._artefact.get("trained_at"),
            "real_only":  self._artefact.get("real_only"),
        }

    def predict(self, x: Sequence[float]) -> Prediction:
        """Return the median predicted cut duration (seconds)."""
        pred = self._model.predict([list(x)])
        return float(pred[0])

    def predict_interval(
        self,
        x: Sequence[float],
        lo_q: float = 0.1,
        hi_q: float = 0.9,
    ) -> Tuple[float, float, float]:
        """Return (p_lo, median, p_hi) from per-tree predictions."""
        per_tree = [float(tree.predict([list(x)])[0]) for tree in self._model.estimators_]
        per_tree.sort()
        n = len(per_tree)
        if n == 0:
            return (self._median_fallback,) * 3

        def q(qv: float) -> float:
            idx = max(0, min(n - 1, int(round(qv * (n - 1)))))
            return per_tree[idx]

        return q(lo_q), q(0.5), q(hi_q)


def load_default(path: Path = DEFAULT_ARTEFACT) -> BaseModel:
    """Return the trained regressor, or a safe :class:`NullModel` fallback."""
    if not path.exists():
        return NullModel(name="duration_regressor", default=5.0)
    try:
        # HMAC-verified load — refuses unsigned or tampered artefacts.
        artefact = _load_signed_artefact(path)
        model = DurationRegressor(artefact)
        log_info(
            f"[MODEL] duration_regressor loaded "
            f"(n={artefact.get('n_samples')}, trained_at={artefact.get('trained_at')})"
        )
        return model
    except ModelIntegrityError as exc:
        log_warning(
            f"[MODEL] duration_regressor refused (integrity): {exc}. "
            "Run `python -m scripts.sign_models` on a known-good file or re-train."
        )
        return NullModel(name="duration_regressor", default=5.0)
    except Exception as exc:  # pragma: no cover
        log_warning(f"[MODEL] duration_regressor load failed: {exc}")
        return NullModel(name="duration_regressor", default=5.0)
