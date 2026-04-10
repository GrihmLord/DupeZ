#!/usr/bin/env python3
"""
Tick-Synchronized Disruption — Phase 3 of DupeZ v5 Roadmap.

Aligns disruption bursts with the game server's tick boundaries for
maximum impact. Instead of disrupting packets uniformly over time,
this module estimates the server's tick rate and times disruption
bursts to coincide with tick boundaries — causing maximum state
desync with minimum total packet manipulation.

DayZ Enfusion Tick Model:
  - Server runs a variable-rate simulation loop (20-60 FPS depending on load)
  - Each tick processes player inputs, runs physics, replicates entity state
  - State replication happens at the END of each tick — all entity updates
    for that tick are batched into UDP datagrams
  - Tick rate is observable via packet inter-arrival timing analysis

Why Tick Sync Matters:
  Uniform disruption (e.g., 30% random drop) wastes effort — many dropped
  packets are mid-tick data that would be superseded by the next tick anyway.
  By concentrating drops AT tick boundaries, we:
    1. Drop the critical state replication packets (the batched updates)
    2. Let keepalives and mid-tick traffic through (maintains connection)
    3. Achieve the same disruption effect with ~50% fewer dropped packets
    4. Much harder for anti-cheat to detect (lower overall drop rate)

  DayZ's 1.27+ player-freeze system monitors connection quality. Steady
  packet loss triggers the freeze. Pulsed disruption (burst-rest-burst)
  stays below the detection threshold because the connection looks healthy
  during rest periods — average metrics stay acceptable even though the
  bursts are devastating.

Tick Rate Estimation:
  Uses inter-packet arrival time analysis on inbound UDP traffic to the
  DayZ port. The dominant frequency in the arrival time histogram
  corresponds to the server's tick rate.

  Method: Running median of inter-arrival times, filtered to remove
  outliers (keepalives, retransmits). The reciprocal of the median IAT
  gives an estimate of the tick rate.

Pulse Mode:
  Configurable burst/rest cycle:
    burst_ticks:  Number of consecutive ticks to disrupt (default 3)
    rest_ticks:   Number of ticks to let through (default 5)

  This creates a sawtooth pattern: 3 ticks of heavy disruption, 5 ticks
  of clear connection, repeat. The client experiences freeze-unfreeze-freeze
  cycles that are extremely disorienting while staying below DayZ's
  connection quality threshold.

Modules:
  - TickEstimator: Passive tick rate estimator (runs on packet timestamps)
  - TickSyncDropModule: Drop packets aligned with tick boundaries
  - PulseDisruptionModule: Burst/rest cycle synchronized to ticks
"""

from __future__ import annotations

import heapq
import time
import threading
from collections import defaultdict, deque
from typing import Dict

from app.logs.logger import log_info

from app.firewall.native_divert_engine import (
    DisruptionModule,
    WINDIVERT_ADDRESS,
)

__all__ = [
    "TickEstimator",
    "TickSyncDropModule",
    "PulseDisruptionModule",
    "TICK_SYNC_MODULE_MAP",
]


class TickEstimator:
    """Estimates game server tick rate from packet inter-arrival times.

    Operates on inbound UDP packet timestamps (server → client direction).
    Uses a sliding window of inter-arrival times and computes the dominant
    frequency via running median.

    The estimator is passive — it only observes packets, never modifies
    them. It should be updated on every inbound packet by the disruption
    module that uses it.

    Attributes:
        estimated_tick_hz: Current tick rate estimate in Hz (0 if unknown)
        estimated_tick_ms: Current tick interval in ms (0 if unknown)
        confidence:        Estimation confidence 0-1
    """

    def __init__(self, window_size: int = 120, min_samples: int = 20) -> None:
        self._window_size = window_size
        self._min_samples = min_samples

        # Sliding window of inter-arrival times (seconds).
        # Kept unbounded-by-deque to allow manual eviction so we can keep
        # the streaming median heaps + running sums in sync.
        self._iats: deque = deque()
        self._last_arrival: float = 0.0
        self._lock = threading.Lock()

        # Streaming median state — two-heap with lazy deletion.
        # _lo is a max-heap (values negated); _hi is a min-heap.
        # Effective sizes exclude pending lazy deletions.
        self._lo: list = []
        self._hi: list = []
        self._lo_size: int = 0
        self._hi_size: int = 0
        self._lo_delete: Dict[float, int] = defaultdict(int)
        self._hi_delete: Dict[float, int] = defaultdict(int)

        # Streaming variance state — running sum and sum-of-squares over
        # the sliding window. variance = (sum_sq - n*mean^2) / (n-1).
        # For IATs in [0.001, 0.5] and n<=120 the cancellation loss is
        # ~2 decimal digits out of 15 — well within tolerance.
        self._sum: float = 0.0
        self._sum_sq: float = 0.0

        # Current estimate
        self.estimated_tick_hz: float = 0.0
        self.estimated_tick_ms: float = 0.0
        self.confidence: float = 0.0

        # Outlier bounds — IATs outside this range are likely not tick-aligned.
        # v5.1: Widened to handle future Enfusion tick rates (could go >200Hz)
        # and degraded servers (<5Hz). Loaded from game profile if available.
        try:
            from app.config.game_profiles import get_tick_model
            tm = get_tick_model("dayz")
            self._iat_min = tm.get("iat_min_sec", 0.001)   # 1ms  (1000 Hz ceiling)
            self._iat_max = tm.get("iat_max_sec", 0.500)   # 500ms (2 Hz floor)
        except Exception:
            self._iat_min = 0.001   # 1ms  (1000 Hz ceiling)
            self._iat_max = 0.500   # 500ms (2 Hz floor)

    @property
    def last_arrival(self) -> float:
        """Last observed packet arrival timestamp (seconds)."""
        return self._last_arrival

    # ── Streaming median helpers (two-heap, lazy deletion) ──────────────

    def _median_prune_lo(self) -> None:
        while self._lo:
            top = -self._lo[0]
            if self._lo_delete.get(top, 0) > 0:
                heapq.heappop(self._lo)
                self._lo_delete[top] -= 1
                if self._lo_delete[top] == 0:
                    del self._lo_delete[top]
            else:
                break

    def _median_prune_hi(self) -> None:
        while self._hi:
            top = self._hi[0]
            if self._hi_delete.get(top, 0) > 0:
                heapq.heappop(self._hi)
                self._hi_delete[top] -= 1
                if self._hi_delete[top] == 0:
                    del self._hi_delete[top]
            else:
                break

    def _median_rebalance(self) -> None:
        # |lo| must equal |hi| or |hi|+1
        while self._lo_size > self._hi_size + 1:
            self._median_prune_lo()
            v = -heapq.heappop(self._lo)
            self._lo_size -= 1
            heapq.heappush(self._hi, v)
            self._hi_size += 1
        while self._hi_size > self._lo_size:
            self._median_prune_hi()
            v = heapq.heappop(self._hi)
            self._hi_size -= 1
            heapq.heappush(self._lo, -v)
            self._lo_size += 1
        self._median_prune_lo()
        self._median_prune_hi()

    def _median_add(self, v: float) -> None:
        self._median_prune_lo()
        if not self._lo or v <= -self._lo[0]:
            heapq.heappush(self._lo, -v)
            self._lo_size += 1
        else:
            heapq.heappush(self._hi, v)
            self._hi_size += 1
        self._median_rebalance()

    def _median_remove(self, v: float) -> None:
        self._median_prune_lo()
        if self._lo and v <= -self._lo[0]:
            self._lo_delete[v] += 1
            self._lo_size -= 1
        else:
            self._hi_delete[v] += 1
            self._hi_size -= 1
        self._median_rebalance()

    def _median_value(self) -> float:
        total = self._lo_size + self._hi_size
        if total == 0:
            return 0.0
        self._median_prune_lo()
        if not self._lo:
            return 0.0
        if total % 2 == 1:
            return -self._lo[0]
        self._median_prune_hi()
        if not self._hi:
            return -self._lo[0]
        return (-self._lo[0] + self._hi[0]) / 2.0

    # ── Public API ─────────────────────────────────────────────────────

    def update(self, timestamp: float) -> None:
        """Record a packet arrival time and update the tick estimate."""
        with self._lock:
            if self._last_arrival > 0:
                iat = timestamp - self._last_arrival
                if self._iat_min <= iat <= self._iat_max:
                    # Manual FIFO eviction so streaming state stays in sync
                    if len(self._iats) >= self._window_size:
                        old = self._iats.popleft()
                        self._sum -= old
                        self._sum_sq -= old * old
                        self._median_remove(old)
                    self._iats.append(iat)
                    self._sum += iat
                    self._sum_sq += iat * iat
                    self._median_add(iat)
            self._last_arrival = timestamp

            if len(self._iats) >= self._min_samples:
                self._recompute()

    def _recompute(self) -> None:
        """Recompute tick rate from current streaming window state.

        O(1) amortized — median comes from the two-heap top, variance
        from running sum and sum-of-squares. Lazy deletions may trigger
        O(log n) heap prunes but those amortize away across the window.
        """
        n = len(self._iats)
        if n < self._min_samples:
            return

        median_iat = self._median_value()
        if median_iat <= 0:
            return

        hz = 1.0 / median_iat
        ms = median_iat * 1000.0

        # Sample variance with Bessel's correction
        if n >= 2:
            mean = self._sum / n
            var = (self._sum_sq - n * mean * mean) / (n - 1)
            if var < 0.0:
                var = 0.0  # clamp floating-point noise
            stdev = var ** 0.5
            cv = stdev / median_iat
        else:
            cv = 1.0

        # Map CV to confidence: CV<0.3 → high, CV>1.0 → low
        confidence = max(0.0, min(1.0, 1.0 - cv))

        self.estimated_tick_hz = hz
        self.estimated_tick_ms = ms
        self.confidence = confidence

    def get_next_tick_time(self, now: float) -> float:
        """Predict when the next tick boundary will occur.

        Returns the estimated timestamp of the next tick, based on the
        last observed packet arrival and the estimated tick interval.
        Returns `now` if estimation isn't ready.
        """
        if self.estimated_tick_ms <= 0 or self._last_arrival <= 0:
            return now

        tick_interval = self.estimated_tick_ms / 1000.0
        elapsed = now - self._last_arrival
        ticks_elapsed = elapsed / tick_interval
        next_tick_offset = (1.0 - (ticks_elapsed % 1.0)) * tick_interval
        return now + next_tick_offset

    def get_stats(self) -> Dict:
        return {
            "tick_hz": round(self.estimated_tick_hz, 1),
            "tick_ms": round(self.estimated_tick_ms, 1),
            "confidence": round(self.confidence, 3),
            "samples": len(self._iats),
        }


class TickSyncDropModule(DisruptionModule):
    """Drop packets aligned with estimated tick boundaries.

    Instead of random uniform drop, concentrates drops around the
    estimated tick boundary (when state replication packets are sent).
    This creates maximum desync with minimum average drop rate.

    The module operates in two phases:
      1. Learning phase: First N packets are passed through while the
         TickEstimator builds a reliable tick rate estimate.
      2. Active phase: Drops packets within a configurable window
         around each estimated tick boundary.

    Parameters:
      ts_drop_window_pct:  float — fraction of tick interval to drop (0-1, default 0.4)
                                   0.4 = drop packets in the last 40% of each tick
                                   (when state replication happens)
      ts_drop_chance:      float — drop probability within the window (0-100, default 90)
      ts_learning_packets: int   — packets to observe before activating (default 100)
      ts_min_confidence:   float — minimum estimator confidence to activate (0-1, default 0.3)
    """

    _direction_key = "tick_sync"

    def __init__(self, params: dict) -> None:
        super().__init__(params)
        self._estimator = TickEstimator()
        self._drop_window_pct = max(0.0, min(1.0,
            float(params.get("ts_drop_window_pct", 0.4))))
        self._drop_chance = max(0, min(100,
            float(params.get("ts_drop_chance", 90))))
        self._learning_packets = max(0,
            int(params.get("ts_learning_packets", 100)))
        self._min_confidence = max(0.0, min(1.0,
            float(params.get("ts_min_confidence", 0.3))))

        self._packets_seen = 0
        self._in_window_drops = 0
        self._out_window_passes = 0
        self._learning = True

        log_info(
            f"TickSyncDrop: window={self._drop_window_pct:.0%}, "
            f"chance={self._drop_chance}%, "
            f"learning={self._learning_packets} pkts")

    def process(self, packet_data: bytearray, addr: WINDIVERT_ADDRESS,
                send_fn) -> bool:
        now = time.monotonic()
        self._packets_seen += 1

        # Always feed the estimator (inbound packets only for tick estimation)
        if not addr.Outbound:
            self._estimator.update(now)

        # Learning phase — pass everything through
        if self._learning:
            if (self._packets_seen >= self._learning_packets and
                    self._estimator.confidence >= self._min_confidence):
                self._learning = False
                log_info(
                    f"TickSyncDrop: learning complete — "
                    f"tick={self._estimator.estimated_tick_hz:.0f}Hz "
                    f"({self._estimator.estimated_tick_ms:.1f}ms), "
                    f"confidence={self._estimator.confidence:.2f}")
            return False

        # Active phase — drop based on tick position
        tick_ms = self._estimator.estimated_tick_ms
        if tick_ms <= 0:
            return False  # no estimate yet

        # Compute position within current tick (0.0 = start, 1.0 = end)
        tick_interval = tick_ms / 1000.0
        if self._estimator.last_arrival <= 0:
            return False

        elapsed = now - self._estimator.last_arrival
        position_in_tick = (elapsed / tick_interval) % 1.0

        # Drop if we're in the drop window (end of tick = state replication)
        window_start = 1.0 - self._drop_window_pct
        if position_in_tick >= window_start:
            if self._roll(self._drop_chance):
                self._in_window_drops += 1
                return True  # drop
        else:
            self._out_window_passes += 1

        return False

    def get_stats(self) -> Dict:
        return {
            "learning": self._learning,
            "packets_seen": self._packets_seen,
            "in_window_drops": self._in_window_drops,
            "out_window_passes": self._out_window_passes,
            "estimator": self._estimator.get_stats(),
        }


class PulseDisruptionModule(DisruptionModule):
    """Burst/rest cycle disruption synchronized to tick boundaries.

    Creates a pulsed disruption pattern:
      BURST phase: disrupt for N ticks (heavy drop/lag)
      REST phase:  pass through for M ticks (connection looks healthy)

    The pulse timing is synchronized to the estimated tick rate so bursts
    align with tick boundaries for maximum impact.

    DayZ 1.27+ anti-desync countermeasure bypass:
      DayZ monitors average connection quality over a sliding window
      (~5-10 seconds). Sustained disruption triggers the player-freeze
      system. Pulsed disruption with appropriately sized rest periods
      keeps the sliding average below the freeze threshold.

      Recommended: burst_ticks=3, rest_ticks=5 at 30Hz server
        → 100ms burst every 267ms
        → Average disruption: ~37.5%
        → But concentrated in 100ms windows for maximum per-burst impact

    Parameters:
      pulse_burst_ticks:   int   — ticks to disrupt (default 3)
      pulse_rest_ticks:    int   — ticks to rest (default 5)
      pulse_drop_chance:   float — drop chance during burst (0-100, default 95)
      pulse_learning:      int   — packets before activation (default 100)
      pulse_min_confidence: float — estimator confidence threshold (default 0.3)
    """

    _direction_key = "pulse"

    def __init__(self, params: dict) -> None:
        super().__init__(params)
        self._estimator = TickEstimator()
        self._burst_ticks = max(1, int(params.get("pulse_burst_ticks", 3)))
        self._rest_ticks = max(1, int(params.get("pulse_rest_ticks", 5)))
        self._drop_chance = max(0, min(100,
            float(params.get("pulse_drop_chance", 95))))
        self._learning_packets = max(0,
            int(params.get("pulse_learning", 100)))
        self._min_confidence = max(0.0, min(1.0,
            float(params.get("pulse_min_confidence", 0.3))))

        self._cycle_length = self._burst_ticks + self._rest_ticks
        self._packets_seen = 0
        self._learning = True
        self._burst_drops = 0
        self._rest_passes = 0
        self._cycle_start_time: float = 0.0

        log_info(
            f"PulseDisruption: burst={self._burst_ticks} ticks, "
            f"rest={self._rest_ticks} ticks, "
            f"drop_chance={self._drop_chance}%")

    def _is_burst_phase(self, now: float) -> bool:
        """Determine if we're in the burst or rest phase of the cycle."""
        tick_ms = self._estimator.estimated_tick_ms
        if tick_ms <= 0:
            return False

        tick_s = tick_ms / 1000.0
        cycle_duration = self._cycle_length * tick_s

        if self._cycle_start_time <= 0:
            self._cycle_start_time = now

        elapsed = now - self._cycle_start_time
        position_in_cycle = elapsed % cycle_duration
        burst_duration = self._burst_ticks * tick_s

        return position_in_cycle < burst_duration

    def process(self, packet_data: bytearray, addr: WINDIVERT_ADDRESS,
                send_fn) -> bool:
        now = time.monotonic()
        self._packets_seen += 1

        # Feed estimator with inbound packets
        if not addr.Outbound:
            self._estimator.update(now)

        # Learning phase
        if self._learning:
            if (self._packets_seen >= self._learning_packets and
                    self._estimator.confidence >= self._min_confidence):
                self._learning = False
                self._cycle_start_time = now
                log_info(
                    f"PulseDisruption: active — "
                    f"tick={self._estimator.estimated_tick_hz:.0f}Hz, "
                    f"cycle={self._burst_ticks}+{self._rest_ticks} ticks")
            return False

        # Active phase
        if self._is_burst_phase(now):
            if self._roll(self._drop_chance):
                self._burst_drops += 1
                return True  # drop during burst
        else:
            self._rest_passes += 1

        return False  # pass through during rest

    def get_stats(self) -> Dict:
        return {
            "learning": self._learning,
            "packets_seen": self._packets_seen,
            "burst_drops": self._burst_drops,
            "rest_passes": self._rest_passes,
            "cycle": f"{self._burst_ticks}B/{self._rest_ticks}R",
            "estimator": self._estimator.get_stats(),
        }


# ═══════════════════════════════════════════════════════════════════════
# Module Registration
# ═══════════════════════════════════════════════════════════════════════

TICK_SYNC_MODULE_MAP = {
    "tick_sync": TickSyncDropModule,
    "pulse":     PulseDisruptionModule,
}
