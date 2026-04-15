"""Offline training entry point — reads JSONL episodes, fits models.

Run from repo root::

    python scripts/train_models.py --episodes app/data/episodes --out app/data/models

Currently a scaffolding stub: enumerates episodes and reports coverage
so you can see whether there's enough labeled data before dropping in a
real trainer (sklearn / lightgbm / torch). Keeping this lightweight so a
fresh checkout can run ``python scripts/train_models.py --dry-run``
without any ML dependencies installed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

# Allow running as `python scripts/train_models.py` from repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def iter_episodes(episode_dir: Path):
    for path in sorted(episode_dir.glob("episode_*.jsonl")):
        yield path


def load_episode(path: Path) -> Dict[str, List[dict]]:
    windows: List[dict] = []
    events: List[dict] = []
    with open(path, "r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("kind") == "window":
                windows.append(rec)
            elif rec.get("kind") == "event":
                events.append(rec)
    return {"windows": windows, "events": events}


def summarize(episode_dir: Path) -> int:
    total_windows = 0
    total_events = 0
    total_cuts = 0
    files = 0
    for path in iter_episodes(episode_dir):
        ep = load_episode(path)
        files += 1
        total_windows += len(ep["windows"])
        total_events += len(ep["events"])
        total_cuts += sum(1 for e in ep["events"] if e.get("name") == "cut_start")

    print(f"Episode dir: {episode_dir}")
    print(f"  files:   {files}")
    print(f"  windows: {total_windows}")
    print(f"  events:  {total_events}")
    print(f"  cuts:    {total_cuts}")
    if total_cuts < 50:
        print("\n[!] Fewer than 50 labeled cuts — collect more sessions before training.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=Path, default=Path("app/data/episodes"))
    ap.add_argument("--out", type=Path, default=Path("app/data/models"))
    ap.add_argument("--dry-run", action="store_true", help="Summarize only, no training.")
    args = ap.parse_args()

    if not args.episodes.exists():
        print(f"No episode dir at {args.episodes}", file=sys.stderr)
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    rc = summarize(args.episodes)
    if args.dry_run:
        return rc

    # Primary model: survival (KM + kNN). The legacy QRF regressor is
    # still trained as a fallback so the Suggest button keeps working
    # when no outcome labels are present.
    try:
        from app.ai.train_survival_model import train as train_survival
    except ImportError as exc:
        print(f"[training] unable to import train_survival_model: {exc}", file=sys.stderr)
        return 1

    surv_out = args.out / "survival_model.pkl"
    print(f"\n[training] survival_model → {surv_out}")
    try:
        surv = train_survival(
            episode_dir=args.episodes,
            model_out=surv_out,
            real_only=True,
        )
    except RuntimeError as exc:
        print(f"[training] survival_model skipped: {exc}", file=sys.stderr)
        surv = None

    if surv:
        print(
            f"  samples={surv['n_samples']} "
            f"events={surv['n_events']} "
            f"censored={surv['n_censored']} "
            f"median={surv['median_s']:.2f}s "
            f"KM_p90={surv['p90_s']:.2f}s"
        )
        if surv["n_events"] == 0:
            print("  [!] 0 dupe-success labels — use the 'Mark dupe success' "
                  "button in the UI, then re-run.")

    # Legacy QRF — kept as a belt-and-braces fallback.
    try:
        from app.ai.train_duration_regressor import train as train_duration
        qrf_out = args.out / "duration_regressor.pkl"
        print(f"\n[training] duration_regressor (legacy QRF) → {qrf_out}")
        qrf = train_duration(
            episode_dir=args.episodes,
            model_out=qrf_out,
            real_only=True,
        )
        mae = qrf["cv_mae_s"]
        mae_str = f"{mae:.2f}s" if mae == mae else "n/a"
        print(
            f"  samples={qrf['n_samples']} "
            f"median={qrf['median_s']:.2f}s "
            f"LOO_MAE={mae_str}"
        )
    except Exception as exc:
        print(f"[training] legacy QRF skipped: {exc}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
