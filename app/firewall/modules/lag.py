"""Lag module — buffer packets and release after a configurable delay.

Connection preservation remains available as an explicit native extension.
When `lag_preserve_connection` is True, the module periodically passes
through small keepalive-sized packets to prevent server timeout while
maintaining the lag effect on game state packets. It is never inferred from
the delay because standalone Clumsy delays every matching packet.
"""

from __future__ import annotations

import ctypes
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
        For extended lag (>5s), periodically passes through small
        keepalive-sized packets to prevent server timeout.  Large
        game state packets remain lagged.  This allows lag durations
        of 30s+ without getting kicked.

    Parameters (via *params* dict):
        lag_delay (int): Delay in milliseconds.
            Defaults to :data:`DEFAULT_LAG_DELAY_MS`.
        lag_passthrough (bool): When ``True`` queue a copy but don't
            consume the original.  Defaults to ``False``.
        lag_preserve_connection (bool): Explicitly enable connection
            preservation for extended lag. Defaults to ``False``.
        lag_keepalive_interval_ms (int): Keepalive pass-through interval.
            Defaults to :data:`DEFAULT_LAG_KEEPALIVE_INTERVAL_MS`.
    """

    _direction_key: str = "lag"

    def __init__(self, params: dict) -> None:
        super().__init__(params)
        self._lag_queue: deque[Tuple[float, bytearray, WINDIVERT_ADDRESS]] = deque(
            maxlen=_MAX_QUEUE_SIZE
        )
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
        self._last_keepalive: float = 0.0

        # Counters
        self._keepalive_passed: int = 0
        self._total_lagged: int = 0
        self._queued: int = 0
        self._released: int = 0
        self._release_failed: int = 0

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
        self._lag_thread = threading.Thread(
            target=self._flush_loop, daemon=True, name="LagFlush"
        )
        self._lag_thread.start()

    def _flush_loop(self) -> None:
        """Continuously flush packets whose release time has arrived."""
        while self._running:
            now = time.monotonic()
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

    # ── Packet processing ────────────────────────────────────────────

    def process(
        self,
        packet_data: bytearray,
        addr: WINDIVERT_ADDRESS,
        send_fn: Callable[[bytearray, WINDIVERT_ADDRESS], bool],
    ) -> bool:
        """Queue the packet for delayed release."""
        now = time.monotonic()

        # ── Connection preservation: pass keepalive-sized packets ────
        if self._preserve and self._keepalive_interval > 0:
            if now - self._last_keepalive >= self._keepalive_interval:
                if self._is_likely_keepalive(packet_data):
                    self._last_keepalive = now
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

        with self._lag_lock:
            if len(self._lag_queue) >= _MAX_QUEUE_SIZE:
                self._lag_queue.popleft()
                self._release_failed += 1
            self._lag_queue.append(
                (release_time, bytearray(packet_data), addr_copy)
            )
            self._total_lagged += 1
            self._queued += 1

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
                "keepalive_passed": self._keepalive_passed,
                "queue_depth": len(self._lag_queue),
                "preserve_connection": self._preserve,
                "passthrough": self._passthrough,
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
            f"keepalive_passed={self._keepalive_passed}, "
            f"preserve={self._preserve}"
        )
        self._send_fn = None
