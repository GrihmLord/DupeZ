#!/usr/bin/env python3
"""
Packet Recorder — DupeZ Traffic Intelligence Data Collection.

Records encrypted packet metadata during live gameplay for offline ML
training. Does NOT record payload contents (encrypted and useless) —
only metadata features that characterize traffic shape.

Recording workflow:
  1. Start recording during God Mode gameplay
  2. Use hotkeys to TAG game events as they happen:
     - F9:  TAG_KILL      (you killed someone)
     - F10: TAG_HIT       (you landed a hit / took damage)
     - F11: TAG_DEATH     (you died)
     - F12: TAG_INVENTORY (opened inventory / picked up item)
  3. Stop recording → CSV file saved with timestamped packet metadata
     and event tags within ±500ms of each tag timestamp
  4. Offline: train ML model on tagged data to learn traffic signatures
     for each event type → feed improved model back into God Mode

CSV columns:
  timestamp, size, payload_size, protocol, direction, src_port, dst_port,
  inter_arrival_ms, burst_density, size_delta, flow_count, size_variance,
  pkt_class, ml_label, event_tag

The event_tag column is empty for most rows. When you press a tag hotkey,
all packets within a ±500ms window around that timestamp get tagged.
This creates labeled training data: "these traffic patterns happened
when a kill occurred."

Over time, the ML model learns that (for example) a burst of 3 outbound
140B packets followed by 2 inbound 200B packets within 100ms = HIT_REPORT,
even without knowing what's inside the encrypted payload.
"""

from __future__ import annotations

import csv
import os
import time
import threading
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Deque, Dict, List, Optional, Tuple

from app.logs.logger import log_info, log_error

# Try importing ML classifier types for labeling
try:
    from app.firewall.ml_classifier import MLPacketType
    _ML_TYPES_AVAILABLE = True
except ImportError:
    _ML_TYPES_AVAILABLE = False

__all__ = [
    "EventTag",
    "PacketRecord",
    "TagEntry",
    "PacketRecorder",
    "OfflineTrainer",
]


# ═══════════════════════════════════════════════════════════════════════
#  Event Tags
# ═══════════════════════════════════════════════════════════════════════

class EventTag:
    """Game event tags applied via hotkeys during recording."""
    KILL = "KILL"
    HIT = "HIT"
    DEATH = "DEATH"
    INVENTORY = "INVENTORY"
    CUSTOM = "CUSTOM"  # user-defined

    ALL = {KILL, HIT, DEATH, INVENTORY, CUSTOM}


# ═══════════════════════════════════════════════════════════════════════
#  Packet Record
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class PacketRecord:
    """Single packet metadata record for the CSV."""
    timestamp: float = 0.0
    size: int = 0
    payload_size: int = 0
    protocol: int = 0          # 6=TCP, 17=UDP
    direction: int = 0         # 0=inbound, 1=outbound
    src_port: int = 0
    dst_port: int = 0
    inter_arrival_ms: float = 0.0
    burst_density: int = 0
    size_delta: int = 0
    flow_count: int = 0
    size_variance: float = 0.0
    pkt_class: str = ""        # God Mode PktClass name
    ml_label: str = ""         # ML classifier label (if active)
    event_tag: str = ""        # Applied retroactively from hotkey tags

    def to_row(self) -> List:
        return [
            f"{self.timestamp:.6f}",
            self.size,
            self.payload_size,
            self.protocol,
            self.direction,
            self.src_port,
            self.dst_port,
            f"{self.inter_arrival_ms:.3f}",
            self.burst_density,
            self.size_delta,
            self.flow_count,
            f"{self.size_variance:.2f}",
            self.pkt_class,
            self.ml_label,
            self.event_tag,
        ]

    @staticmethod
    def csv_header() -> List[str]:
        return [
            "timestamp", "size", "payload_size", "protocol", "direction",
            "src_port", "dst_port", "inter_arrival_ms", "burst_density",
            "size_delta", "flow_count", "size_variance",
            "pkt_class", "ml_label", "event_tag",
        ]


# ═══════════════════════════════════════════════════════════════════════
#  Event Tag Entry
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class TagEntry:
    """A tagged game event with timestamp."""
    timestamp: float
    tag: str


# ═══════════════════════════════════════════════════════════════════════
#  Packet Recorder
# ═══════════════════════════════════════════════════════════════════════

# Tag window: packets within ±TAG_WINDOW_MS of a tag get labeled
TAG_WINDOW_MS: float = 500.0
TAG_WINDOW_S: float = TAG_WINDOW_MS / 1000.0

# Max records in memory before auto-flush to disk
MAX_BUFFER_SIZE: int = 50_000

# CSV output directory
DEFAULT_RECORDING_DIR: str = "recordings"


class PacketRecorder:
    """Records packet metadata and event tags to CSV for offline ML training.

    Thread-safe. Designed to run alongside God Mode in the packet loop.

    Usage:
        recorder = PacketRecorder()
        recorder.start("session_001")

        # In packet loop:
        recorder.record(packet_data, is_outbound, pkt_class_name, ml_label_name)

        # On hotkey press:
        recorder.tag_event(EventTag.KILL)

        # When done:
        path = recorder.stop()  # Returns path to CSV file
    """

    def __init__(self, output_dir: str = "") -> None:
        self._output_dir = output_dir or DEFAULT_RECORDING_DIR
        self._lock = threading.Lock()
        self._recording = False
        self._session_name: str = ""
        self._start_time: float = 0.0

        # In-memory buffer of packet records
        self._buffer: Deque[PacketRecord] = deque(maxlen=MAX_BUFFER_SIZE)

        # Event tags (applied retroactively to nearby packets)
        self._tags: List[TagEntry] = []

        # Per-direction tracking for feature extraction
        self._last_time_in: float = 0.0
        self._last_time_out: float = 0.0
        self._last_size_in: int = 0
        self._last_size_out: int = 0
        self._recent_times_in: deque = deque(maxlen=20)
        self._recent_times_out: deque = deque(maxlen=20)
        self._recent_sizes_in: deque = deque(maxlen=10)
        self._recent_sizes_out: deque = deque(maxlen=10)
        self._flow_counts: Dict[Tuple[int, int], int] = {}

        # Stats
        self._total_recorded: int = 0
        self._total_tags: int = 0
        self._total_tagged_packets: int = 0

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def session_name(self) -> str:
        return self._session_name

    def start(self, session_name: str = "") -> str:
        """Start recording. Returns the session name."""
        with self._lock:
            if self._recording:
                log_info("[Recorder] Already recording — stop first")
                return self._session_name

            if not session_name:
                session_name = time.strftime("session_%Y%m%d_%H%M%S")

            self._session_name = session_name
            self._start_time = time.time()
            self._buffer.clear()
            self._tags.clear()
            self._total_recorded = 0
            self._total_tags = 0
            self._total_tagged_packets = 0
            self._last_time_in = 0.0
            self._last_time_out = 0.0
            self._last_size_in = 0
            self._last_size_out = 0
            self._recent_times_in.clear()
            self._recent_times_out.clear()
            self._recent_sizes_in.clear()
            self._recent_sizes_out.clear()
            self._flow_counts.clear()
            self._recording = True

        log_info(f"[Recorder] Recording started: {session_name}")
        return session_name

    def stop(self) -> str:
        """Stop recording, apply tags, write CSV. Returns file path."""
        with self._lock:
            if not self._recording:
                return ""
            self._recording = False
            records = list(self._buffer)
            tags = list(self._tags)

        # Apply event tags to nearby packets
        tagged_count = self._apply_tags(records, tags)
        self._total_tagged_packets = tagged_count

        # Write to CSV
        filepath = self._write_csv(records)

        duration = time.time() - self._start_time
        log_info(
            f"[Recorder] Recording stopped: {self._session_name} | "
            f"{self._total_recorded} packets, {self._total_tags} tags, "
            f"{tagged_count} packets tagged | "
            f"{duration:.1f}s | saved to {filepath}"
        )
        return filepath

    def record(self, packet_data: bytearray, is_outbound: bool,
               pkt_class_name: str = "", ml_label_name: str = "") -> None:
        """Record a single packet's metadata. Called from the packet loop."""
        if not self._recording:
            return

        now = time.time()
        pkt_len = len(packet_data)

        # Parse IP header for ports and protocol
        protocol = 0
        src_port = 0
        dst_port = 0
        payload_size = 0

        if pkt_len >= 20:
            ihl = (packet_data[0] & 0x0F) * 4
            protocol = packet_data[9]

            if protocol == 17 and pkt_len >= ihl + 8:  # UDP
                src_port = int.from_bytes(packet_data[ihl:ihl + 2], 'big')
                dst_port = int.from_bytes(packet_data[ihl + 2:ihl + 4], 'big')
                payload_size = pkt_len - ihl - 8
            elif protocol == 6 and pkt_len >= ihl + 4:  # TCP
                src_port = int.from_bytes(packet_data[ihl:ihl + 2], 'big')
                dst_port = int.from_bytes(packet_data[ihl + 2:ihl + 4], 'big')

        # Compute features
        rec = PacketRecord(
            timestamp=now,
            size=pkt_len,
            payload_size=payload_size,
            protocol=protocol,
            direction=1 if is_outbound else 0,
            src_port=src_port,
            dst_port=dst_port,
            pkt_class=pkt_class_name,
            ml_label=ml_label_name,
        )

        with self._lock:
            # Inter-arrival time and burst density
            if is_outbound:
                if self._last_time_out > 0:
                    rec.inter_arrival_ms = (now - self._last_time_out) * 1000
                rec.size_delta = pkt_len - self._last_size_out
                cutoff = now - 0.050
                rec.burst_density = sum(
                    1 for t in self._recent_times_out if t >= cutoff)
                if len(self._recent_sizes_out) >= 3:
                    rec.size_variance = _std(self._recent_sizes_out)
                self._last_time_out = now
                self._last_size_out = pkt_len
                self._recent_times_out.append(now)
                self._recent_sizes_out.append(pkt_len)
            else:
                if self._last_time_in > 0:
                    rec.inter_arrival_ms = (now - self._last_time_in) * 1000
                rec.size_delta = pkt_len - self._last_size_in
                cutoff = now - 0.050
                rec.burst_density = sum(
                    1 for t in self._recent_times_in if t >= cutoff)
                if len(self._recent_sizes_in) >= 3:
                    rec.size_variance = _std(self._recent_sizes_in)
                self._last_time_in = now
                self._last_size_in = pkt_len
                self._recent_times_in.append(now)
                self._recent_sizes_in.append(pkt_len)

            # Flow count
            flow_key = (src_port, dst_port)
            self._flow_counts[flow_key] = self._flow_counts.get(flow_key, 0) + 1
            rec.flow_count = self._flow_counts[flow_key]

            self._buffer.append(rec)
            self._total_recorded += 1

    def tag_event(self, tag: str) -> None:
        """Tag a game event at the current timestamp. Call from hotkey handler."""
        if not self._recording:
            return
        now = time.time()
        with self._lock:
            self._tags.append(TagEntry(timestamp=now, tag=tag))
            self._total_tags += 1
        log_info(f"[Recorder] Event tagged: {tag} at t+{now - self._start_time:.1f}s")

    def _apply_tags(self, records: List[PacketRecord],
                    tags: List[TagEntry]) -> int:
        """Apply event tags to packets within ±TAG_WINDOW_S of each tag.

        Returns count of packets that received tags.
        """
        if not tags or not records:
            return 0

        tagged = 0
        for tag_entry in tags:
            t_lo = tag_entry.timestamp - TAG_WINDOW_S
            t_hi = tag_entry.timestamp + TAG_WINDOW_S

            for rec in records:
                if t_lo <= rec.timestamp <= t_hi:
                    if rec.event_tag:
                        rec.event_tag += f"|{tag_entry.tag}"
                    else:
                        rec.event_tag = tag_entry.tag
                    tagged += 1

        return tagged

    def _write_csv(self, records: List[PacketRecord]) -> str:
        """Write records to a CSV file. Returns the file path."""
        # Ensure output directory exists
        base_dir = self._output_dir
        try:
            os.makedirs(base_dir, exist_ok=True)
        except OSError:
            # Fall back to current directory
            base_dir = "."

        filename = f"{self._session_name}.csv"
        filepath = os.path.join(base_dir, filename)

        try:
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(PacketRecord.csv_header())
                for rec in records:
                    writer.writerow(rec.to_row())
        except Exception as exc:
            log_error(f"[Recorder] Failed to write CSV: {exc}")
            return ""

        return filepath

    def get_stats(self) -> Dict:
        """Return recording statistics."""
        return {
            "recording": self._recording,
            "session_name": self._session_name,
            "total_recorded": self._total_recorded,
            "total_tags": self._total_tags,
            "total_tagged_packets": self._total_tagged_packets,
            "buffer_size": len(self._buffer),
            "duration_s": round(time.time() - self._start_time, 1) if self._start_time else 0,
        }


# ═══════════════════════════════════════════════════════════════════════
#  Offline Training — Replay CSV into ML Model
# ═══════════════════════════════════════════════════════════════════════

class OfflineTrainer:
    """Trains the ML classifier from recorded CSV data.

    Reads one or more CSV files produced by PacketRecorder, extracts
    features and event tags, and trains the TinyNet model to associate
    traffic patterns with game events.

    Usage:
        trainer = OfflineTrainer()
        trainer.load_csv("recordings/session_20260409_152016.csv")
        trainer.load_csv("recordings/session_20260409_153000.csv")

        # Train on all loaded data
        stats = trainer.train(epochs=10)

        # Export trained model weights
        weights = trainer.export_weights()

        # Load weights into live ML classifier
        trainer.apply_to_classifier(live_ml_classifier)
    """

    def __init__(self) -> None:
        self._samples: List[Tuple[List[float], int]] = []  # (feature_vec, target_idx)
        self._loaded_files: List[str] = []
        self._label_counts: Dict[str, int] = {}

    def load_csv(self, filepath: str) -> int:
        """Load a recorded CSV file. Returns number of tagged samples loaded."""
        if not os.path.exists(filepath):
            log_error(f"[OfflineTrainer] File not found: {filepath}")
            return 0

        loaded = 0
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    tag = row.get("event_tag", "").strip()
                    if not tag:
                        continue  # Only train on tagged packets

                    # Parse the primary tag (first if multiple)
                    primary_tag = tag.split("|")[0]
                    target_idx = _tag_to_target(primary_tag)
                    if target_idx < 0:
                        continue

                    # Build feature vector from CSV columns
                    vec = _row_to_features(row)
                    if vec is None:
                        continue

                    self._samples.append((vec, target_idx))
                    self._label_counts[primary_tag] = (
                        self._label_counts.get(primary_tag, 0) + 1)
                    loaded += 1

        except Exception as exc:
            log_error(f"[OfflineTrainer] Error reading {filepath}: {exc}")
            return 0

        self._loaded_files.append(filepath)
        log_info(
            f"[OfflineTrainer] Loaded {loaded} tagged samples from {filepath} "
            f"(labels: {self._label_counts})")
        return loaded

    def train(self, epochs: int = 10) -> Dict:
        """Train a TinyNet model on all loaded samples. Returns stats."""
        if not self._samples:
            log_error("[OfflineTrainer] No samples loaded")
            return {"error": "no samples"}

        try:
            from app.firewall.ml_classifier import TinyNet
        except ImportError:
            log_error("[OfflineTrainer] ML classifier not available")
            return {"error": "import failed"}

        model = TinyNet(n_input=10, n_hidden=16, n_output=9, lr=0.005)
        total_loss = 0.0
        n_trained = 0

        for epoch in range(epochs):
            epoch_loss = 0.0
            # Shuffle-free for determinism; real impl would shuffle
            for vec, target in self._samples:
                loss = model.train_one(vec, target)
                epoch_loss += loss
                n_trained += 1
            avg_loss = epoch_loss / len(self._samples) if self._samples else 0
            if epoch == 0 or epoch == epochs - 1:
                log_info(
                    f"[OfflineTrainer] Epoch {epoch+1}/{epochs}: "
                    f"avg_loss={avg_loss:.4f}")
            total_loss = avg_loss

        self._trained_model = model
        return {
            "epochs": epochs,
            "samples": len(self._samples),
            "final_loss": round(total_loss, 4),
            "labels": dict(self._label_counts),
            "files": self._loaded_files,
        }

    def export_weights(self) -> Optional[Dict]:
        """Export model weights as a serializable dict."""
        if not hasattr(self, '_trained_model'):
            return None
        m = self._trained_model
        return {
            "w1": m.w1, "b1": m.b1,
            "w2": m.w2, "b2": m.b2,
            "n_input": m.n_input, "n_hidden": m.n_hidden,
            "n_output": m.n_output,
        }

    def apply_to_classifier(self, ml_classifier) -> bool:
        """Copy trained weights into a live MLPacketClassifier's model."""
        if not hasattr(self, '_trained_model'):
            log_error("[OfflineTrainer] No trained model to apply")
            return False

        try:
            src = self._trained_model
            dst = ml_classifier._model
            dst.w1 = [row[:] for row in src.w1]
            dst.b1 = src.b1[:]
            dst.w2 = [row[:] for row in src.w2]
            dst.b2 = src.b2[:]
            ml_classifier._ml_active = True
            log_info("[OfflineTrainer] Weights applied to live classifier")
            return True
        except Exception as exc:
            log_error(f"[OfflineTrainer] Failed to apply weights: {exc}")
            return False


# ═══════════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════════

from app.utils.helpers import std_dev as _std  # noqa: E402 — consolidated from local duplicate


# Event tag → ML target index mapping
# These map game events to the MLPacketType enum indices
_TAG_TARGET_MAP = {
    "KILL": 2,       # HIT_REPORT (kill = confirmed hit)
    "HIT": 2,        # HIT_REPORT
    "DEATH": 4,      # STATE_SYNC (death = state change)
    "INVENTORY": 3,  # INVENTORY_RPC
}


def _tag_to_target(tag: str) -> int:
    """Convert an event tag string to a TinyNet target index."""
    return _TAG_TARGET_MAP.get(tag, -1)


def _row_to_features(row: Dict) -> Optional[List[float]]:
    """Convert a CSV row dict to a normalized feature vector."""
    try:
        size = int(row.get("size", 0))
        payload = int(row.get("payload_size", 0))
        direction = int(row.get("direction", 0))
        iat = float(row.get("inter_arrival_ms", 0))
        burst = int(row.get("burst_density", 0))
        delta = int(row.get("size_delta", 0))
        flow = int(row.get("flow_count", 0))
        variance = float(row.get("size_variance", 0))
        protocol = int(row.get("protocol", 0))
        dst_port = int(row.get("dst_port", 0))

        return [
            size / 1500.0,
            payload / 1472.0,
            float(direction),
            min(iat / 1000.0, 1.0),
            min(burst / 20.0, 1.0),
            (delta + 1500) / 3000.0,
            min(flow / 1000.0, 1.0),
            min(variance / 500.0, 1.0),
            1.0 if protocol == 6 else 0.0,
            1.0 if dst_port < 10000 else 0.0,
        ]
    except (ValueError, TypeError):
        return None
