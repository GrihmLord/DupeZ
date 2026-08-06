"""Lag module — buffer packets and release after a configurable delay.

Connection preservation remains available as an explicit native extension.
When `lag_preserve_connection` is True, the module periodically passes
through small keepalive-sized packets as a best-effort connection-resilience
diagnostic.  This cannot guarantee that an application or remote server will
keep a session alive: UDP has no universal keepalive contract and server
timeouts remain external policy.  The mode is never inferred from the delay
because standalone Clumsy delays every matching packet.
"""

from __future__ import annotations

import ctypes
import math
import time
import threading
from collections import deque
from typing import Callable, Optional, Tuple

from app.firewall.native_divert_engine import DisruptionModule, WINDIVERT_ADDRESS
from app.logs.logger import log_error, log_info

__all__ = ["LagModule"]

# ── Defaults ─────────────────────────────────────────────────────────
DEFAULT_LAG_DELAY_MS: int = 1500
# Max queued packets to prevent unbounded memory growth.
_MAX_QUEUE_SIZE: int = 10_000
# Leave at least one second of recovery margin before the 30-second ceiling.
_MAX_BOUNDED_ACTIVE_MS: int = 29_000
# Flush-thread polling interval — 1 ms gives sub-frame resolution at 60 Hz.
_FLUSH_POLL_INTERVAL_S: float = 0.001

# ── Connection preservation defaults ─────────────────────────────────
# Pass one packet through every N ms to keep the connection alive.
DEFAULT_LAG_KEEPALIVE_INTERVAL_MS: int = 1500
# Packets below this size are likely keepalive probes.
_KEEPALIVE_SIZE_THRESHOLD: int = 100
class LagModule(DisruptionModule):
    """Buffer packets and release them after a delay.

    Behaviour modes (controlled by ``lag_passthrough``):

    **Consume mode** (default):
        Lag is the only disruption or is combined with drop/disconnect.
        The packet is queued and ``True`` is returned so the original does
        **not** continue through the module chain.

    **Passthrough mode** (``lag_passthrough=True``):
        Lag is stacked with duplicate/ood/corrupt for desync presets.
        A delayed *copy* is queued but ``False`` is returned so the original
        continues through the chain to be duplicated/reordered/corrupted.
        This creates the desync effect: the target receives real-time
        manipulated packets **and** a delayed echo.

    **Connection preservation** (``lag_preserve_connection=True``):
        Periodically passes through small keepalive-sized packets using
        independent inbound/outbound cadence. This is a best-effort lab
        diagnostic, not a guarantee against application/server timeouts.

    **Bounded active window** (``lag_max_active_ms`` > 0):
        Stops adding latency at the requested deadline, clamped below
        30 seconds, and fails open thereafter. Delayed backlog is released
        promptly after expiry while new traffic fails open.

    Parameters (via *params* dict):
        lag_delay (int): Delay in milliseconds.
            Defaults to :data:`DEFAULT_LAG_DELAY_MS`.
        lag_passthrough (bool): When ``True`` queue a copy but don't
            consume the original.  Defaults to ``False``.
        lag_preserve_connection (bool): Explicitly enable connection
            preservation for extended lag. Defaults to ``False``.
        lag_keepalive_interval_ms (int): Keepalive pass-through interval.
            Defaults to :data:`DEFAULT_LAG_KEEPALIVE_INTERVAL_MS`.
        lag_max_active_ms (int): Optional hard impairment window. Values are
            clamped to 29000ms; 0 keeps the ordinary manual behavior.
    """

    _direction_key: str = "lag"

    def __init__(self, params: dict) -> None:
        super().__init__(params)
        # Do not use deque(maxlen=...): it silently evicts the oldest packet.
        # Overflow is handled explicitly below and fails open for this module.
        self._lag_queue: deque[Tuple[float, bytearray, WINDIVERT_ADDRESS]] = deque()
        self._lag_lock = threading.Lock()
        self._lag_thread: Optional[threading.Thread] = None
        self._running: bool = False
        self._send_fn: Optional[
            Callable[[bytearray, WINDIVERT_ADDRESS], bool]
        ] = None
        self._passthrough: bool = params.get("lag_passthrough", False)

        # ── Connection preservation ─────────────────────────────────
        delay_ms: int = params.get("lag_delay", DEFAULT_LAG_DELAY_MS)

        # This native extension must be explicit. Inferring it from a high
        # delay silently diverges from standalone Clumsy packet semantics.
        self._preserve: bool = bool(
            params.get("lag_preserve_connection", False)
        )

        keepalive_ms: int = params.get(
            "lag_keepalive_interval_ms", DEFAULT_LAG_KEEPALIVE_INTERVAL_MS
        )
        self._keepalive_interval: float = max(0, keepalive_ms) / 1000.0
        # Keep independent cadence for each capture direction.  A single
        # shared timestamp can starve one direction under asymmetric traffic.
        self._last_keepalive = {"inbound": 0.0, "outbound": 0.0}

        try:
            requested_active_ms = float(
                params.get("lag_max_active_ms", 0) or 0
            )
        except (TypeError, ValueError):
            requested_active_ms = 0.0
        if not math.isfinite(requested_active_ms):
            requested_active_ms = 0.0
        self._max_active_ms: int = int(max(
            0,
            min(_MAX_BOUNDED_ACTIVE_MS, requested_active_ms),
        ))
        self._expires_at: float = 0.0
        self._expired: bool = False

        # Counters
        self._keepalive_passed: int = 0
        self._total_lagged: int = 0
        self._queued: int = 0
        self._released: int = 0
        self._release_failed: int = 0
        self._queue_overflow_passed: int = 0
        self._expired_backlog_released: int = 0

        if self._preserve:
            log_info(
                f"LagModule: connection preservation ACTIVE "
                f"(keepalive every {keepalive_ms}ms, lag={delay_ms}ms)"
            )

    # ── Flush thread management ──────────────────────────────────────

    def start_flush_thread(
        self,
        send_fn: Callable[[bytearray, WINDIVERT_ADDRESS], bool],
        divert_dll: object,
        handle: object,
    ) -> None:
        """Start background thread that flushes lagged packets."""
        if self._lag_thread and self._lag_thread.is_alive():
            return
        self._send_fn = send_fn
        self._running = True
        if self._max_active_ms > 0:
            self._expires_at = (
                time.monotonic() + (self._max_active_ms / 1000.0)
            )
        self._lag_thread = threading.Thread(
            target=self._flush_loop, daemon=True, name="LagFlush"
        )
        self._lag_thread.start()

    def _flush_loop(self) -> None:
        """Continuously flush packets whose release time has arrived."""
        while self._running:
            now = time.monotonic()
            if self._expire_if_needed(now):
                with self._lag_lock:
                    to_send = list(self._lag_queue)
                    self._lag_queue.clear()
                for _, pkt_data, addr in to_send:
                    if self._release_packet(pkt_data, addr, "expiry flush"):
                        with self._lag_lock:
                            self._expired_backlog_released += 1
                time.sleep(_FLUSH_POLL_INTERVAL_S)
                continue
            to_send: list[Tuple[float, bytearray, WINDIVERT_ADDRESS]] = []
            with self._lag_lock:
                while self._lag_queue and self._lag_queue[0][0] <= now:
                    to_send.append(self._lag_queue.popleft())
            for _, pkt_data, addr in to_send:
                self._release_packet(pkt_data, addr, "flush")
            time.sleep(_FLUSH_POLL_INTERVAL_S)

    def _release_packet(
        self,
        packet_data: bytearray,
        addr: WINDIVERT_ADDRESS,
        context: str,
    ) -> bool:
        """Release one queued packet and account for verified completion."""
        sender = self._send_fn
        if sender is None:
            with self._lag_lock:
                self._release_failed += 1
            return False
        try:
            released = bool(sender(packet_data, addr))
        except Exception as exc:
            released = False
            log_error(f"LagModule {context} error: {exc}")
        with self._lag_lock:
            if released:
                self._released += 1
            else:
                self._release_failed += 1
        return released

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _is_likely_keepalive(packet_data: bytearray) -> bool:
        """Heuristic: small packets are likely keepalive probes."""
        return len(packet_data) < _KEEPALIVE_SIZE_THRESHOLD

    @staticmethod
    def _capture_direction(addr: WINDIVERT_ADDRESS) -> str:
        """Return the WinDivert capture direction used for cadence isolation."""
        return "outbound" if bool(getattr(addr, "Outbound", False)) else "inbound"

    def _expire_if_needed(self, now: float) -> bool:
        """End a bounded impairment exactly once.

        New traffic immediately fails open after expiry. The flush thread then
        releases the small remaining delayed window without waiting for each
        original release timestamp.
        """
        if self._max_active_ms <= 0:
            return False

        with self._lag_lock:
            if self._expired:
                return True
            if self._expires_at <= 0.0 or now < self._expires_at:
                return False
            self._expired = True
            backlog = len(self._lag_queue)

        log_info(
            "LagModule: bounded resilience window expired; "
            f"traffic released after {self._max_active_ms}ms "
            f"(backlog_to_flush={backlog})"
        )
        return True

    # ── Packet processing ────────────────────────────────────────────

    def process(
        self,
        packet_data: bytearray,
        addr: WINDIVERT_ADDRESS,
        send_fn: Callable[[bytearray, WINDIVERT_ADDRESS], bool],
    ) -> bool:
        """Queue the packet for delayed release."""
        now = time.monotonic()

        if self._expire_if_needed(now):
            return False

        # ── Connection preservation: pass keepalive-sized packets ────
        if self._preserve and self._keepalive_interval > 0:
            capture_direction = self._capture_direction(addr)
            last_keepalive = self._last_keepalive[capture_direction]
            if now - last_keepalive >= self._keepalive_interval:
                if self._is_likely_keepalive(packet_data):
                    self._last_keepalive[capture_direction] = now
                    self._keepalive_passed += 1
                    return False  # let through immediately

        # ── Queue for delayed release ────────────────────────────────
        delay_ms: int = self.params.get("lag_delay", DEFAULT_LAG_DELAY_MS)
        release_time: float = now + (delay_ms / 1000.0)

        # Deep-copy the WinDivert address struct for deferred send
        addr_copy = WINDIVERT_ADDRESS()
        ctypes.memmove(
            ctypes.byref(addr_copy),
            ctypes.byref(addr),
            ctypes.sizeof(WINDIVERT_ADDRESS),
        )

        queue_overflow = False
        with self._lag_lock:
            if len(self._lag_queue) >= _MAX_QUEUE_SIZE:
                self._queue_overflow_passed += 1
                queue_overflow = True
            else:
                self._lag_queue.append(
                    (release_time, bytearray(packet_data), addr_copy)
                )
                self._total_lagged += 1
                self._queued += 1

        if queue_overflow:
            # Preserve connectivity under memory pressure instead of silently
            # evicting an older packet or consuming the current one.
            return False

        if self._passthrough:
            return False  # let original continue through module chain
        return True  # consume mode: original held until delay expires

    # ── Stats ────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        with self._lag_lock:
            return {
                "total_lagged": self._total_lagged,
                "queued": self._queued,
                "released": self._released,
                "release_failed": self._release_failed,
                "queue_overflow_passed": self._queue_overflow_passed,
                "keepalive_passed": self._keepalive_passed,
                "queue_depth": len(self._lag_queue),
                "preserve_connection": self._preserve,
                "passthrough": self._passthrough,
                "bounded_max_active_ms": self._max_active_ms,
                "bounded_expired": self._expired,
                "bounded_remaining_ms": max(
                    0,
                    int((self._expires_at - time.monotonic()) * 1000),
                ) if self._expires_at > 0.0 and not self._expired else 0,
                "expired_backlog_released": self._expired_backlog_released,
            }

    # ── Shutdown ─────────────────────────────────────────────────────

    def stop(self) -> None:
        """Stop flush thread and drain remaining queued packets."""
        self._running = False
        if self._lag_thread and self._lag_thread.is_alive():
            self._lag_thread.join(timeout=1.0)

        # Flush remaining queued packets so they aren't silently lost
        with self._lag_lock:
            remaining = list(self._lag_queue)
            self._lag_queue.clear()

        for _, pkt_data, addr in remaining:
            self._release_packet(pkt_data, addr, "shutdown flush")

        log_info(
            f"LagModule stopped: lagged={self._total_lagged}, "
            f"released={self._released}, "
            f"release_failed={self._release_failed}, "
            f"overflow_passed={self._queue_overflow_passed}, "
            f"keepalive_passed={self._keepalive_passed}, "
            f"preserve={self._preserve}, "
            f"bounded_expired={self._expired}"
        )
        self._send_fn = None
