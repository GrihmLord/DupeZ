#!/usr/bin/env python3
"""
ML-Enhanced Traffic Analyzer — Phase 6 of DupeZ v5 Roadmap.

Adds real-time traffic pattern analysis and session learning to the
network profiler. Runs alongside the packet engine to classify live
traffic, estimate server tick rate, detect game state transitions
(lobby → loading → in-game → combat), and auto-tune disruption
parameters based on observed traffic patterns.

This module is designed as a passive observer — it receives packet
metadata from the engine without modifying packets. It publishes
recommendations that the SmartDisruptionEngine can act on.

Components:
  - TrafficPatternAnalyzer: Real-time traffic statistics and pattern detection
  - SessionLearner: Accumulates per-session data to improve recommendations
  - GameStateDetector: Classifies game state from traffic patterns
  - AdaptiveTuner: Adjusts disruption params in real-time based on feedback

Architecture:
  Engine packet loop → observer callback → TrafficPatternAnalyzer
    → GameStateDetector (classifies state)
    → AdaptiveTuner (adjusts params)
    → SessionLearner (records session data)
"""

from __future__ import annotations

import time
import threading
import statistics
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Tuple

from app.logs.logger import log_info

__all__ = [
    "GameState",
    "TrafficSnapshot",
    "TrafficPatternAnalyzer",
    "GameStateDetector",
    "AdaptiveTuner",
    "SessionLearner",
]


class GameState(Enum):
    """Detected game state based on traffic patterns."""
    UNKNOWN = auto()
    MENU = auto()         # Main menu / server browser (low traffic)
    LOADING = auto()       # Loading screen (burst of bulk downloads)
    IN_GAME_IDLE = auto()  # In-game, not in combat (steady moderate traffic)
    IN_GAME_COMBAT = auto()  # Active combat (elevated traffic, more inputs)
    DISCONNECTED = auto()  # No traffic / connection lost


@dataclass
class TrafficSnapshot:
    """A snapshot of traffic statistics over a time window."""
    timestamp: float = 0.0
    window_sec: float = 1.0

    # Packet counts
    total_packets: int = 0
    inbound_packets: int = 0
    outbound_packets: int = 0

    # Byte counts
    total_bytes: int = 0
    inbound_bytes: int = 0
    outbound_bytes: int = 0

    # Rates (per second)
    packets_per_sec: float = 0.0
    bytes_per_sec: float = 0.0
    inbound_pps: float = 0.0
    outbound_pps: float = 0.0

    # Size distribution
    avg_packet_size: float = 0.0
    min_packet_size: int = 0
    max_packet_size: int = 0

    # Timing
    avg_iat_ms: float = 0.0  # inter-arrival time
    jitter_ms: float = 0.0

    # Derived
    asymmetry_ratio: float = 1.0  # inbound/outbound ratio


class TrafficPatternAnalyzer:
    """Real-time traffic pattern analysis.

    Maintains a sliding window of packet events and computes rolling
    statistics. Designed for the packet loop's hot path — all operations
    are O(1) amortized.
    """

    def __init__(self, window_sec: float = 2.0, snapshot_interval: float = 1.0) -> None:
        self._window_sec = window_sec
        self._snapshot_interval = snapshot_interval

        # Per-packet event log: (timestamp, size, is_outbound)
        self._events: deque = deque(maxlen=5000)
        self._lock = threading.Lock()

        # IAT tracking for inbound packets
        self._last_inbound_time: float = 0.0
        self._iats: deque = deque(maxlen=200)

        # Rolling snapshots
        self._snapshots: deque = deque(maxlen=120)  # ~2 min history
        self._last_snapshot_time: float = 0.0

        # Aggregate stats
        self._total_packets = 0
        self._total_bytes = 0

    def record_packet(self, timestamp: float, size: int,
                      is_outbound: bool) -> None:
        """Record a packet event. Called from packet loop — must be fast."""
        with self._lock:
            self._events.append((timestamp, size, is_outbound))
            self._total_packets += 1
            self._total_bytes += size

            # Track IAT for inbound packets
            if not is_outbound:
                if self._last_inbound_time > 0:
                    iat = timestamp - self._last_inbound_time
                    if 0.001 <= iat <= 1.0:  # filter outliers
                        self._iats.append(iat)
                self._last_inbound_time = timestamp

        # Periodic snapshot generation
        if timestamp - self._last_snapshot_time >= self._snapshot_interval:
            self._generate_snapshot(timestamp)

    def _generate_snapshot(self, now: float) -> None:
        """Compute a TrafficSnapshot from the current window."""
        self._last_snapshot_time = now
        cutoff = now - self._window_sec

        with self._lock:
            # Filter events in window
            in_window = [(t, s, o) for t, s, o in self._events if t >= cutoff]

        if not in_window:
            return

        snap = TrafficSnapshot(
            timestamp=now,
            window_sec=self._window_sec,
            total_packets=len(in_window),
        )

        sizes = []
        for t, s, o in in_window:
            sizes.append(s)
            snap.total_bytes += s
            if o:
                snap.outbound_packets += 1
                snap.outbound_bytes += s
            else:
                snap.inbound_packets += 1
                snap.inbound_bytes += s

        snap.packets_per_sec = snap.total_packets / self._window_sec
        snap.bytes_per_sec = snap.total_bytes / self._window_sec
        snap.inbound_pps = snap.inbound_packets / self._window_sec
        snap.outbound_pps = snap.outbound_packets / self._window_sec

        if sizes:
            snap.avg_packet_size = sum(sizes) / len(sizes)
            snap.min_packet_size = min(sizes)
            snap.max_packet_size = max(sizes)

        # IAT stats
        with self._lock:
            iats = list(self._iats)
        if len(iats) >= 2:
            snap.avg_iat_ms = statistics.mean(iats) * 1000
            snap.jitter_ms = statistics.stdev(iats) * 1000

        # Asymmetry ratio
        if snap.outbound_packets > 0:
            snap.asymmetry_ratio = snap.inbound_packets / snap.outbound_packets
        elif snap.inbound_packets > 0:
            snap.asymmetry_ratio = float('inf')

        self._snapshots.append(snap)

    def get_latest_snapshot(self) -> Optional[TrafficSnapshot]:
        """Return the most recent snapshot."""
        return self._snapshots[-1] if self._snapshots else None

    def get_snapshot_history(self, count: int = 10) -> List[TrafficSnapshot]:
        """Return the last N snapshots."""
        return list(self._snapshots)[-count:]

    def get_stats(self) -> Dict:
        snap = self.get_latest_snapshot()
        if not snap:
            return {"total_packets": self._total_packets, "total_bytes": self._total_bytes}
        return {
            "total_packets": self._total_packets,
            "total_bytes": self._total_bytes,
            "pps": round(snap.packets_per_sec, 1),
            "bps": round(snap.bytes_per_sec, 0),
            "inbound_pps": round(snap.inbound_pps, 1),
            "outbound_pps": round(snap.outbound_pps, 1),
            "avg_size": round(snap.avg_packet_size, 0),
            "avg_iat_ms": round(snap.avg_iat_ms, 1),
            "jitter_ms": round(snap.jitter_ms, 1),
            "asymmetry": round(snap.asymmetry_ratio, 2),
        }


class GameStateDetector:
    """Classifies the current game state from traffic patterns.

    v5.1: Supports both absolute thresholds (defaults from game profile)
    and relative/baseline mode where thresholds are multipliers against
    an observed baseline. Relative mode makes detection resilient to
    tick rate changes and server performance shifts.

    States:
      - MENU: low pps, small packets
      - LOADING: high bps, large packets (bulk state download)
      - IN_GAME_IDLE: steady moderate pps, mixed sizes
      - IN_GAME_COMBAT: elevated pps, higher outbound ratio
      - DISCONNECTED: zero or near-zero traffic

    The classifier operates on TrafficSnapshots produced by the analyzer.
    """

    def __init__(self, use_baseline: bool = True) -> None:
        self._current_state = GameState.UNKNOWN
        self._state_since: float = time.monotonic()
        self._state_history: deque = deque(maxlen=60)

        # Baseline mode: thresholds are relative to observed in-game baseline
        self._use_baseline = use_baseline
        self._baseline_pps: float = 0.0
        self._baseline_bps: float = 0.0
        self._baseline_set = False
        self._baseline_samples: deque = deque(maxlen=30)  # collect first 30 snapshots

        # Multipliers (from game profile or defaults)
        try:
            from app.config.game_profiles import get as gp_get
            gsd = gp_get("dayz", "game_state_detection", "baseline_multipliers", default={})
            self._m_disconnected = gsd.get("disconnected", 0.05)
            self._m_menu = gsd.get("menu", 0.25)
            self._m_loading_bps = gsd.get("loading_bps", 3.0)
            self._m_combat_pps = gsd.get("combat_pps", 1.5)
        except Exception:
            self._m_disconnected = 0.05
            self._m_menu = 0.25
            self._m_loading_bps = 3.0
            self._m_combat_pps = 1.5

        # Absolute fallback thresholds (used before baseline is set)
        try:
            from app.config.game_profiles import get as gp_get
            gsd_abs = gp_get("dayz", "game_state_detection", "thresholds", default={})
            self._abs_disconnected_pps = gsd_abs.get("disconnected_pps", 2)
            self._abs_menu_pps = gsd_abs.get("menu_pps", 10)
            self._abs_menu_avg_size = gsd_abs.get("menu_avg_size", 200)
            self._abs_loading_bps = gsd_abs.get("loading_bps", 50000)
            self._abs_loading_avg_size = gsd_abs.get("loading_avg_size", 500)
            self._abs_combat_pps = gsd_abs.get("combat_pps", 40)
            self._abs_combat_outbound_ratio = gsd_abs.get("combat_outbound_ratio", 0.8)
        except Exception:
            self._abs_disconnected_pps = 2
            self._abs_menu_pps = 10
            self._abs_menu_avg_size = 200
            self._abs_loading_bps = 50000
            self._abs_loading_avg_size = 500
            self._abs_combat_pps = 40
            self._abs_combat_outbound_ratio = 0.8

    def set_baseline(self, snapshot: TrafficSnapshot) -> None:
        """Manually set baseline from a known in-game snapshot."""
        self._baseline_pps = snapshot.packets_per_sec
        self._baseline_bps = snapshot.bytes_per_sec
        self._baseline_set = True
        log_info(f"GameStateDetector: baseline set — "
                 f"pps={self._baseline_pps:.1f}, bps={self._baseline_bps:.0f}")

    def _auto_baseline(self, snapshot: TrafficSnapshot) -> None:
        """Auto-detect baseline from first N snapshots with meaningful traffic."""
        if snapshot.packets_per_sec > self._abs_disconnected_pps:
            self._baseline_samples.append(snapshot)

        if len(self._baseline_samples) >= 10:
            avg_pps = sum(s.packets_per_sec for s in self._baseline_samples) / len(self._baseline_samples)
            avg_bps = sum(s.bytes_per_sec for s in self._baseline_samples) / len(self._baseline_samples)
            self._baseline_pps = avg_pps
            self._baseline_bps = avg_bps
            self._baseline_set = True
            log_info(f"GameStateDetector: auto-baseline — "
                     f"pps={avg_pps:.1f}, bps={avg_bps:.0f} "
                     f"(from {len(self._baseline_samples)} samples)")

    def update(self, snapshot: TrafficSnapshot) -> GameState:
        """Classify game state from a traffic snapshot."""
        prev_state = self._current_state

        # Try to establish baseline if not set
        if self._use_baseline and not self._baseline_set:
            self._auto_baseline(snapshot)

        pps = snapshot.packets_per_sec
        bps = snapshot.bytes_per_sec
        avg_size = snapshot.avg_packet_size

        # Use relative thresholds if baseline is available
        if self._use_baseline and self._baseline_set and self._baseline_pps > 0:
            bp = self._baseline_pps
            bb = self._baseline_bps

            if pps < bp * self._m_disconnected:
                new_state = GameState.DISCONNECTED
            elif pps < bp * self._m_menu and avg_size < self._abs_menu_avg_size:
                new_state = GameState.MENU
            elif bps > bb * self._m_loading_bps and avg_size > self._abs_loading_avg_size:
                new_state = GameState.LOADING
            elif pps >= bp * self._m_menu:
                outbound_ratio = (snapshot.outbound_pps /
                                  max(1, snapshot.inbound_pps))
                if outbound_ratio > self._abs_combat_outbound_ratio and pps > bp * self._m_combat_pps:
                    new_state = GameState.IN_GAME_COMBAT
                else:
                    new_state = GameState.IN_GAME_IDLE
            else:
                new_state = GameState.UNKNOWN
        else:
            # Absolute fallback (profile defaults)
            if pps < self._abs_disconnected_pps:
                new_state = GameState.DISCONNECTED
            elif pps < self._abs_menu_pps and avg_size < self._abs_menu_avg_size:
                new_state = GameState.MENU
            elif bps > self._abs_loading_bps and avg_size > self._abs_loading_avg_size:
                new_state = GameState.LOADING
            elif pps >= self._abs_menu_pps:
                outbound_ratio = (snapshot.outbound_pps /
                                  max(1, snapshot.inbound_pps))
                if outbound_ratio > self._abs_combat_outbound_ratio and pps > self._abs_combat_pps:
                    new_state = GameState.IN_GAME_COMBAT
                else:
                    new_state = GameState.IN_GAME_IDLE
            else:
                new_state = GameState.UNKNOWN

        if new_state != prev_state:
            self._current_state = new_state
            self._state_since = snapshot.timestamp
            log_info(f"GameState: {prev_state.name} → {new_state.name}")

        self._state_history.append((snapshot.timestamp, new_state))
        return new_state

    @property
    def current_state(self) -> GameState:
        return self._current_state

    @property
    def time_in_state(self) -> float:
        return time.monotonic() - self._state_since


class AdaptiveTuner:
    """Auto-tunes disruption parameters based on live traffic feedback.

    Monitors the effect of current disruption settings by comparing
    pre-disruption and during-disruption traffic patterns. Adjusts
    parameters to maintain target effectiveness without over-disrupting
    (which triggers DayZ disconnect detection).

    Tuning strategy:
      1. Monitor target's outbound pps (their keepalive/input rate)
      2. If outbound pps drops to zero for >5s → over-disrupted, reduce intensity
      3. If inbound pps stays too high → under-disrupted, increase intensity
      4. Adjust every N seconds within bounds

    This is a simple proportional controller, not true ML. The "ML" label
    refers to the system's ability to learn per-session optimal settings.
    """

    def __init__(self, adjustment_interval: float = 5.0) -> None:
        self._interval = adjustment_interval
        self._last_adjustment = 0.0
        self._baseline_inbound_pps: float = 0.0
        self._baseline_outbound_pps: float = 0.0
        self._baseline_set = False
        self._adjustments: List[Dict] = []

    def set_baseline(self, snapshot: TrafficSnapshot) -> None:
        """Record baseline traffic before disruption starts."""
        self._baseline_inbound_pps = snapshot.inbound_pps
        self._baseline_outbound_pps = snapshot.outbound_pps
        self._baseline_set = True
        log_info(
            f"AdaptiveTuner: baseline set — "
            f"in={self._baseline_inbound_pps:.1f} pps, "
            f"out={self._baseline_outbound_pps:.1f} pps")

    def evaluate(self, snapshot: TrafficSnapshot,
                 current_params: Dict) -> Optional[Dict]:
        """Evaluate current disruption and suggest parameter adjustments.

        Returns None if no adjustment needed, or a dict of param changes.
        """
        if not self._baseline_set:
            return None

        now = snapshot.timestamp
        if now - self._last_adjustment < self._interval:
            return None
        self._last_adjustment = now

        adjustments = {}

        # Check if target is still alive (outbound keepalives)
        if self._baseline_outbound_pps > 0:
            outbound_ratio = (snapshot.outbound_pps /
                              self._baseline_outbound_pps)
            if outbound_ratio < 0.05:
                # Target may have disconnected — reduce disruption
                adjustments["_reduce_intensity"] = True
                log_info("AdaptiveTuner: target outbound near zero — reducing")

        # Check inbound disruption effectiveness
        if self._baseline_inbound_pps > 0:
            inbound_ratio = (snapshot.inbound_pps /
                             self._baseline_inbound_pps)
            if inbound_ratio > 0.8:
                # Inbound traffic barely affected — increase disruption
                adjustments["_increase_intensity"] = True

        if adjustments:
            self._adjustments.append({
                "timestamp": now,
                "adjustments": adjustments,
            })

        return adjustments if adjustments else None

    def get_history(self) -> List[Dict]:
        return list(self._adjustments)


class SessionLearner:
    """Accumulates session data and learns optimal disruption parameters.

    Records the full timeline of a disruption session:
      - Pre-disruption baseline
      - Disruption start/stop events
      - Parameter changes
      - Traffic snapshots during disruption
      - Outcome (user satisfaction, disruption effectiveness)

    This data is stored in-memory per session and can be exported for
    offline analysis. Future versions could train a simple model on
    accumulated session data to predict optimal parameters for a given
    target profile.
    """

    @dataclass
    class SessionRecord:
        session_id: str = ""
        target_ip: str = ""
        start_time: float = 0.0
        end_time: float = 0.0
        initial_params: Dict = field(default_factory=dict)
        parameter_changes: List[Dict] = field(default_factory=list)
        traffic_snapshots: List[Dict] = field(default_factory=list)
        game_states: List[Tuple] = field(default_factory=list)
        outcome: str = ""  # "success", "disconnect", "manual_stop"

    def __init__(self) -> None:
        self._sessions: Dict[str, SessionLearner.SessionRecord] = {}
        self._active_session: Optional[str] = None

    def start_session(self, session_id: str, target_ip: str,
                      initial_params: Dict) -> None:
        record = self.SessionRecord(
            session_id=session_id,
            target_ip=target_ip,
            start_time=time.monotonic(),
            initial_params=dict(initial_params),
        )
        self._sessions[session_id] = record
        self._active_session = session_id

    def record_snapshot(self, snapshot: TrafficSnapshot) -> None:
        if self._active_session:
            record = self._sessions.get(self._active_session)
            if record:
                record.traffic_snapshots.append({
                    "timestamp": snapshot.timestamp,
                    "pps": snapshot.packets_per_sec,
                    "bps": snapshot.bytes_per_sec,
                    "inbound_pps": snapshot.inbound_pps,
                    "outbound_pps": snapshot.outbound_pps,
                })

    def record_game_state(self, state: GameState) -> None:
        if self._active_session:
            record = self._sessions.get(self._active_session)
            if record:
                record.game_states.append(
                    (time.monotonic(), state.name))

    def record_param_change(self, changes: Dict) -> None:
        if self._active_session:
            record = self._sessions.get(self._active_session)
            if record:
                record.parameter_changes.append({
                    "timestamp": time.monotonic(),
                    "changes": changes,
                })

    def end_session(self, outcome: str = "manual_stop") -> Optional["SessionLearner.SessionRecord"]:
        if self._active_session:
            record = self._sessions.get(self._active_session)
            if record:
                record.end_time = time.monotonic()
                record.outcome = outcome
                duration = record.end_time - record.start_time
                log_info(
                    f"SessionLearner: session ended — "
                    f"duration={duration:.0f}s, "
                    f"outcome={outcome}, "
                    f"snapshots={len(record.traffic_snapshots)}")
            self._active_session = None
            return record
        return None

    def get_session_count(self) -> int:
        return len(self._sessions)

    def get_session(self, session_id: str) -> Optional["SessionLearner.SessionRecord"]:
        return self._sessions.get(session_id)
