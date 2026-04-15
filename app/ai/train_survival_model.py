"""Train the survival-based cut-duration model from recorded episodes.

Reads JSONL episodes from ``app/data/episodes/``, extracts one training
sample per real DisconnectModule cut, and fits two estimators:

    * A marginal Kaplan-Meier curve over all (duration, persisted) pairs
      — serves as the feature-free baseline.
    * A k-NN survival lookup over pre-cut feature baselines — feature-
      conditional prediction used at inference.

The persisted label comes from two places, in priority order:

    1. An explicit ``cut_outcome`` event in the episode with a
       ``persisted`` boolean (emitted by the GUI "mark last cut" button).
    2. The ``payload.persisted`` field on a ``cut_end`` event (plumbed
       through ``DisconnectModule.force_cut_end(persisted=...)``).

If neither label is present the cut is treated as right-censored —
i.e. we know the cut stayed open for ``duration_s`` without the
operator confirming a flush, so that duration enters the risk set but
doesn't trigger the event.

Run from repo root::

    python -m app.ai.train_survival_model
    python -m app.ai.train_survival_model --real-only --k 8

Artefact (pickle)::

    {
        "knn": KNNSurvival | None,
        "km":  KaplanMeier,
        "meta": {
            "n_samples": int,
            "n_events":  int,          # count with persisted=True
            "trained_at": str,
            "real_only": bool,
            "feature_names": [...],
        },
    }
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.ai.feature_extractor import FEATURE_DIM, FEATURE_NAMES
from app.ai.models.survival_model import (
    KNNSurvival,
    KaplanMeier,
    _fit_km,
)

__all__ = ["train", "extract_samples", "PRECUT_WINDOWS"]

PRECUT_WINDOWS: int = 8
DEFAULT_EPISODES: Path = Path("app/data/episodes")
DEFAULT_MODEL_OUT: Path = Path("app/data/models/survival_model.pkl")


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
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, List[str]]:
    """Walk episodes and emit (X, durations, events, source_paths)."""
    X_rows: List[List[float]] = []
    durations: List[float] = []
    events_out: List[bool] = []
    sources: List[str] = []

    for path in sorted(episode_dir.glob("episode_*.jsonl")):
        windows, events = _load_episode(path)
        if not events:
            continue

        methods: Optional[List[str]] = None
        cut_start_ts: Optional[float] = None
        cut_end_ts: Optional[float] = None
        persisted: Optional[bool] = None

        for ev in events:
            name = ev.get("name")
            payload = ev.get("payload") or {}
            if name == "engine_start":
                methods = payload.get("methods")
            elif name == "cut_start" and cut_start_ts is None:
                cut_start_ts = ev.get("ts")
            elif name == "cut_end" and cut_end_ts is None:
                cut_end_ts = ev.get("ts")
                if "persisted" in payload:
                    persisted = bool(payload["persisted"])
            elif name == "cut_outcome":
                # GUI-posted label — highest priority.
                if "persisted" in payload:
                    persisted = bool(payload["persisted"])

        if cut_start_ts is None or cut_end_ts is None:
            continue
        if real_only and not (methods and "disconnect" in methods):
            continue

        duration_s = cut_end_ts - cut_start_ts
        if duration_s <= 0.1:
            continue

        # Pre-cut baseline features: mean of last PRECUT_WINDOWS windows
        # strictly before cut_start. Fall back to first PRECUT_WINDOWS of
        # the episode when none are available (backfilled cuts).
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
        durations.append(duration_s)
        # If the operator didn't label the cut, treat as censored.
        events_out.append(bool(persisted) if persisted is not None else False)
        sources.append(path.name)

    X = np.asarray(X_rows, dtype=np.float64)
    d = np.asarray(durations, dtype=np.float64)
    e = np.asarray(events_out, dtype=bool)
    return X, d, e, sources


def train(
    episode_dir: Path = DEFAULT_EPISODES,
    model_out: Path = DEFAULT_MODEL_OUT,
    real_only: bool = True,
    k: int = 8,
) -> Dict[str, Any]:
    X, durations, events, sources = extract_samples(episode_dir, real_only=real_only)
    if len(durations) == 0:
        raise RuntimeError(
            f"No trainable cuts in {episode_dir} (real_only={real_only}). "
            "Record more sessions or label outcomes."
        )

    # Marginal Kaplan-Meier baseline.
    km_curve = _fit_km(durations, events)
    km = KaplanMeier(
        curve=km_curve,
        n_samples=int(len(durations)),
        n_events=int(events.sum()),
    )

    # Feature-conditional kNN — only useful once we have ≥ k labeled
    # samples. Below that the marginal KM is the honest answer.
    knn: Optional[KNNSurvival] = None
    if len(durations) >= max(3, k):
        knn = KNNSurvival(
            features=X,
            durations=durations,
            events=events,
            feature_names=list(FEATURE_NAMES),
            k=k,
        )

    meta = {
        "n_samples":     int(len(durations)),
        "n_events":      int(events.sum()),
        "n_censored":    int((~events).sum()),
        "duration_min":  float(durations.min()),
        "duration_max":  float(durations.max()),
        "duration_med":  float(np.median(durations)),
        "trained_at":    time.strftime("%Y-%m-%dT%H:%M:%S"),
        "real_only":     real_only,
        "feature_names": list(FEATURE_NAMES),
        "k":             k,
    }

    artefact = {"knn": knn, "km": km, "meta": meta}
    model_out.parent.mkdir(parents=True, exist_ok=True)
    import pickle
    with open(model_out, "wb") as fp:
        pickle.dump(artefact, fp)

    return {
        "n_samples":  meta["n_samples"],
        "n_events":   meta["n_events"],
        "n_censored": meta["n_censored"],
        "median_s":   meta["duration_med"],
        "p90_s":      km.quantile_duration([0.0] * FEATURE_DIM, p=0.9),
        "path":       str(model_out),
        "source_count": len(sources),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=Path, default=DEFAULT_EPISODES)
    ap.add_argument("--out", type=Path, default=DEFAULT_MODEL_OUT)
    ap.add_argument("--real-only", action="store_true", default=True)
    ap.add_argument("--all", dest="real_only", action="store_false",
                    help="Train on all episodes including godmode/backfill")
    ap.add_argument("--k", type=int, default=8)
    args = ap.parse_args()

    try:
        summary = train(
            episode_dir=args.episodes,
            model_out=args.out,
            real_only=args.real_only,
            k=args.k,
        )
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print("Survival model trained.")
    print(f"  samples:         {summary['n_samples']}")
    print(f"  events (dupes):  {summary['n_events']}")
    print(f"  censored:        {summary['n_censored']}")
    print(f"  median cut (s):  {summary['median_s']:.2f}")
    print(f"  KM p90 (s):      {summary['p90_s']:.2f}")
    print(f"  saved:           {summary['path']}")
    if summary["n_events"] == 0:
        print("\n[!] 0 labeled successes — model is censored-only. "
              "Use the 'Mark dupe success' button in the UI to label cuts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
