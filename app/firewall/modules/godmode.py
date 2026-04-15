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

import time
import threading
from collections import deque
from typing import Callable, Dict, List, Optional, Tuple

from app.firewall.native_divert_engine import (
    DisruptionModule,
    WINDIVERT_ADDRESS,
    DIR_BOTH,
)
from app.logs.logger import log_error, log_info

# Tick estimator (optional — for tick-aligned flush timing)
try:
    from app.firewall.tick_sync import TickEstimator
    _TICK_AVAILABLE = True
except ImportError:
    _TICK_AVAILABLE = False

# Stealth timing (optional — jitter on flush cadence to avoid detection)
try:
    from app.firewall.stealth import (
        TimingRandomizer, NaturalPatternGenerator, SessionFingerprintRotator,
    )
    _STEALTH_AVAILABLE = True
except ImportError:
    _STEALTH_AVAILABLE = False

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
#  Packet Classifier — delegated to shared _packet_utils module.
#  Local aliases retained for backward compatibility.
# ═══════════════════════════════════════════════════════════════════════

from app.firewall.modules._packet_utils import (
    PktClass,
    classify_packet as _classify_packet_impl,
    ipv4_addrs_u32 as _ipv4_addrs_u32,
    ip_to_u32 as _ip_to_u32,
    copy_windivert_addr as _copy_windivert_addr,
    PROTO_TCP as _PROTO_TCP,
    PROTO_UDP as _PROTO_UDP,
)


def _classify_packet(packet_data: bytearray, is_target: bool = False) -> Tuple[PktClass, int, int, int]:
    """Classify an IPv4 packet — delegates to shared _packet_utils."""
    return _classify_packet_impl(packet_data, is_target)


# ═══════════════════════════════════════════════════════════════════════
#  Defaults
# ═══════════════════════════════════════════════════════════════════════

DEFAULT_GODMODE_LAG_MS: int = 3500       # deeper desync between pulses
DEFAULT_KEEPALIVE_INTERVAL_MS: int = 800
DEFAULT_QUEUE_MAXLEN: int = 50_000
_MAX_LAG_MS: int = 120_000
_FLUSH_POLL_INTERVAL_S: float = 0.001
_BURST_SIZE: int = 50
_BURST_PAUSE_S: float = 0.005

DEFAULT_PULSE_BLOCK_MS: int = 3500       # longer block = deeper ghost desync
DEFAULT_PULSE_FLUSH_MS: int = 300        # shorter flush = less time enemies react
DEFAULT_PULSE_FLUSH_MAX_PACKETS: int = 300

# During flush, how many GAME_STATE packets to keep per direction.
# Rest are dropped.
#
# v6.2: Direction-specific culling:
#   OUTBOUND (your position → server): keep 1. Only the newest position
#     goes out → server sees a single clean teleport to your current pos.
#     This is the #1 change for "teleport, not skip around" behavior.
#   INBOUND (enemy positions → you): keep 2. Two newest packets give the
#     client a recent position pair for interpolation, producing smoother
#     enemy rendering after flush. Keeping only 1 inbound causes enemies
#     to "pop" into position; 2 lets the client lerp between them.
DEFAULT_FLUSH_GAMESTATE_KEEP_OUT: int = 1   # YOUR position: clean teleport
DEFAULT_FLUSH_GAMESTATE_KEEP_IN: int = 2    # ENEMY positions: smooth interpolation
# Backward-compat alias used when per-direction isn't configured
DEFAULT_FLUSH_GAMESTATE_KEEP: int = 1

# Staggered flush: inbound arrives first so client gets fresh enemy positions,
# THEN outbound (including hit reports) flushes after a delay. Gives the
# client updated enemy positions before hit reports are validated by the
# server, dramatically improving hit registration accuracy.
DEFAULT_FLUSH_STAGGER_MS: int = 100      # tighter stagger = faster hit validation

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
        self._target_ip_u32: int = _ip_to_u32(self._target_ip)

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

        # ── Tick estimator (tick-aligned flush timing) ────────────────
        # v6.1: Align FLUSH phase start to server tick boundary so the
        # position data in the newest GAME_STATE is as fresh as possible.
        # This maximizes teleport accuracy — flushing mid-tick means the
        # "newest" packet is already half a tick stale.
        self._tick_estimator: Optional[object] = None
        if _TICK_AVAILABLE:
            try:
                self._tick_estimator = TickEstimator()
                log_info("[GodMode] TickEstimator initialized for tick-aligned flush")
            except Exception as exc:
                log_error(f"[GodMode] TickEstimator init failed: {exc}")

        # ── Stealth timing (jitter on pulse cadence) ──────────────────
        # v6.1: Add Gaussian jitter to block/flush timing to prevent
        # BattlEye from detecting periodic pulse patterns.
        self._timing_jitter: Optional[object] = None
        self._keepalive_pattern: Optional[object] = None
        self._session_rotator: Optional[object] = None
        if _STEALTH_AVAILABLE:
            try:
                # v6.2: SessionFingerprintRotator varies pulse timing each
                # session so no two sessions have identical block/flush/stagger
                # patterns. Anti-cheat can't build a behavioral signature
                # across sessions because the parameters shift.
                self._session_rotator = SessionFingerprintRotator()
                _jitter_pct = self._session_rotator.vary(
                    "godmode_jitter_pct",
                    params.get("godmode_jitter_pct", 0.10),
                    variance_pct=0.30)
                self._timing_jitter = TimingRandomizer(jitter_pct=_jitter_pct)

                # Vary keepalive cycle length per session (10-20s range)
                _ka_cycle = self._session_rotator.vary(
                    "keepalive_cycle", 15.0, variance_pct=0.30)
                _ka_pattern = self._session_rotator.get_pattern()
                self._keepalive_pattern = NaturalPatternGenerator(
                    pattern=_ka_pattern, cycle_sec=_ka_cycle)

                log_info(
                    f"[GodMode] Stealth active: jitter={_jitter_pct:.3f}, "
                    f"keepalive_pattern={_ka_pattern}, "
                    f"ka_cycle={_ka_cycle:.1f}s, "
                    f"session={self._session_rotator._session_hash[:8]}")
            except Exception as exc:
                log_error(f"[GodMode] Stealth init failed: {exc}")

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
            params.setdefault("godmode_pulse_flush_ms", 250)
            params.setdefault("godmode_pulse_flush_max", 200)
            params.setdefault("godmode_keepalive_interval_ms", 2000)
            params.setdefault("godmode_flush_gamestate_keep", 1)
            params.setdefault("godmode_flush_stagger_ms", 80)
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
        # v6.2: Per-direction overrides (fall back to unified value)
        self._flush_gamestate_keep_out: int = max(0, params.get(
            "godmode_flush_gamestate_keep_out",
            DEFAULT_FLUSH_GAMESTATE_KEEP_OUT))
        self._flush_gamestate_keep_in: int = max(0, params.get(
            "godmode_flush_gamestate_keep_in",
            DEFAULT_FLUSH_GAMESTATE_KEEP_IN))

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

        # v6.2: Apply session fingerprint rotation to pulse timing.
        # Each session gets ±15% variation on block/flush/stagger so
        # BattlEye can't correlate timing patterns across sessions.
        if self._session_rotator is not None:
            self._pulse_block_ms = max(500, int(self._session_rotator.vary(
                "pulse_block", float(self._pulse_block_ms), 0.15)))
            self._pulse_flush_ms = max(100, int(self._session_rotator.vary(
                "pulse_flush", float(self._pulse_flush_ms), 0.15)))
            self._flush_stagger_ms = max(30, int(self._session_rotator.vary(
                "flush_stagger", float(self._flush_stagger_ms), 0.20)))
            self._flush_stagger_s = self._flush_stagger_ms / 1000.0

        # v6.2: Adaptive block duration based on tick rate.
        # Enabled by default — uses tick estimator to scale block length:
        #   High tick rate (60Hz) → shorter block (faster state replication
        #     means less time needed to create deep desync)
        #   Low tick rate (20Hz) → longer block (slower replication needs
        #     more time to accumulate position divergence)
        # Scaling: block_ms * (30 / estimated_hz) → normalized to 30Hz baseline
        # Applied dynamically in _is_flush_phase after tick estimate stabilizes.
        self._adaptive_block: bool = params.get("godmode_adaptive_block", True)
        self._base_block_ms: int = self._pulse_block_ms  # save pre-adapt value

        self._cycle_duration_s: float = (
            (self._pulse_block_ms + self._pulse_flush_ms) / 1000.0
        )
        self._block_duration_s: float = self._pulse_block_ms / 1000.0
        self._cycle_start: float = 0.0
        self._last_tick_adapt: float = 0.0  # track when we last adapted

        mode = "PULSE" if self._pulse_enabled else "CLASSIC"
        if params.get("godmode_infinite", False):
            mode = "INFINITE"
        log_info(
            f"GodMode v6.2 BIDIR initialized: mode={mode}, "
            f"target_ip={self._target_ip}, "
            f"block={self._pulse_block_ms}ms, "
            f"flush={self._pulse_flush_ms}ms, "
            f"stagger={self._flush_stagger_ms}ms, "
            f"keepalive={keepalive_ms}ms, "
            f"gamestate_keep_out={self._flush_gamestate_keep_out}, "
            f"gamestate_keep_in={self._flush_gamestate_keep_in}, "
            f"adaptive_block={self._adaptive_block}, "
            f"queue_max={queue_max}"
        )

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _load_profile_defaults() -> dict:
        try:
            from app.config.game_profiles import get_disruption_defaults
            return get_disruption_defaults("dayz")
        except Exception as exc:
            log_error(f"GodMode: failed to load DayZ profile defaults: {exc}")
            return {}

    def _is_flush_phase(self, now: float) -> bool:
        if not self._pulse_enabled:
            return False
        if self._cycle_start <= 0:
            self._cycle_start = now
        elapsed = (now - self._cycle_start) % self._cycle_duration_s
        return elapsed >= self._block_duration_s

    def _maybe_adapt_block_duration(self, now: float) -> None:
        """Dynamically adjust block duration based on observed tick rate.

        Called periodically from process(). Recalculates at most once per
        second to avoid thrashing. Scales block_ms relative to a 30Hz
        baseline: higher tick rates get shorter blocks, lower rates get longer.

        Clamped to [500ms, 2x base] to prevent extreme values.
        """
        if not self._adaptive_block or self._tick_estimator is None:
            return
        if now - self._last_tick_adapt < 1.0:
            return  # rate-limit to 1 adapt/sec
        self._last_tick_adapt = now
        te = self._tick_estimator
        if te.estimated_tick_hz <= 0 or te.confidence < 0.4:
            return  # not confident enough

        # Scale factor: 30Hz baseline. 60Hz → 0.5x block, 15Hz → 2x block.
        scale = 30.0 / te.estimated_tick_hz
        scale = max(0.5, min(2.0, scale))  # clamp
        new_block = int(self._base_block_ms * scale)
        new_block = max(500, new_block)

        if new_block != self._pulse_block_ms:
            self._pulse_block_ms = new_block
            self._block_duration_s = new_block / 1000.0
            self._cycle_duration_s = (
                (new_block + self._pulse_flush_ms) / 1000.0)

    def _tick_align_flush_start(self, now_mono: float) -> float:
        """Return a small sleep duration to align flush start to tick boundary.

        Args:
            now_mono: Current time from time.monotonic() (must match the
                clock used by TickEstimator.update()).

        v6.1: When the flush phase is about to begin, this nudges the
        start time forward to coincide with the next estimated tick
        boundary.  Flushing at tick start means the GAME_STATE packet
        kept (newest-1) contains the freshest position the server just
        computed, yielding maximum teleport accuracy.

        Returns 0.0 if tick estimation isn't ready or alignment is disabled.
        """
        if self._tick_estimator is None:
            return 0.0
        te = self._tick_estimator
        if te.estimated_tick_ms <= 0 or te.confidence < 0.3:
            return 0.0
        next_tick = te.get_next_tick_time(now_mono)
        wait = next_tick - now_mono
        if wait <= 0 or wait > 0.050:  # cap at 50ms to avoid stalling
            return 0.0
        # Apply stealth jitter so alignment isn't perfectly periodic
        if self._timing_jitter is not None:
            wait = self._timing_jitter.jitter(wait * 1000.0) / 1000.0
        return max(0.0, min(wait, 0.050))

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
        self, queue: deque, max_packets: int,
        is_inbound: bool = False,
    ) -> list:
        """Drain a queue with priority ordering and GAME_STATE/BULK culling.

        Returns list of (packet_data, addr) tuples to send.

        v6.2: Direction-specific GAME_STATE culling:
          - OUTBOUND: keep newest 1 → clean teleport (YOUR position)
          - INBOUND: keep newest 2 → smooth enemy interpolation

        Culling strategy:
          - GAME_STATE: keep newest N (direction-dependent, see above)
          - GAME_BULK: keep newest 1 (world sync — bandwidth-expensive)
          - GAME_SMALL: keep all (acks, small control — cheap)
          - KEEPALIVE: keep all (connection maintenance)

        Flush order (optimized for hit registration):
          1. KEEPALIVE — re-establish connection liveness first
          2. GAME_SMALL — acks arrive, server knows client is responsive
          3. GAME_STATE — fresh positions for hit validation
          4. GAME_BULK — world sync last (least time-sensitive)
        """
        raw: list[_QEntry] = []
        with self._lock:
            count = 0
            while queue and count < max_packets:
                raw.append(queue.popleft())
                count += 1

        if not raw:
            return []

        # Bucket by packet class
        keepalive: list[_QEntry] = []
        game_small: list[_QEntry] = []
        gamestate: list[_QEntry] = []
        game_bulk: list[_QEntry] = []
        other: list[_QEntry] = []

        for entry in raw:
            pkt_class = entry[3]
            if pkt_class == PktClass.KEEPALIVE:
                keepalive.append(entry)
            elif pkt_class == PktClass.GAME_SMALL:
                game_small.append(entry)
            elif pkt_class == PktClass.GAME_STATE:
                gamestate.append(entry)
            elif pkt_class == PktClass.GAME_BULK:
                game_bulk.append(entry)
            else:
                other.append(entry)

        # v6.2: Direction-specific GAME_STATE culling with ML-aware ranking
        gs_keep = (self._flush_gamestate_keep_in if is_inbound
                   else self._flush_gamestate_keep_out)
        if len(gamestate) > gs_keep:
            # v6.2: If ML classifier is available, use it to rank GAME_STATE
            # packets. Position-carrying packets (POSITION_UPDATE, MOVEMENT)
            # are preferred over entity state or inventory updates because
            # position data is what determines teleport accuracy.
            if (self._ml_classifier is not None and _ML_AVAILABLE
                    and len(gamestate) > 1):
                # Score each GAME_STATE: position packets get +10 priority,
                # plus recency bonus (index in list = arrival order).
                _scored: list[Tuple[float, int, _QEntry]] = []
                for i, entry in enumerate(gamestate):
                    score = float(i)  # recency: higher = newer
                    try:
                        ml_pred = self._ml_classifier.classify(
                            entry[1],  # packet_data
                            is_outbound=(not is_inbound),
                            timestamp=entry[0])
                        if ml_pred.label in (
                            MLPacketType.POSITION_UPDATE,
                            MLPacketType.MOVEMENT,
                        ):
                            score += 10.0  # strong preference for position
                    except Exception:
                        pass  # fall back to recency-only
                    _scored.append((score, i, entry))
                # Sort by score descending, keep top N
                _scored.sort(key=lambda x: x[0], reverse=True)
                kept_entries = [s[2] for s in _scored[:gs_keep]]
                # Restore arrival order for flush sequencing
                kept_entries.sort(key=lambda e: e[0])
                dropped = len(gamestate) - gs_keep
                self._flush_gamestate_dropped += dropped
                gamestate = kept_entries
            else:
                # Fallback: simple newest-N culling
                dropped = len(gamestate) - gs_keep
                self._flush_gamestate_dropped += dropped
                gamestate = gamestate[-gs_keep:]

        # Cull GAME_BULK to newest 1 (bandwidth-expensive)
        _BULK_KEEP: int = 1
        if len(game_bulk) > _BULK_KEEP:
            self._flush_gamestate_dropped += len(game_bulk) - _BULK_KEEP
            game_bulk = game_bulk[-_BULK_KEEP:]

        # Priority-ordered flush: keepalive → acks → positions → bulk
        result: list[Tuple[bytearray, WINDIVERT_ADDRESS]] = []
        for bucket in (keepalive, game_small, other, gamestate, game_bulk):
            for _, pkt, addr, _ in bucket:
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
                    # v6.1: Tick-align flush start for maximum position freshness
                    # Use monotonic clock for tick alignment (matches TickEstimator)
                    _tick_wait = self._tick_align_flush_start(time.monotonic())
                    if _tick_wait > 0:
                        time.sleep(_tick_wait)
                        now = time.time()  # refresh wall clock after alignment sleep

                    _in_pending = self._drain_queue_smart(
                        self._inbound_queue, self._pulse_flush_max,
                        is_inbound=True)
                    _in_draining = True
                    _out_done = False
                    # Adaptive stagger: scale delay based on inbound packet count.
                    # More inbound packets = client needs longer to process position
                    # updates before outbound hit reports are validated.
                    # Base stagger + 0.5ms per inbound packet, capped at 2x base.
                    _adaptive_stagger = self._flush_stagger_s
                    if _in_pending:
                        _per_pkt_extra = 0.0005  # 0.5ms per packet
                        _extra = len(_in_pending) * _per_pkt_extra
                        _adaptive_stagger = min(
                            self._flush_stagger_s * 2.0,
                            self._flush_stagger_s + _extra,
                        )
                    _out_flush_at = now + _adaptive_stagger

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
                        self._outbound_queue, self._pulse_flush_max,
                        is_inbound=False)
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
            # v6.1: Feed tick estimator with inbound UDP for tick rate estimation
            if self._tick_estimator is not None and proto == _PROTO_UDP:
                try:
                    _now_mono = time.monotonic()
                    self._tick_estimator.update(_now_mono)
                    # v6.2: Adapt block duration based on observed tick rate
                    self._maybe_adapt_block_duration(_now_mono)
                except Exception:
                    pass  # estimator is non-critical
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
            except Exception as exc:
                self._ml_errors = getattr(self, "_ml_errors", 0) + 1
                if self._ml_errors <= 5:
                    log_error(f"GodMode: ML classify failed: {exc}")
                if self._ml_errors >= 50:
                    log_error("GodMode: ML classifier disabled after 50 failures")
                    self._ml_classifier = None

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
            # v6.1: Natural keepalive timing — apply jitter so intervals
            # look like genuine wifi interference rather than perfect spacing.
            # The NaturalPatternGenerator modulates the effective interval
            # with a sinusoidal + random spike pattern.
            effective_interval = self._keepalive_interval
            if self._keepalive_pattern is not None:
                # Modulate interval: base * (0.6 to 1.4) via pattern
                modulated_drop = self._keepalive_pattern.get_drop_chance(50.0)
                # Map drop_chance (0-100) → interval multiplier (0.6-1.4)
                effective_interval = self._keepalive_interval * (0.6 + 0.8 * modulated_drop / 100.0)

            if is_inbound:
                elapsed_in = now - self._last_keepalive_in
                if pkt_class == PktClass.KEEPALIVE and elapsed_in >= effective_interval:
                    self._last_keepalive_in = now
                    self._in_keepalive += 1
                    return False
                # Fallback: pass smallest game packet if overdue
                if pkt_class == PktClass.GAME_SMALL and elapsed_in >= effective_interval * 2:
                    self._last_keepalive_in = now
                    self._in_keepalive += 1
                    return False
            elif is_outbound:
                elapsed_out = now - self._last_keepalive_out
                if pkt_class == PktClass.KEEPALIVE and elapsed_out >= effective_interval:
                    self._last_keepalive_out = now
                    self._out_keepalive += 1
                    return False
                # Fallback: pass smallest game packet if overdue
                if pkt_class == PktClass.GAME_SMALL and elapsed_out >= effective_interval * 2:
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

        addr_copy = _copy_windivert_addr(addr)
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
            "tick_estimator": (
                self._tick_estimator.get_stats()
                if self._tick_estimator is not None else None
            ),
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
                except Exception as exc:
                    log_error(f"GodMode: shutdown flush failed ({len(pkt_data)}B): {exc}")
                if (i + 1) % _BURST_SIZE == 0 and i + 1 < len(remaining):
                    time.sleep(_BURST_PAUSE_S)

        cls_in = ", ".join(f"{c.name}={n}" for c, n in self._class_counts_in.items() if n)
        cls_out = ", ".join(f"{c.name}={n}" for c, n in self._class_counts_out.items() if n)

        ml_summary = ""
        if self._ml_classifier is not None:
            try:
                ml_summary = f", {self._ml_classifier.get_prediction_summary()}"
            except Exception as exc:
                log_error(f"GodMode: ML summary failed: {exc}")

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
