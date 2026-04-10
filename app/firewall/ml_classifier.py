#!/usr/bin/env python3
"""
ML-Enhanced Packet Classifier — DupeZ Traffic Intelligence.

Uses online learning (lightweight neural network or gradient boosted model)
to classify encrypted DayZ packets by traffic metadata WITHOUT decryption.

Research basis:
  Encrypted traffic classification via packet metadata is well-established
  in academic literature (CNN/BiLSTM on flow features). For real-time game
  traffic, we use a simplified approach: a sliding window of packet features
  fed into a lightweight online classifier.

Features extracted per packet (NO payload inspection):
  1. Packet size (total bytes)
  2. UDP payload size
  3. Direction (inbound=0, outbound=1)
  4. Inter-arrival time (ms since last packet in same direction)
  5. Burst density (packets in last 50ms same direction)
  6. Size delta (difference from previous packet same direction)
  7. Flow packet count (how many packets on this src:port→dst:port)
  8. Packet size variance (rolling std of last 10 packets same direction)

Classification targets (finer than God Mode's 4-class system):
  - KEEPALIVE: Connection maintenance heartbeats
  - POSITION_UPDATE: Player/entity position, rotation, velocity
  - HIT_REPORT: Damage/hit registration packets (client→server)
  - INVENTORY_RPC: Inventory manipulation RPCs
  - STATE_SYNC: General entity state replication
  - BULK_TRANSFER: Large data (base building, terrain, loot tables)
  - VOICE: VOIP data
  - CONTROL: TCP auth, BattlEye, Steam

The classifier starts in OBSERVATION mode, collecting labeled training data
from God Mode's existing size-based classifier. Once enough data is collected,
it trains and switches to PREDICTION mode, providing finer-grained
classifications that God Mode can use for smarter packet decisions.

Usage:
  ml = MLPacketClassifier(target_ip="198.51.100.2")
  # Feed packets:
  prediction = ml.classify(packet_data, is_outbound=True, timestamp=time.time())
  # prediction.label, prediction.confidence, prediction.features
"""

from __future__ import annotations

import math
import time
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Tuple

from app.logs.logger import log_info, log_error

__all__ = [
    "MLPacketType",
    "PacketFeatures",
    "MLPrediction",
    "TinyNet",
    "MLPacketClassifier",
]


# ═══════════════════════════════════════════════════════════════════════
#  Fine-grained packet categories
# ═══════════════════════════════════════════════════════════════════════

class MLPacketType(Enum):
    """Fine-grained packet types learned from traffic patterns."""
    KEEPALIVE = auto()
    POSITION_UPDATE = auto()
    HIT_REPORT = auto()
    INVENTORY_RPC = auto()
    STATE_SYNC = auto()
    BULK_TRANSFER = auto()
    VOICE = auto()
    CONTROL = auto()
    UNKNOWN = auto()


@dataclass
class PacketFeatures:
    """Feature vector extracted from a single packet's metadata."""
    size: int = 0                    # Total packet size
    payload_size: int = 0            # UDP payload size (0 for TCP)
    direction: int = 0               # 0=inbound, 1=outbound
    inter_arrival_ms: float = 0.0    # ms since last packet same direction
    burst_density: int = 0           # packets in last 50ms same direction
    size_delta: int = 0              # size - prev size same direction
    flow_count: int = 0              # total packets on this flow
    size_variance: float = 0.0       # rolling std of last 10 same dir
    protocol: int = 0                # 6=TCP, 17=UDP
    src_port: int = 0
    dst_port: int = 0

    def to_vector(self) -> List[float]:
        """Convert to normalized feature vector for the model."""
        return [
            self.size / 1500.0,                    # normalize to typical MTU
            self.payload_size / 1472.0,             # max UDP payload
            float(self.direction),
            min(self.inter_arrival_ms / 1000.0, 1.0),  # cap at 1s
            min(self.burst_density / 20.0, 1.0),    # cap at 20
            (self.size_delta + 1500) / 3000.0,      # center around 0.5
            min(self.flow_count / 1000.0, 1.0),     # cap at 1000
            min(self.size_variance / 500.0, 1.0),   # cap at 500
            1.0 if self.protocol == 6 else 0.0,     # TCP flag
            1.0 if self.dst_port < 10000 else 0.0,  # server port flag
        ]


@dataclass
class MLPrediction:
    """Result of ML classification."""
    label: MLPacketType
    confidence: float
    features: PacketFeatures
    used_ml: bool = False  # True if ML model made the prediction, False if rules


# ═══════════════════════════════════════════════════════════════════════
#  Lightweight Online Neural Network
# ═══════════════════════════════════════════════════════════════════════

class TinyNet:
    """Minimal single-hidden-layer neural network for online learning.

    No external dependencies (no numpy/sklearn/torch). Pure Python math.
    Architecture: 10 inputs → 16 hidden (ReLU) → 9 outputs (softmax)

    Uses stochastic gradient descent with momentum for online updates.
    """

    def __init__(self, n_input: int = 10, n_hidden: int = 16,
                 n_output: int = 9, lr: float = 0.01, momentum: float = 0.9) -> None:
        self.n_input = n_input
        self.n_hidden = n_hidden
        self.n_output = n_output
        self.lr = lr
        self.momentum = momentum

        # Xavier initialization
        scale1 = math.sqrt(2.0 / n_input)
        scale2 = math.sqrt(2.0 / n_hidden)

        # Weights: input→hidden
        self.w1: List[List[float]] = [
            [_xavier(scale1) for _ in range(n_input)]
            for _ in range(n_hidden)
        ]
        self.b1: List[float] = [0.0] * n_hidden

        # Weights: hidden→output
        self.w2: List[List[float]] = [
            [_xavier(scale2) for _ in range(n_hidden)]
            for _ in range(n_output)
        ]
        self.b2: List[float] = [0.0] * n_output

        # Momentum buffers
        self.vw1 = [[0.0] * n_input for _ in range(n_hidden)]
        self.vb1 = [0.0] * n_hidden
        self.vw2 = [[0.0] * n_hidden for _ in range(n_output)]
        self.vb2 = [0.0] * n_output

        self._lock = threading.Lock()
        self._train_count = 0

    def forward(self, x: List[float]) -> Tuple[List[float], List[float]]:
        """Forward pass. Returns (hidden_activations, output_probabilities)."""
        # Hidden layer: ReLU
        hidden = []
        for j in range(self.n_hidden):
            z = self.b1[j]
            for i in range(self.n_input):
                z += self.w1[j][i] * x[i]
            hidden.append(max(0.0, z))  # ReLU

        # Output layer: softmax
        logits = []
        for k in range(self.n_output):
            z = self.b2[k]
            for j in range(self.n_hidden):
                z += self.w2[k][j] * hidden[j]
            logits.append(z)

        probs = _softmax(logits)
        return hidden, probs

    def predict(self, x: List[float]) -> Tuple[int, float]:
        """Predict class and confidence."""
        with self._lock:
            _, probs = self.forward(x)
        best_idx = 0
        best_val = probs[0]
        for i in range(1, len(probs)):
            if probs[i] > best_val:
                best_val = probs[i]
                best_idx = i
        return best_idx, best_val

    def train_one(self, x: List[float], target_idx: int) -> float:
        """Single-sample SGD with momentum. Returns loss."""
        with self._lock:
            hidden, probs = self.forward(x)

            # Cross-entropy loss
            loss = -math.log(max(probs[target_idx], 1e-10))

            # Output gradient: dL/d_logit = prob - one_hot
            d_output = list(probs)
            d_output[target_idx] -= 1.0

            # Backprop: output → hidden
            d_hidden = [0.0] * self.n_hidden
            for k in range(self.n_output):
                for j in range(self.n_hidden):
                    d_hidden[j] += self.w2[k][j] * d_output[k]
                    grad = d_output[k] * hidden[j]
                    self.vw2[k][j] = self.momentum * self.vw2[k][j] - self.lr * grad
                    self.w2[k][j] += self.vw2[k][j]
                self.vb2[k] = self.momentum * self.vb2[k] - self.lr * d_output[k]
                self.b2[k] += self.vb2[k]

            # Backprop: hidden → input (ReLU derivative)
            for j in range(self.n_hidden):
                if hidden[j] <= 0:
                    continue  # ReLU gate: gradient is 0
                for i in range(self.n_input):
                    grad = d_hidden[j] * x[i]
                    self.vw1[j][i] = self.momentum * self.vw1[j][i] - self.lr * grad
                    self.w1[j][i] += self.vw1[j][i]
                self.vb1[j] = self.momentum * self.vb1[j] - self.lr * d_hidden[j]
                self.b1[j] += self.vb1[j]

            self._train_count += 1
            return loss

    @property
    def trained_samples(self) -> int:
        return self._train_count


# ═══════════════════════════════════════════════════════════════════════
#  Math helpers (no numpy)
# ═══════════════════════════════════════════════════════════════════════

_rng_state = [42]  # simple PRNG for weight init


def _xavier(scale: float) -> float:
    """Simple LCG-based random for Xavier initialization."""
    _rng_state[0] = (_rng_state[0] * 1103515245 + 12345) & 0x7FFFFFFF
    # Map to [-scale, scale]
    return ((_rng_state[0] / 0x7FFFFFFF) * 2 - 1) * scale


def _softmax(logits: List[float]) -> List[float]:
    """Numerically stable softmax."""
    max_l = max(logits)
    exps = [math.exp(l - max_l) for l in logits]
    total = sum(exps)
    return [e / total for e in exps]


# ═══════════════════════════════════════════════════════════════════════
#  ML Packet Classifier
# ═══════════════════════════════════════════════════════════════════════

# Map MLPacketType enum to TinyNet output indices
_TYPE_TO_IDX: Dict[MLPacketType, int] = {
    MLPacketType.KEEPALIVE: 0,
    MLPacketType.POSITION_UPDATE: 1,
    MLPacketType.HIT_REPORT: 2,
    MLPacketType.INVENTORY_RPC: 3,
    MLPacketType.STATE_SYNC: 4,
    MLPacketType.BULK_TRANSFER: 5,
    MLPacketType.VOICE: 6,
    MLPacketType.CONTROL: 7,
    MLPacketType.UNKNOWN: 8,
}
_IDX_TO_TYPE: Dict[int, MLPacketType] = {v: k for k, v in _TYPE_TO_IDX.items()}

# Minimum training samples before ML predictions are used
_MIN_TRAIN_SAMPLES: int = 200
# Confidence threshold — below this, fall back to rules
_MIN_CONFIDENCE: float = 0.45


class MLPacketClassifier:
    """ML-enhanced packet classifier using traffic metadata.

    Operates in two phases:
      1. LEARNING: Uses rule-based heuristics (from existing classifier)
         to label packets and trains the neural network online.
      2. PREDICTING: Once trained on enough samples, uses the neural
         network for finer-grained classification, with rule-based
         fallback when confidence is low.

    Thread-safe. Designed for the packet loop hot path.
    """

    def __init__(self, target_ip: str = "") -> None:
        self._target_ip = target_ip
        self._model = TinyNet(n_input=10, n_hidden=16, n_output=9)
        self._lock = threading.Lock()

        # Per-direction tracking for feature extraction
        self._last_time_in: float = 0.0
        self._last_time_out: float = 0.0
        self._last_size_in: int = 0
        self._last_size_out: int = 0
        self._recent_times_in: deque = deque(maxlen=20)
        self._recent_times_out: deque = deque(maxlen=20)
        self._recent_sizes_in: deque = deque(maxlen=10)
        self._recent_sizes_out: deque = deque(maxlen=10)

        # Flow counters
        self._flow_counts: Dict[Tuple[int, int], int] = defaultdict(int)

        # Training buffer — accumulates labeled samples for batch training
        self._train_buffer: deque = deque(maxlen=5000)
        self._total_trained: int = 0
        self._ml_active: bool = False

        # Stats
        self._stats: Dict[str, int] = defaultdict(int)
        self._ml_predictions: int = 0
        self._rule_predictions: int = 0
        self._train_losses: deque = deque(maxlen=100)

    def extract_features(self, packet_data: bytearray,
                         is_outbound: bool,
                         timestamp: float) -> PacketFeatures:
        """Extract metadata features from a packet WITHOUT reading payload."""
        pkt_len = len(packet_data)
        feat = PacketFeatures(size=pkt_len)

        # Parse IP header
        if pkt_len < 20:
            return feat

        ihl = (packet_data[0] & 0x0F) * 4
        feat.protocol = packet_data[9]
        feat.direction = 1 if is_outbound else 0

        # UDP specifics
        if feat.protocol == 17 and pkt_len >= ihl + 8:
            feat.src_port = int.from_bytes(packet_data[ihl:ihl + 2], 'big')
            feat.dst_port = int.from_bytes(packet_data[ihl + 2:ihl + 4], 'big')
            feat.payload_size = pkt_len - ihl - 8
        elif feat.protocol == 6 and pkt_len >= ihl + 4:
            feat.src_port = int.from_bytes(packet_data[ihl:ihl + 2], 'big')
            feat.dst_port = int.from_bytes(packet_data[ihl + 2:ihl + 4], 'big')

        # Direction-dependent features
        with self._lock:
            if is_outbound:
                if self._last_time_out > 0:
                    feat.inter_arrival_ms = (timestamp - self._last_time_out) * 1000
                feat.size_delta = pkt_len - self._last_size_out

                # Burst density: count packets in last 50ms
                cutoff = timestamp - 0.050
                feat.burst_density = sum(
                    1 for t in self._recent_times_out if t >= cutoff)

                # Size variance
                if len(self._recent_sizes_out) >= 3:
                    feat.size_variance = _std(self._recent_sizes_out)

                self._last_time_out = timestamp
                self._last_size_out = pkt_len
                self._recent_times_out.append(timestamp)
                self._recent_sizes_out.append(pkt_len)
            else:
                if self._last_time_in > 0:
                    feat.inter_arrival_ms = (timestamp - self._last_time_in) * 1000
                feat.size_delta = pkt_len - self._last_size_in

                cutoff = timestamp - 0.050
                feat.burst_density = sum(
                    1 for t in self._recent_times_in if t >= cutoff)

                if len(self._recent_sizes_in) >= 3:
                    feat.size_variance = _std(self._recent_sizes_in)

                self._last_time_in = timestamp
                self._last_size_in = pkt_len
                self._recent_times_in.append(timestamp)
                self._recent_sizes_in.append(pkt_len)

            # Flow count
            flow_key = (feat.src_port, feat.dst_port)
            self._flow_counts[flow_key] += 1
            feat.flow_count = self._flow_counts[flow_key]

        return feat

    def classify(self, packet_data: bytearray, is_outbound: bool,
                 timestamp: float = 0.0) -> MLPrediction:
        """Classify a packet using ML model or rule-based fallback.

        Args:
            packet_data: Raw IP packet
            is_outbound: True if PS5→server
            timestamp: Packet arrival time (time.time())

        Returns:
            MLPrediction with label, confidence, and features.
        """
        if timestamp <= 0:
            timestamp = time.time()

        feat = self.extract_features(packet_data, is_outbound, timestamp)

        # Rule-based classification (always computed as baseline + training label)
        rule_label = self._rule_classify(feat)

        # Train the model with this sample
        self._train_online(feat, rule_label)

        # Use ML if trained enough and confident
        if self._ml_active:
            vec = feat.to_vector()
            idx, conf = self._model.predict(vec)
            ml_label = _IDX_TO_TYPE.get(idx, MLPacketType.UNKNOWN)

            if conf >= _MIN_CONFIDENCE:
                self._ml_predictions += 1
                self._stats[ml_label.name] += 1
                return MLPrediction(
                    label=ml_label, confidence=conf,
                    features=feat, used_ml=True)

        # Fallback to rules
        self._rule_predictions += 1
        self._stats[rule_label.name] += 1
        return MLPrediction(
            label=rule_label, confidence=1.0,
            features=feat, used_ml=False)

    def _rule_classify(self, feat: PacketFeatures) -> MLPacketType:
        """Rule-based classification using DayZ traffic heuristics.

        This provides training labels for the ML model AND serves as
        fallback when ML confidence is low. Rules are based on observed
        DayZ Enfusion traffic patterns.
        """
        # TCP → always CONTROL (BattlEye, Steam)
        if feat.protocol == 6:
            return MLPacketType.CONTROL

        payload = feat.payload_size

        # Keepalive: small, regular cadence
        # DayZ keepalives are ~86B payload (114B total), sent every ~200ms
        if payload <= 90 and feat.inter_arrival_ms > 100:
            return MLPacketType.KEEPALIVE

        # Hit reports: outbound, medium size, low frequency
        # Hit reports are RPCs sent when player fires/hits — typically 120-180B
        # payload, outbound only, sporadic (not every tick)
        if (feat.direction == 1 and 100 <= payload <= 200
                and feat.burst_density <= 3
                and feat.inter_arrival_ms > 30):
            return MLPacketType.HIT_REPORT

        # Position updates: frequent, consistent size, both directions
        # Enfusion sends position at tick rate (~16ms intervals)
        # Outbound: 100-160B payload, high frequency
        # Inbound: 100-220B payload (includes nearby entity positions)
        if payload <= 220 and feat.burst_density >= 4:
            return MLPacketType.POSITION_UPDATE

        # Inventory RPCs: outbound, medium-large, sporadic
        # Inventory actions (pickup, drop, swap) are reliable RPCs
        # Typically 200-600B payload, outbound, infrequent
        if feat.direction == 1 and 200 < payload <= 600 and feat.burst_density <= 2:
            return MLPacketType.INVENTORY_RPC

        # Voice: consistent ~160-320B, high frequency when active
        # DayZ VOIP uses Opus codec, ~20ms frames
        if 140 <= payload <= 350 and feat.inter_arrival_ms < 25:
            return MLPacketType.VOICE

        # State sync: medium-large inbound state replication
        if payload <= 760:
            return MLPacketType.STATE_SYNC

        # Bulk: large packets (base building, loot tables, terrain)
        if payload > 760:
            return MLPacketType.BULK_TRANSFER

        return MLPacketType.UNKNOWN

    def _train_online(self, feat: PacketFeatures, label: MLPacketType) -> None:
        """Feed one labeled sample to the neural network."""
        vec = feat.to_vector()
        target_idx = _TYPE_TO_IDX.get(label, 8)

        # Train immediately (online SGD)
        loss = self._model.train_one(vec, target_idx)
        self._total_trained += 1
        self._train_losses.append(loss)

        # Activate ML predictions after enough training
        if not self._ml_active and self._total_trained >= _MIN_TRAIN_SAMPLES:
            avg_loss = sum(self._train_losses) / len(self._train_losses)
            self._ml_active = True
            log_info(
                f"[MLClassifier] ML predictions ACTIVE after "
                f"{self._total_trained} samples (avg_loss={avg_loss:.3f})")

    def get_stats(self) -> Dict:
        """Return classifier statistics."""
        avg_loss = 0.0
        if self._train_losses:
            avg_loss = sum(self._train_losses) / len(self._train_losses)
        return {
            "ml_active": self._ml_active,
            "total_trained": self._total_trained,
            "ml_predictions": self._ml_predictions,
            "rule_predictions": self._rule_predictions,
            "avg_loss": round(avg_loss, 4),
            "class_counts": dict(self._stats),
        }

    def get_prediction_summary(self) -> str:
        """Human-readable summary for logging."""
        stats = self.get_stats()
        total = stats["ml_predictions"] + stats["rule_predictions"]
        ml_pct = (stats["ml_predictions"] / total * 100) if total > 0 else 0
        return (
            f"MLClassifier: {stats['total_trained']} trained, "
            f"{ml_pct:.0f}% ML ({stats['ml_predictions']}/{total}), "
            f"loss={stats['avg_loss']:.3f}, "
            f"active={stats['ml_active']}"
        )


from app.utils.helpers import std_dev as _std  # noqa: E402 — consolidated from local duplicate
