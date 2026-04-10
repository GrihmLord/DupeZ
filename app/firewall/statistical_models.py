#!/usr/bin/env python3
"""
Statistical Disruption Models — Phase 1 of DupeZ v5 Roadmap.

Adds mathematically rigorous disruption modules that model real-world
network degradation patterns instead of simple uniform-random chance rolls.

Modules:
  - GilbertElliottDropModule: Two-state Markov chain for bursty packet loss.
    Models real network loss far more accurately than uniform random —
    real losses come in bursts (correlated), not uniformly distributed.

  - ParetoLagModule: Pareto/Paretonormal jitter distribution matching
    tc-netem's delay model. Produces heavy-tailed latency spikes that
    mirror real-world congestion patterns (many small delays, occasional
    large ones).

  - TokenBucketDropModule: Token bucket rate limiter with configurable
    burst capacity. More sophisticated than simple bandwidth limiting —
    allows short bursts at full speed then throttles, exactly like ISP
    traffic shaping and game server rate limiting.

  - CorrelatedDropModule: Drop with temporal autocorrelation — each
    decision is influenced by the previous one. Creates realistic
    degradation patterns where losses tend to cluster in time.

References:
  - Gilbert (1960): "Capacity of a Burst-Noise Channel"
  - Elliott (1963): "Estimates of Error Rates for Codes on Burst-Noise Channels"
  - tc-netem: Linux kernel network emulator (net/sched/sch_netem.c)
  - Pareto distribution: P(X > x) = (x_min/x)^alpha, alpha typically 1.5-3.0
  - Token bucket: RFC 2697 / RFC 2698
"""

from __future__ import annotations

import ctypes
import random
import threading
import time
from collections import deque
from typing import Dict, Optional

from app.logs.logger import log_info

# Import base classes from native engine — these MUST exist for the module
# system to work.  If native engine isn't available, these modules can't
# run either (they need WinDivert packet interception).
from app.firewall.native_divert_engine import (
    DisruptionModule,
    WINDIVERT_ADDRESS,
)

__all__ = [
    "GilbertElliottDropModule",
    "ParetoLagModule",
    "TokenBucketDropModule",
    "CorrelatedDropModule",
    "STATISTICAL_MODULE_MAP",
    "FLUSH_THREAD_MODULES",
]

# ═══════════════════════════════════════════════════════════════════════
# Gilbert-Elliott Two-State Markov Chain Drop Module
# ═══════════════════════════════════════════════════════════════════════

class GilbertElliottDropModule(DisruptionModule):
    """Bursty packet loss using a Gilbert-Elliott two-state Markov chain.

    The model has two states:
      GOOD  — low loss probability (p_loss_good, default 0%)
      BAD   — high loss probability (p_loss_bad, default 100%)

    Transitions between states are controlled by:
      p_good_to_bad  — probability of entering a loss burst (default 5%)
      p_bad_to_good  — probability of exiting a loss burst (default 30%)

    Why this matters for DayZ:
      Real network loss is bursty — packets are lost in clusters, not
      uniformly. A 10% average loss rate with Gilbert-Elliott feels MUCH
      worse than 10% uniform random because the losses are concentrated
      into bursts that overwhelm DayZ's UDP reliability layer.

      DayZ uses a GafferOnGames-style ack bitfield (33 redundant acks).
      Uniform 10% loss rarely loses enough consecutive packets to break
      this redundancy. Gilbert-Elliott with the same average loss rate
      creates bursts of 3-10 consecutive losses that exceed the ack
      window, causing genuine state desync.

    Steady-state analysis:
      Average time in GOOD state: 1 / p_good_to_bad
      Average time in BAD state:  1 / p_bad_to_good
      Steady-state loss rate ≈ p_good_to_bad / (p_good_to_bad + p_bad_to_good)
                                * p_loss_bad

    Parameters:
      ge_p_good_to_bad: float  — transition probability GOOD→BAD (0-1, default 0.05)
      ge_p_bad_to_good: float  — transition probability BAD→GOOD (0-1, default 0.30)
      ge_p_loss_good:   float  — loss probability in GOOD state (0-1, default 0.0)
      ge_p_loss_bad:    float  — loss probability in BAD state (0-1, default 1.0)
    """

    _direction_key = "ge_drop"

    # States
    _STATE_GOOD = 0
    _STATE_BAD = 1

    def __init__(self, params: dict) -> None:
        super().__init__(params)
        self._state = self._STATE_GOOD

        # Transition probabilities (per packet)
        self._p_good_to_bad = self._clamp01(
            params.get("ge_p_good_to_bad", 0.05))
        self._p_bad_to_good = self._clamp01(
            params.get("ge_p_bad_to_good", 0.30))

        # Loss probabilities in each state
        self._p_loss_good = self._clamp01(
            params.get("ge_p_loss_good", 0.0))
        self._p_loss_bad = self._clamp01(
            params.get("ge_p_loss_bad", 1.0))

        # Statistics
        self._packets_seen = 0
        self._packets_dropped = 0
        self._bursts_entered = 0
        self._current_burst_len = 0
        self._max_burst_len = 0

        log_info(
            f"GilbertElliott: p_g2b={self._p_good_to_bad:.3f}, "
            f"p_b2g={self._p_bad_to_good:.3f}, "
            f"p_loss_good={self._p_loss_good:.3f}, "
            f"p_loss_bad={self._p_loss_bad:.3f}, "
            f"steady_state_loss≈{self._steady_state_loss():.1%}")

    @staticmethod
    def _clamp01(v: float) -> float:
        return max(0.0, min(1.0, float(v)))

    def _steady_state_loss(self) -> float:
        """Calculate the theoretical steady-state loss rate."""
        denom = self._p_good_to_bad + self._p_bad_to_good
        if denom == 0:
            return 0.0
        p_in_bad = self._p_good_to_bad / denom
        p_in_good = self._p_bad_to_good / denom
        return p_in_good * self._p_loss_good + p_in_bad * self._p_loss_bad

    def process(self, packet_data: bytearray, addr: WINDIVERT_ADDRESS,
                send_fn) -> bool:
        self._packets_seen += 1

        # State transition
        r = random.random()
        if self._state == self._STATE_GOOD:
            if r < self._p_good_to_bad:
                self._state = self._STATE_BAD
                self._bursts_entered += 1
                self._current_burst_len = 0
        else:  # BAD
            if r < self._p_bad_to_good:
                self._state = self._STATE_GOOD
                self._max_burst_len = max(
                    self._max_burst_len, self._current_burst_len)

        # Loss decision based on current state
        if self._state == self._STATE_GOOD:
            drop = random.random() < self._p_loss_good
        else:
            self._current_burst_len += 1
            drop = random.random() < self._p_loss_bad

        if drop:
            self._packets_dropped += 1
            return True  # consumed (dropped)

        return False  # pass through

    def get_stats(self) -> Dict:
        return {
            "state": "BAD" if self._state == self._STATE_BAD else "GOOD",
            "packets_seen": self._packets_seen,
            "packets_dropped": self._packets_dropped,
            "loss_rate": (self._packets_dropped / max(1, self._packets_seen)),
            "bursts_entered": self._bursts_entered,
            "max_burst_length": self._max_burst_len,
            "theoretical_loss": self._steady_state_loss(),
        }


# ═══════════════════════════════════════════════════════════════════════
# Pareto / Paretonormal Jitter Lag Module
# ═══════════════════════════════════════════════════════════════════════

class ParetoLagModule(DisruptionModule):
    """Heavy-tailed latency jitter using Pareto distribution.

    Models real-world network jitter far more accurately than fixed delay.
    Real jitter follows a heavy-tailed distribution: most packets arrive
    with small delay, but occasional packets experience very large delays.
    This is the pattern that breaks game netcode.

    Distribution (matching tc-netem's paretonormal model):
      base_delay_ms + jitter_ms * pareto_sample

    Where pareto_sample is drawn from a Pareto distribution with shape
    parameter alpha (default 1.5). The Pareto distribution has the property
    that P(X > x) = (x_min/x)^alpha — heavy tail means occasional extreme
    values.

    For DayZ specifically:
      A base delay of 50ms with Pareto jitter (alpha=1.5, jitter=200ms)
      creates a pattern where most packets arrive ~50-100ms late but
      approximately 5% arrive 200-1000ms+ late. These extreme outliers
      are what cause DayZ's "rubber banding" and position desync —
      the client receives a burst of very stale position data that
      conflicts with its prediction model.

    Paretonormal variant (use_normal_blend=True):
      Blends Pareto samples with Gaussian noise for more realistic jitter.
      This matches tc-netem's "distribution paretonormal" mode exactly.

    Parameters:
      pareto_base_ms:    float — base delay applied to all packets (default 50)
      pareto_jitter_ms:  float — jitter amplitude (default 200)
      pareto_alpha:      float — Pareto shape parameter (default 1.5)
                                 Lower alpha = heavier tail = more extreme spikes
                                 1.0 = very heavy, 3.0 = mild
      pareto_correlation: float — temporal correlation 0-1 (default 0.25)
                                  How much each delay depends on the previous one.
                                  0 = independent, 1 = fully correlated (random walk)
      pareto_normal_blend: float — blend factor with Gaussian noise (0-1, default 0)
                                   0 = pure Pareto, 1 = pure normal
      pareto_cap_ms:     float — maximum delay cap to prevent extreme outliers
                                 from stalling indefinitely (default 5000)
    """

    _direction_key = "pareto_lag"

    def __init__(self, params: dict) -> None:
        super().__init__(params)
        self._base_ms = max(0, float(params.get("pareto_base_ms", 50)))
        self._jitter_ms = max(0, float(params.get("pareto_jitter_ms", 200)))
        self._alpha = max(0.1, float(params.get("pareto_alpha", 1.5)))
        self._correlation = max(0.0, min(1.0,
            float(params.get("pareto_correlation", 0.25))))
        self._normal_blend = max(0.0, min(1.0,
            float(params.get("pareto_normal_blend", 0.0))))
        self._cap_ms = max(0, float(params.get("pareto_cap_ms", 5000)))

        # State for correlated jitter
        self._last_jitter = 0.0

        # Deferred packet queue (same pattern as LagModule)
        self._queue = deque(maxlen=10000)
        self._queue_lock = threading.Lock()
        self._flush_thread: Optional[threading.Thread] = None
        self._running = True
        self._send_fn = None

        # Stats
        self._total_packets = 0
        self._total_delay_ms = 0.0
        self._max_delay_ms = 0.0
        self._delay_histogram = [0] * 10  # buckets: 0-50, 50-100, ..., 400-450, 450+

        log_info(
            f"ParetoLag: base={self._base_ms}ms, jitter={self._jitter_ms}ms, "
            f"alpha={self._alpha}, correlation={self._correlation}, "
            f"blend={self._normal_blend}, cap={self._cap_ms}ms")

    def _sample_pareto(self) -> float:
        """Draw a sample from the Pareto distribution.

        Uses inverse CDF method: X = x_min / U^(1/alpha) where U ~ Uniform(0,1).
        Normalized so minimum value is 0 (shifted Pareto).
        """
        u = random.random()
        if u == 0:
            u = 1e-10  # avoid division by zero
        raw = (1.0 / u) ** (1.0 / self._alpha) - 1.0
        return raw

    def _sample_delay(self) -> float:
        """Generate a single delay sample with correlation and optional blending."""
        # Pure Pareto sample
        pareto = self._sample_pareto()

        # Optional blend with Gaussian
        if self._normal_blend > 0:
            normal = abs(random.gauss(0, 1))  # half-normal (only positive)
            sample = (1.0 - self._normal_blend) * pareto + self._normal_blend * normal
        else:
            sample = pareto

        # Apply jitter scaling
        jitter = self._jitter_ms * sample

        # Temporal correlation: new_jitter = rho * old_jitter + (1-rho) * fresh_jitter
        if self._correlation > 0:
            jitter = (self._correlation * self._last_jitter +
                      (1.0 - self._correlation) * jitter)

        self._last_jitter = jitter

        # Total delay = base + jitter, capped
        total = self._base_ms + jitter
        total = min(total, self._cap_ms)
        total = max(0, total)

        return total

    def start_flush_thread(self, send_fn, divert_dll, handle) -> None:
        """Start background flush thread (same pattern as LagModule)."""
        self._send_fn = send_fn
        self._flush_thread = threading.Thread(
            target=self._flush_loop, daemon=True, name="ParetoLagFlush")
        self._flush_thread.start()

    def _flush_loop(self) -> None:
        while self._running:
            now = time.time()
            to_send = []
            with self._queue_lock:
                while self._queue and self._queue[0][0] <= now:
                    to_send.append(self._queue.popleft())
            for _, pkt_data, addr in to_send:
                try:
                    self._send_fn(pkt_data, addr)
                except Exception:
                    pass
            time.sleep(0.001)

    def process(self, packet_data: bytearray, addr: WINDIVERT_ADDRESS,
                send_fn) -> bool:
        delay_ms = self._sample_delay()

        # Track stats
        self._total_packets += 1
        self._total_delay_ms += delay_ms
        self._max_delay_ms = max(self._max_delay_ms, delay_ms)
        bucket = min(9, int(delay_ms / 50))
        self._delay_histogram[bucket] += 1

        # Zero delay → pass through immediately
        if delay_ms < 1.0:
            return False

        release_time = time.time() + (delay_ms / 1000.0)

        # Deep copy address for deferred send
        addr_copy = WINDIVERT_ADDRESS()
        ctypes.memmove(ctypes.byref(addr_copy), ctypes.byref(addr),
                        ctypes.sizeof(WINDIVERT_ADDRESS))

        with self._queue_lock:
            self._queue.append(
                (release_time, bytearray(packet_data), addr_copy))

        return True  # consumed — will be sent later

    def stop(self) -> None:
        self._running = False
        if self._flush_thread and self._flush_thread.is_alive():
            self._flush_thread.join(timeout=1.0)
        # Flush remaining packets
        with self._queue_lock:
            remaining = list(self._queue)
            self._queue.clear()
        for _, pkt_data, addr in remaining:
            try:
                if self._send_fn:
                    self._send_fn(pkt_data, addr)
            except Exception:
                pass
        avg = (self._total_delay_ms / max(1, self._total_packets))
        log_info(
            f"ParetoLag stats: packets={self._total_packets}, "
            f"avg_delay={avg:.1f}ms, max_delay={self._max_delay_ms:.1f}ms")

    def get_stats(self) -> Dict:
        avg = self._total_delay_ms / max(1, self._total_packets)
        return {
            "total_packets": self._total_packets,
            "avg_delay_ms": avg,
            "max_delay_ms": self._max_delay_ms,
            "delay_histogram": list(self._delay_histogram),
        }


# ═══════════════════════════════════════════════════════════════════════
# Token Bucket Rate Limiter
# ═══════════════════════════════════════════════════════════════════════

class TokenBucketDropModule(DisruptionModule):
    """Token bucket rate limiter with configurable burst capacity.

    More sophisticated than BandwidthModule's fixed-window approach.
    Token bucket allows short bursts at full speed, then throttles —
    exactly like ISP traffic shaping, game server rate limiting, and
    hardware QoS implementations.

    Algorithm:
      - Bucket starts full at `bucket_capacity` tokens
      - Tokens refill at `token_rate` tokens/second (1 token = 1 byte)
      - Each packet costs `len(packet)` tokens
      - If enough tokens: packet passes, tokens deducted
      - If not enough tokens: packet is dropped (or queued, if configured)

    Why this is better than fixed-window bandwidth limiting:
      Fixed-window (BandwidthModule) resets every second, creating a
      "burst at window edge" artifact where traffic concentrates at
      window boundaries. Token bucket produces smooth, realistic shaping
      that's indistinguishable from ISP throttling — DayZ can't detect
      it as artificial.

    DayZ implications:
      DayZ UDP averages ~20-60 KB/s depending on player density.
      A bucket_capacity of 2048 bytes with rate 5120 bytes/sec (~5 KB/s)
      allows one full-sized UDP datagram through, then starves the
      connection until tokens refill. This creates micro-stutter that
      degrades position prediction without triggering DayZ's disconnect
      detection (which looks for total loss, not slow throughput).

    Parameters:
      tb_rate_bytes_sec:   int   — token refill rate (bytes/sec, default 5120)
      tb_bucket_capacity:  int   — maximum bucket size (bytes, default 8192)
      tb_initial_tokens:   int   — starting tokens (-1 = full, default -1)
      tb_packet_overhead:  int   — extra cost per packet beyond its size
                                   (default 0, set >0 to penalize small packets)
    """

    _direction_key = "token_bucket"

    def __init__(self, params: dict) -> None:
        super().__init__(params)
        self._rate = max(1, int(params.get("tb_rate_bytes_sec", 5120)))
        self._capacity = max(1, int(params.get("tb_bucket_capacity", 8192)))
        self._overhead = max(0, int(params.get("tb_packet_overhead", 0)))

        initial = int(params.get("tb_initial_tokens", -1))
        self._tokens = float(self._capacity if initial < 0 else
                             min(initial, self._capacity))

        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

        # Stats
        self._passed = 0
        self._dropped = 0
        self._total_bytes_passed = 0

        log_info(
            f"TokenBucket: rate={self._rate} B/s, "
            f"capacity={self._capacity} B, "
            f"overhead={self._overhead} B/pkt")

    def _refill(self) -> None:
        """Add tokens based on elapsed time since last refill."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._last_refill = now
        self._tokens = min(
            self._capacity,
            self._tokens + elapsed * self._rate)

    def process(self, packet_data: bytearray, addr: WINDIVERT_ADDRESS,
                send_fn) -> bool:
        cost = len(packet_data) + self._overhead

        with self._lock:
            self._refill()

            if self._tokens >= cost:
                self._tokens -= cost
                self._passed += 1
                self._total_bytes_passed += len(packet_data)
                return False  # packet passes

            # Not enough tokens — drop (inside lock to keep stats consistent)
            self._dropped += 1
            return True

    def get_stats(self) -> Dict:
        total = self._passed + self._dropped
        return {
            "tokens_remaining": self._tokens,
            "capacity": self._capacity,
            "rate_bytes_sec": self._rate,
            "packets_passed": self._passed,
            "packets_dropped": self._dropped,
            "drop_rate": self._dropped / max(1, total),
            "throughput_bytes": self._total_bytes_passed,
        }


# ═══════════════════════════════════════════════════════════════════════
# Correlated Drop Module
# ═══════════════════════════════════════════════════════════════════════

class CorrelatedDropModule(DisruptionModule):
    """Drop with temporal autocorrelation (matching tc-netem's correlation model).

    Each drop decision is influenced by the previous one, creating
    realistic loss clustering. The correlation parameter controls how
    "sticky" the current state is:

      effective_chance = correlation * last_decision + (1 - correlation) * base_chance

    Where last_decision is 1.0 if the previous packet was dropped, 0.0 otherwise.

    This means: if the last packet was dropped, the next packet is MORE
    likely to be dropped too (the correlation "remembers" the loss state).
    This produces bursty loss that's simpler than Gilbert-Elliott but
    still far more realistic than uniform random.

    Comparison with Gilbert-Elliott:
      - Simpler: only 2 parameters vs 4
      - Less control: can't independently set loss rates in good/bad states
      - Good for: quick "make it feel like real packet loss" without tuning
      - Use Gilbert-Elliott when you need precise control over burst behavior

    Parameters:
      corr_drop_chance:     float — base drop probability (0-100, default 20)
      corr_correlation:     float — autocorrelation factor (0-1, default 0.50)
                                    0 = independent (same as DropModule)
                                    1 = fully correlated (loss is permanent once started)
    """

    _direction_key = "corr_drop"

    def __init__(self, params: dict) -> None:
        super().__init__(params)
        self._base_chance = max(0.0, min(100.0,
            float(params.get("corr_drop_chance", 20))))
        self._correlation = max(0.0, min(1.0,
            float(params.get("corr_correlation", 0.50))))
        self._last_dropped = False

        # Stats
        self._seen = 0
        self._dropped = 0

        log_info(
            f"CorrelatedDrop: chance={self._base_chance}%, "
            f"correlation={self._correlation}")

    def process(self, packet_data: bytearray, addr: WINDIVERT_ADDRESS,
                send_fn) -> bool:
        self._seen += 1

        # Compute effective drop chance with correlation
        last_val = 100.0 if self._last_dropped else 0.0
        effective = (self._correlation * last_val +
                     (1.0 - self._correlation) * self._base_chance)

        drop = random.random() * 100 < effective
        self._last_dropped = drop

        if drop:
            self._dropped += 1
            return True

        return False

    def get_stats(self) -> Dict:
        return {
            "packets_seen": self._seen,
            "packets_dropped": self._dropped,
            "drop_rate": self._dropped / max(1, self._seen),
            "base_chance": self._base_chance,
            "correlation": self._correlation,
        }


# ═══════════════════════════════════════════════════════════════════════
# Module Registration
# ═══════════════════════════════════════════════════════════════════════

# Maps module name → class. These will be merged into the engine's MODULE_MAP.
STATISTICAL_MODULE_MAP = {
    "ge_drop":      GilbertElliottDropModule,
    "pareto_lag":   ParetoLagModule,
    "token_bucket": TokenBucketDropModule,
    "corr_drop":    CorrelatedDropModule,
}

# Modules that need flush threads (same pattern as LagModule/GodModeModule)
FLUSH_THREAD_MODULES = (ParetoLagModule,)
