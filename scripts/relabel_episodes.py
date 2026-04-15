"""Backfill cut_start / cut_end labels on legacy episode JSONL files.

Sessions recorded before the DisconnectModule sink-replay fix contain
engine_start / engine_stop events but no cut_start / cut_end, because
the module transitioned into CUTTING before the engine could attach
the recorder sink.

For every affected file this script synthesizes:
    * cut_start at engine_start.ts
    * cut_end   at engine_stop.ts
and rewrites the file in place, with a .bak copy next to it.

Idempotent: skips files that already have cut_start events.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import List, Optional


def backfill(path: Path, dry_run: bool = False) -> Optional[str]:
    lines: List[str] = path.read_text(encoding="utf-8").splitlines()
    records = []
    engine_start_ts: Optional[float] = None
    engine_stop_ts: Optional[float] = None
    has_cut_start = False
    has_cut_end = False
    for ln in lines:
        if not ln.strip():
            continue
        try:
            rec = json.loads(ln)
        except json.JSONDecodeError:
            continue
        records.append(rec)
        if rec.get("kind") == "event":
            name = rec.get("name")
            if name == "engine_start":
                engine_start_ts = rec.get("ts")
            elif name == "engine_stop":
                engine_stop_ts = rec.get("ts")
            elif name == "cut_start":
                has_cut_start = True
            elif name == "cut_end":
                has_cut_end = True

    if has_cut_start and has_cut_end:
        return None  # already labeled
    if engine_start_ts is None or engine_stop_ts is None:
        return "missing engine_start/stop"

    new_records = []
    for rec in records:
        new_records.append(rec)
        if rec.get("kind") == "event" and rec.get("name") == "engine_start" and not has_cut_start:
            new_records.append({
                "kind": "event",
                "ts": engine_start_ts,
                "name": "cut_start",
                "payload": {
                    "state": "cutting",
                    "source": "backfill",
                    "cut_started_at": engine_start_ts,
                },
            })

    if not has_cut_end:
        # Insert cut_end just before engine_stop
        final = []
        for rec in new_records:
            if rec.get("kind") == "event" and rec.get("name") == "engine_stop":
                final.append({
                    "kind": "event",
                    "ts": engine_stop_ts,
                    "name": "cut_end",
                    "payload": {
                        "state": "done",
                        "source": "backfill",
                        "cut_started_at": engine_start_ts,
                        "cut_ended_at": engine_stop_ts,
                        "duration_s": engine_stop_ts - engine_start_ts,
                    },
                })
            final.append(rec)
        new_records = final

    if dry_run:
        return f"would label (duration={engine_stop_ts - engine_start_ts:.1f}s)"

    bak = path.with_suffix(path.suffix + ".bak")
    if not bak.exists():
        shutil.copy2(path, bak)
    with open(path, "w", encoding="utf-8") as fp:
        for rec in new_records:
            fp.write(json.dumps(rec, separators=(",", ":")))
            fp.write("\n")
    return f"labeled (duration={engine_stop_ts - engine_start_ts:.1f}s)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=Path, default=Path("app/data/episodes"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.episodes.exists():
        print(f"No episode dir at {args.episodes}", file=sys.stderr)
        return 1

    touched = 0
    skipped = 0
    for path in sorted(args.episodes.glob("episode_*.jsonl")):
        status = backfill(path, dry_run=args.dry_run)
        if status is None:
            skipped += 1
        else:
            touched += 1
            print(f"  {path.name}: {status}")

    verb = "would label" if args.dry_run else "labeled"
    print(f"\n{verb} {touched} file(s), skipped {skipped} already-labeled.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
