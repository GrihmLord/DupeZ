"""ML model scaffolding — trained offline, served online.

Each model lives in its own submodule with a consistent interface:
    * :class:`BaseModel` — load/predict/fallback contract
    * ``load_default()`` — module-level helper that returns either the
      trained model or a safe NullModel fallback when the artefact is missing.

The online engine only ever depends on :class:`BaseModel`; training is
kept out-of-process so production DLL imports stay lean.

Models:
    * duration_regressor — legacy QRF point estimate (fallback)
    * survival_model     — KM baseline + kNN survival (primary). Use
                           :func:`load_default` to get the right model.

Future defensive model ideas:
    * quality_forecaster — predicts degraded connection-health windows
    * rpc_classifier    — classifies benign packet bursts for diagnostics
    * baseline_model    — compares local lab traffic to prior healthy runs
"""

from __future__ import annotations

from app.ai.models.base import BaseModel, NullModel
from app.ai.models.duration_regressor import DurationRegressor
from app.ai.models.survival_model import (
    KaplanMeier,
    KNNSurvival,
    SurvivalDurationModel,
    HIVE_FLUSH_FLOOR_S,
    load_default,
)

__all__ = [
    "BaseModel",
    "NullModel",
    "DurationRegressor",
    "KaplanMeier",
    "KNNSurvival",
    "SurvivalDurationModel",
    "HIVE_FLUSH_FLOOR_S",
    "load_default",
]
