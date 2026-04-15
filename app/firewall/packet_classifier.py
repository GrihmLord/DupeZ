#!/usr/bin/env python3
"""
Packet Classification Engine — Phase 2 of DupeZ v5 Roadmap.

Classifies intercepted packets by game-relevant categories using header
inspection, size heuristics, and frequency analysis. This enables
surgical disruption: target only position updates while leaving keepalives
alone, or selectively corrupt state replication without killing the
connection.

v5.1 Auto-Calibration:
  On startup the classifier enters a calibration phase where it observes
  live traffic and derives size/frequency thresholds from percentiles of
  observed packet data.  Hardcoded defaults from the game profile config
  are used only until calibration completes.

  The game port is also auto-detected from the highest-pps UDP flow when
  port_auto_detect is enabled in the game profile.

Supports any game profile loaded from app/config/game_profiles/.
All game-specific constants live in the profile JSON, not in code.

Usage:
  classifier = PacketClassifier()
  category = classifier.classify(packet_data, addr)
"""

from __future__ import annotations

import struct
import time
import threading
from collections import defaultdict, deque
from enum import Enum, auto
from typing import Dict, List, Optional, Tuple

from app.logs.logger import log_info

__all__ = [
    "PacketCategory",
    "FlowTracker",
    "PacketClassifier",
    "SelectiveDisruptionFilter",
]

# ── Constants ────────────────────────────────────────────────────────
# IP header (20 bytes) + UDP header (8 bytes) = 28 bytes overhead
IP_UDP_HEADER_OVERHEAD: int = 28

# ── Game profile loader (provides defaults from JSON config) ──────────
try:
    from app.config.game_profiles import (
        get_classification_config,
        get_default_port,
        get_ports,
    )
    _PROFILE_AVAILABLE = True
except Exception:
    _PROFILE_AVAILABLE = False


class PacketCategory(Enum):
    """Classification categories for game network packets."""
    KEEPALIVE = auto()   # Heartbeat / connection maintenance
    MOVEMENT = auto()    # Position, rotation, velocity updates
    STATE = auto()       # Entity state replication (inventory, health, etc.)
    BULK = auto()         # Large state sync (base building, loot spawn)
    VOICE = auto()        # In-game VOIP data
    CONNECTION = auto()   # Handshake, setup, teardown
    UNKNOWN = auto()      # Unclassifiable

    @property
    def label(self) -> str:
        return self.name.lower()


# ── Config-driven defaults (loaded from game profile or fallback) ─────
def _load_defaults() -> dict:
    """Load thresholds from game profile; fall back to hardcoded if unavailable."""
    if _PROFILE_AVAILABLE:
        cfg = get_classification_config("dayz")
        st = cfg.get("size_thresholds", {})
        ft = cfg.get("frequency_thresholds", {})
        return {
            "keepalive_max": st.get("keepalive_max_bytes", 60),
            "movement_max": st.get("movement_max_bytes", 150),
            "state_max": st.get("state_max_bytes", 500),
            "freq_high": ft.get("high_pps", 25),
            "freq_medium": ft.get("medium_pps", 5),
            "game_port": get_default_port("dayz"),
            "known_ports": set(get_ports("dayz")),
            "auto_calibrate": cfg.get("auto_calibrate", True),
            "calibration_sec": cfg.get("calibration_duration_sec", 10),
        }
    return {
        "keepalive_max": 60, "movement_max": 150, "state_max": 500,
        "freq_high": 25, "freq_medium": 5,
        "game_port": 2302, "known_ports": {2302, 2303, 2304, 2305},
        "auto_calibrate": True, "calibration_sec": 10,
    }

_DEFAULTS: Optional[dict] = None


def _get_defaults() -> dict:
    """Lazy accessor for classification defaults (avoids import-time I/O)."""
    global _DEFAULTS
    if _DEFAULTS is None:
        _DEFAULTS = _load_defaults()
    return _DEFAULTS


# Default game port — resolved lazily on first use via _get_defaults()
DAYZ_PORT: int = 2302  # fallback; overridden at first _get_defaults() call


class FlowTracker:
    """Tracks per-flow statistics for frequency-based classification.

    A "flow" is identified by (src_ip, dst_ip, src_port, dst_port).
    Maintains a sliding window of packet timestamps and sizes to compute
    instantaneous rates and size distributions.
    """

    __slots__ = (
        '_window_sec', '_timestamps', '_sizes', '_total_packets',
        '_total_bytes', '_lock',
    )

    def __init__(self, window_sec: float = 2.0) -> None:
        self._window_sec = window_sec
        self._timestamps: deque = deque(maxlen=500)
        self._sizes: deque = deque(maxlen=500)
        self._total_packets = 0
        self._total_bytes = 0
        self._lock = threading.Lock()

    def record(self, timestamp: float, size: int) -> None:
        with self._lock:
            self._timestamps.append(timestamp)
            self._sizes.append(size)
            self._total_packets += 1
            self._total_bytes += size

    def get_rate(self, now: float) -> float:
        """Packets per second over the sliding window."""
        with self._lock:
            # Prune old entries
            cutoff = now - self._window_sec
            while self._timestamps and self._timestamps[0] < cutoff:
                self._timestamps.popleft()
                self._sizes.popleft()
            count = len(self._timestamps)
        if count < 2:
            return 0.0
        return count / self._window_sec

    def get_avg_size(self) -> float:
        with self._lock:
            if not self._sizes:
                return 0.0
            return sum(self._sizes) / len(self._sizes)

    @property
    def total_packets(self) -> int:
        return self._total_packets

    def last_seen(self) -> float:
        """Return timestamp of the most recent packet, or 0 if none."""
        with self._lock:
            return self._timestamps[-1] if self._timestamps else 0.0

    def is_stale(self, now: float, timeout: float = 60.0) -> bool:
        """Return True if no packets recorded within timeout seconds."""
        last = self.last_seen()
        return last == 0.0 or (now - last) > timeout


class PacketClassifier:
    """Classifies intercepted packets into game-relevant categories.

    Thread-safe. Designed to be called from the packet loop's hot path
    with minimal overhead. Classification is O(1) per packet (no deep
    payload inspection by default).

    v5.1 Auto-Calibration:
      When auto_calibrate=True (default from game profile), the classifier
      collects packet sizes during a calibration window and then derives
      thresholds from percentiles of observed data. This makes it resilient
      to tick rate changes, protocol updates, and server performance shifts.

      Game port auto-detection: identifies the primary game port by finding
      the highest-pps UDP flow, rather than assuming 2302.
    """

    def __init__(self, game_port: int = None,
                 enable_frequency: bool = True,
                 auto_calibrate: bool = None,
                 calibration_sec: float = None,
                 known_ports: set = None) -> None:
        # Config-driven defaults (lazy load)
        d = _get_defaults()
        self._game_port = game_port if game_port is not None else d["game_port"]
        self._known_ports = known_ports if known_ports is not None else d["known_ports"]
        self._enable_frequency = enable_frequency

        # Auto-calibration state
        self._auto_calibrate = auto_calibrate if auto_calibrate is not None else d["auto_calibrate"]
        self._calibration_sec = calibration_sec if calibration_sec is not None else d["calibration_sec"]
        self._calibrated = False
        self._calibration_start: float = 0.0
        self._calibration_sizes: List[int] = []   # UDP payload sizes collected during calibration
        self._calibration_lock = threading.Lock()

        # Port auto-detection
        self._port_auto_detect = True
        self._port_detected = False
        self._port_flow_counts: Dict[int, int] = defaultdict(int)  # port → packet count

        # Active thresholds (start with profile defaults, override after calibration)
        self._size_keepalive_max = d["keepalive_max"]
        self._size_movement_max = d["movement_max"]
        self._size_state_max = d["state_max"]
        self._freq_high = d["freq_high"]
        self._freq_medium = d["freq_medium"]

        # Flow tracking
        self._flows: Dict[Tuple, FlowTracker] = defaultdict(FlowTracker)
        self._flow_lock = threading.Lock()

        # Cleanup interval — prune dead flows every 30s
        self._last_cleanup = time.monotonic()
        self._cleanup_interval = 30.0

        # Classification stats
        self._stats: Dict[str, int] = defaultdict(int)

    # ── Backward-compatible property ──
    @property
    def _dayz_port(self) -> int:
        return self._game_port

    @_dayz_port.setter
    def _dayz_port(self, value: int) -> None:
        self._game_port = value

    # ── Auto-calibration ──────────────────────────────────────────────

    def _maybe_calibrate(self, payload_len: int, port: int) -> None:
        """Collect data during calibration window; finalize when window closes."""
        now = time.monotonic()

        # Start calibration on first packet
        if self._calibration_start == 0.0:
            self._calibration_start = now

        # Collect sizes
        with self._calibration_lock:
            self._calibration_sizes.append(payload_len)
            self._port_flow_counts[port] += 1

        # Check if calibration window has elapsed
        if now - self._calibration_start >= self._calibration_sec:
            self._finalize_calibration()

    def _finalize_calibration(self) -> None:
        """Derive thresholds from observed traffic percentiles."""
        with self._calibration_lock:
            sizes = sorted(self._calibration_sizes)
            port_counts = dict(self._port_flow_counts)

        if len(sizes) < 20:
            # Not enough data — keep defaults
            log_info(f"PacketClassifier: calibration skipped "
                     f"(only {len(sizes)} packets in {self._calibration_sec}s)")
            self._calibrated = True
            return

        # Percentile-based thresholds
        def percentile(data, pct):
            idx = int(len(data) * pct / 100)
            return data[min(idx, len(data) - 1)]

        old_ka = self._size_keepalive_max
        old_mv = self._size_movement_max
        old_st = self._size_state_max

        self._size_keepalive_max = percentile(sizes, 10)
        self._size_movement_max = percentile(sizes, 40)
        self._size_state_max = percentile(sizes, 75)

        # Port auto-detection: highest packet count = game port
        if self._port_auto_detect and port_counts:
            detected_port = max(port_counts, key=port_counts.get)
            if detected_port != self._game_port:
                log_info(f"PacketClassifier: auto-detected game port "
                         f"{detected_port} (was {self._game_port}, "
                         f"{port_counts[detected_port]} pkts)")
                self._game_port = detected_port
            self._port_detected = True

        self._calibrated = True
        log_info(f"PacketClassifier: calibration complete "
                 f"({len(sizes)} packets over {self._calibration_sec}s) — "
                 f"keepalive<={self._size_keepalive_max}B "
                 f"(was {old_ka}), "
                 f"movement<={self._size_movement_max}B "
                 f"(was {old_mv}), "
                 f"state<={self._size_state_max}B "
                 f"(was {old_st})")

    @property
    def calibrated(self) -> bool:
        return self._calibrated

    @property
    def detected_game_port(self) -> int:
        return self._game_port

    # ── Classification ────────────────────────────────────────────────

    def classify(self, packet_data: bytearray,
                 addr=None) -> PacketCategory:
        """Classify a packet. Returns a PacketCategory enum value.

        Args:
            packet_data: Raw IP packet (starts with IP header)
            addr: Optional WINDIVERT_ADDRESS for direction info

        Returns:
            PacketCategory indicating the packet's likely function.
        """
        pkt_len = len(packet_data)

        # Minimum IP header
        if pkt_len < 20:
            self._stats["unknown"] += 1
            return PacketCategory.UNKNOWN

        # Parse IP header
        ip_version = (packet_data[0] >> 4) & 0x0F
        if ip_version != 4:
            # IPv6 — classify as unknown for now (IPv6 path is a v5.2 item)
            self._stats["unknown"] += 1
            return PacketCategory.UNKNOWN

        ihl = (packet_data[0] & 0x0F) * 4
        protocol = packet_data[9]

        # Extract IP addresses for flow tracking
        src_ip = struct.unpack("!I", packet_data[12:16])[0]
        dst_ip = struct.unpack("!I", packet_data[16:20])[0]

        # TCP (protocol 6)
        if protocol == 6:
            cat = self._classify_tcp(packet_data, ihl, pkt_len)
            self._stats[cat.label] += 1
            return cat

        # UDP (protocol 17)
        if protocol == 17 and pkt_len >= ihl + 8:
            src_port = struct.unpack("!H", packet_data[ihl:ihl + 2])[0]
            dst_port = struct.unpack("!H", packet_data[ihl + 2:ihl + 4])[0]
            udp_payload_len = pkt_len - ihl - 8

            # Track flow for frequency analysis
            if self._enable_frequency:
                flow_key = (src_ip, dst_ip, src_port, dst_port)
                now = time.monotonic()
                with self._flow_lock:
                    tracker = self._flows[flow_key]
                tracker.record(now, pkt_len)

                # Periodic cleanup
                if now - self._last_cleanup > self._cleanup_interval:
                    self._cleanup_flows(now)

            # Feed auto-calibration if active
            if self._auto_calibrate and not self._calibrated:
                # Use whichever port is not ephemeral (< 10000) for port detection
                game_port_candidate = src_port if src_port < 10000 else dst_port
                self._maybe_calibrate(udp_payload_len, game_port_candidate)

            cat = self._classify_udp(
                packet_data, ihl, pkt_len, src_port, dst_port,
                udp_payload_len, src_ip, dst_ip)
            self._stats[cat.label] += 1
            return cat

        # Other protocol
        self._stats["unknown"] += 1
        return PacketCategory.UNKNOWN

    def _classify_udp(self, packet_data: bytearray, ihl: int,
                      pkt_len: int, src_port: int, dst_port: int,
                      payload_len: int,
                      src_ip: int, dst_ip: int) -> PacketCategory:
        """Classify a UDP packet using size heuristics and port matching."""

        is_game = (src_port == self._game_port or
                   dst_port == self._game_port or
                   src_port in self._known_ports or
                   dst_port in self._known_ports)

        if not is_game:
            # Non-game UDP — classify generically by size
            return self._classify_by_size(payload_len)

        # Game-specific classification using active thresholds
        # (these are either profile defaults or auto-calibrated percentiles)
        overhead = IP_UDP_HEADER_OVERHEAD
        if payload_len <= max(0, self._size_keepalive_max - overhead):
            return PacketCategory.KEEPALIVE

        if payload_len <= max(0, self._size_movement_max - overhead):
            if self._enable_frequency:
                flow_key = (src_ip, dst_ip, src_port, dst_port)
                with self._flow_lock:
                    tracker = self._flows.get(flow_key)
                if tracker:
                    rate = tracker.get_rate(time.monotonic())
                    if rate >= self._freq_high:
                        return PacketCategory.MOVEMENT
            return PacketCategory.MOVEMENT

        if payload_len <= max(0, self._size_state_max - overhead):
            return PacketCategory.STATE

        return PacketCategory.BULK

    def _classify_tcp(self, packet_data: bytearray, ihl: int,
                      pkt_len: int) -> PacketCategory:
        """Classify TCP packets (auth, anti-cheat, Steam queries)."""
        if pkt_len < ihl + 20:
            return PacketCategory.UNKNOWN

        tcp_flags = packet_data[ihl + 13]
        syn = bool(tcp_flags & 0x02)
        fin = bool(tcp_flags & 0x01)
        rst = bool(tcp_flags & 0x04)

        if syn or fin or rst:
            return PacketCategory.CONNECTION

        return PacketCategory.STATE

    def _classify_by_size(self, payload_len: int) -> PacketCategory:
        """Generic size-based classification for non-game traffic."""
        if payload_len <= 32:
            return PacketCategory.KEEPALIVE
        if payload_len <= 120:
            return PacketCategory.MOVEMENT
        if payload_len <= 450:
            return PacketCategory.STATE
        return PacketCategory.BULK

    def _cleanup_flows(self, now: float) -> None:
        """Remove stale flow entries to prevent unbounded memory growth."""
        self._last_cleanup = now
        with self._flow_lock:
            stale_keys = [
                k for k, v in self._flows.items()
                if v.is_stale(now, timeout=60.0)
            ]
            for k in stale_keys:
                del self._flows[k]
        if stale_keys:
            log_info(f"PacketClassifier: pruned {len(stale_keys)} stale flows")

    def get_stats(self) -> Dict[str, int]:
        """Return classification statistics."""
        return dict(self._stats)

    def get_flow_count(self) -> int:
        with self._flow_lock:
            return len(self._flows)

    def get_calibration_info(self) -> Dict:
        """Return calibration state for diagnostics."""
        return {
            "calibrated": self._calibrated,
            "game_port": self._game_port,
            "port_detected": self._port_detected,
            "size_keepalive_max": self._size_keepalive_max,
            "size_movement_max": self._size_movement_max,
            "size_state_max": self._size_state_max,
            "freq_high": self._freq_high,
        }


class SelectiveDisruptionFilter:
    """Wraps a DisruptionModule to only process specific packet categories.

    This is the bridge between the classifier and the module chain.
    Instead of modifying every module, wrap the module with this filter
    to selectively apply disruption based on packet classification.

    Example:
      # Only drop position updates, not keepalives
      drop_mod = DropModule(params)
      selective = SelectiveDisruptionFilter(
          drop_mod, classifier,
          target_categories={PacketCategory.MOVEMENT, PacketCategory.STATE})

      # In packet loop:
      if selective.process(packet_data, addr, send_fn):
          # packet was disrupted
    """

    def __init__(self, module, classifier: PacketClassifier,
                 target_categories: set,
                 bypass_categories: Optional[set] = None) -> None:
        self.module = module
        self.classifier = classifier
        self.target_categories = target_categories
        self.bypass_categories = bypass_categories or {PacketCategory.KEEPALIVE}
        self.direction = module.direction

        # Stats
        self._bypassed = 0
        self._processed = 0

    def matches_direction(self, addr) -> bool:
        return self.module.matches_direction(addr)

    def process(self, packet_data: bytearray, addr, send_fn) -> bool:
        category = self.classifier.classify(packet_data, addr)

        # Explicitly bypass certain categories
        if category in self.bypass_categories:
            self._bypassed += 1
            return False  # pass through untouched

        # Only process target categories (if specified)
        if self.target_categories and category not in self.target_categories:
            self._bypassed += 1
            return False

        self._processed += 1
        return self.module.process(packet_data, addr, send_fn)

    def stop(self) -> None:
        if hasattr(self.module, 'stop'):
            self.module.stop()

    def start_flush_thread(self, send_fn, divert_dll, handle) -> None:
        if hasattr(self.module, 'start_flush_thread'):
            self.module.start_flush_thread(send_fn, divert_dll, handle)

    def get_stats(self) -> Dict:
        stats = {"bypassed": self._bypassed, "processed": self._processed}
        if hasattr(self.module, 'get_stats'):
            stats["module_stats"] = self.module.get_stats()
        return stats
