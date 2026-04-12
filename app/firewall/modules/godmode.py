"""God Mode module — bidirectional pulse-cycling for DayZ PvP invulnerability.

v6.0: Bidirectional block + IP-based direction + deep packet classifier.

How it works
────────────
During BLOCK phase (e.g. 3 seconds):
  - OUTBOUND (device→server): queued. Server has your STALE position.
    Other players see a frozen ghost at your last known location.
    They shoot the ghost — misses your real position.
  - INBOUND (server→device): queued. You see frozen enemies at their
    last known positions. Line up shots.
  - TCP (both dirs): always passes (BattlEye, Steam auth).
  - Keepalive (both dirs): one passes every N ms to prevent timeout.

During FLUSH phase (e.g. 400ms), staggered:
  1. INBOUND flushes FIRST: fresh enemy position updates arrive.
     GAME_STATE culled to newest N to prevent replay-teleporting.
     Client now has current enemy positions for hit calculation.
  2. Stagger delay (e.g. 120ms): client processes inbound updates.
  3. OUTBOUND flushes SECOND: position + hit reports burst to server.
     Hit reports reference the CURRENT enemy positions the client
     just received — server validation succeeds because the hit
     report matches the server's view of where enemies actually are.
  - Window is too short for enemies to react to your new position.

Result:
  - You teleport around (position only updates in bursts)
  - You're hard to hit (frozen ghost between updates, only briefly
    visible at real position during flush)
  - Your shots register (staggered flush ensures client has fresh
    enemy positions → hit reports are valid against server state)
  - You take minimal damage (enemies shoot at ghost position)

Direction detection uses IPv4 header inspection (NOT addr.Outbound)
because on NETWORK_FORWARD + ICS, all forwarded packets read as
outbound regardless of actual direction.

DayZ kick prevention:
  1. Server timeout (30-60s): prevented by keepalive pass-through
  2. Quality monitor (~5-10s window): prevented by flush phase
     releasing enough packets to reset the sliding average
  3. BattlEye: not addressed (pattern-based, unrelated to timing)
"""

from __future__ import annotations

import ctypes
import socket
import time
import threading
from collections import deque
from enum import Enum, auto
from typing import Callable, Dict, List, Optional, Tuple

from app.firewall.native_divert_engine import (
    DisruptionModule,
    WINDIVERT_ADDRESS,
    DIR_BOTH,
)
from app.logs.logger import log_error, log_info

# ML classifier (optional — degrades gracefully if unavailable)
try:
    from app.firewall.ml_classifier import MLPacketClassifier, MLPacketType
    _ML_AVAILABLE = True
except ImportError:
    _ML_AVAILABLE = False

# Packet recorder (optional — for offline ML training data collection)
try:
    from app.firewall.packet_recorder import PacketRecorder, EventTag
    _RECORDER_AVAILABLE = True
except ImportError:
    _RECORDER_AVAILABLE = False

__all__ = ["PktClass", "GodModeModule"]


# ═══════════════════════════════════════════════════════════════════════
#  Packet Classifier
# ═══════════════════════════════════════════════════════════════════════

class PktClass(Enum):
    """Packet classification categories."""
    KEEPALIVE  = auto()   # Small UDP heartbeat/probe
    CONTROL    = auto()   # TCP (auth, BattlEye, Steam session)
    GAME_SMALL = auto()   # Small game UDP (acks, input echo)
    GAME_STATE = auto()   # Medium game UDP (position, entity state)
    GAME_BULK  = auto()   # Large game UDP (world/inventory sync)
    OTHER      = auto()   # Anything else (ICMP, unknown)


_PROTO_TCP = 6
_PROTO_UDP = 17

# DayZ game server port range (Enfusion engine default + common configs)
_GAME_PORT_MIN = 2300
_GAME_PORT_MAX = 2410

# Steam port range
_STEAM_PORT_MIN = 27015
_STEAM_PORT_MAX = 27050

# UDP payload size thresholds (payload = total - IP header - UDP 8B)
# DayZ's smallest packets are ~77B payload (105B total).  The original 40B
# threshold was too low — zero packets qualified as keepalive.  Raised to
# 90B to capture DayZ heartbeat/ack packets while excluding game state.
_KEEPALIVE_PAYLOAD_MAX = 90      # DayZ heartbeat/ack probes (≤90B payload)
_GAME_SMALL_PAYLOAD_MAX = 200    # Small game UDP (acks, input, small state)
_GAME_STATE_PAYLOAD_MAX = 760    # Position, entity replication


def _parse_ipv4_addrs(packet_data: bytearray) -> Tuple[str, str]:
    """Extract (src_ip, dst_ip) from an IPv4 packet header.

    Retained for diagnostics/logging only. The hot path uses
    :func:`_ipv4_addrs_u32` to avoid per-packet string allocations.
    """
    if len(packet_data) < 20:
        return ("", "")
    version = (packet_data[0] >> 4) & 0xF
    if version != 4:
        return ("", "")
    src = socket.inet_ntoa(packet_data[12:16])
    dst = socket.inet_ntoa(packet_data[16:20])
    return (src, dst)


def _ipv4_addrs_u32(packet_data: bytearray) -> Tuple[int, int]:
    """Zero-allocation extraction of IPv4 (src, dst) as u32 ints.

    Returns ``(0, 0)`` for non-IPv4 or undersized packets so the caller
    can treat "no match" the same as "unrelated traffic". This path runs
    once per packet (100-400 pps for PS5 DayZ) so it must not allocate.
    """
    if len(packet_data) < 20 or (packet_data[0] >> 4) & 0xF != 4:
        return (0, 0)
    src_u32 = (
        (packet_data[12] << 24)
        | (packet_data[13] << 16)
        | (packet_data[14] << 8)
        | packet_data[15]
    )
    dst_u32 = (
        (packet_data[16] << 24)
        | (packet_data[17] << 16)
        | (packet_data[18] << 8)
        | packet_data[19]
    )
    return (src_u32, dst_u32)


def _classify_packet(packet_data: bytearray, is_target: bool = False) -> Tuple[PktClass, int, int, int]:
    """Classify an IPv4 packet by protocol and payload size.

    When ``is_target`` is True, ALL UDP traffic is treated as game
    traffic (classified by payload size).  This is the correct approach
    for ICS/hotspot setups where the console's only traffic through the
    hotspot is DayZ — no port detection needed.  Also works for PC-local
    mode when the WinDivert filter already isolates game server traffic.

    Returns (classification, protocol, src_port, dst_port).
    """
    if len(packet_data) < 20:
        return (PktClass.OTHER, 0, 0, 0)

    version = (packet_data[0] >> 4) & 0xF
    if version != 4:
        return (PktClass.OTHER, 0, 0, 0)

    ihl = (packet_data[0] & 0xF) * 4
    protocol = packet_data[9]
    total_len = len(packet_data)

    # TCP → CONTROL (BattlEye, Steam auth, session management)
    if protocol == _PROTO_TCP:
        src_port = dst_port = 0
        if total_len >= ihl + 4:
            src_port = (packet_data[ihl] << 8) | packet_data[ihl + 1]
            dst_port = (packet_data[ihl + 2] << 8) | packet_data[ihl + 3]
        return (PktClass.CONTROL, protocol, src_port, dst_port)

    # UDP → classify by payload size
    if protocol == _PROTO_UDP:
        if total_len < ihl + 8:
            return (PktClass.OTHER, protocol, 0, 0)

        src_port = (packet_data[ihl] << 8) | packet_data[ihl + 1]
        dst_port = (packet_data[ihl + 2] << 8) | packet_data[ihl + 3]
        udp_payload = total_len - ihl - 8

        # For target traffic: ALL UDP is game traffic — classify by size.
        # Console only sends DayZ through the hotspot; PC-local is filtered.
        if is_target:
            if udp_payload <= _KEEPALIVE_PAYLOAD_MAX:
                return (PktClass.KEEPALIVE, protocol, src_port, dst_port)
            elif udp_payload <= _GAME_SMALL_PAYLOAD_MAX:
                return (PktClass.GAME_SMALL, protocol, src_port, dst_port)
            elif udp_payload <= _GAME_STATE_PAYLOAD_MAX:
                return (PktClass.GAME_STATE, protocol, src_port, dst_port)
            else:
                return (PktClass.GAME_BULK, protocol, src_port, dst_port)

        # Non-target UDP: use port heuristic
        is_game_port = (
            (_GAME_PORT_MIN <= src_port <= _GAME_PORT_MAX) or
            (_GAME_PORT_MIN <= dst_port <= _GAME_PORT_MAX) or
            (_STEAM_PORT_MIN <= src_port <= _STEAM_PORT_MAX) or
            (_STEAM_PORT_MIN <= dst_port <= _STEAM_PORT_MAX)
        )
        if is_game_port and udp_payload <= _KEEPALIVE_PAYLOAD_MAX:
            return (PktClass.KEEPALIVE, protocol, src_port, dst_port)
        return (PktClass.OTHER, protocol, src_port, dst_port)

    return (PktClass.OTHER, protocol, 0, 0)


# ═══════════════════════════════════════════════════════════════════════
#  Defaults
# ═══════════════════════════════════════════════════════════════════════

DEFAULT_GODMODE_LAG_MS: int = 2000
DEFAULT_KEEPALIVE_INTERVAL_MS: int = 800
DEFAULT_QUEUE_MAXLEN: int = 50_000
_MAX_LAG_MS: int = 120_000
_FLUSH_POLL_INTERVAL_S: float = 0.001
_BURST_SIZE: int = 50
_BURST_PAUSE_S: float = 0.005

DEFAULT_PULSE_BLOCK_MS: int = 3000
DEFAULT_PULSE_FLUSH_MS: int = 400
DEFAULT_PULSE_FLUSH_MAX_PACKETS: int = 300

# During flush, how many GAME_STATE packets to keep per direction.
# Rest are dropped. For inbound: prevents teleporting enemy playback.
# For outbound: sends only newest position → clean teleport to current pos.
DEFAULT_FLUSH_GAMESTATE_KEEP: int = 5

# Staggered flush: inbound arrives first so client gets fresh enemy positions,
# THEN outbound (including hit reports) flushes after a delay.  This gives
# the client updated enemy positions before hit reports are validated by the
# server, dramatically improving hit registration accuracy.
DEFAULT_FLUSH_STAGGER_MS: int = 120  # ms delay between inbound and outbound flush

# Drip-feed: max inbound packets sent per flush-loop tick (1ms).
# Spreading inbound over the flush window prevents visual teleporting
# caused by dumping hundreds of state updates in a single burst.
# 5 pkt/ms ≈ 5000 pkt/s → 200 packets spread over ~40ms.
_FLUSH_DRIP_IN: int = 5


# ═══════════════════════════════════════════════════════════════════════
#  GodModeModule — Bidirectional Pulse Cycling
# ═══════════════════════════════════════════════════════════════════════

# Type alias for queue entries: (release_time, packet_data, addr, classification)
_QEntry = Tuple[float, bytearray, WINDIVERT_ADDRESS, PktClass]


class GodModeModule(DisruptionModule):
    """Bidirectional God Mode — pulse-cycling both directions for PvP invulnerability.

    BLOCK phase:
      - Outbound game packets queued → server has stale position → ghost
      - Inbound game packets queued → frozen enemies on screen
      - TCP always passes (both dirs) → connection health
      - Keepalives pass at interval (both dirs) → prevent timeout

    FLUSH phase:
      - Both queues drain with GAME_STATE culling
      - Outbound: only newest N position packets → clean teleport
      - Inbound: only newest N state packets → no replay teleport

    Parameters (via *params* dict):
        _target_ip (str): **Required.** Device IP (console/remote PC) or
            game server IP (PC-local mode).
        godmode_pulse (bool): Enable pulse cycling. Default True.
        godmode_pulse_block_ms (int): Block phase duration. Default 3000.
        godmode_pulse_flush_ms (int): Flush phase duration. Default 400.
        godmode_pulse_flush_max (int): Max packets per flush per queue.
        godmode_flush_gamestate_keep (int): GAME_STATE to keep per flush.
        godmode_flush_stagger_ms (int): Delay between inbound and outbound
            flush. Inbound arrives first → client gets fresh enemy positions
            → outbound hit reports are validated. Default 120.
        godmode_keepalive_interval_ms (int): Keepalive interval. Default 800.
        godmode_drop_inbound_pct (int): Extra % of inbound to drop.
        godmode_infinite (bool): Aggressive tuning preset.
    """

    def __init__(self, params: dict) -> None:
        super().__init__(params)
        self.direction = DIR_BOTH

        # ── Target IP for direction detection ──────────────────────
        # PC-local mode: _target_ip = game server IP, direction inverted
        # Remote mode:   _target_ip = device IP (PS5/Xbox/remote PC)
        self._target_ip: str = params.get("_target_ip", "")
        self._is_local: bool = params.get("_network_local", False)
        if not self._target_ip:
            log_error("GodMode: _target_ip not set! Direction detection "
                      "will fail — all packets will pass through.")

        # Precomputed u32 form of target for zero-allocation hot-path
        # direction matching. 0 means "unset" → process() short-circuits.
        self._target_ip_u32: int = 0
        try:
            if self._target_ip:
                self._target_ip_u32 = int.from_bytes(
                    socket.inet_aton(self._target_ip), "big")
        except OSError:
            self._target_ip_u32 = 0

        profile_defaults = self._load_profile_defaults()

        queue_max: int = params.get(
            "godmode_lag_queue_maxlen",
            profile_defaults.get("godmode_lag_queue_maxlen", DEFAULT_QUEUE_MAXLEN),
        )

        # ── Two separate queues: inbound and outbound ──────────────
        self._inbound_queue: deque[_QEntry] = deque(maxlen=queue_max)
        self._outbound_queue: deque[_QEntry] = deque(maxlen=queue_max)
        self._lock = threading.Lock()
        self._flush_thread: Optional[threading.Thread] = None
        self._running: bool = True
        self._send_fn: Optional[Callable[[bytearray, WINDIVERT_ADDRESS], None]] = None

        # ── Counters ────────────────────────────────────────────────
        self._in_queued: int = 0
        self._in_dropped: int = 0
        self._in_keepalive: int = 0
        self._in_control: int = 0
        self._out_queued: int = 0
        self._out_keepalive: int = 0
        self._out_control: int = 0
        self._unrelated_passed: int = 0
        self._pulse_flushes: int = 0
        self._flush_in_released: int = 0
        self._flush_out_released: int = 0
        self._flush_gamestate_dropped: int = 0
        self._class_counts_in: Dict[PktClass, int] = {c: 0 for c in PktClass}
        self._class_counts_out: Dict[PktClass, int] = {c: 0 for c in PktClass}

        # ── ML packet classifier ────────────────────────────────────
        self._ml_classifier: Optional[object] = None
        if _ML_AVAILABLE:
            try:
                self._ml_classifier = MLPacketClassifier(
                    target_ip=self._target_ip)
                log_info("[GodMode] ML packet classifier initialized")
            except Exception as exc:
                log_error(f"[GodMode] ML classifier init failed: {exc}")

        # ── Packet recorder (for offline ML training) ───────────────
        self._recorder: Optional[object] = None
        if _RECORDER_AVAILABLE:
            try:
                rec_dir = params.get("recording_dir", "recordings")
                self._recorder = PacketRecorder(output_dir=rec_dir)
                if params.get("godmode_record", False):
                    self._recorder.start()
                    log_info("[GodMode] Packet recording ACTIVE")
                else:
                    log_info("[GodMode] Packet recorder available (use hotkeys to start)")
            except Exception as exc:
                log_error(f"[GodMode] Recorder init failed: {exc}")

        # ── Auto-detect game server port ─────────────────────────────
        # Track UDP destination ports from outbound target traffic.
        # After _PORT_DETECT_SAMPLES packets, lock to the most common port.
        self._port_counts: Dict[int, int] = {}
        self._detected_server_port: int = 0
        self._port_detect_remaining: int = 50  # samples before lock

        # ── Keepalive (both directions) ─────────────────────────────
        keepalive_ms: int = params.get(
            "godmode_keepalive_interval_ms",
            profile_defaults.get(
                "godmode_keepalive_interval_ms", DEFAULT_KEEPALIVE_INTERVAL_MS
            ),
        )
        self._keepalive_interval: float = max(0, keepalive_ms) / 1000.0
        self._last_keepalive_in: float = 0.0
        self._last_keepalive_out: float = 0.0

        # ── Infinite mode preset ────────────────────────────────────
        if params.get("godmode_infinite", False):
            params.setdefault("godmode_pulse", True)
            params.setdefault("godmode_pulse_block_ms", 5000)
            params.setdefault("godmode_pulse_flush_ms", 300)
            params.setdefault("godmode_pulse_flush_max", 200)
            params.setdefault("godmode_keepalive_interval_ms", 2000)
            params.setdefault("godmode_flush_gamestate_keep", 3)
            self._keepalive_interval = max(0,
                params.get("godmode_keepalive_interval_ms", 2000)) / 1000.0

        # ── Pulse cycling ───────────────────────────────────────────
        self._pulse_enabled: bool = params.get("godmode_pulse", True)
        self._pulse_block_ms: int = max(500, params.get(
            "godmode_pulse_block_ms",
            profile_defaults.get("godmode_pulse_block_ms", DEFAULT_PULSE_BLOCK_MS),
        ))
        self._pulse_flush_ms: int = max(100, params.get(
            "godmode_pulse_flush_ms",
            profile_defaults.get("godmode_pulse_flush_ms", DEFAULT_PULSE_FLUSH_MS),
        ))
        self._pulse_flush_max: int = max(10, params.get(
            "godmode_pulse_flush_max",
            profile_defaults.get("godmode_pulse_flush_max",
                                 DEFAULT_PULSE_FLUSH_MAX_PACKETS),
        ))
        self._flush_gamestate_keep: int = max(0, params.get(
            "godmode_flush_gamestate_keep",
            profile_defaults.get("godmode_flush_gamestate_keep",
                                 DEFAULT_FLUSH_GAMESTATE_KEEP),
        ))

        # ── Staggered flush ─────────────────────────────────────────
        # Inbound flushes first (client gets fresh enemy positions),
        # then outbound flushes after stagger delay (hit reports go
        # out with updated knowledge of enemy locations).
        self._flush_stagger_ms: int = max(0, params.get(
            "godmode_flush_stagger_ms",
            profile_defaults.get("godmode_flush_stagger_ms",
                                 DEFAULT_FLUSH_STAGGER_MS),
        ))
        self._flush_stagger_s: float = self._flush_stagger_ms / 1000.0

        self._cycle_duration_s: float = (
            (self._pulse_block_ms + self._pulse_flush_ms) / 1000.0
        )
        self._block_duration_s: float = self._pulse_block_ms / 1000.0
        self._cycle_start: float = 0.0

        mode = "PULSE" if self._pulse_enabled else "CLASSIC"
        if params.get("godmode_infinite", False):
            mode = "INFINITE"
        log_info(
            f"GodMode v6 BIDIR initialized: mode={mode}, "
            f"target_ip={self._target_ip}, "
            f"block={self._pulse_block_ms}ms, "
            f"flush={self._pulse_flush_ms}ms, "
            f"stagger={self._flush_stagger_ms}ms, "
            f"keepalive={keepalive_ms}ms, "
            f"gamestate_keep={self._flush_gamestate_keep}, "
            f"queue_max={queue_max}"
        )

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _load_profile_defaults() -> dict:
        try:
            from app.config.game_profiles import get_disruption_defaults
            return get_disruption_defaults("dayz")
        except Exception:
            return {}

    def _is_flush_phase(self, now: float) -> bool:
        if not self._pulse_enabled:
            return False
        if self._cycle_start <= 0:
            self._cycle_start = now
        elapsed = (now - self._cycle_start) % self._cycle_duration_s
        return elapsed >= self._block_duration_s

    # ── Flush thread ─────────────────────────────────────────────────

    def start_flush_thread(
        self,
        send_fn: Callable[[bytearray, WINDIVERT_ADDRESS], None],
        divert_dll: object,
        handle: object,
    ) -> None:
        self._send_fn = send_fn
        self._flush_thread = threading.Thread(
            target=self._flush_loop, daemon=True, name="GodModeFlush"
        )
        self._flush_thread.start()

    def _drain_queue_smart(
        self, queue: deque, max_packets: int
    ) -> list:
        """Drain a queue with GAME_STATE culling.

        Returns list of (packet_data, addr) tuples to send.
        Drops all but the newest ``_flush_gamestate_keep`` GAME_STATE
        packets. All other classes pass through.
        """
        raw: list[_QEntry] = []
        with self._lock:
            count = 0
            while queue and count < max_packets:
                raw.append(queue.popleft())
                count += 1

        if not raw:
            return []

        # Separate GAME_STATE from everything else
        gamestate: list[_QEntry] = []
        other: list[_QEntry] = []
        for entry in raw:
            if entry[3] == PktClass.GAME_STATE:
                gamestate.append(entry)
            else:
                other.append(entry)

        # Cull GAME_STATE to newest N
        if len(gamestate) > self._flush_gamestate_keep:
            dropped = len(gamestate) - self._flush_gamestate_keep
            self._flush_gamestate_dropped += dropped
            gamestate = gamestate[-self._flush_gamestate_keep:]

        # Return in order: other first, then newest gamestate
        result = []
        for _, pkt, addr, _ in other:
            result.append((pkt, addr))
        for _, pkt, addr, _ in gamestate:
            result.append((pkt, addr))
        return result

    def _flush_loop(self) -> None:
        """Bidirectional pulse-aware flush loop with staggered flush.

        FLUSH phase: drain inbound FIRST (client gets fresh enemy positions),
        wait stagger delay, THEN drain outbound (hit reports go out with
        updated target positions → server validates against current state).

        This ordering is critical for hit registration:
          1. Inbound flush → client receives real enemy positions
          2. Stagger delay → client processes the position updates (~100ms)
          3. Outbound flush → hit reports reference current enemy positions
             → server validation succeeds because positions match

        Without stagger: hit reports reference stale positions from BLOCK
        phase → server rejects because enemy has moved.

        BLOCK phase / classic: release only expired-timer packets.
        """
        _in_pending: list[Tuple[bytearray, WINDIVERT_ADDRESS]] = []
        _out_flush_at: float = 0.0  # timestamp when outbound flush should fire
        _in_draining = False  # True while drip-feeding inbound
        _out_done = False  # True once outbound flushed this cycle

        while self._running:
            now = time.time()

            if self._pulse_enabled and self._is_flush_phase(now):
                # ── FLUSH PHASE: drip-feed inbound, then stagger outbound ──

                # Step 1: Drain inbound queue once into a local buffer
                if not _in_draining and not _in_pending:
                    _in_pending = self._drain_queue_smart(
                        self._inbound_queue, self._pulse_flush_max)
                    _in_draining = True
                    _out_done = False
                    # Schedule outbound after stagger delay from NOW
                    _out_flush_at = now + self._flush_stagger_s

                # Step 2: Drip-feed inbound packets (_FLUSH_DRIP_IN per tick)
                if _in_pending:
                    batch = _in_pending[:_FLUSH_DRIP_IN]
                    _in_pending = _in_pending[_FLUSH_DRIP_IN:]
                    for pkt_data, addr in batch:
                        try:
                            self._send_fn(pkt_data, addr)  # type: ignore[misc]
                        except Exception as exc:
                            log_error(f"GodMode flush IN error: {exc}")
                    self._flush_in_released += len(batch)

                # Step 3: Flush OUTBOUND after stagger delay (once)
                if _in_draining and not _out_done and now >= _out_flush_at:
                    out_pkts = self._drain_queue_smart(
                        self._outbound_queue, self._pulse_flush_max)
                    for pkt_data, addr in out_pkts:
                        try:
                            self._send_fn(pkt_data, addr)  # type: ignore[misc]
                        except Exception as exc:
                            log_error(f"GodMode flush OUT error: {exc}")
                    self._pulse_flushes += 1
                    self._flush_out_released += len(out_pkts)
                    _out_done = True

            else:
                # ── BLOCK PHASE / CLASSIC: timed release only ───────
                # Reset flush tracking for next cycle
                if _in_draining:
                    # Flush any remaining inbound that didn't drip in time
                    for pkt_data, addr in _in_pending:
                        try:
                            self._send_fn(pkt_data, addr)  # type: ignore[misc]
                        except Exception as exc:
                            log_error(f"GodMode flush IN tail error: {exc}")
                    self._flush_in_released += len(_in_pending)
                _in_pending = []
                _in_draining = False
                _out_done = False
                _out_flush_at = 0.0

                for queue in (self._outbound_queue, self._inbound_queue):
                    to_send: list[Tuple[bytearray, WINDIVERT_ADDRESS]] = []
                    with self._lock:
                        while queue and queue[0][0] <= now:
                            _, pkt, addr, _ = queue.popleft()
                            to_send.append((pkt, addr))
                    for pkt_data, addr in to_send:
                        try:
                            self._send_fn(pkt_data, addr)  # type: ignore[misc]
                        except Exception as exc:
                            log_error(f"GodMode timed flush error: {exc}")

            time.sleep(_FLUSH_POLL_INTERVAL_S)

    # ── Packet processing ────────────────────────────────────────────

    def process(
        self,
        packet_data: bytearray,
        addr: WINDIVERT_ADDRESS,
        send_fn: Callable[[bytearray, WINDIVERT_ADDRESS], None],
    ) -> bool:
        """Bidirectional pulse-cycling with packet classification.

        Both inbound AND outbound game packets are queued during BLOCK.
        TCP and keepalives pass through always. During FLUSH, both queues
        drain with GAME_STATE culling.
        """
        # Zero-allocation direction detection — u32 int compare, no
        # per-packet inet_ntoa string churn. At PS5 DayZ rates (100-400 pps)
        # this eliminates ~400 string allocations/sec from the hot path,
        # which directly helps tick-aligned drop timing precision.
        src_u32, dst_u32 = _ipv4_addrs_u32(packet_data)
        target_u32 = self._target_ip_u32

        if target_u32 == 0:
            # No target set → bail before classification
            self._unrelated_passed += 1
            return False

        if self._is_local:
            # PC-local: _target_ip is the game SERVER IP.
            #   dst == server → outbound (local → server)
            #   src == server → inbound  (server → local)
            is_outbound = (dst_u32 == target_u32)
            is_inbound = (src_u32 == target_u32)
        else:
            # Remote (console/PC over hotspot): _target_ip is the DEVICE IP.
            #   src == device → outbound (device → server)
            #   dst == device → inbound  (server → device)
            is_inbound = (dst_u32 == target_u32)
            is_outbound = (src_u32 == target_u32)

        # Not our target's traffic → pass through
        if not is_inbound and not is_outbound:
            self._unrelated_passed += 1
            return False

        # ── Classify (is_target=True: all UDP = game traffic) ───────
        pkt_class, proto, src_port, dst_port = _classify_packet(packet_data, is_target=True)

        if is_inbound:
            self._class_counts_in[pkt_class] += 1
        else:
            self._class_counts_out[pkt_class] += 1

        # ── Auto-detect game server port ───────────────────────────
        if (self._port_detect_remaining > 0 and is_outbound
                and proto == _PROTO_UDP and dst_port > 0):
            self._port_counts[dst_port] = self._port_counts.get(dst_port, 0) + 1
            self._port_detect_remaining -= 1
            if self._port_detect_remaining == 0:
                # Lock to most common port
                best_port = max(self._port_counts, key=self._port_counts.get)
                self._detected_server_port = best_port
                log_info(
                    f"[GodMode] Auto-detected game server port: {best_port} "
                    f"(from {self._port_counts})")

        # ── ML classification (runs alongside size-based) ──────────
        ml_label = None
        if self._ml_classifier is not None:
            try:
                ml_pred = self._ml_classifier.classify(
                    packet_data, is_outbound=is_outbound, timestamp=time.time())
                ml_label = ml_pred.label
            except Exception:
                pass  # ML failure is non-fatal

        # Debug: log first 10 packets per direction
        if is_inbound:
            total_in = self._in_queued + self._in_keepalive + self._in_control + self._in_dropped
            if total_in < 10:
                ml_tag = f" ml={ml_label.name}" if ml_label else ""
                log_info(f"[GodMode] IN#{total_in+1} {pkt_class.name}{ml_tag} "
                         f"{'TCP' if proto == _PROTO_TCP else 'UDP'} "
                         f"{src_port}→{dst_port} {len(packet_data)}B")
        else:
            total_out = self._out_queued + self._out_keepalive + self._out_control
            if total_out < 10:
                ml_tag = f" ml={ml_label.name}" if ml_label else ""
                log_info(f"[GodMode] OUT#{total_out+1} {pkt_class.name}{ml_tag} "
                         f"{'TCP' if proto == _PROTO_TCP else 'UDP'} "
                         f"{src_port}→{dst_port} {len(packet_data)}B")

        now = time.time()

        # ── TCP / CONTROL: always pass both directions ──────────────
        if pkt_class == PktClass.CONTROL:
            if is_inbound:
                self._in_control += 1
            else:
                self._out_control += 1
            return False

        # ── FLUSH PHASE: pass everything through ────────────────────
        if self._pulse_enabled and self._is_flush_phase(now):
            return False

        # ── BLOCK PHASE ─────────────────────────────────────────────

        # Keepalive strategy: pass small packets at timed intervals.
        # Primary: pass KEEPALIVE-classified packets on schedule.
        # Fallback: if no keepalive has been sent in 2× the interval,
        # pass ANY small game packet (GAME_SMALL) to prevent timeout.
        # This handles DayZ where the smallest packets may exceed the
        # KEEPALIVE threshold but we still need periodic pass-through.
        if self._keepalive_interval > 0:
            if is_inbound:
                elapsed_in = now - self._last_keepalive_in
                if pkt_class == PktClass.KEEPALIVE and elapsed_in >= self._keepalive_interval:
                    self._last_keepalive_in = now
                    self._in_keepalive += 1
                    return False
                # Fallback: pass smallest game packet if overdue
                if pkt_class == PktClass.GAME_SMALL and elapsed_in >= self._keepalive_interval * 2:
                    self._last_keepalive_in = now
                    self._in_keepalive += 1
                    return False
            elif is_outbound:
                elapsed_out = now - self._last_keepalive_out
                if pkt_class == PktClass.KEEPALIVE and elapsed_out >= self._keepalive_interval:
                    self._last_keepalive_out = now
                    self._out_keepalive += 1
                    return False
                # Fallback: pass smallest game packet if overdue
                if pkt_class == PktClass.GAME_SMALL and elapsed_out >= self._keepalive_interval * 2:
                    self._last_keepalive_out = now
                    self._out_keepalive += 1
                    return False

        # Optional extra inbound drop
        if is_inbound:
            drop_pct: int = min(100, max(0,
                self.params.get("godmode_drop_inbound_pct", 0)))
            if drop_pct > 0 and self._roll(drop_pct):
                self._in_dropped += 1
                return True  # hard drop

        # ── Record packet metadata (if recorder active) ────────────
        if self._recorder is not None and self._recorder.is_recording:
            ml_name = ml_label.name if ml_label else ""
            self._recorder.record(
                packet_data, is_outbound=is_outbound,
                pkt_class_name=pkt_class.name, ml_label_name=ml_name)

        # ── ML-aware: pass hit reports immediately during block ─────
        # If the ML classifier identifies an outbound packet as a HIT_REPORT
        # during block phase, let it through immediately. Hit reports are
        # time-sensitive RPCs — delaying them reduces registration accuracy.
        # This only fires when the ML model is active and confident.
        if (ml_label is not None and _ML_AVAILABLE
                and is_outbound
                and ml_label == MLPacketType.HIT_REPORT):
            self._out_queued += 1  # count but don't actually queue
            return False  # pass through immediately

        # ── QUEUE the packet ────────────────────────────────────────
        if self._pulse_enabled:
            elapsed = (now - self._cycle_start) % self._cycle_duration_s
            time_until_flush = self._block_duration_s - elapsed
            if time_until_flush < 0:
                time_until_flush = 0
            release_time = now + time_until_flush
        else:
            delay_ms: int = self.params.get("godmode_lag_ms", DEFAULT_GODMODE_LAG_MS)
            delay_ms = max(0, min(_MAX_LAG_MS, delay_ms))
            release_time = now + (delay_ms / 1000.0)

        addr_copy = WINDIVERT_ADDRESS()
        ctypes.memmove(
            ctypes.byref(addr_copy),
            ctypes.byref(addr),
            ctypes.sizeof(WINDIVERT_ADDRESS),
        )
        entry: _QEntry = (release_time, bytearray(packet_data), addr_copy, pkt_class)

        with self._lock:
            if is_inbound:
                self._inbound_queue.append(entry)
                self._in_queued += 1
            else:
                self._outbound_queue.append(entry)
                self._out_queued += 1

        return True  # consumed — released by flush thread

    # ── Stats ────────────────────────────────────────────────────────

    def get_stats(self) -> Dict:
        with self._lock:
            in_depth = len(self._inbound_queue)
            out_depth = len(self._outbound_queue)
        return {
            "mode": "bidir_pulse" if self._pulse_enabled else "classic",
            "target_ip": self._target_ip,
            "in_queued": self._in_queued,
            "in_dropped": self._in_dropped,
            "in_keepalive": self._in_keepalive,
            "in_control": self._in_control,
            "out_queued": self._out_queued,
            "out_keepalive": self._out_keepalive,
            "out_control": self._out_control,
            "unrelated_passed": self._unrelated_passed,
            "in_queue_depth": in_depth,
            "out_queue_depth": out_depth,
            "pulse_flushes": self._pulse_flushes,
            "flush_in_released": self._flush_in_released,
            "flush_out_released": self._flush_out_released,
            "flush_gamestate_dropped": self._flush_gamestate_dropped,
            "block_ms": self._pulse_block_ms,
            "flush_ms": self._pulse_flush_ms,
            "flush_stagger_ms": self._flush_stagger_ms,
            "detected_server_port": self._detected_server_port,
            "class_in": {c.name: n for c, n in self._class_counts_in.items() if n},
            "class_out": {c.name: n for c, n in self._class_counts_out.items() if n},
            "ml_classifier": (
                self._ml_classifier.get_stats()
                if self._ml_classifier is not None else None
            ),
            "recorder": (
                self._recorder.get_stats()
                if self._recorder is not None else None
            ),
        }

    # ── Recorder controls ──────────────────────────────────────────

    def start_recording(self, session_name: str = "") -> str:
        """Start packet recording. Returns session name."""
        if self._recorder is not None:
            return self._recorder.start(session_name)
        return ""

    def stop_recording(self) -> str:
        """Stop recording and save CSV. Returns file path."""
        if self._recorder is not None:
            return self._recorder.stop()
        return ""

    def tag_event(self, tag: str) -> None:
        """Tag a game event (KILL, HIT, DEATH, INVENTORY)."""
        if self._recorder is not None:
            self._recorder.tag_event(tag)

    @property
    def is_recording(self) -> bool:
        if self._recorder is not None:
            return self._recorder.is_recording
        return False

    # ── Shutdown ─────────────────────────────────────────────────────

    def stop(self) -> None:
        """Stop flush thread, recorder, and drain both queues."""
        self._running = False
        if self._flush_thread and self._flush_thread.is_alive():
            self._flush_thread.join(timeout=1.0)

        # Stop recorder if active
        if self._recorder is not None and self._recorder.is_recording:
            csv_path = self._recorder.stop()
            if csv_path:
                log_info(f"[GodMode] Recording saved: {csv_path}")

        # Drain both queues
        with self._lock:
            remaining_in = list(self._inbound_queue)
            remaining_out = list(self._outbound_queue)
            self._inbound_queue.clear()
            self._outbound_queue.clear()

        remaining = remaining_out + remaining_in
        flushed: int = 0
        if self._send_fn:
            for i, (_, pkt_data, addr, _) in enumerate(remaining):
                try:
                    self._send_fn(pkt_data, addr)
                    flushed += 1
                except Exception:
                    pass
                if (i + 1) % _BURST_SIZE == 0 and i + 1 < len(remaining):
                    time.sleep(_BURST_PAUSE_S)

        cls_in = ", ".join(f"{c.name}={n}" for c, n in self._class_counts_in.items() if n)
        cls_out = ", ".join(f"{c.name}={n}" for c, n in self._class_counts_out.items() if n)

        ml_summary = ""
        if self._ml_classifier is not None:
            try:
                ml_summary = f", {self._ml_classifier.get_prediction_summary()}"
            except Exception:
                pass

        log_info(
            f"GodMode v6 BIDIR stats: "
            f"IN(queued={self._in_queued}, dropped={self._in_dropped}, "
            f"keepalive={self._in_keepalive}, control={self._in_control}) "
            f"OUT(queued={self._out_queued}, keepalive={self._out_keepalive}, "
            f"control={self._out_control}) "
            f"unrelated={self._unrelated_passed}, "
            f"flushes={self._pulse_flushes}, "
            f"flush_in={self._flush_in_released}, flush_out={self._flush_out_released}, "
            f"gamestate_culled={self._flush_gamestate_dropped}, "
            f"shutdown_flushed={flushed}, "
            f"class_in=[{cls_in}], class_out=[{cls_out}]"
            f"{ml_summary}"
        )
