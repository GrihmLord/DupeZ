"""Disconnect module — stateful cut-with-timer as the primary dupe vector.

State machine:
    ARMED   → arm delay counting down, packets pass through untouched
    CUTTING → hard drop per disconnect_chance (bidirectional)
    DONE    → cut duration elapsed, packets pass through again

When *disconnect_duration_ms* is 0 (default legacy behavior) the module
stays in CUTTING forever after the arm delay — matches the previous
"drop everything until you turn it off" semantics.

When *disconnect_duration_ms* > 0 the module auto-transitions to DONE
after the cut elapses, so the session can reconnect on its own without
the operator having to tear down the engine. This is the shape the
Week 1 sprint needs: arm → cut for N seconds → release, all driven by
the module itself.

Parameters (via *params* dict):
    disconnect_chance       (int):   Drop probability 0-100. Default 100.
    disconnect_duration_ms  (float): Cut length in ms. 0 = forever.
    disconnect_arm_delay_ms (float): Pre-cut pass-through window in ms.
    disconnect_direction    (str):   "both" | "inbound" | "outbound".

Stats exposed on the instance (read-only for telemetry):
    state              — current phase (str)
    packets_dropped    — total drops this activation
    packets_passed     — total pass-throughs
    cut_started_at     — monotonic ts cut entered (0 if never)
    cut_ended_at       — monotonic ts cut left    (0 if still cutting)
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Any, Callable, Optional

from app.firewall.native_divert_engine import DisruptionModule

if TYPE_CHECKING:
    from app.firewall.native_divert_engine import WINDIVERT_ADDRESS

# Optional event sink: engine injects a callable of the shape
# ``record_event(name, **payload)`` (see EpisodeRecorder.record_event).
# Never raises — errors are swallowed in ``_emit``.
EventSink = Callable[..., None]

__all__ = [
    "DisconnectModule",
    "STATE_ARMED",
    "STATE_CUTTING",
    "STATE_QUIET",
    "STATE_DONE",
]

# Default disconnect probability — true 100 % with zero leakage.
DEFAULT_DISCONNECT_CHANCE: int = 100

# State labels — plain strings so they serialize cleanly for telemetry.
STATE_ARMED: str = "armed"
STATE_CUTTING: str = "cutting"
STATE_QUIET: str = "quiet"  # post-cut inbound-only drop window
STATE_DONE: str = "done"


class DisconnectModule(DisruptionModule):
    """Primary dupe vector — stateful bidirectional hard disconnect.

    Back-compat: with default params (``disconnect_duration_ms == 0``,
    ``disconnect_arm_delay_ms == 0``) this behaves identically to the
    legacy one-shot 100 %-drop module — every packet is dropped the
    moment the engine starts.

    Opt-in to the timed cut by setting ``disconnect_duration_ms`` > 0
    and, optionally, an arm delay to line up with a server tick or
    combat-log window.
    """

    _direction_key: str = "disconnect"

    def __init__(self, params: dict) -> None:
        super().__init__(params)

        chance = params.get("disconnect_chance", DEFAULT_DISCONNECT_CHANCE)
        try:
            self._chance: int = max(0, min(100, int(chance)))
        except (TypeError, ValueError):
            self._chance = DEFAULT_DISCONNECT_CHANCE

        duration_ms = params.get("disconnect_duration_ms", 0) or 0
        arm_delay_ms = params.get("disconnect_arm_delay_ms", 0) or 0
        quiet_ms = params.get("disconnect_quiet_after_ms", 0) or 0
        self._duration_s: float = max(0.0, float(duration_ms)) / 1000.0
        self._arm_delay_s: float = max(0.0, float(arm_delay_ms)) / 1000.0
        # Post-cut quiet window: continue dropping *inbound* packets for
        # this long after CUTTING ends. Prevents the server's buffered
        # clean-logout ACK from committing state after release.
        self._quiet_s: float = max(0.0, float(quiet_ms)) / 1000.0

        self._lock = threading.Lock()
        self._armed_at: float = time.monotonic()
        self._cut_started_at: float = 0.0
        self._cut_ended_at: float = 0.0
        self._quiet_started_at: float = 0.0

        if self._arm_delay_s > 0:
            self.state: str = STATE_ARMED
        else:
            self.state = STATE_CUTTING
            self._cut_started_at = self._armed_at

        self.packets_dropped: int = 0
        self.packets_passed: int = 0

        self._event_sink: "EventSink | None" = None

        # Fire the initial state event so recorders capture the exact
        # moment the cut starts (or the arm delay begins).
        self._emit(self.state)

    # ── wiring ───────────────────────────────────────────────────────
    def attach_event_sink(self, sink: "EventSink | None") -> None:
        """Register an optional state-transition callback (engine uses this).

        If the module is already in ``CUTTING`` when the sink attaches —
        which happens whenever ``arm_delay_ms == 0`` because the module
        transitions in ``__init__`` before the engine can wire the
        recorder — we replay a ``cut_start`` event so the episode has a
        label. Without this every default-configured cut would be
        unlabeled.
        """
        self._event_sink = sink
        if sink is None:
            return
        if self.state == STATE_CUTTING:
            self._emit("cut_start")

    def _emit(self, event: str, **extra: Any) -> None:
        sink = self._event_sink
        if sink is None:
            return
        try:
            payload = self.stats()
            if extra:
                payload.update(extra)
            sink(event, **payload)
        except Exception:
            # Never let telemetry break the hot path.
            pass

    # ── telemetry helpers ─────────────────────────────────────────────
    def stats(self) -> dict:
        """Snapshot of module state for logging / UI."""
        with self._lock:
            return {
                "state": self.state,
                "dropped": self.packets_dropped,
                "passed": self.packets_passed,
                "cut_started_at": self._cut_started_at,
                "cut_ended_at": self._cut_ended_at,
                "chance": self._chance,
                "duration_s": self._duration_s,
                "arm_delay_s": self._arm_delay_s,
                "quiet_s": self._quiet_s,
            }

    def force_cut_end(self, persisted: Optional[bool] = None) -> None:
        """Externally terminate an in-progress cut — used by the engine on
        shutdown so open-ended cuts (``duration_ms == 0``) still emit a
        ``cut_end`` label.

        If the caller knows the operational outcome (``persisted=True``
        means the hive flushed and the dupe failed, ``False`` means the
        cut prevented persistence and the dupe succeeded), pass it
        through — the survival trainer uses it as the event label.
        """
        fired = False
        with self._lock:
            if self.state == STATE_CUTTING:
                self.state = STATE_DONE
                self._cut_ended_at = time.monotonic()
                fired = True
        if fired:
            extra = {} if persisted is None else {"persisted": bool(persisted)}
            self._emit("cut_end", **extra)

    def reset(self) -> None:
        """Re-arm the module (used by UI 'restart cut' action)."""
        with self._lock:
            self._armed_at = time.monotonic()
            self._cut_started_at = 0.0
            self._cut_ended_at = 0.0
            self.packets_dropped = 0
            self.packets_passed = 0
            if self._arm_delay_s > 0:
                self.state = STATE_ARMED
            else:
                self.state = STATE_CUTTING
                self._cut_started_at = self._armed_at

    # ── hot path ──────────────────────────────────────────────────────
    def process(
        self,
        packet_data: bytearray,
        addr: WINDIVERT_ADDRESS,
        send_fn: Callable[[bytearray, WINDIVERT_ADDRESS], None],
    ) -> bool:
        """Return ``True`` to consume (drop) the packet."""
        now = time.monotonic()

        # Fast path: terminal state — never touch packets again.
        if self.state == STATE_DONE:
            self.packets_passed += 1
            return False

        # ARMED → CUTTING transition.
        if self.state == STATE_ARMED:
            if now - self._armed_at >= self._arm_delay_s:
                fired = False
                with self._lock:
                    if self.state == STATE_ARMED:
                        self.state = STATE_CUTTING
                        self._cut_started_at = now
                        fired = True
                if fired:
                    self._emit("cut_start")
            else:
                self.packets_passed += 1
                return False

        # CUTTING → QUIET/DONE transition (only when a duration was configured).
        if (
            self.state == STATE_CUTTING
            and self._duration_s > 0
            and now - self._cut_started_at >= self._duration_s
        ):
            next_state = STATE_QUIET if self._quiet_s > 0 else STATE_DONE
            fired = False
            with self._lock:
                if self.state == STATE_CUTTING:
                    self.state = next_state
                    self._cut_ended_at = now
                    if next_state == STATE_QUIET:
                        self._quiet_started_at = now
                    fired = True
            if fired:
                self._emit("cut_end")
                if next_state == STATE_QUIET:
                    self._emit("quiet_start")

        # QUIET → DONE transition.
        if (
            self.state == STATE_QUIET
            and now - self._quiet_started_at >= self._quiet_s
        ):
            fired = False
            with self._lock:
                if self.state == STATE_QUIET:
                    self.state = STATE_DONE
                    fired = True
            if fired:
                self._emit("quiet_end")
            self.packets_passed += 1
            return False

        # QUIET: drop inbound only, let outbound through so the client
        # can start reconnecting immediately — the server just can't
        # answer with a clean-logout ACK.
        if self.state == STATE_QUIET:
            if getattr(addr, "Outbound", 0):
                self.packets_passed += 1
                return False
            if self._roll(self._chance):
                self.packets_dropped += 1
                return True
            self.packets_passed += 1
            return False

        # Active cut — roll the drop dice.
        if self._roll(self._chance):
            self.packets_dropped += 1
            return True

        self.packets_passed += 1
        return False
