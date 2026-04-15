"""Base model contract — every trained model behind a uniform surface.

The online engine imports :class:`BaseModel` only. Concrete models load
lazily from ``app/data/models/<name>.pkl`` (or ``.onnx``), and fall back
to :class:`NullModel` when the artefact is missing so the firewall path
stays deterministic even on a clean checkout.

Contract:
    * :meth:`predict` takes a 1-D feature vector of length
      ``app.ai.feature_extractor.FEATURE_DIM`` (or a list-of-vectors for
      windowed models) and returns a ``float`` (regressor / scorer) or
      ``dict`` (classifier with class probabilities).
    * :meth:`ready` — True when the model is loaded and safe to call.
    * :meth:`name`  — short identifier for logging.

Implementation must be thread-safe for concurrent reads (hot-path
inference). Training helpers live in ``scripts/train_*.py`` and never
import from this package.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Sequence, Union

__all__ = ["BaseModel", "NullModel", "Prediction"]

Prediction = Union[float, Dict[str, float]]


class BaseModel(ABC):
    """Abstract read-only inference model."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    def ready(self) -> bool:
        return True

    @abstractmethod
    def predict(self, x: Sequence[float]) -> Prediction: ...


class NullModel(BaseModel):
    """Safe fallback — returns a fixed default and never raises.

    Used when the real model's artefact is missing or deserialization
    fails. Lets the rest of the system run with feature extraction and
    data collection active, so the first collected episodes can train
    the real model.
    """

    def __init__(self, name: str = "null", default: Prediction = 0.0) -> None:
        self._name = name
        self._default = default

    @property
    def name(self) -> str:
        return self._name

    @property
    def ready(self) -> bool:
        return False

    def predict(self, x: Sequence[float]) -> Prediction:
        return self._default
