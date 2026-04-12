"""Dupe Engine v2 — Smart Selective Duplication for DayZ 1.29+.

Replaces the v1 total-hard-cut approach with classified packet filtering
that maintains connection health while creating inventory desync windows.

DayZ 1.29 Changes Addressed
────────────────────────────
  - Hand/inventory desync exploit patched (1.27 P3 + 1.29)
  - Server crash rollback vector patched
  - 400% server FPS improvement → narrower timing windows
  - Disconnect logging added for forensic tracing
  - Reliable UDP: 32-bit ack bitfield, each ack sent 32 times

Core Innovation: Selective Cut
──────────────────────────────
Instead of dropping ALL packets (v1), v2 classifies each packet and only
blocks game-state replication while passing connection-health traffic:

  PASS:  TCP (BattlEye, Steam), keepalives, small acks
  DROP:  GAME_STATE, GAME_BULK (inventory/entity replication)
  QUEUE: Outbound game packets (released during graduated restore)

This allows cut durations of 30s+ without server kick, while preventing
the server from replicating inventory change confirmations back to the
client — creating the desync window needed for duplication.

Dupe Methods
────────────
  drop_pick  — Drop item, wait for outbound RPC, selective cut
  swap       — Initiate swap, selective cut (blocks both dirs STATE)
  container  — Put in container, selective cut (blocks inbound STATE)
  rift       — Pulse-cycle with extended block, action during block
  legacy     — Total hard cut (v1 fallback for pre-1.29 servers)

State Machine
─────────────
  IDLE → ARMED → LISTENING → SELECTIVE_CUT → GRADUATED_RESTORE → COOLDOWN → IDLE
"""

from __future__ import annotations

import enum
import time
import threading
from collections import deque
from typing import Callable, Dict, List, Optional, Tuple

from app.firewall.native_divert_engine import (
    DisruptionModule,
    WINDIVERT_ADDRESS,
    DIR_BOTH,
)
from app.firewall.modules._packet_utils import (
    PktClass,
    classify_packet,
    ipv4_addrs_u32,
    ip_to_u32,
    detect_direction,
    copy_windivert_addr,
    KeepaliveTracker,
    PROTO_TCP,
)
from app.logs.logger import log_info, log_error

# Optional: TickEstimator for tick-aligned cut entry
try:
    from app.firewall.tick_sync import TickEstimator
    _TICK_AVAILABLE = True
except ImportError:
    _TICK_AVAILABLE = False

# Optional: stealth timing randomizer
try:
    from app.firewall.stealth import TimingRandomizer
    _STEALTH_AVAILABLE = True
except ImportError:
    _STEALTH_AVAILABLE = False

__all__ = ["DupePhaseV2", "DupeMethod", "DupeEngineV2"]


# ── Defaults ─────────────────────────────────────────────────────────

DEFAULT_CUT_DURATION_MS: int = 5000
DEFAULT_RESTORE_DURATION_MS: int = 800
DEFAULT_RPC_TIMEOUT_MS: int = 2000
DEFAULT_KEEPALIVE_INTERVAL_MS: int = 800
DEFAULT_CYCLE_COUNT: int = 1
DEFAULT_CYCLE_DELAY_MS: int = 3000
DEFAULT_COOLDOWN_MS: int = 1500

_MIN_CUT_MS: int = 1000
_MAX_CUT_MS: int = 60000  # v2 supports much longer cuts via selective filtering

# RPC detection: outbound game-state burst within this window triggers cut
_RPC_BURST_WINDOW_S: float = 0.200  # 200ms
_RPC_BURST_MIN_PACKETS: int = 2     # min outbound game packets in window

# Graduated restore phase timings (fraction of total restore duration)
_RESTORE_PHASE1_FRAC: float = 0.25  # keepalives + acks
_RESTORE_PHASE2_FRAC: float = 0.50  # + outbound game state
# phase 3 = remainder: + inbound game state (full open)

# Queue limits
_OUTBOUND_QUEUE_MAX: int = 10_000
_FLUSH_POLL_INTERVAL_S: float = 0.001
_DRIP_PER_TICK: int = 5  # packets per ms during graduated restore


class DupePhaseV2(enum.Enum):
    """State machine phases for Dupe Engine v2."""
    IDLE = "idle"
    ARMED = "armed"
    LISTENING = "listening"
    SELECTIVE_CUT = "selective_cut"
    GRADUATED_RESTORE = "graduated_restore"
    COOLDOWN = "cooldown"


class DupeMethod(enum.Enum):
    """Supported dupe method profiles."""
    DROP_PICK = "drop_pick"
    SWAP = "swap"
    CONTAINER = "container"
    RIFT = "rift"          # Pulse-cycle hybrid (formerly "god mode dupe")
    LEGACY = "legacy"      # Total hard cut (v1 fallback)


# ── Per-method packet filtering rules ────────────────────────────────

# Each method defines which packet classes to DROP during SELECTIVE_CUT.
# Classes not in the drop set pass through (unless queued).
_METHOD_RULES: Dict[DupeMethod, Dict] = {
    DupeMethod.DROP_PICK: {
        "drop_inbound": {PktClass.GAME_STATE, PktClass.GAME_BULK},
        "drop_outbound": set(),  # outbound passes (RPC already sent)
        "queue_outbound": {PktClass.GAME_STATE},  # queue for graduated release
        "description": "Block inbound state replication. Server applied action but client doesn't get confirmation.",
    },
    DupeMethod.SWAP: {
        "drop_inbound": {PktClass.GAME_STATE, PktClass.GAME_BULK},
        "drop_outbound": {PktClass.GAME_STATE},  # block both dirs to freeze partial swap
        "queue_outbound": set(),
        "description": "Block both directions state. Partial swap state persists.",
    },
    DupeMethod.CONTAINER: {
        "drop_inbound": {PktClass.GAME_STATE, PktClass.GAME_BULK},
        "drop_outbound": set(),
        "queue_outbound": {PktClass.GAME_STATE},
        "description": "Block inbound state. Server applied container transfer, client doesn't see.",
    },
    DupeMethod.RIFT: {
        "drop_inbound": {PktClass.GAME_STATE, PktClass.GAME_BULK},
        "drop_outbound": {PktClass.GAME_STATE, PktClass.GAME_BULK},
        "queue_outbound": set(),
        "description": "Full bidirectional state block. Extended desync window via pulse cycling.",
    },
    DupeMethod.LEGACY: {
        "drop_inbound": {PktClass.KEEPALIVE, PktClass.CONTROL, PktClass.GAME_SMALL,
                         PktClass.GAME_STATE, PktClass.GAME_BULK, PktClass.OTHER},
        "drop_outbound": {PktClass.KEEPALIVE, PktClass.CONTROL, PktClass.GAME_SMALL,
                          PktClass.GAME_STATE, PktClass.GAME_BULK, PktClass.OTHER},
        "queue_outbound": set(),
        "description": "Total hard cut. V1 fallback for pre-1.29 servers.",
    },
}


# ═══════════════════════════════════════════════════════════════════════
#  DupeEngineV2
# ═══════════════════════════════════════════════════════════════════════

# Type alias for queued outbound packets
_QEntry = Tuple[float, bytearray, WINDIVERT_ADDRESS, PktClass]


class DupeEngineV2(DisruptionModule):
    """Smart Selective Dupe Engine for DayZ 1.29+.

    Uses classified packet filtering to create inventory desync windows
    while maintaining connection health. Replaces the v1 total-hard-cut
    approach with surgical selective blocking.

    Parameters (via *params* dict):
        _target_ip (str): Required. Device IP or game server IP.
        _network_local (bool): True for PC-local mode.
        dupe_method (str): Method profile. Default "drop_pick".
        dupe_rpc_detect (bool): Wait for outbound RPC before cutting. Default True.
        dupe_rpc_timeout_ms (int): Fallback timeout if no RPC detected. Default 2000.
        dupe_tick_align (bool): Align cut entry to tick boundary. Default True.
        dupe_cut_duration_ms (int): Selective cut duration. Default 5000.
        dupe_graduated_restore (bool): Phased reconnection. Default True.
        dupe_restore_duration_ms (int): Restore phase duration. Default 800.
        dupe_keepalive_during_cut (bool): Pass keepalives. Default True.
        dupe_keepalive_interval_ms (int): Keepalive interval. Default 800.
        dupe_stealth (bool): Wrap in stealth layer. Default True.
        dupe_cycle_count (int): Number of cut cycles. Default 1.
        dupe_cycle_delay_ms (int): Delay between cycles. Default 3000.
    """

    _direction_key: str = "dupe_v2"

    def __init__(self, params: dict) -> None:
        super().__init__(params)
        self.direction = DIR_BOTH

        # ── Phase state ──────────────────────────────────────────────
        self._phase: DupePhaseV2 = DupePhaseV2.IDLE
        self._phase_lock = threading.Lock()
        self._phase_start: float = 0.0
        self._running: bool = True

        # ── Target IP for direction detection ────────────────────────
        self._target_ip: str = params.get("_target_ip", "")
        self._is_local: bool = params.get("_network_local", False)
        self._target_ip_u32: int = ip_to_u32(self._target_ip)

        if not self._target_ip:
            log_error("DupeV2: _target_ip not set! Direction detection will fail.")

        # ── Method profile ───────────────────────────────────────────
        method_str: str = params.get("dupe_method", "drop_pick")
        try:
            self._method: DupeMethod = DupeMethod(method_str)
        except ValueError:
            log_error(f"DupeV2: unknown method '{method_str}', falling back to drop_pick")
            self._method = DupeMethod.DROP_PICK

        self._rules = _METHOD_RULES[self._method]

        # ── Feature toggles ──────────────────────────────────────────
        self._rpc_detect: bool = params.get("dupe_rpc_detect", True)
        self._tick_align: bool = params.get("dupe_tick_align", True)
        self._graduated: bool = params.get("dupe_graduated_restore", True)
        self._stealth_enabled: bool = params.get("dupe_stealth", True)

        # ── Timing ───────────────────────────────────────────────────
        self._cut_ms: int = max(_MIN_CUT_MS, min(_MAX_CUT_MS,
            params.get("dupe_cut_duration_ms", DEFAULT_CUT_DURATION_MS)))
        self._restore_ms: int = max(200,
            params.get("dupe_restore_duration_ms", DEFAULT_RESTORE_DURATION_MS))
        self._rpc_timeout_ms: int = max(500,
            params.get("dupe_rpc_timeout_ms", DEFAULT_RPC_TIMEOUT_MS))
        self._cycle_count: int = max(1,
            params.get("dupe_cycle_count", DEFAULT_CYCLE_COUNT))
        self._cycle_delay_ms: int = max(0,
            params.get("dupe_cycle_delay_ms", DEFAULT_CYCLE_DELAY_MS))
        self._cooldown_ms: int = max(0,
            params.get("dupe_cooldown_ms", DEFAULT_COOLDOWN_MS))

        # ── Keepalive tracker ────────────────────────────────────────
        keepalive_ms: int = params.get(
            "dupe_keepalive_interval_ms", DEFAULT_KEEPALIVE_INTERVAL_MS)
        self._keepalive_enabled: bool = params.get("dupe_keepalive_during_cut", True)
        self._keepalive = KeepaliveTracker(keepalive_ms)

        # ── Tick estimator ───────────────────────────────────────────
        self._tick_estimator: Optional[object] = None
        if self._tick_align and _TICK_AVAILABLE:
            try:
                self._tick_estimator = TickEstimator()
            except Exception:
                pass

        # ── Stealth randomizer ───────────────────────────────────────
        self._jitter: Optional[object] = None
        if self._stealth_enabled and _STEALTH_AVAILABLE:
            try:
                self._jitter = TimingRandomizer(
                    jitter_pct=params.get("dupe_jitter_pct", 0.12))
            except Exception:
                pass

        # ── Outbound queue (for graduated restore) ───────────────────
        self._out_queue: deque[_QEntry] = deque(maxlen=_OUTBOUND_QUEUE_MAX)
        self._queue_lock = threading.Lock()
        self._send_fn: Optional[Callable] = None
        self._flush_thread: Optional[threading.Thread] = None

        # ── RPC detection state ──────────────────────────────────────
        self._rpc_lock = threading.Lock()
        self._rpc_outbound_times: List[float] = []
        self._rpc_detected: bool = False

        # ── Cycle tracking ───────────────────────────────────────────
        self._current_cycle: int = 0
        self._cuts_completed: int = 0

        # ── Counters ────────────────────────────────────────────────
        self._pkts_dropped: int = 0
        self._pkts_passed: int = 0
        self._pkts_queued: int = 0
        self._pkts_keepalive: int = 0
        self._pkts_control: int = 0
        self._pkts_unrelated: int = 0

        # ── Phase callbacks ──────────────────────────────────────────
        self._on_phase_change: Optional[Callable[[DupePhaseV2], None]] = None

        log_info(
            f"DupeV2 initialized: method={self._method.value}, "
            f"rpc_detect={self._rpc_detect}, "
            f"tick_align={self._tick_align}, cut={self._cut_ms}ms, "
            f"restore={self._restore_ms}ms, cycles={self._cycle_count}, "
            f"target={self._target_ip}"
        )

    # ── State machine control ────────────────────────────────────────

    def activate(self) -> None:
        """Begin the dupe sequence. Transitions IDLE → ARMED."""
        with self._phase_lock:
            if self._phase != DupePhaseV2.IDLE:
                log_info(f"DupeV2: already in {self._phase.value}, ignoring activate")
                return
            self._current_cycle = 0
            with self._rpc_lock:
                self._rpc_outbound_times.clear()
                self._rpc_detected = False
            self._transition(DupePhaseV2.ARMED)
            log_info("DupeV2: ARMED — monitoring traffic, waiting for trigger")

    def trigger_cut(self) -> None:
        """User triggered the inventory action. Transitions ARMED → LISTENING."""
        with self._phase_lock:
            if self._phase == DupePhaseV2.ARMED:
                self._current_cycle += 1
                with self._rpc_lock:
                    self._rpc_outbound_times.clear()
                    self._rpc_detected = False
                self._transition(DupePhaseV2.LISTENING)
                log_info("DupeV2: LISTENING — watching for outbound RPC confirmation")
                # Schedule fallback timeout
                if self._rpc_detect:
                    self._schedule(self._rpc_timeout_ms / 1000.0, self._rpc_timeout_handler)
                else:
                    # No RPC detection — go straight to cut
                    self._enter_selective_cut()
            elif self._phase == DupePhaseV2.LISTENING:
                # Manual override — force cut now
                self._enter_selective_cut()
            else:
                log_info(f"DupeV2: not in ARMED/LISTENING ({self._phase.value}), ignoring trigger")

    def trigger_restore(self) -> None:
        """Manually restore the network. Transitions SELECTIVE_CUT → GRADUATED_RESTORE."""
        with self._phase_lock:
            if self._phase != DupePhaseV2.SELECTIVE_CUT:
                return
            self._enter_restore()

    def abort(self) -> None:
        """Abort the dupe sequence immediately. Returns to IDLE."""
        with self._phase_lock:
            self._transition(DupePhaseV2.IDLE)
            with self._queue_lock:
                self._flush_remaining()
            log_info("DupeV2: ABORTED — returned to IDLE")

    # ── Internal state transitions ───────────────────────────────────

    def _transition(self, phase: DupePhaseV2) -> None:
        """Transition to a new phase."""
        old = self._phase
        self._phase = phase
        self._phase_start = time.time()
        log_info(f"DupeV2: {old.value} → {phase.value}")
        if self._on_phase_change:
            try:
                self._on_phase_change(phase)
            except Exception:
                pass

    def _enter_selective_cut(self) -> None:
        """Enter SELECTIVE_CUT phase."""
        # Optional: align to tick boundary
        if self._tick_align and self._tick_estimator is not None:
            tick_ms = self._tick_estimator.estimated_tick_ms
            confidence = self._tick_estimator.confidence
            if tick_ms > 0 and confidence > 0.3:
                last = self._tick_estimator.last_arrival
                if last > 0:
                    now = time.time()
                    tick_s = tick_ms / 1000.0
                    elapsed = (now - last) % tick_s
                    wait = tick_s - elapsed
                    if 0 < wait < tick_s:
                        # Apply stealth jitter to alignment
                        if self._jitter:
                            wait = self._jitter.jitter(wait * 1000) / 1000.0
                        time.sleep(max(0, min(wait, 0.050)))  # cap at 50ms

        self._keepalive.reset()
        self._transition(DupePhaseV2.SELECTIVE_CUT)

        cut_s = self._cut_ms / 1000.0
        if self._jitter:
            cut_s = self._jitter.jitter(self._cut_ms) / 1000.0

        log_info(
            f"DupeV2: SELECTIVE CUT — method={self._method.value}, "
            f"cycle {self._current_cycle}/{self._cycle_count}, "
            f"duration={int(cut_s * 1000)}ms"
        )
        # Auto-restore after cut duration
        self._schedule(cut_s, self._auto_restore_handler)

    def _enter_restore(self) -> None:
        """Enter GRADUATED_RESTORE phase."""
        self._cuts_completed += 1
        self._transition(DupePhaseV2.GRADUATED_RESTORE)

        restore_s = self._restore_ms / 1000.0
        log_info(
            f"DupeV2: GRADUATED RESTORE — "
            f"cycle {self._current_cycle}/{self._cycle_count}, "
            f"duration={self._restore_ms}ms"
        )
        # Schedule end of restore → cooldown
        self._schedule(restore_s, self._restore_complete_handler)

    def _enter_cooldown(self) -> None:
        """Enter COOLDOWN phase. Flush any remaining queued packets."""
        with self._queue_lock:
            self._flush_remaining()
        self._transition(DupePhaseV2.COOLDOWN)

        cooldown_s = self._cooldown_ms / 1000.0
        if self._current_cycle < self._cycle_count:
            # More cycles — schedule next cycle
            delay = (self._cycle_delay_ms + self._cooldown_ms) / 1000.0
            self._schedule(delay, self._next_cycle_handler)
        else:
            # All done — back to idle
            self._schedule(cooldown_s, self._all_done_handler)

    # ── Scheduled callbacks ──────────────────────────────────────────

    def _rpc_timeout_handler(self) -> None:
        """RPC detection timed out — fall back to timer-based cut."""
        with self._phase_lock:
            with self._rpc_lock:
                rpc_was_detected = self._rpc_detected
            if self._phase == DupePhaseV2.LISTENING and not rpc_was_detected:
                log_info("DupeV2: RPC timeout — falling back to timer-based cut")
                self._enter_selective_cut()

    def _auto_restore_handler(self) -> None:
        """Cut duration expired — auto-restore."""
        with self._phase_lock:
            if self._phase == DupePhaseV2.SELECTIVE_CUT:
                self._enter_restore()

    def _restore_complete_handler(self) -> None:
        """Graduated restore complete — enter cooldown."""
        with self._phase_lock:
            if self._phase == DupePhaseV2.GRADUATED_RESTORE:
                self._enter_cooldown()

    def _next_cycle_handler(self) -> None:
        """Start next dupe cycle."""
        with self._phase_lock:
            if self._phase == DupePhaseV2.COOLDOWN:
                with self._rpc_lock:
                    self._rpc_outbound_times.clear()
                    self._rpc_detected = False
                self._transition(DupePhaseV2.ARMED)
                log_info(f"DupeV2: starting cycle {self._current_cycle + 1}/{self._cycle_count}")

    def _all_done_handler(self) -> None:
        """All cycles complete — return to idle."""
        with self._phase_lock:
            if self._phase == DupePhaseV2.COOLDOWN:
                self._transition(DupePhaseV2.IDLE)
                log_info(
                    f"DupeV2: all {self._cycle_count} cycles complete — "
                    f"dropped={self._pkts_dropped}, passed={self._pkts_passed}, "
                    f"queued={self._pkts_queued}"
                )

    def _schedule(self, delay_s: float, callback: Callable) -> None:
        """Schedule a callback after a delay."""
        def _worker():
            time.sleep(delay_s)
            if self._running:
                callback()
        t = threading.Thread(target=_worker, daemon=True, name="DupeV2Timer")
        t.start()

    # ── Flush thread ─────────────────────────────────────────────────

    def start_flush_thread(
        self,
        send_fn: Callable[[bytearray, WINDIVERT_ADDRESS], None],
        divert_dll: object,
        handle: object,
    ) -> None:
        """Start background thread for graduated restore drip-feed."""
        self._send_fn = send_fn
        self._flush_thread = threading.Thread(
            target=self._flush_loop, daemon=True, name="DupeV2Flush"
        )
        self._flush_thread.start()

    def _flush_loop(self) -> None:
        """Drip-feed queued outbound packets during graduated restore."""
        while self._running:
            if self._phase == DupePhaseV2.GRADUATED_RESTORE:
                now = time.time()
                elapsed = now - self._phase_start
                restore_s = self._restore_ms / 1000.0

                # Phase 1: first 25% — only keepalives/acks (already passing)
                # Phase 2: 25-75% — release queued outbound game state
                # Phase 3: 75%+ — full open (all pass in process())
                frac = elapsed / restore_s if restore_s > 0 else 1.0

                if frac >= _RESTORE_PHASE1_FRAC:
                    # Drip-feed outbound queue
                    to_send: list = []
                    with self._queue_lock:
                        for _ in range(min(_DRIP_PER_TICK, len(self._out_queue))):
                            if self._out_queue:
                                to_send.append(self._out_queue.popleft())
                    for _, pkt_data, addr, _ in to_send:
                        try:
                            if self._send_fn:
                                self._send_fn(pkt_data, addr)
                        except Exception as exc:
                            log_error(f"DupeV2 flush error: {exc}")

            time.sleep(_FLUSH_POLL_INTERVAL_S)

    def _flush_remaining(self) -> None:
        """Flush all remaining queued packets immediately."""
        remaining = list(self._out_queue)
        self._out_queue.clear()
        if self._send_fn:
            flush_errors = 0
            for _, pkt_data, addr, _ in remaining:
                try:
                    self._send_fn(pkt_data, addr)
                except Exception as exc:
                    flush_errors += 1
                    if flush_errors <= 3:
                        log_error(f"DupeV2 flush_remaining error: {exc}")
            if flush_errors > 3:
                log_error(f"DupeV2 flush_remaining: {flush_errors} total send failures")

    # ── Packet processing (hot path) ─────────────────────────────────

    def process(
        self,
        packet_data: bytearray,
        addr: WINDIVERT_ADDRESS,
        send_fn: Callable[[bytearray, WINDIVERT_ADDRESS], None],
    ) -> bool:
        """Classify and handle each packet based on current phase and method rules."""

        # ── Direction detection ──────────────────────────────────────
        src_u32, dst_u32 = ipv4_addrs_u32(packet_data)
        is_inbound, is_outbound = detect_direction(
            src_u32, dst_u32, self._target_ip_u32, self._is_local)

        if not is_inbound and not is_outbound:
            self._pkts_unrelated += 1
            return False  # not our target's traffic

        # ── Classify ────────────────────────────────────────────────
        pkt_class, proto, src_port, dst_port = classify_packet(
            packet_data, is_target=True)

        # ── Feed tick estimator (inbound only) ──────────────────────
        if is_inbound and self._tick_estimator is not None:
            if proto != PROTO_TCP:
                try:
                    self._tick_estimator.update(time.time())
                except Exception:
                    pass

        # ── Phase-specific handling ─────────────────────────────────
        phase = self._phase

        # IDLE / COOLDOWN: pass everything
        if phase in (DupePhaseV2.IDLE, DupePhaseV2.COOLDOWN):
            self._pkts_passed += 1
            return False

        # ARMED: pass everything, monitoring only
        if phase == DupePhaseV2.ARMED:
            self._pkts_passed += 1
            return False

        # LISTENING: pass everything but watch for outbound RPC
        if phase == DupePhaseV2.LISTENING:
            if is_outbound and pkt_class in (PktClass.GAME_STATE, PktClass.GAME_BULK):
                now = time.time()
                burst_detected = False
                burst_count = 0
                with self._rpc_lock:
                    self._rpc_outbound_times.append(now)
                    # Prune old entries
                    cutoff = now - _RPC_BURST_WINDOW_S
                    self._rpc_outbound_times = [
                        t for t in self._rpc_outbound_times if t >= cutoff
                    ]
                    burst_count = len(self._rpc_outbound_times)
                    if burst_count >= _RPC_BURST_MIN_PACKETS:
                        burst_detected = True
                        self._rpc_detected = True
                # Transition outside rpc_lock to avoid nested lock ordering issues
                if burst_detected:
                    log_info(
                        f"DupeV2: outbound RPC detected "
                        f"({burst_count} packets in "
                        f"{int(_RPC_BURST_WINDOW_S * 1000)}ms window)"
                    )
                    with self._phase_lock:
                        if self._phase == DupePhaseV2.LISTENING:
                            self._enter_selective_cut()
            self._pkts_passed += 1
            return False

        # SELECTIVE_CUT: classified packet filtering
        if phase == DupePhaseV2.SELECTIVE_CUT:
            return self._handle_selective_cut(
                packet_data, addr, pkt_class, is_inbound, is_outbound)

        # GRADUATED_RESTORE: phased reconnection
        if phase == DupePhaseV2.GRADUATED_RESTORE:
            return self._handle_graduated_restore(
                packet_data, addr, pkt_class, is_inbound, is_outbound)

        # Default: pass
        self._pkts_passed += 1
        return False

    def _handle_selective_cut(
        self,
        packet_data: bytearray,
        addr: WINDIVERT_ADDRESS,
        pkt_class: PktClass,
        is_inbound: bool,
        is_outbound: bool,
    ) -> bool:
        """Handle packets during SELECTIVE_CUT phase."""
        now = time.time()

        # TCP / CONTROL: always pass (BattlEye, Steam)
        if pkt_class == PktClass.CONTROL:
            self._pkts_control += 1
            return False

        # Legacy mode: drop everything
        if self._method == DupeMethod.LEGACY:
            self._pkts_dropped += 1
            return True

        # Keepalive pass-through
        if self._keepalive_enabled:
            if is_inbound and self._keepalive.should_pass_inbound(pkt_class, now):
                self._pkts_keepalive += 1
                return False
            if is_outbound and self._keepalive.should_pass_outbound(pkt_class, now):
                self._pkts_keepalive += 1
                return False

        # Inbound filtering
        if is_inbound:
            if pkt_class in self._rules["drop_inbound"]:
                self._pkts_dropped += 1
                return True  # drop
            self._pkts_passed += 1
            return False  # pass

        # Outbound filtering
        if is_outbound:
            # Queue for graduated release?
            if pkt_class in self._rules.get("queue_outbound", set()):
                addr_copy = copy_windivert_addr(addr)
                entry = (now, bytearray(packet_data), addr_copy, pkt_class)
                with self._queue_lock:
                    self._out_queue.append(entry)
                self._pkts_queued += 1
                return True  # consumed — released during restore

            # Hard drop?
            if pkt_class in self._rules["drop_outbound"]:
                self._pkts_dropped += 1
                return True

            self._pkts_passed += 1
            return False

        self._pkts_passed += 1
        return False

    def _handle_graduated_restore(
        self,
        packet_data: bytearray,
        addr: WINDIVERT_ADDRESS,
        pkt_class: PktClass,
        is_inbound: bool,
        is_outbound: bool,
    ) -> bool:
        """Handle packets during GRADUATED_RESTORE phase."""
        now = time.time()
        elapsed = now - self._phase_start
        restore_s = self._restore_ms / 1000.0
        frac = elapsed / restore_s if restore_s > 0 else 1.0

        # TCP always passes
        if pkt_class == PktClass.CONTROL:
            self._pkts_passed += 1
            return False

        # Phase 1 (0-25%): only keepalives, acks, TCP pass
        if frac < _RESTORE_PHASE1_FRAC:
            if pkt_class in (PktClass.KEEPALIVE, PktClass.GAME_SMALL):
                self._pkts_passed += 1
                return False
            # Still block game state during early restore
            if is_inbound and pkt_class in (PktClass.GAME_STATE, PktClass.GAME_BULK):
                self._pkts_dropped += 1
                return True
            self._pkts_passed += 1
            return False

        # Phase 2 (25-75%): + outbound game state (drip-fed by flush thread)
        if frac < _RESTORE_PHASE1_FRAC + _RESTORE_PHASE2_FRAC:
            # Outbound game state is being drip-fed by flush thread
            # New outbound passes through
            if is_outbound:
                self._pkts_passed += 1
                return False
            # Inbound game state still partially blocked
            if is_inbound and pkt_class == PktClass.GAME_BULK:
                self._pkts_dropped += 1
                return True  # still block bulk during phase 2
            self._pkts_passed += 1
            return False

        # Phase 3 (75%+): everything passes
        self._pkts_passed += 1
        return False

    # ── Stats ────────────────────────────────────────────────────────

    def get_stats(self) -> Dict:
        with self._queue_lock:
            queue_depth = len(self._out_queue)
        return {
            "phase": self._phase.value,
            "method": self._method.value,
            "current_cycle": self._current_cycle,
            "total_cycles": self._cycle_count,
            "cuts_completed": self._cuts_completed,
            "packets_dropped": self._pkts_dropped,
            "packets_passed": self._pkts_passed,
            "packets_queued": self._pkts_queued,
            "packets_keepalive": self._pkts_keepalive,
            "packets_control": self._pkts_control,
            "packets_unrelated": self._pkts_unrelated,
            "outbound_queue_depth": queue_depth,
            "rpc_detected": self._rpc_detected,
            "cut_duration_ms": self._cut_ms,
            "restore_duration_ms": self._restore_ms,
            "tick_estimator": (
                {
                    "hz": self._tick_estimator.estimated_tick_hz,
                    "ms": self._tick_estimator.estimated_tick_ms,
                    "confidence": self._tick_estimator.confidence,
                } if self._tick_estimator else None
            ),
        }

    @property
    def phase(self) -> DupePhaseV2:
        return self._phase

    @property
    def is_cutting(self) -> bool:
        return self._phase == DupePhaseV2.SELECTIVE_CUT

    @property
    def method(self) -> DupeMethod:
        return self._method

    # ── Shutdown ─────────────────────────────────────────────────────

    def stop(self) -> None:
        """Stop the dupe engine and restore normal traffic flow."""
        self._running = False
        self._phase = DupePhaseV2.IDLE

        if self._flush_thread and self._flush_thread.is_alive():
            self._flush_thread.join(timeout=1.0)

        with self._queue_lock:
            self._flush_remaining()

        log_info(
            f"DupeV2 stopped: method={self._method.value}, "
            f"cuts={self._cuts_completed}, dropped={self._pkts_dropped}, "
            f"passed={self._pkts_passed}, queued={self._pkts_queued}"
        )
