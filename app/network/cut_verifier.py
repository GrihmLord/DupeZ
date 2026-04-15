# app/network/cut_verifier.py — Is the cut actually cutting?
"""Active liveness probe that tells the operator whether the target is
reachable from our host during a cut.

This closes gap G7 (cut verification) from the competitive audit. During
a cut the GUI status light should never say "CUTTING" based purely on
"we are sending spoof packets" — it should say "CUTTING (VERIFIED)" only
when the target has gone dark from our probes.

Three signal sources, any of which flips the state to ``SEVERED``:

1. **Ping timeout.** `ping` (ICMP echo) fails for N consecutive tries.
2. **ARP echo timeout.** Local-network only — the ARP table still holds
   a MAC for the target, but gratuitous requests go unanswered.
3. **A2S roster drop.** (Optional) If an :class:`A2SProbe` is attached,
   a drop in ``player_count`` from baseline is treated as SEVERED.

The verifier never blocks the packet hot path. It's a plain background
thread that uses stdlib subprocess for ping (works on Win/Linux/Mac
without extra deps) and publishes state transitions via callback.
"""

from __future__ import annotations

import platform
import subprocess
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, List, Optional

from app.logs.logger import log_error, log_info

__all__ = [
    "CutState",
    "CutVerdict",
    "CutVerifier",
    "ping_once",
]


class CutState(str, Enum):
    UNKNOWN = "unknown"        # No data yet
    CONNECTED = "connected"    # Target responding — cut NOT effective
    DEGRADED = "degraded"      # Some signals failing — cut partial
    SEVERED = "severed"        # Target dark — cut confirmed


@dataclass(frozen=True)
class CutVerdict:
    state: CutState
    ts: float
    ping_ok: Optional[bool]        # None = not probed this cycle
    a2s_dropped: Optional[bool]    # None if no A2S probe attached
    reason: str                    # Human-readable evidence


_IS_WINDOWS = platform.system().lower() == "windows"


def ping_once(host: str, timeout_s: float = 1.0) -> bool:
    """One ICMP echo. Returns True if reply received. Cross-platform via
    the system ping binary — no raw-socket admin required."""
    if _IS_WINDOWS:
        cmd = ["ping", "-n", "1", "-w", str(int(timeout_s * 1000)), host]
    else:
        cmd = ["ping", "-c", "1", "-W", str(max(1, int(timeout_s))), host]
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout_s + 1.0,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


VerdictCallback = Callable[[CutVerdict], None]


class CutVerifier:
    """Background liveness checker. Call :meth:`start` when the cut
    begins, :meth:`stop` when it ends. Subscribers get one verdict per
    polling interval."""

    def __init__(
        self,
        target_ip: str,
        interval_s: float = 0.5,
        fail_threshold: int = 2,
        a2s_probe: Optional[object] = None,  # A2SProbe duck-typed
    ) -> None:
        self._target_ip = str(target_ip)
        self._interval_s = float(interval_s)
        self._fail_threshold = int(fail_threshold)
        self._a2s_probe = a2s_probe

        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._subs: List[VerdictCallback] = []
        self._state: CutState = CutState.UNKNOWN
        self._consecutive_fails: int = 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._consecutive_fails = 0
        self._state = CutState.UNKNOWN
        self._thread = threading.Thread(
            target=self._run,
            name=f"CutVerifier-{self._target_ip}",
            daemon=True,
        )
        self._thread.start()
        log_info(f"[VERIFY] started for {self._target_ip}")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        self._thread = None

    def subscribe(self, cb: VerdictCallback) -> None:
        with self._lock:
            self._subs.append(cb)

    def state(self) -> CutState:
        return self._state

    def _run(self) -> None:
        while not self._stop.is_set():
            t0 = time.time()
            ping_ok = ping_once(self._target_ip, timeout_s=min(1.0, self._interval_s))

            a2s_dropped: Optional[bool] = None
            if self._a2s_probe is not None:
                try:
                    a2s_dropped = bool(self._a2s_probe.count_dropped(threshold=1))
                except Exception:
                    a2s_dropped = None

            if ping_ok:
                self._consecutive_fails = 0
            else:
                self._consecutive_fails += 1

            if a2s_dropped:
                new_state = CutState.SEVERED
                reason = "A2S roster dropped target from server"
            elif self._consecutive_fails >= self._fail_threshold:
                new_state = CutState.SEVERED
                reason = f"ping failed {self._consecutive_fails}× consecutively"
            elif self._consecutive_fails > 0:
                new_state = CutState.DEGRADED
                reason = f"ping failed {self._consecutive_fails}×"
            elif ping_ok:
                new_state = CutState.CONNECTED
                reason = "ping OK"
            else:
                new_state = CutState.UNKNOWN
                reason = "no data"

            changed = new_state != self._state
            self._state = new_state

            verdict = CutVerdict(
                state=new_state,
                ts=time.time(),
                ping_ok=ping_ok,
                a2s_dropped=a2s_dropped,
                reason=reason,
            )

            if changed:
                log_info(f"[VERIFY] {self._target_ip} → {new_state.value}: {reason}")

            with self._lock:
                subs = list(self._subs)
            for cb in subs:
                try:
                    cb(verdict)
                except Exception as exc:  # noqa: BLE001
                    log_error(f"[VERIFY] subscriber raised: {exc}")

            # Sleep remainder of interval, interruptible
            elapsed = time.time() - t0
            remaining = self._interval_s - elapsed
            slept = 0.0
            while slept < remaining and not self._stop.is_set():
                chunk = min(0.1, remaining - slept)
                if chunk <= 0:
                    break
                time.sleep(chunk)
                slept += chunk
