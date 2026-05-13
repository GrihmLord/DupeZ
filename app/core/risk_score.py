"""Risk score aggregator (v5.7.0 feature #5).

Single 0-100 number derived entirely from telemetry the rest of DupeZ
already records. No new sensors, no new dependencies — just a weighted
read over the existing episode store + audit log + engine packet
counters.

The score lives in three bands:

    0-29    GREEN  — recent activity is well within baseline; carry on
    30-69   AMBER  — elevated; consider easing off, longer cooldown
    70-100  RED    — sustained anomaly; recommend stopping for a while

The score is ADVISORY. It does not auto-stop disruptions (that's the
:mod:`app.core.kill_switch` job, which can optionally consume risk
score as one of its triggers). It does not predict anti-cheat behavior
— it measures distance from the operator's own historical baseline.

Inputs and weights (each contributes 0..N points to the total):

    +25  Recent cut RATE — more than 6 cuts in the last 30 min adds
         linearly to +25. Empirically, sustained burst patterns are
         the single biggest indicator of operator fatigue / risk.
    +20  Recent FAILURE streak — last 5 episodes' outcome=False count
         scales linearly. Repeated failure suggests the network state
         drifted, target moved, or anti-cheat is interfering.
    +20  Overall SUCCESS RATE shortfall — if <50% of all labeled
         episodes succeeded, scale (0.5 - rate) * 40 → up to +20.
    +15  Time-since-last-cut COMPRESSION — cuts within 60s of each
         other add up to +15. Spaced-out activity stays at 0.
    +10  NEVER-CUT ratio — episodes where the engine started but the
         A2S verifier never saw severance. Suggests preset isn't
         landing; high counts add up to +10.
    +10  Audit-log VOLUME — high event rate in the last hour adds up
         to +10. Captures operator activity bursts not visible in the
         episode store (settings spam, repeated stops, etc.).

The weights total 100 by design. A perfectly cold install scores 0.
The maximum theoretical hit during a heavy session is 100; in practice
operator scores cap around 60-80 during sustained activity, leaving
headroom for an actually anomalous event to push into RED.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional

from app.logs.logger import log_warning


__all__ = [
    "RiskBand",
    "RiskScore",
    "RiskContribution",
    "compute_risk_score",
]


# ── Constants ─────────────────────────────────────────────────────────

# Band thresholds. Inclusive lower bound, exclusive upper for the next.
_GREEN_MAX = 30
_AMBER_MAX = 70


class RiskBand:
    """Discriminator for risk bands. Use ``is`` to compare."""
    GREEN = "green"
    AMBER = "amber"
    RED = "red"


# Per-input cap + scaling constants. Tuned conservatively — over-fitting
# these to one operator's habits would make the score useless for
# anyone else. Adjust only with real data showing systematic bias.
_RATE_WINDOW_S = 30 * 60                  # 30-min rate window
_RATE_THRESHOLD_PER_WINDOW = 6            # cuts before rate signal fires
_RATE_CAP = 25

_FAILURE_STREAK_WINDOW = 5                # last N episodes count
_FAILURE_STREAK_CAP = 20

_SUCCESS_RATE_FLOOR = 0.5                 # below this, signal accrues
_SUCCESS_RATE_CAP = 20

_COMPRESSION_THRESHOLD_S = 60             # cuts <60s apart count
_COMPRESSION_CAP = 15

_NEVER_CUT_FLOOR = 0.30                   # >30% never-cut accrues
_NEVER_CUT_CAP = 10

_AUDIT_RATE_WINDOW_S = 60 * 60            # 1-hour audit window
_AUDIT_THRESHOLD_EVENTS = 120             # >120 events/hr accrues
_AUDIT_CAP = 10


# ── Data classes ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class RiskContribution:
    """One factor's contribution to the total."""
    label: str        # human-readable factor name
    value: int        # 0..cap, points contributed
    cap: int          # max possible from this factor
    detail: str = ""  # one-line explanation for the dashboard


@dataclass(frozen=True)
class RiskScore:
    """Aggregate risk assessment."""
    score: int                          # 0..100
    band: str                           # one of RiskBand constants
    contributions: List[RiskContribution] = field(default_factory=list)
    computed_at: float = 0.0            # epoch seconds
    advisory: str = ""                  # one-line operator-facing message

    @property
    def is_red(self) -> bool:
        return self.band is RiskBand.RED

    @property
    def is_amber(self) -> bool:
        return self.band is RiskBand.AMBER


# ── Internal scoring helpers ──────────────────────────────────────────

def _classify_band(score: int) -> str:
    if score < _GREEN_MAX:
        return RiskBand.GREEN
    if score < _AMBER_MAX:
        return RiskBand.AMBER
    return RiskBand.RED


def _advisory_for(band: str) -> str:
    if band is RiskBand.GREEN:
        return "Activity baseline normal. Carry on."
    if band is RiskBand.AMBER:
        return (
            "Elevated activity. Consider longer cooldowns between cuts, "
            "or step away for 10-15 minutes."
        )
    return (
        "Sustained anomaly detected. Recommend stopping disruption for "
        "30+ minutes and reviewing recent outcomes before resuming."
    )


def _scale(numerator: float, denominator: float, cap: int) -> int:
    """Linear scale clamped to [0, cap]. denominator==0 → 0."""
    if denominator <= 0:
        return 0
    return max(0, min(cap, int(round((numerator / denominator) * cap))))


def _rate_contribution(start_times: List[float], now: float) -> RiskContribution:
    """Cuts in the last 30 minutes."""
    cutoff = now - _RATE_WINDOW_S
    recent = sum(1 for t in start_times if t >= cutoff)
    over_threshold = max(0, recent - _RATE_THRESHOLD_PER_WINDOW)
    value = _scale(over_threshold, _RATE_THRESHOLD_PER_WINDOW, _RATE_CAP)
    return RiskContribution(
        label="Recent cut rate",
        value=value,
        cap=_RATE_CAP,
        detail=f"{recent} cuts in last 30m (threshold {_RATE_THRESHOLD_PER_WINDOW})",
    )


def _failure_streak_contribution(outcomes: List[Optional[bool]]) -> RiskContribution:
    """Failures in the most recent N labeled episodes."""
    labeled = [o for o in outcomes if o is not None]
    window = labeled[:_FAILURE_STREAK_WINDOW]
    failures = sum(1 for o in window if o is False)
    value = _scale(failures, _FAILURE_STREAK_WINDOW, _FAILURE_STREAK_CAP)
    return RiskContribution(
        label="Recent failure streak",
        value=value,
        cap=_FAILURE_STREAK_CAP,
        detail=f"{failures} failures in last {len(window)} labeled episodes",
    )


def _success_rate_contribution(summary: dict) -> RiskContribution:
    """Overall success rate shortfall vs 50% floor."""
    labeled = summary.get("labeled", 0) or 0
    if labeled < 3:
        return RiskContribution(
            label="Overall success rate",
            value=0,
            cap=_SUCCESS_RATE_CAP,
            detail="too few labeled episodes (<3) to assess",
        )
    rate = summary.get("success_rate", 0.0) or 0.0
    shortfall = max(0.0, _SUCCESS_RATE_FLOOR - rate)
    # Map shortfall (0..0.5) to (0..cap) linearly.
    value = int(round((shortfall / _SUCCESS_RATE_FLOOR) * _SUCCESS_RATE_CAP))
    value = max(0, min(_SUCCESS_RATE_CAP, value))
    return RiskContribution(
        label="Overall success rate",
        value=value,
        cap=_SUCCESS_RATE_CAP,
        detail=f"{rate*100:.0f}% success across {labeled} labeled episodes",
    )


def _compression_contribution(start_times: List[float]) -> RiskContribution:
    """Pairs of consecutive cuts within 60s of each other."""
    if len(start_times) < 2:
        return RiskContribution(
            label="Cut compression",
            value=0,
            cap=_COMPRESSION_CAP,
            detail="not enough cuts to assess spacing",
        )
    sorted_ts = sorted(start_times)
    close_pairs = sum(
        1 for i in range(1, len(sorted_ts))
        if (sorted_ts[i] - sorted_ts[i - 1]) < _COMPRESSION_THRESHOLD_S
    )
    value = _scale(close_pairs, len(sorted_ts), _COMPRESSION_CAP)
    return RiskContribution(
        label="Cut compression",
        value=value,
        cap=_COMPRESSION_CAP,
        detail=f"{close_pairs}/{len(sorted_ts)-1} pairs <{_COMPRESSION_THRESHOLD_S}s apart",
    )


def _never_cut_contribution(summary: dict) -> RiskContribution:
    """Episodes where the cut verifier never saw severance."""
    total = summary.get("total", 0) or 0
    never_cut = summary.get("never_cut", 0) or 0
    if total < 5:
        return RiskContribution(
            label="Cut effectiveness",
            value=0,
            cap=_NEVER_CUT_CAP,
            detail="too few episodes (<5) to assess",
        )
    ratio = never_cut / total
    excess = max(0.0, ratio - _NEVER_CUT_FLOOR)
    value = int(round(
        (excess / (1.0 - _NEVER_CUT_FLOOR)) * _NEVER_CUT_CAP
    ))
    value = max(0, min(_NEVER_CUT_CAP, value))
    return RiskContribution(
        label="Cut effectiveness",
        value=value,
        cap=_NEVER_CUT_CAP,
        detail=f"{ratio*100:.0f}% of {total} episodes never severed",
    )


def _audit_volume_contribution(audit_path: Optional[str], now: float) -> RiskContribution:
    """Audit-log event count in the last hour."""
    import os
    if not audit_path or not os.path.exists(audit_path):
        return RiskContribution(
            label="Audit activity",
            value=0,
            cap=_AUDIT_CAP,
            detail="audit log not available",
        )
    cutoff = now - _AUDIT_RATE_WINDOW_S
    count = 0
    # Streamed line read; audit log is JSONL with a "ts" or "timestamp"
    # field. Keep parsing forgiving — a malformed line yields skip.
    try:
        import json
        with open(audit_path, "r", encoding="utf-8") as f:
            # Read from the END since we want recent events; cheap
            # approximation: tail last 4096 events worth of bytes.
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 256 * 1024))  # ~256 KB tail
            tail = f.read()
        for line in tail.splitlines():
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            ts = obj.get("ts") or obj.get("timestamp") or 0
            try:
                ts_val = float(ts) if isinstance(ts, (int, float)) else 0.0
            except Exception:
                ts_val = 0.0
            if ts_val >= cutoff:
                count += 1
    except Exception as exc:
        log_warning(f"risk_score: audit tail read failed: {exc}")
        return RiskContribution(
            label="Audit activity",
            value=0,
            cap=_AUDIT_CAP,
            detail="audit read error",
        )
    over_threshold = max(0, count - _AUDIT_THRESHOLD_EVENTS)
    value = _scale(over_threshold, _AUDIT_THRESHOLD_EVENTS, _AUDIT_CAP)
    return RiskContribution(
        label="Audit activity",
        value=value,
        cap=_AUDIT_CAP,
        detail=f"{count} events in last 1h (threshold {_AUDIT_THRESHOLD_EVENTS})",
    )


# ── Public API ────────────────────────────────────────────────────────

def compute_risk_score(
    *,
    audit_log_path: Optional[str] = None,
    now: Optional[float] = None,
) -> RiskScore:
    """Compute the current risk score.

    All inputs come from the existing telemetry layer. Safe to call
    from a UI thread at refresh cadence (1-5s); the heaviest path is
    a 256KB tail read of the audit log.

    Args:
        audit_log_path: optional override for the audit JSONL path.
            Defaults to ``app/data/audit.jsonl`` via the persistence
            manager.
        now: optional clock injection for tests. Defaults to time.time().

    Returns:
        :class:`RiskScore` with per-factor breakdown for the UI.
        Never raises — internal failures degrade the offending factor
        to zero with a log warning.
    """
    ts = now if now is not None else time.time()

    # Pull episode telemetry from the learning loop.
    try:
        from app.ai.learning_loop import LearningLoop
        ll = LearningLoop()
        summary = ll.session_summary()
        recent = ll.recent_episodes(limit=200)
    except Exception as exc:
        log_warning(f"risk_score: learning_loop unavailable: {exc}")
        summary = {
            "total": 0, "labeled": 0, "successes": 0, "failures": 0,
            "success_rate": 0.0, "severed": 0, "degraded": 0,
            "never_cut": 0, "last_session_ts": None,
        }
        recent = []

    start_times = [getattr(e, "start_ts", 0.0) for e in recent if getattr(e, "start_ts", 0.0) > 0]
    outcomes = [getattr(e, "outcome", None) for e in recent]

    # Resolve audit log path lazily.
    if audit_log_path is None:
        try:
            from app.core.data_persistence import persistence_manager
            audit_log_path = str(
                persistence_manager.data_directory / "audit.jsonl"
            )
        except Exception:
            audit_log_path = None

    contributions = [
        _rate_contribution(start_times, ts),
        _failure_streak_contribution(outcomes),
        _success_rate_contribution(summary),
        _compression_contribution(start_times),
        _never_cut_contribution(summary),
        _audit_volume_contribution(audit_log_path, ts),
    ]
    score = sum(c.value for c in contributions)
    score = max(0, min(100, score))
    band = _classify_band(score)
    return RiskScore(
        score=score,
        band=band,
        contributions=contributions,
        computed_at=ts,
        advisory=_advisory_for(band),
    )
