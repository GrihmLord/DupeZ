"""Train the QRF cut-duration regressor from recorded episodes.

Reads JSONL episodes from ``app/data/episodes/``, extracts one training
sample per real DisconnectModule cut, fits a quantile random forest
(RandomForestRegressor backed by per-tree predictions for quantiles so
we don't need the ``quantile-forest`` extra dep), and persists the
trained model to ``app/data/models/duration_regressor.pkl``.

Training sample per cut:
    * Features: mean of the ``PRECUT_WINDOWS`` feature vectors that land
      between ``engine_start`` and ``cut_start`` — this is the ambient
      network baseline the operator saw right before firing the cut.
      If fewer than ``PRECUT_WINDOWS`` windows were observed, we mean
      whatever we have (min 1). Episodes with zero pre-cut windows are
      skipped.
    * Target : ``cut_end.ts - cut_start.ts`` in seconds.

Cuts sourced from the backfill labeler (``payload.source == "backfill"``)
are kept — they're coarse but reflect real session lengths. A
``real_disconnect_only`` CLI flag filters to episodes whose
``engine_start.payload.methods`` contains ``"disconnect"``.

Run from repo root::

    python -m app.ai.train_duration_regressor
    python -m app.ai.train_duration_regressor --real-only

Artefact shape (pickle)::

    {
        "model": RandomForestRegressor,
        "feature_names": [...],      # matches FEATURE_NAMES
        "n_samples": int,
        "cv_mae_s": float,           # leave-one-out MAE in seconds
        "median_s": float,           # training-set median target (fallback)
        "trained_at": str,           # ISO timestamp
        "dupe_z_version": str,
    }
"""

from __future__ import annotations

import argparse
import json
import pickle
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.ai.feature_extractor import FEATURE_DIM, FEATURE_NAMES

__all__ = ["train", "extract_samples", "PRECUT_WINDOWS"]

PRECUT_WINDOWS: int = 8  # ~1.6 s of baseline at 200 ms/window
DEFAULT_EPISODES: Path = Path("app/data/episodes")
DEFAULT_MODEL_OUT: Path = Path("app/data/models/duration_regressor.pkl")


def _load_episode(path: Path) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    windows: List[Dict[str, Any]] = []
    events: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = rec.get("kind")
            if kind == "window":
                windows.append(rec)
            elif kind == "event":
                events.append(rec)
    return windows, events


def extract_samples(
    episode_dir: Path,
    real_only: bool = False,
) -> Tuple[np.ndarray, np.ndarray, List[str]]:
    """Walk episodes and emit (X, y, source_paths)."""
    X_rows: List[List[float]] = []
    y_rows: List[float] = []
    src_paths: List[str] = []

    for path in sorted(episode_dir.glob("episode_*.jsonl")):
        windows, events = _load_episode(path)
        if not events:
            continue

        methods: Optional[List[str]] = None
        engine_start_ts: Optional[float] = None
        cut_start_ts: Optional[float] = None
        cut_end_ts: Optional[float] = None
        for ev in events:
            name = ev.get("name")
            if name == "engine_start":
                engine_start_ts = ev.get("ts")
                methods = ev.get("payload", {}).get("methods")
            elif name == "cut_start" and cut_start_ts is None:
                cut_start_ts = ev.get("ts")
            elif name == "cut_end" and cut_end_ts is None:
                cut_end_ts = ev.get("ts")

        if cut_start_ts is None or cut_end_ts is None:
            continue
        if real_only and not (methods and "disconnect" in methods):
            continue
        duration_s = cut_end_ts - cut_start_ts
        if duration_s <= 0.1:  # guard against clock skew / zero-length cuts
            continue

        # Pick the pre-cut windows — those whose ts < cut_start_ts.
        # For backfilled cuts where cut_start == engine_start there are
        # none, so we fall back to the first windows of the episode —
        # those still represent the ambient baseline during the cut.
        pre: List[List[float]] = []
        for w in windows:
            ts = w.get("ts", 0)
            vec = w.get("vec")
            if ts >= cut_start_ts:
                break
            if isinstance(vec, list) and len(vec) == FEATURE_DIM:
                pre.append(vec)
        if not pre:
            pre = [
                w["vec"] for w in windows[:PRECUT_WINDOWS]
                if isinstance(w.get("vec"), list) and len(w["vec"]) == FEATURE_DIM
            ]
        if not pre:
            continue
        pre_tail = pre[-PRECUT_WINDOWS:]
        feat = np.mean(np.asarray(pre_tail, dtype=np.float64), axis=0)

        X_rows.append(feat.tolist())
        y_rows.append(duration_s)
        src_paths.append(path.name)

    X = np.asarray(X_rows, dtype=np.float64)
    y = np.asarray(y_rows, dtype=np.float64)
    return X, y, src_paths


def _loo_mae(model_factory, X: np.ndarray, y: np.ndarray) -> float:
    """Leave-one-out MAE. Cheap at these sample sizes."""
    n = len(y)
    if n < 3:
        return float("nan")
    errors: List[float] = []
    for i in range(n):
        mask = np.ones(n, dtype=bool)
        mask[i] = False
        mdl = model_factory()
        mdl.fit(X[mask], y[mask])
        pred = float(mdl.predict(X[i:i + 1])[0])
        errors.append(abs(pred - y[i]))
    return float(np.mean(errors))


def train(
    episode_dir: Path = DEFAULT_EPISODES,
    model_out: Path = DEFAULT_MODEL_OUT,
    real_only: bool = False,
    n_estimators: int = 200,
    min_samples_leaf: int = 2,
    seed: int = 42,
) -> Dict[str, Any]:
    from sklearn.ensemble import RandomForestRegressor  # lazy import

    X, y, paths = extract_samples(episode_dir, real_only=real_only)
    if len(y) == 0:
        raise RuntimeError(
            f"No trainable cuts in {episode_dir} "
            f"(real_only={real_only}). Record more sessions."
        )

    def factory() -> RandomForestRegressor:
        return RandomForestRegressor(
            n_estimators=n_estimators,
            min_samples_leaf=min_samples_leaf,
            random_state=seed,
            n_jobs=-1,
        )

    mae = _loo_mae(factory, X, y) if len(y) >= 5 else float("nan")

    model = factory()
    model.fit(X, y)

    artefact = {
        "model": model,
        "feature_names": list(FEATURE_NAMES),
        "n_samples": int(len(y)),
        "cv_mae_s": mae,
        "median_s": float(statistics.median(y.tolist())),
        "target_min_s": float(y.min()),
        "target_max_s": float(y.max()),
        "target_mean_s": float(y.mean()),
        "trained_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "real_only": real_only,
    }

    model_out.parent.mkdir(parents=True, exist_ok=True)
    with open(model_out, "wb") as fp:
        pickle.dump(artefact, fp)

    return {
        "n_samples": len(y),
        "cv_mae_s": mae,
        "median_s": artefact["median_s"],
        "target_range_s": (artefact["target_min_s"], artefact["target_max_s"]),
        "path": str(model_out),
        "source_count": len(paths),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=Path, default=DEFAULT_EPISODES)
    ap.add_argument("--out", type=Path, default=DEFAULT_MODEL_OUT)
    ap.add_argument("--real-only", action="store_true",
                    help="Only train on sessions that include 'disconnect' in methods.")
    args = ap.parse_args()

    try:
        summary = train(
            episode_dir=args.episodes,
            model_out=args.out,
            real_only=args.real_only,
        )
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print("Duration regressor trained.")
    print(f"  samples:           {summary['n_samples']}")
    print(f"  target range (s):  {summary['target_range_s'][0]:.2f} – "
          f"{summary['target_range_s'][1]:.2f}")
    print(f"  training median s: {summary['median_s']:.2f}")
    mae = summary["cv_mae_s"]
    if mae == mae:  # not NaN
        print(f"  LOO MAE (s):       {mae:.2f}")
    else:
        print("  LOO MAE (s):       n/a (need ≥5 samples)")
    print(f"  saved:             {summary['path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
