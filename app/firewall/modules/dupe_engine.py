"""Dupe Engine — precise timed disconnect-reconnect for inventory duplication.

DayZ Inventory Duplication Mechanics
─────────────────────────────────────
DayZ uses a client-authoritative-ish inventory system where the client
proposes an inventory action and the server validates + persists it.
The replication flow for an item transfer (e.g. ground → inventory):

  1. Client sends RPC: "I'm picking up item X at position P"
  2. Server validates: item exists, in range, not locked by another player
  3. Server applies: removes item from ground, adds to player inventory
  4. Server replicates: sends state update to all nearby clients
  5. Server persists: writes to persistence storage (hive) on next save

The duplication window exists between steps 3 and 5.  If the client's
network connection drops AFTER the server has applied the action but
BEFORE the next persistence save, two outcomes race:

  A. Server rollback: server detects disconnect, rolls back the player's
     state to last persisted snapshot → item appears back on ground
  B. Persistence race: if the server happens to persist DURING the
     disconnect window, the item is in the player's inventory AND the
     ground state rolls back to pre-pickup → item exists in both places

The key parameters:
  - Server persistence interval: typically 5-15 minutes (configurable)
  - Disconnect grace period: ~30s before server removes the player entity
  - Item transfer RPC → server apply latency: 50-200ms
  - Reconnect window: must reconnect before player entity is destroyed

This module implements a three-phase cycle:
  Phase 1 (PREP):    Normal traffic — perform the inventory action
  Phase 2 (CUT):     Hard network cut — block ALL traffic both directions
  Phase 3 (RESTORE): Reconnect — allow all traffic, player reconnects

The CUT duration must be:
  - Long enough: server processes the action but can't replicate confirmation
  - Short enough: stay within the disconnect grace period (~30s)
  - Optimal: 3-8 seconds for most servers

For the "drop and pick" method:
  1. Drop item on ground (outbound RPC reaches server)
  2. Wait for server to process (the `dupe_action_delay_ms`)
  3. CUT network (this module activates)
  4. During cut: item is on ground (server state) AND player has the
     item (server just processed the drop but hasn't replicated confirmation
     of the removal from inventory)
  5. RESTORE: player reconnects, server reconciles — depending on
     timing, the item may exist in both locations

For "swap" method:
  1. Have item in hand, approach container
  2. Initiate swap via drag (outbound RPC)
  3. CUT network after `dupe_action_delay_ms`
  4. During cut: server may have applied the swap partially
  5. RESTORE: server reconciles partial state → possible duplication

Implementation:
  This module registers as a DisruptionModule with direction=BOTH.
  When activated, it runs a state machine:
    IDLE → PREP → CUT → RESTORE → IDLE

  The transition from PREP→CUT is triggered either by:
    a) Timer: after `dupe_prep_duration_ms` (manual timing)
    b) Signal: external call to `trigger_cut()` (UI button or voice command)

  During CUT phase, ALL packets in BOTH directions are silently dropped.
  During RESTORE, all packets pass through normally.
"""

from __future__ import annotations

import enum
import time
import threading
from typing import Callable, Dict, Optional

from app.firewall.native_divert_engine import (
    DisruptionModule,
    WINDIVERT_ADDRESS,
    DIR_BOTH,
)
from app.logs.logger import log_info, log_error

__all__ = ["DupePhase", "DupeEngineModule"]

# ── Defaults ─────────────────────────────────────────────────────────
# How long after activation before the network cut (ms).
# Set to 0 for immediate cut (use trigger_cut() for manual timing).
DEFAULT_PREP_DURATION_MS: int = 0
# How long to hold the network cut (ms).
# 5 seconds is the sweet spot: long enough for server to process the
# action, short enough to stay within disconnect grace.
DEFAULT_CUT_DURATION_MS: int = 5000
# Minimum cut duration safety floor (ms).
_MIN_CUT_MS: int = 1000
# Maximum cut duration safety ceiling (ms) — exceeding 25s risks
# server removing the player entity entirely.
_MAX_CUT_MS: int = 25000
# Auto-restore: automatically transition from CUT→RESTORE after duration.
DEFAULT_AUTO_RESTORE: bool = True
# Number of rapid cycles for multi-attempt duplication.
DEFAULT_CYCLE_COUNT: int = 1
# Delay between cycles for multi-attempt (ms).
DEFAULT_CYCLE_DELAY_MS: int = 2000


class DupePhase(enum.Enum):
    """State machine phases for the dupe engine."""
    IDLE = "idle"
    PREP = "prep"
    CUT = "cut"
    RESTORE = "restore"


class DupeEngineModule(DisruptionModule):
    """Precise timed disconnect-reconnect for inventory duplication.

    Operates as a state machine. When the module is in the active
    method list and the engine is running, it starts in IDLE state
    and transitions through PREP → CUT → RESTORE → IDLE.

    In CUT state, ALL packets (both directions) are dropped.
    In all other states, packets pass through normally.

    Trigger methods:
      1. Timer-based: set `dupe_prep_duration_ms` > 0, module auto-
         transitions PREP→CUT after that delay.
      2. Manual: call `trigger_cut()` from UI/voice to immediately
         enter CUT phase.  Set `dupe_prep_duration_ms` = 0.
      3. Auto-cycle: set `dupe_cycle_count` > 1 for automatic
         repeated CUT cycles (for retry reliability).

    Parameters (via *params* dict):
        dupe_prep_duration_ms (int): Time in PREP before auto-cut.
            0 = manual trigger only.
        dupe_cut_duration_ms (int): How long to hold the network cut.
            Defaults to :data:`DEFAULT_CUT_DURATION_MS`.
        dupe_auto_restore (bool): Auto-restore after cut duration.
            Defaults to True.
        dupe_cycle_count (int): Number of cut cycles per activation.
            Defaults to 1.
        dupe_cycle_delay_ms (int): Delay between cycles.
            Defaults to :data:`DEFAULT_CYCLE_DELAY_MS`.
        dupe_action_delay_ms (int): Delay after PREP before CUT starts,
            to allow the inventory RPC to reach the server.
            Merged into prep_duration if prep_duration > 0.
    """

    _direction_key: str = "dupe"

    def __init__(self, params: dict) -> None:
        super().__init__(params)
        self.direction = DIR_BOTH

        self._phase: DupePhase = DupePhase.IDLE
        self._phase_lock = threading.Lock()
        self._phase_start: float = 0.0

        # Timing configuration
        self._prep_ms: int = max(0,
            params.get("dupe_prep_duration_ms", DEFAULT_PREP_DURATION_MS))
        self._cut_ms: int = max(_MIN_CUT_MS, min(_MAX_CUT_MS,
            params.get("dupe_cut_duration_ms", DEFAULT_CUT_DURATION_MS)))
        self._auto_restore: bool = params.get(
            "dupe_auto_restore", DEFAULT_AUTO_RESTORE)
        self._cycle_count: int = max(1,
            params.get("dupe_cycle_count", DEFAULT_CYCLE_COUNT))
        self._cycle_delay_ms: int = max(0,
            params.get("dupe_cycle_delay_ms", DEFAULT_CYCLE_DELAY_MS))

        # Action delay — additional wait after prep to let RPC reach server
        action_delay: int = max(0,
            params.get("dupe_action_delay_ms", 0))
        if action_delay > 0 and self._prep_ms > 0:
            self._prep_ms += action_delay

        # State tracking
        self._current_cycle: int = 0
        self._packets_dropped: int = 0
        self._packets_passed: int = 0
        self._cuts_completed: int = 0

        # Background thread for auto-transitions
        self._timer_thread: Optional[threading.Thread] = None
        self._running: bool = True

        log_info(
            f"DupeEngine initialized: prep={self._prep_ms}ms, "
            f"cut={self._cut_ms}ms, auto_restore={self._auto_restore}, "
            f"cycles={self._cycle_count}"
        )

    # ── State machine control ────────────────────────────────────────

    def activate(self) -> None:
        """Begin the dupe sequence.  Transitions IDLE → PREP (or CUT)."""
        with self._phase_lock:
            if self._phase != DupePhase.IDLE:
                log_info(f"DupeEngine: already in {self._phase.value}, ignoring activate")
                return
            self._current_cycle = 0
            self._start_cycle()

    def _start_cycle(self) -> None:
        """Start a single PREP→CUT→RESTORE cycle."""
        self._current_cycle += 1
        if self._prep_ms > 0:
            self._transition(DupePhase.PREP)
            # Auto-transition to CUT after prep duration
            self._schedule_transition(
                DupePhase.CUT, self._prep_ms / 1000.0
            )
        else:
            # No prep — go straight to waiting for manual trigger
            # or immediate CUT if auto
            self._transition(DupePhase.PREP)
            log_info("DupeEngine: in PREP — call trigger_cut() to cut network")

    def trigger_cut(self) -> None:
        """Manually trigger the network cut.  Transitions PREP → CUT."""
        with self._phase_lock:
            if self._phase != DupePhase.PREP:
                log_info(f"DupeEngine: not in PREP (in {self._phase.value}), "
                         "ignoring trigger_cut")
                return
            self._do_cut()

    def _do_cut(self) -> None:
        """Enter CUT phase — block all traffic."""
        self._transition(DupePhase.CUT)
        log_info(f"DupeEngine: NETWORK CUT — cycle {self._current_cycle}/{self._cycle_count}, "
                 f"duration={self._cut_ms}ms")
        if self._auto_restore:
            self._schedule_transition(
                DupePhase.RESTORE, self._cut_ms / 1000.0
            )

    def trigger_restore(self) -> None:
        """Manually restore the network.  Transitions CUT → RESTORE."""
        with self._phase_lock:
            if self._phase != DupePhase.CUT:
                return
            self._do_restore()

    def _do_restore(self) -> None:
        """Enter RESTORE phase — allow all traffic."""
        self._transition(DupePhase.RESTORE)
        self._cuts_completed += 1
        log_info(f"DupeEngine: NETWORK RESTORED — "
                 f"cycle {self._current_cycle}/{self._cycle_count}")

        # Check if more cycles remain
        if self._current_cycle < self._cycle_count:
            self._schedule_transition(
                None,  # custom handler
                self._cycle_delay_ms / 1000.0,
                callback=self._next_cycle,
            )
        else:
            # All cycles complete — transition to IDLE after brief settle
            self._schedule_transition(DupePhase.IDLE, 1.0)

    def _next_cycle(self) -> None:
        """Start the next dupe cycle."""
        with self._phase_lock:
            if self._phase == DupePhase.RESTORE:
                self._start_cycle()

    def _transition(self, phase: DupePhase) -> None:
        """Transition to a new phase."""
        old = self._phase
        self._phase = phase
        self._phase_start = time.time()
        log_info(f"DupeEngine: {old.value} → {phase.value}")

    def _schedule_transition(
        self,
        target_phase: Optional[DupePhase],
        delay_s: float,
        callback: Optional[Callable] = None,
    ) -> None:
        """Schedule a phase transition after a delay."""
        def _worker() -> None:
            time.sleep(delay_s)
            if not self._running:
                return
            with self._phase_lock:
                if callback:
                    callback()
                elif target_phase == DupePhase.CUT:
                    self._do_cut()
                elif target_phase == DupePhase.RESTORE:
                    self._do_restore()
                elif target_phase == DupePhase.IDLE:
                    self._transition(DupePhase.IDLE)
                    log_info(f"DupeEngine: all {self._cycle_count} cycles complete, "
                             f"dropped={self._packets_dropped}")

        t = threading.Thread(target=_worker, daemon=True, name="DupeTimer")
        t.start()

    # ── Packet processing ────────────────────────────────────────────

    def process(
        self,
        packet_data: bytearray,
        addr: WINDIVERT_ADDRESS,
        send_fn: Callable[[bytearray, WINDIVERT_ADDRESS], None],
    ) -> bool:
        """Drop all packets during CUT phase, pass through otherwise."""
        if self._phase == DupePhase.CUT:
            self._packets_dropped += 1
            return True  # drop
        self._packets_passed += 1
        return False  # pass through

    # ── Stats ────────────────────────────────────────────────────────

    def get_stats(self) -> Dict:
        return {
            "phase": self._phase.value,
            "current_cycle": self._current_cycle,
            "total_cycles": self._cycle_count,
            "cuts_completed": self._cuts_completed,
            "packets_dropped": self._packets_dropped,
            "packets_passed": self._packets_passed,
            "cut_duration_ms": self._cut_ms,
        }

    @property
    def phase(self) -> DupePhase:
        return self._phase

    @property
    def is_cutting(self) -> bool:
        return self._phase == DupePhase.CUT

    # ── Shutdown ─────────────────────────────────────────────────────

    def stop(self) -> None:
        """Stop the dupe engine and restore normal traffic flow."""
        self._running = False
        self._phase = DupePhase.IDLE
        log_info(
            f"DupeEngine stopped: cuts={self._cuts_completed}, "
            f"dropped={self._packets_dropped}, passed={self._packets_passed}"
        )
