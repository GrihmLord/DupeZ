"""WiFi adapter detection + AP-isolation watchdog for DupeZ.

When a target is on the same WiFi /24 as the operator and ARP spoof is
needed to redirect traffic, the spoof can silently fail on consumer APs
that have client isolation enabled (Eero, Google Nest, ISP gateways,
guest/public networks). The spoofer reports "active" because Npcap-level
packet emission succeeded, but no station-to-station L2 frames reach the
target — the AP drops them. Symptom: WinDivert FORWARD layer opens fine,
captures zero packets, every cut is a no-op.

v5.6.4 stopped lying about success on Npcap-missing / spoofer-start
failures. v5.6.5 closes the harder case: spoof started cleanly, AP is
silently dropping it. We do this with a watchdog that observes the
ArpSpoofer's outbound packet counter and the NativeWinDivertEngine's
inbound counter for a few seconds after start. When the gap reveals
isolation (we're emitting poison, but no forwarded traffic is materializing),
the watchdog invokes a callback so the orchestrator can fall back to
self-disrupt mode (NETWORK layer, drops operator's own egress to target).

Self-disrupt is honest: it can only affect what the operator's own
machine sends to / receives from the target — not the target's traffic
to / from third parties. For "lag my own connection to <peer/server>"
use cases (which is what most WiFi-on-WiFi DayZ duping actually needs),
self-disrupt is sufficient. For "block another player's connection",
nothing client-side will work behind AP isolation; that requires either
a managed switch or being upstream of the AP.

Public API:

    is_local_adapter_wifi() -> bool
        True if the adapter handling the default route appears to be
        IEEE 802.11. Used for pre-flight branching and user messaging.
        Best-effort: matches adapter name against a known wordlist; on
        non-English Windows locales may return False even on WiFi.

    IsolationWatchdog(spoofer, engine, on_isolation_detected, ...)
        Spawns a daemon thread that fires the callback once if, after
        `grace_s` seconds, the engine has processed zero packets while
        the spoofer has emitted > 0. Safe to construct + start before
        the engine begins seeing traffic — the watchdog samples the
        live counters at check time, not at construction.
"""

from __future__ import annotations

import socket
import threading
import time
from typing import Any, Callable, Optional

# Lazy imports for psutil / log — module must be importable in test
# environments without these. Logging falls back to stderr.

try:
    from app.logs.unified_logger import log_info, log_warning, log_error
except Exception:  # pragma: no cover — fallback for standalone use
    import sys
    def log_info(msg: str) -> None: print(f"[INFO] {msg}", file=sys.stderr)
    def log_warning(msg: str) -> None: print(f"[WARN] {msg}", file=sys.stderr)
    def log_error(msg: str) -> None: print(f"[ERR] {msg}", file=sys.stderr)


# ── WiFi adapter detection ───────────────────────────────────────────

# Substrings that indicate a WiFi adapter on Windows (and common Linux /
# Mac patterns for hypothetical future cross-platform support). Match is
# case-insensitive. Order doesn't matter — first hit wins.
_WIFI_NAME_INDICATORS = (
    "wi-fi",
    "wifi",
    "wireless",
    "wlan",
    "802.11",
    "airport",     # macOS
)


def is_local_adapter_wifi() -> bool:
    """Return True if the adapter handling the default route is WiFi.

    Method: open a UDP socket to a non-routable destination, read which
    local IP the OS would use (this is the default-route adapter — no
    packets are actually sent because UDP connect is stateless), then
    walk ``psutil.net_if_addrs()`` to find the adapter NAME bound to
    that IP, and check the name against ``_WIFI_NAME_INDICATORS``.

    Returns False on any error or if psutil is unavailable. The safer
    default is "not WiFi" — it means we don't show WiFi-specific
    warnings to a wired user; the existing flow handles both cases.

    Notes:
      - This is a heuristic. It will miss non-English Windows locales
        that name the adapter (e.g.) "Sans fil" or "Drahtlos". For
        v5.6.5 we accept that and rely on the IsolationWatchdog (which
        observes actual packet behavior, not adapter labels) as the
        ground-truth detector.
      - Hotspot mode users: the adapter handling traffic to a hotspot
        client is the ICS host adapter (often a virtual one named like
        "Local Area Connection*"). This probe correctly returns False
        for them, which is what we want — hotspot mode doesn't need
        ARP spoof and isn't affected by AP isolation.
    """
    try:
        import psutil  # noqa: WPS433 — runtime optional dep, guarded
    except Exception:
        return False

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            # 8.8.8.8 is just a stable non-routable-from-LAN target. UDP
            # connect doesn't actually transmit — it just configures the
            # kernel routing table lookup so getsockname() returns the
            # local IP the OS would use for that destination.
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
    except Exception as exc:
        log_warning(f"is_local_adapter_wifi: route probe failed: {exc}")
        return False

    try:
        adapters = psutil.net_if_addrs()
    except Exception as exc:
        log_warning(f"is_local_adapter_wifi: net_if_addrs failed: {exc}")
        return False

    adapter_name: Optional[str] = None
    for name, addrs in adapters.items():
        for addr in addrs:
            # AF_INET addresses; psutil's address field is a string here.
            if getattr(addr, "address", "") == local_ip:
                adapter_name = name
                break
        if adapter_name:
            break

    if not adapter_name:
        return False

    lower = adapter_name.lower()
    return any(ind in lower for ind in _WIFI_NAME_INDICATORS)


# ── Isolation watchdog ──────────────────────────────────────────────

class IsolationResult:
    """Discriminator for ``IsolationWatchdog`` outcomes.

    Treated as an enum without importing ``enum`` — keeps the module
    importable in degraded test environments. Compare with ``is``, not
    ``==``, to make intent obvious at call sites.
    """
    WORKING = "working"               # spoof landed; forwarded traffic seen
    ISOLATION_DETECTED = "isolation"  # spoof emitted, zero forwarded traffic
    INCONCLUSIVE = "inconclusive"     # nothing emitted; can't tell
    ABORTED = "aborted"               # engine/spoofer stopped before grace


class IsolationWatchdog:
    """Detects AP-isolation no-ops post-engine-start.

    Construct after both the ArpSpoofer and the NativeWinDivertEngine
    are running. Call :meth:`start` to launch the daemon thread; the
    callback fires exactly once with the result. The watchdog never
    touches the engine or spoofer — it only OBSERVES counters and
    delegates the fallback decision to the orchestrator via the
    callback. Keeps responsibilities clean and unit-testable.

    Parameters
    ----------
    spoofer:
        ``ArpSpoofer`` instance. Must expose ``_packets_sent`` (int);
        watchdog uses it to detect "we attempted poison" vs. "we never
        even tried" — only the former implies isolation.
    engine:
        ``NativeWinDivertEngine`` instance. Must expose
        ``_packets_processed`` (int) and ``_running`` (bool).
    on_result:
        Callback ``(IsolationResult) -> None``. Called once. Will be
        invoked from the watchdog daemon thread — caller is responsible
        for any thread-safety on shared state (e.g. ``threading.Lock``
        around mutation of the engine registry).
    grace_s:
        Seconds to wait before sampling. Default 5.0 — short enough
        that the operator notices quickly, long enough that genuine
        slow-start traffic (a target that's not actively communicating)
        isn't misclassified as isolation. Mirrors the 3.0s default of
        the engine's built-in ``_flow_health_check`` watchdog with a
        small additional margin.
    target_ip:
        Optional. Used purely for log readability.
    """

    def __init__(
        self,
        spoofer: Any,
        engine: Any,
        on_result: Callable[[str], None],
        grace_s: float = 5.0,
        target_ip: Optional[str] = None,
    ) -> None:
        self._spoofer = spoofer
        self._engine = engine
        self._on_result = on_result
        self._grace_s = float(grace_s)
        self._target_ip = target_ip or "?"

        self._thread: Optional[threading.Thread] = None
        self._fired = threading.Event()
        # Allows a parent that's tearing things down to short-circuit
        # the result — we don't want to call back into orchestrator
        # state mutation after the orchestrator has already moved on.
        self._cancelled = threading.Event()

    def start(self) -> None:
        """Spawn the daemon thread. Idempotent."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name=f"IsolationWatchdog[{self._target_ip}]",
        )
        self._thread.start()

    def cancel(self) -> None:
        """Cancel pending result delivery.

        Use when the operator (or another path) stops the disruption
        before the grace window elapses. Prevents stale callbacks
        firing into an orchestrator that has already torn the engine
        down — without this guard the fallback would attempt to
        restart an engine whose target was already released.
        """
        self._cancelled.set()

    # ── internals ────────────────────────────────────────────────

    def _run(self) -> None:
        # Sleep in short ticks so cancel() is responsive.
        deadline = time.monotonic() + self._grace_s
        while time.monotonic() < deadline:
            if self._cancelled.is_set():
                self._fire(IsolationResult.ABORTED)
                return
            time.sleep(0.25)

        if self._cancelled.is_set():
            self._fire(IsolationResult.ABORTED)
            return

        # Engine could have been torn down by an unrelated stop path.
        # Treat that the same as cancel — no result useful here.
        try:
            engine_running = bool(getattr(self._engine, "_running", False))
        except Exception:
            engine_running = False
        if not engine_running:
            self._fire(IsolationResult.ABORTED)
            return

        try:
            processed = int(getattr(self._engine, "_packets_processed", 0))
        except Exception:
            processed = 0
        try:
            sent = int(getattr(self._spoofer, "_packets_sent", 0))
        except Exception:
            sent = 0

        if processed > 0:
            log_info(
                f"[WiFi-WATCHDOG] target={self._target_ip} OK — "
                f"{processed} forwarded packets in {self._grace_s:.1f}s"
            )
            self._fire(IsolationResult.WORKING)
            return

        if sent <= 0:
            # Spoofer never emitted — different failure mode (likely
            # MAC resolution stuck or Npcap handle issue). Don't
            # assume isolation; let the engine's own watchdog handle
            # the logging and fall back conservatively.
            log_warning(
                f"[WiFi-WATCHDOG] target={self._target_ip} INCONCLUSIVE — "
                f"spoofer emitted 0 packets, engine processed 0. "
                f"Not declaring isolation; check ArpSpoofer logs."
            )
            self._fire(IsolationResult.INCONCLUSIVE)
            return

        # Spoof was emitted, but nothing came back through the filter.
        # Classic AP-isolation signature.
        log_warning(
            f"[WiFi-WATCHDOG] target={self._target_ip} ISOLATION DETECTED — "
            f"{sent} ARP frames emitted, 0 forwarded packets in "
            f"{self._grace_s:.1f}s. AP is dropping station-to-station "
            f"traffic. Falling back to self-disrupt mode."
        )
        self._fire(IsolationResult.ISOLATION_DETECTED)

    def _fire(self, result: str) -> None:
        if self._fired.is_set():
            return
        self._fired.set()
        try:
            self._on_result(result)
        except Exception as exc:
            log_error(
                f"[WiFi-WATCHDOG] callback raised for result={result}: {exc}"
            )
