# app/ai/learning_loop.py — Episode → Recommendation feedback loop
"""Closes the Smart Mode loop by consuming past episode JSONL files and
surfacing aggregate stats that `SmartDisruptionEngine.recommend()` can merge
with its live network profile.

Design constraints:

* **Never blocks the packet hot path.** All reads happen on demand from the
  GUI thread (when the user presses SMART DISRUPT) or from a background
  refresh thread. EpisodeRecorder still owns the write path.

* **Outcome-labeled only.** Episodes without a `cut_outcome` event are
  right-censored — we know the cut happened but not whether it duped. Those
  are used only for duration-distribution stats, not for
  direction/method recommendations.

* **Keyed aggregation.** Episodes are grouped by
  `(target_profile_key, goal, network_class)` so PS5 hotspot wins don't
  contaminate PC local recommendations, and vice versa.

* **Explicit fallback.** When fewer than ``MIN_EPISODES_FOR_RECS`` matching
  labeled episodes exist for a key, the loop returns ``None`` and the
  engine falls through to its live-profile heuristic. This prevents a
  single lucky cut from overriding the default.
"""

from __future__ import annotations

import json
import statistics
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.ai.episode_recorder import DEFAULT_EPISODE_DIR
from app.logs.logger import log_error, log_info

__all__ = [
    "LearningLoop",
    "EpisodeSummary",
    "HistoricalRecommendation",
    "MIN_EPISODES_FOR_RECS",
]

MIN_EPISODES_FOR_RECS: int = 5
"""Minimum labeled episodes needed for a (key, goal) bucket to override
the live-profile recommendation. Below this threshold, the loop returns
None and the engine uses its default heuristic."""


@dataclass(frozen=True)
class EpisodeSummary:
    """Reduced form of one JSONL file — only the fields we key/aggregate on."""

    tag: str
    start_ts: float
    target_profile: str         # "ps5_hotspot", "pc_local", "xbox_hotspot", ...
    network_class: str          # "hotspot", "lan", "wan", "unknown"
    goal: str                   # "disconnect", "lag", "desync", ...
    direction: str              # "inbound", "outbound", "both"
    methods: Tuple[str, ...]
    duration_s: float           # cut_end - cut_start, seconds
    outcome: Optional[bool]     # True=dupe success, False=fail, None=unlabeled
    max_cut_state: str = "unknown"  # unknown|connected|degraded|severed
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HistoricalRecommendation:
    """Aggregate recommendation derived from ≥MIN_EPISODES_FOR_RECS episodes."""

    sample_size: int
    success_rate: float                  # labeled-success / labeled-total
    best_direction: str                  # winning direction by success rate
    best_duration_s: float               # median of successful cuts
    best_methods: Tuple[str, ...]        # modal method set from successful cuts
    confidence: float                    # 0..1, scales with sample size
    reasoning: Tuple[str, ...]           # human-readable evidence lines


class LearningLoop:
    """Reads episodes from disk, aggregates by (target_profile, goal)."""

    def __init__(self, episodes_dir: Optional[Path] = None) -> None:
        self._dir: Path = Path(episodes_dir) if episodes_dir else DEFAULT_EPISODE_DIR
        self._lock = threading.Lock()
        self._cache: List[EpisodeSummary] = []
        self._cache_mtime: float = 0.0
        # Indices built once per cache refresh for O(1) bucket lookup.
        # Keys: (target_profile, goal). Values: list of episodes in that bucket.
        self._index_labeled: Dict[Tuple[str, str], List[EpisodeSummary]] = {}
        self._index_all: Dict[Tuple[str, str], List[EpisodeSummary]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def recommend(
        self,
        target_profile: str,
        goal: str,
        network_class: str = "unknown",
    ) -> Optional[HistoricalRecommendation]:
        """Return aggregate recommendation, or None if below threshold."""
        self._refresh_if_stale()

        with self._lock:
            matching = self._index_labeled.get((target_profile, goal), [])

        if len(matching) < MIN_EPISODES_FOR_RECS:
            return None

        # Direction: pick the one with highest success rate (ties → more data)
        by_dir: Dict[str, List[EpisodeSummary]] = {}
        for e in matching:
            by_dir.setdefault(e.direction, []).append(e)

        def _dir_score(items: List[EpisodeSummary]) -> Tuple[float, int]:
            wins = sum(1 for x in items if x.outcome)
            return (wins / len(items), len(items))

        best_direction = max(by_dir, key=lambda d: _dir_score(by_dir[d]))
        dir_success_rate, dir_n = _dir_score(by_dir[best_direction])

        # Duration: median of successful cuts in the winning direction
        wins_in_best = [e for e in by_dir[best_direction] if e.outcome]
        if wins_in_best:
            best_duration_s = statistics.median(e.duration_s for e in wins_in_best)
        else:
            # Best direction has zero wins — can't recommend duration
            best_duration_s = statistics.median(
                e.duration_s for e in by_dir[best_direction]
            )

        # Methods: modal method-set among successful cuts
        if wins_in_best:
            method_sets = [e.methods for e in wins_in_best]
            best_methods = _modal_tuple(method_sets)
        else:
            best_methods = tuple()

        total_wins = sum(1 for e in matching if e.outcome)
        success_rate = total_wins / len(matching)

        # Confidence scales with sample size, capped at 0.9
        confidence = min(0.9, 0.3 + 0.1 * (len(matching) - MIN_EPISODES_FOR_RECS))

        reasoning = (
            f"{len(matching)} labeled episodes for "
            f"{target_profile}/{goal} ({total_wins} wins, "
            f"{success_rate * 100:.0f}% overall).",
            f"Direction '{best_direction}' wins "
            f"{dir_success_rate * 100:.0f}% of {dir_n} attempts.",
            f"Median successful cut duration: {best_duration_s:.1f}s.",
        )

        return HistoricalRecommendation(
            sample_size=len(matching),
            success_rate=success_rate,
            best_direction=best_direction,
            best_duration_s=best_duration_s,
            best_methods=best_methods,
            confidence=confidence,
            reasoning=reasoning,
        )

    def cut_effectiveness(
        self,
        target_profile: str,
        goal: str = "disconnect",
    ) -> Optional[Dict[str, Any]]:
        """Return severance stats for a (profile, goal) bucket.

        Distinct from ``recommend`` — this measures whether the cut even
        fired correctly (severance), not whether the dupe stuck. Lets the
        auto-tuner pick a different preset when the current one can't
        sever this target class at all.

        Returns ``None`` when no sessions exist for the bucket.
        """
        self._refresh_if_stale()
        with self._lock:
            rows = self._index_all.get((target_profile, goal), ())
        if not rows:
            return None

        severed = degraded = never_cut = 0
        for episode in rows:
            state = episode.max_cut_state
            if state == "severed":
                severed += 1
            elif state == "degraded":
                degraded += 1
            else:  # "unknown" or "connected" — both mean "cut never landed"
                never_cut += 1

        total = len(rows)
        return {
            "n": total,
            "severed_rate": severed / total,
            "degraded_rate": degraded / total,
            "never_cut_rate": never_cut / total,
            "sufficient_data": total >= MIN_EPISODES_FOR_RECS,
        }

    def all_episodes(self) -> List[EpisodeSummary]:
        """Return a copy of the cached episode summaries (read-only use)."""
        self._refresh_if_stale()
        with self._lock:
            return list(self._cache)

    # ------------------------------------------------------------------
    # Cache refresh
    # ------------------------------------------------------------------
    def _refresh_if_stale(self) -> None:
        """Rescan disk if the episodes dir mtime advanced since last read."""
        try:
            mtime = self._dir.stat().st_mtime if self._dir.exists() else 0.0
        except OSError:
            mtime = 0.0

        with self._lock:
            if mtime <= self._cache_mtime and self._cache:
                return
            self._cache_mtime = mtime
            self._cache = list(self._scan())
            self._rebuild_indices()

    def _rebuild_indices(self) -> None:
        """Rebuild (target_profile, goal) bucket indices from the cache.

        Caller must hold ``self._lock``. Runs once per cache refresh; after
        that, all aggregation queries are O(bucket_size) instead of O(total).
        """
        labeled: Dict[Tuple[str, str], List[EpisodeSummary]] = {}
        full: Dict[Tuple[str, str], List[EpisodeSummary]] = {}
        for episode in self._cache:
            key = (episode.target_profile, episode.goal)
            full.setdefault(key, []).append(episode)
            if episode.outcome is not None:
                labeled.setdefault(key, []).append(episode)
        self._index_labeled = labeled
        self._index_all = full

    def _scan(self) -> Iterable[EpisodeSummary]:
        if not self._dir.exists():
            return
        for path in sorted(self._dir.glob("episode_*.jsonl")):
            try:
                summary = _summarize_episode(path)
            except Exception as exc:  # noqa: BLE001 — one bad file shouldn't kill the loop
                log_error(f"[LEARNING] skipping {path.name}: {exc}")
                continue
            if summary is not None:
                yield summary


# ----------------------------------------------------------------------
# Per-file summarization
# ----------------------------------------------------------------------
def _summarize_episode(path: Path) -> Optional[EpisodeSummary]:
    """Reduce a JSONL episode file to one EpisodeSummary.

    Returns None if the file has no cut_start event (not a disruption session).
    """
    cut_start_ts: Optional[float] = None
    cut_end_ts: Optional[float] = None
    outcome: Optional[bool] = None
    max_cut_state: str = "unknown"
    _state_order = {"unknown": 0, "connected": 1, "degraded": 2, "severed": 3}
    meta: Dict[str, Any] = {}

    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue

            kind = row.get("kind")
            if kind != "event":
                continue

            name = row.get("name", "")
            payload = row.get("payload", {}) or {}

            if name == "engine_start" or name == "cut_start":
                if cut_start_ts is None:
                    cut_start_ts = row.get("ts", 0.0)
                # Merge any metadata carried on the start event
                for k in ("target_profile", "network_class", "goal",
                          "direction", "methods", "params", "target_ip"):
                    if k in payload and k not in meta:
                        meta[k] = payload[k]
            elif name == "cut_end" or name == "engine_stop":
                cut_end_ts = row.get("ts", cut_end_ts)
                # cut_end may carry the auto-labeled persisted flag
                # (force_cut_end(persisted=...) from the engine stop path).
                # Accept it as the outcome if no explicit mark landed.
                if outcome is None and "persisted" in payload:
                    outcome = not bool(payload["persisted"])
                # engine_stop carries the peak cut_state reached this session
                _mcs = str(payload.get("max_cut_state", ""))
                if _mcs and _state_order.get(_mcs, 0) > _state_order.get(max_cut_state, 0):
                    max_cut_state = _mcs
            elif name == "cut_verified":
                _cs = str(payload.get("state", ""))
                if _cs and _state_order.get(_cs, 0) > _state_order.get(max_cut_state, 0):
                    max_cut_state = _cs
            elif name in ("outcome", "cut_outcome"):
                # Labeled by user: {"persisted": bool}. persisted=False => dupe
                # success (hive did not flush). Manual mark overrides any
                # earlier auto-label picked up from cut_end.
                if "persisted" in payload:
                    outcome = not bool(payload["persisted"])
                elif "success" in payload:
                    outcome = bool(payload["success"])

    if cut_start_ts is None:
        return None

    duration = (cut_end_ts - cut_start_ts) if cut_end_ts else 0.0

    methods_raw = meta.get("methods", [])
    if not isinstance(methods_raw, (list, tuple)):
        methods_raw = []

    return EpisodeSummary(
        tag=path.stem.replace("episode_", ""),
        start_ts=cut_start_ts,
        target_profile=str(meta.get("target_profile", "unknown")),
        network_class=str(meta.get("network_class", "unknown")),
        goal=str(meta.get("goal", "disconnect")),
        direction=str(meta.get("direction", "unknown")),
        methods=tuple(str(m) for m in methods_raw),
        duration_s=float(max(0.0, duration)),
        outcome=outcome,
        max_cut_state=max_cut_state,
        params=dict(meta.get("params", {}) or {}),
    )


def _modal_tuple(rows: List[Tuple[str, ...]]) -> Tuple[str, ...]:
    """Most common method-set; ties broken by first occurrence."""
    if not rows:
        return tuple()
    counts: Dict[Tuple[str, ...], int] = {}
    for r in rows:
        counts[r] = counts.get(r, 0) + 1
    return max(counts, key=lambda k: counts[k])
