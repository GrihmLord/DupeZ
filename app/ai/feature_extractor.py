"""Feature extractor — per-window packet feature vectors for ML models.

Produces a fixed-dimension numeric feature vector for each time window,
suitable for streaming into the Week 3-6 ML models (CNN flush detector,
LightGBM RPC burst classifier, QRF cut-duration regressor, VAE stealth
keepalive).

Design goals:
    * Zero per-packet allocation — all accumulators are plain Python
      scalars; one vector allocation per window close.
    * Classification-aware — leverages :class:`app.firewall.modules._packet_utils.PktClass`
      so features capture "keepalive vs game state vs bulk" semantics
      without re-parsing payloads.
    * Direction-aware — separate accumulators for inbound and outbound.
    * Stateless across windows — each :meth:`close_window` call returns
      a self-contained vector and clears accumulators.

Feature vector layout (28 dims, ordered — NEVER reorder, models are
trained on positional indices):

     0  window_duration_s
     1  total_pkts
     2  total_bytes
     3  in_pkts          4  in_bytes
     5  out_pkts         6  out_bytes
     7  keepalive_in     8  keepalive_out
     9  control_in      10  control_out
    11  game_small_in   12  game_small_out
    13  game_state_in   14  game_state_out
    15  game_bulk_in    16  game_bulk_out
    17  other_in        18  other_out
    19  mean_payload_in
    20  mean_payload_out
    21  iat_mean_in_ms       (inter-arrival)
    22  iat_mean_out_ms
    23  iat_std_in_ms
    24  iat_std_out_ms
    25  burst_ratio_in       (frac of pkts < 5ms from prev)
    26  burst_ratio_out
    27  unique_dst_ports
"""

from __future__ import annotations

import math
import time
from typing import Dict, List, Set, Tuple

from app.firewall.modules._packet_utils import PktClass

__all__ = [
    "FEATURE_DIM",
    "FEATURE_NAMES",
    "FeatureExtractor",
]

FEATURE_DIM: int = 28

FEATURE_NAMES: Tuple[str, ...] = (
    "window_duration_s",
    "total_pkts", "total_bytes",
    "in_pkts", "in_bytes",
    "out_pkts", "out_bytes",
    "keepalive_in", "keepalive_out",
    "control_in", "control_out",
    "game_small_in", "game_small_out",
    "game_state_in", "game_state_out",
    "game_bulk_in", "game_bulk_out",
    "other_in", "other_out",
    "mean_payload_in", "mean_payload_out",
    "iat_mean_in_ms", "iat_mean_out_ms",
    "iat_std_in_ms", "iat_std_out_ms",
    "burst_ratio_in", "burst_ratio_out",
    "unique_dst_ports",
)

_BURST_THRESHOLD_S: float = 0.005  # <5 ms between arrivals → burst
_CLASS_INDEX: Dict[PktClass, int] = {
    PktClass.KEEPALIVE:   0,
    PktClass.CONTROL:     1,
    PktClass.GAME_SMALL:  2,
    PktClass.GAME_STATE:  3,
    PktClass.GAME_BULK:   4,
    PktClass.OTHER:       5,
}


class FeatureExtractor:
    """Accumulates packet stats within a sliding window.

    Expected usage (single-threaded from the engine packet loop)::

        fx = FeatureExtractor()
        for pkt in stream:
            fx.observe(pkt_class, payload_len, is_inbound, dst_port, now)
        vec = fx.close_window(now)      # 28-float list
        # feed vec to model or recorder, then loop
    """

    __slots__ = (
        "_started_at", "_in_counts", "_out_counts",
        "_in_pkts", "_out_pkts", "_in_bytes", "_out_bytes",
        "_in_payload_sum", "_out_payload_sum",
        "_in_last_ts", "_out_last_ts",
        "_in_iat_sum", "_out_iat_sum",
        "_in_iat_sq", "_out_iat_sq",
        "_in_iat_n", "_out_iat_n",
        "_in_burst", "_out_burst",
        "_dst_ports",
    )

    def __init__(self) -> None:
        self._reset(time.monotonic())

    def _reset(self, now: float) -> None:
        self._started_at: float = now
        # Per-class counts: index 0=in, 1=out
        self._in_counts: List[int] = [0] * len(_CLASS_INDEX)
        self._out_counts: List[int] = [0] * len(_CLASS_INDEX)

        self._in_pkts: int = 0
        self._out_pkts: int = 0
        self._in_bytes: int = 0
        self._out_bytes: int = 0
        self._in_payload_sum: int = 0
        self._out_payload_sum: int = 0

        self._in_last_ts: float = 0.0
        self._out_last_ts: float = 0.0
        self._in_iat_sum: float = 0.0
        self._out_iat_sum: float = 0.0
        self._in_iat_sq: float = 0.0
        self._out_iat_sq: float = 0.0
        self._in_iat_n: int = 0
        self._out_iat_n: int = 0
        self._in_burst: int = 0
        self._out_burst: int = 0

        self._dst_ports: Set[int] = set()

    # ── hot path ──────────────────────────────────────────────────────
    def observe(
        self,
        pkt_class: PktClass,
        payload_len: int,
        is_inbound: bool,
        dst_port: int,
        now: float,
    ) -> None:
        """Record a single packet observation."""
        cls_idx = _CLASS_INDEX.get(pkt_class, _CLASS_INDEX[PktClass.OTHER])
        if dst_port:
            self._dst_ports.add(dst_port)

        if is_inbound:
            self._in_counts[cls_idx] += 1
            self._in_pkts += 1
            self._in_bytes += payload_len
            self._in_payload_sum += payload_len
            if self._in_last_ts:
                iat = now - self._in_last_ts
                self._in_iat_sum += iat
                self._in_iat_sq += iat * iat
                self._in_iat_n += 1
                if iat < _BURST_THRESHOLD_S:
                    self._in_burst += 1
            self._in_last_ts = now
        else:
            self._out_counts[cls_idx] += 1
            self._out_pkts += 1
            self._out_bytes += payload_len
            self._out_payload_sum += payload_len
            if self._out_last_ts:
                iat = now - self._out_last_ts
                self._out_iat_sum += iat
                self._out_iat_sq += iat * iat
                self._out_iat_n += 1
                if iat < _BURST_THRESHOLD_S:
                    self._out_burst += 1
            self._out_last_ts = now

    # ── window close ─────────────────────────────────────────────────
    def close_window(self, now: float) -> List[float]:
        """Emit a fixed-dim feature vector and reset accumulators."""
        duration = max(1e-6, now - self._started_at)

        mean_in = (self._in_payload_sum / self._in_pkts) if self._in_pkts else 0.0
        mean_out = (self._out_payload_sum / self._out_pkts) if self._out_pkts else 0.0

        iat_mean_in_ms = (self._in_iat_sum / self._in_iat_n * 1000.0) if self._in_iat_n else 0.0
        iat_mean_out_ms = (self._out_iat_sum / self._out_iat_n * 1000.0) if self._out_iat_n else 0.0

        iat_std_in_ms = _std_ms(self._in_iat_sum, self._in_iat_sq, self._in_iat_n)
        iat_std_out_ms = _std_ms(self._out_iat_sum, self._out_iat_sq, self._out_iat_n)

        burst_in = (self._in_burst / self._in_iat_n) if self._in_iat_n else 0.0
        burst_out = (self._out_burst / self._out_iat_n) if self._out_iat_n else 0.0

        total_pkts = self._in_pkts + self._out_pkts
        total_bytes = self._in_bytes + self._out_bytes

        vec: List[float] = [
            duration,
            float(total_pkts), float(total_bytes),
            float(self._in_pkts), float(self._in_bytes),
            float(self._out_pkts), float(self._out_bytes),
            float(self._in_counts[0]), float(self._out_counts[0]),   # keepalive
            float(self._in_counts[1]), float(self._out_counts[1]),   # control
            float(self._in_counts[2]), float(self._out_counts[2]),   # game_small
            float(self._in_counts[3]), float(self._out_counts[3]),   # game_state
            float(self._in_counts[4]), float(self._out_counts[4]),   # game_bulk
            float(self._in_counts[5]), float(self._out_counts[5]),   # other
            mean_in, mean_out,
            iat_mean_in_ms, iat_mean_out_ms,
            iat_std_in_ms, iat_std_out_ms,
            burst_in, burst_out,
            float(len(self._dst_ports)),
        ]
        assert len(vec) == FEATURE_DIM, "feature vector size mismatch"
        self._reset(now)
        return vec


def _std_ms(sum_s: float, sum_sq: float, n: int) -> float:
    if n < 2:
        return 0.0
    mean = sum_s / n
    var = max(0.0, sum_sq / n - mean * mean)
    return math.sqrt(var) * 1000.0
