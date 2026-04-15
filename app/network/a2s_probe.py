# app/network/a2s_probe.py — Source A2S server roster probe
"""External-truth oracle for cut verification and episode auto-labeling.

DayZ (and every Source-engine-derived server) answers two UDP queries on
its query port that tell us whether our character is still logged into
the hive:

* **A2S_INFO**  — returns current ``player_count``. If it drops by one
  while we're mid-cut, our session got evicted on the server side even
  though our client still thinks it's connected → classic dupe window.

* **A2S_PLAYER** — returns the roster. Some servers strip names (BE
  anti-cheat / Nitrado), but when present it's a perfect signal: name
  disappears from the list = character dropped.

The probe runs on its own thread, polls every ``interval_s`` seconds,
and publishes snapshots via a callback. The engine's cut path subscribes
to these snapshots to:

1. Flip the GUI status light GREEN (cut verified) when count drops.
2. Auto-write a ``cut_outcome`` event with ``persisted=false`` so the
   learning loop finally sees labeled episodes without the operator
   needing to press MARK DUPE SUCCESS.

Design constraints:

* **Zero cost per miss.** UDP is fire-and-forget; a missing response just
  means the server rate-limited us. We back off, we don't retry tight.
* **Never blocks the packet hot path.** All I/O on the probe thread.
* **Free tool.** No external deps — stdlib socket + struct only.
"""

from __future__ import annotations

import socket
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from app.logs.logger import log_error, log_info, log_warning

__all__ = [
    "A2SSnapshot",
    "A2SProbe",
    "query_info_once",
]

# Source query protocol magic
_HEADER_SINGLE = b"\xff\xff\xff\xff"
_HEADER_SPLIT  = b"\xfe\xff\xff\xff"
_A2S_INFO      = b"TSource Engine Query\x00"
_A2S_PLAYER    = b"U"
_S2C_CHALLENGE = 0x41  # 'A'
_S2A_INFO      = 0x49  # 'I'
_S2A_PLAYER    = 0x44  # 'D'

_DEFAULT_TIMEOUT_S = 1.0
_DEFAULT_INTERVAL_S = 1.0
_MAX_BACKOFF_S = 8.0


@dataclass(frozen=True)
class A2SSnapshot:
    """One poll result. ``reachable`` = got any response this cycle."""
    ts: float
    reachable: bool
    player_count: Optional[int]
    max_players: Optional[int]
    server_name: Optional[str]
    players: Tuple[str, ...] = field(default_factory=tuple)
    rtt_ms: Optional[float] = None
    error: Optional[str] = None


# ----------------------------------------------------------------------
# Low-level: single query helpers
# ----------------------------------------------------------------------
def _recv_single(sock: socket.socket) -> bytes:
    """Receive one packet; strip single-packet header. Returns payload
    starting with the response type byte. Raises on split packets (rare
    for small queries)."""
    data, _ = sock.recvfrom(4096)
    if data[:4] == _HEADER_SPLIT:
        raise RuntimeError("split-packet response not supported")
    if data[:4] != _HEADER_SINGLE:
        raise RuntimeError(f"bad header: {data[:4]!r}")
    return data[4:]


def _read_cstr(buf: bytes, off: int) -> Tuple[str, int]:
    end = buf.index(b"\x00", off)
    return buf[off:end].decode("utf-8", errors="replace"), end + 1


def query_info_once(
    host: str,
    port: int,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> A2SSnapshot:
    """One-shot A2S_INFO. Returns a snapshot with player_count or an
    unreachable snapshot on timeout."""
    t0 = time.time()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout_s)
    try:
        sock.sendto(_HEADER_SINGLE + _A2S_INFO, (host, port))
        payload = _recv_single(sock)

        # Some servers (Source 2008+) require a challenge even for A2S_INFO
        if payload[:1] == bytes([_S2C_CHALLENGE]):
            challenge = payload[1:5]
            sock.sendto(_HEADER_SINGLE + _A2S_INFO + challenge, (host, port))
            payload = _recv_single(sock)

        if payload[:1] != bytes([_S2A_INFO]):
            return A2SSnapshot(
                ts=time.time(), reachable=False, player_count=None,
                max_players=None, server_name=None,
                error=f"unexpected response byte 0x{payload[0]:02x}",
            )

        # Parse A2S_INFO response (goldsrc/source combined)
        off = 2  # skip type byte + protocol byte
        name, off = _read_cstr(payload, off)
        _map, off = _read_cstr(payload, off)
        _folder, off = _read_cstr(payload, off)
        _game, off = _read_cstr(payload, off)
        off += 2  # app id (short)
        players = payload[off]; off += 1
        max_players = payload[off]; off += 1
        # remaining fields (bots, server type, env, visibility, vac…) ignored

        return A2SSnapshot(
            ts=time.time(),
            reachable=True,
            player_count=int(players),
            max_players=int(max_players),
            server_name=name,
            rtt_ms=(time.time() - t0) * 1000.0,
        )
    except socket.timeout:
        return A2SSnapshot(
            ts=time.time(), reachable=False, player_count=None,
            max_players=None, server_name=None, error="timeout",
        )
    except Exception as exc:  # noqa: BLE001 — probe is best-effort
        return A2SSnapshot(
            ts=time.time(), reachable=False, player_count=None,
            max_players=None, server_name=None, error=str(exc),
        )
    finally:
        sock.close()


def _query_players_once(
    host: str, port: int, timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> Tuple[Tuple[str, ...], Optional[str]]:
    """Best-effort A2S_PLAYER. Returns (names, error). Many servers
    strip names — absence is not failure."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout_s)
    try:
        # Challenge handshake
        sock.sendto(_HEADER_SINGLE + _A2S_PLAYER + b"\xff\xff\xff\xff", (host, port))
        payload = _recv_single(sock)
        if payload[:1] != bytes([_S2C_CHALLENGE]):
            return tuple(), f"no challenge (got 0x{payload[0]:02x})"
        challenge = payload[1:5]

        sock.sendto(_HEADER_SINGLE + _A2S_PLAYER + challenge, (host, port))
        payload = _recv_single(sock)
        if payload[:1] != bytes([_S2A_PLAYER]):
            return tuple(), f"bad response (0x{payload[0]:02x})"

        count = payload[1]
        off = 2
        names: List[str] = []
        for _ in range(count):
            off += 1  # index byte
            name, off = _read_cstr(payload, off)
            off += 4 + 4  # score (long) + duration (float)
            names.append(name)
        return tuple(names), None
    except socket.timeout:
        return tuple(), "timeout"
    except Exception as exc:  # noqa: BLE001
        return tuple(), str(exc)
    finally:
        sock.close()


# ----------------------------------------------------------------------
# Probe: background polling + subscriber callbacks
# ----------------------------------------------------------------------
SnapshotCallback = Callable[[A2SSnapshot], None]


class A2SProbe:
    """Background A2S poller. Thread-safe start/stop, callback-based
    delivery. One probe per (host, port) is typical."""

    def __init__(
        self,
        host: str,
        port: int,
        interval_s: float = _DEFAULT_INTERVAL_S,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        include_roster: bool = False,
    ) -> None:
        self._host = host
        self._port = int(port)
        self._interval_s = float(interval_s)
        self._timeout_s = float(timeout_s)
        self._include_roster = bool(include_roster)

        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._subs: List[SnapshotCallback] = []
        self._latest: Optional[A2SSnapshot] = None
        self._baseline_count: Optional[int] = None

    # ------------- lifecycle -----------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name=f"A2SProbe-{self._host}:{self._port}",
            daemon=True,
        )
        self._thread.start()
        log_info(f"[A2S] probe started {self._host}:{self._port} every {self._interval_s}s")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        self._thread = None
        log_info(f"[A2S] probe stopped {self._host}:{self._port}")

    # ------------- subscribers ---------------
    def subscribe(self, cb: SnapshotCallback) -> None:
        with self._lock:
            self._subs.append(cb)

    def latest(self) -> Optional[A2SSnapshot]:
        with self._lock:
            return self._latest

    def baseline_count(self) -> Optional[int]:
        """Player count captured on the first reachable poll — use as
        the reference for drop detection."""
        return self._baseline_count

    def count_dropped(self, threshold: int = 1) -> bool:
        """True if current reachable count is below baseline by
        ``threshold`` players. Returns False if no baseline or
        currently unreachable (unreachable ≠ dropped)."""
        if self._baseline_count is None:
            return False
        snap = self.latest()
        if snap is None or not snap.reachable or snap.player_count is None:
            return False
        return snap.player_count <= (self._baseline_count - threshold)

    # ------------- thread --------------------
    def _run(self) -> None:
        backoff = self._interval_s
        while not self._stop.is_set():
            snap = query_info_once(self._host, self._port, self._timeout_s)

            roster_names: Tuple[str, ...] = tuple()
            if self._include_roster and snap.reachable:
                roster_names, roster_err = _query_players_once(
                    self._host, self._port, self._timeout_s,
                )
                if roster_err and roster_err != "timeout":
                    log_warning(f"[A2S] roster fetch: {roster_err}")
                snap = A2SSnapshot(
                    ts=snap.ts, reachable=snap.reachable,
                    player_count=snap.player_count,
                    max_players=snap.max_players,
                    server_name=snap.server_name,
                    players=roster_names,
                    rtt_ms=snap.rtt_ms,
                    error=snap.error,
                )

            with self._lock:
                self._latest = snap
                if snap.reachable and snap.player_count is not None and self._baseline_count is None:
                    self._baseline_count = snap.player_count
                    log_info(
                        f"[A2S] baseline player_count={snap.player_count} "
                        f"({snap.server_name!r})"
                    )
                subs = list(self._subs)

            for cb in subs:
                try:
                    cb(snap)
                except Exception as exc:  # noqa: BLE001
                    log_error(f"[A2S] subscriber raised: {exc}")

            # Adaptive backoff on repeated unreachable
            if snap.reachable:
                backoff = self._interval_s
            else:
                backoff = min(_MAX_BACKOFF_S, backoff * 1.5)

            # Sleep in small chunks so stop() returns promptly
            slept = 0.0
            while slept < backoff and not self._stop.is_set():
                time.sleep(min(0.2, backoff - slept))
                slept += 0.2
