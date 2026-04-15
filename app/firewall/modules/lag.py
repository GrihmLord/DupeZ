"""Lag module — buffer packets and release after a configurable delay.

v5.2: Added connection preservation mode for extended lag durations.
When `lag_preserve_connection` is True, the module periodically passes
through small keepalive-sized packets to prevent server timeout while
maintaining the lag effect on game state packets.
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
# Maximum lag delay before connection preservation auto-activates (ms).
# Below this threshold, normal lag works fine without preservation.
_PRESERVE_AUTO_THRESHOLD_MS: int = 5000


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
        lag_preserve_connection (bool): Enable connection preservation
            for extended lag.  Auto-activates when lag_delay > 5000ms.
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
        self._running: bool = True
        self._send_fn: Optional[Callable[[bytearray, WINDIVERT_ADDRESS], None]] = None
        self._passthrough: bool = params.get("lag_passthrough", False)

        # ── Connection preservation ─────────────────────────────────
        delay_ms: int = params.get("lag_delay", DEFAULT_LAG_DELAY_MS)

        # Auto-activate preservation for high lag values
        auto_preserve = delay_ms >= _PRESERVE_AUTO_THRESHOLD_MS
        self._preserve: bool = params.get(
            "lag_preserve_connection", auto_preserve
        )

        keepalive_ms: int = params.get(
            "lag_keepalive_interval_ms", DEFAULT_LAG_KEEPALIVE_INTERVAL_MS
        )
        self._keepalive_interval: float = max(0, keepalive_ms) / 1000.0
        self._last_keepalive: float = 0.0

        # Counters
        self._keepalive_passed: int = 0
        self._total_lagged: int = 0

        if self._preserve:
            log_info(
                f"LagModule: connection preservation ACTIVE "
                f"(keepalive every {keepalive_ms}ms, lag={delay_ms}ms)"
            )

    # ── Flush thread management ──────────────────────────────────────

    def start_flush_thread(
        self,
        send_fn: Callable[[bytearray, WINDIVERT_ADDRESS], None],
        divert_dll: object,
        handle: object,
    ) -> None:
        """Start background thread that flushes lagged packets."""
        self._send_fn = send_fn
        self._lag_thread = threading.Thread(
            target=self._flush_loop, daemon=True, name="LagFlush"
        )
        self._lag_thread.start()

    def _flush_loop(self) -> None:
        """Continuously flush packets whose release time has arrived."""
        while self._running:
            now = time.time()
            to_send: list[Tuple[float, bytearray, WINDIVERT_ADDRESS]] = []
            with self._lag_lock:
                while self._lag_queue and self._lag_queue[0][0] <= now:
                    to_send.append(self._lag_queue.popleft())
            for _, pkt_data, addr in to_send:
                try:
                    self._send_fn(pkt_data, addr)  # type: ignore[misc]
                except Exception as exc:
                    log_error(f"LagModule flush error: {exc}")
            time.sleep(_FLUSH_POLL_INTERVAL_S)

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
        send_fn: Callable[[bytearray, WINDIVERT_ADDRESS], None],
    ) -> bool:
        """Queue the packet for delayed release."""
        now = time.time()

        # ── Connection preservation: pass keepalive-sized packets ────
        if self._preserve and self._keepalive_interval > 0:
            if now - self._last_keepalive >= self._keepalive_interval:
                if self._is_likely_keepalive(packet_data):
                    self._last_keepalive = now
                    self._keepalive_passed += 1
                    return False  # let through immediately

        # ── Queue for delayed release ────────────────────────────────
        self._total_lagged += 1
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
            self._lag_queue.append(
                (release_time, bytearray(packet_data), addr_copy)
            )

        if self._passthrough:
            return False  # let original continue through module chain
        return True  # consume mode: original held until delay expires

    # ── Stats ────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        with self._lag_lock:
            queue_depth = len(self._lag_queue)
        return {
            "total_lagged": self._total_lagged,
            "keepalive_passed": self._keepalive_passed,
            "queue_depth": queue_depth,
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

        if self._send_fn:
            flush_errors: int = 0
            for _, pkt_data, addr in remaining:
                try:
                    self._send_fn(pkt_data, addr)
                except Exception as exc:
                    flush_errors += 1
                    if flush_errors <= 3:
                        log_error(f"LagModule: shutdown flush failed ({len(pkt_data)}B): {exc}")
            if flush_errors > 3:
                log_error(f"LagModule: {flush_errors} total shutdown flush failures")

        log_info(
            f"LagModule stopped: lagged={self._total_lagged}, "
            f"keepalive_passed={self._keepalive_passed}, "
            f"preserve={self._preserve}"
        )
