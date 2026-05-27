"""Kill switch with trigger-based auto-stop (v5.7.0 feature #6).

A configurable safety layer that stops every active disruption when
any of N triggers fires. Sits on top of the existing
``controller.stop_all_disruptions()`` — no new disruption logic,
just an automated "STOP ALL" button driven by signals the rest of
DupeZ already produces.

Available triggers:

    AntiCheatProcessTrigger
        Polls ``psutil.process_iter()`` for known anti-cheat process
        names (BEService.exe, EasyAntiCheat.exe, GameGuard.des, etc.).
        Fires when any appears. Useful for stopping when an
        unexpected protection layer starts.

    RiskScoreTrigger
        Reads :func:`app.core.risk_score.compute_risk_score` on a
        timer. Fires when the score crosses ``threshold`` (default
        80). Catches "too many cuts too fast" before the operator
        notices.

    PacketCounterTrigger
        Hooks into the engine's packet stats. Fires when the
        post-cut drop rate exceeds ``max_drop_per_second`` for
        ``sustain_s`` seconds — catches runaway disruption (engine
        misconfiguration, looped script, etc.) that the operator
        didn't intentionally start.

    ManualTrigger
        Programmatic fire — wire to a UI button, global hotkey,
        webhook, etc. Always available.

The KillSwitch owns a daemon thread that polls each trigger at
``poll_interval_s``. When any trigger returns True, KillSwitch calls
the registered stop callback (typically
``controller.stop_all_disruptions``) and logs the trigger reason.
It then enters a cooldown so it doesn't fire repeatedly while the
operator is restoring state.

Config is a plain dict, persistable via the existing settings layer:

    {
        "enabled": true,
        "poll_interval_s": 1.0,
        "cooldown_s": 30.0,
        "triggers": [
            {"type": "anticheat_process", "processes": ["BEService.exe"]},
            {"type": "risk_score", "threshold": 80},
            {"type": "packet_counter", "max_drop_per_second": 5000, "sustain_s": 5.0},
            {"type": "manual"}
        ]
    }
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set

from app.logs.logger import log_error, log_info, log_warning


__all__ = [
    "KillSwitch",
    "KillSwitchConfig",
    "KillSwitchTrigger",
    "AntiCheatProcessTrigger",
    "RiskScoreTrigger",
    "PacketCounterTrigger",
    "ManualTrigger",
    "KNOWN_ANTICHEAT_PROCESSES",
]


# Common anti-cheat process names. Lowercase for case-insensitive match.
# Extend with care — false positives here trigger spurious kill events.
KNOWN_ANTICHEAT_PROCESSES: Set[str] = {
    "beservice.exe",       # BattlEye
    "easyanticheat.exe",   # Easy Anti-Cheat
    "gameguard.des",       # nProtect GameGuard (rare in DayZ ecosystem)
    "vanguard.exe",        # Riot Vanguard
    "fairfight.exe",       # FairFight
    "punkbuster.exe",      # PunkBuster (legacy but still active)
    "ricochet.exe",        # Activision RICOCHET
    "hyperion.exe",        # FACEIT / ESEA-class
}


# ── Trigger base + concrete implementations ──────────────────────────

class KillSwitchTrigger:
    """Base class. Subclasses override :meth:`check`."""

    type_id: str = "base"

    def check(self) -> Optional[str]:
        """Return a reason string when triggered, else None.

        Must be fast (called on the poll loop) and side-effect free.
        Returning the reason lets the KillSwitch log a useful event.
        """
        return None


class AntiCheatProcessTrigger(KillSwitchTrigger):
    """Fires when any process whose name matches *processes* is alive."""

    type_id = "anticheat_process"

    def __init__(self, processes: Optional[List[str]] = None) -> None:
        names = processes if processes is not None else list(KNOWN_ANTICHEAT_PROCESSES)
        self._names: Set[str] = {n.strip().lower() for n in names if n.strip()}

    def check(self) -> Optional[str]:
        if not self._names:
            return None
        try:
            import psutil
        except Exception:
            return None
        try:
            for p in psutil.process_iter(attrs=("name",)):
                try:
                    nm = (p.info.get("name") or "").lower()
                except Exception:
                    continue
                if nm in self._names:
                    return f"anti-cheat process detected: {nm}"
        except Exception as exc:
            log_warning(f"AntiCheatProcessTrigger: process_iter failed: {exc}")
        return None


class RiskScoreTrigger(KillSwitchTrigger):
    """Fires when the v5.7.0 risk score crosses *threshold*."""

    type_id = "risk_score"

    def __init__(self, threshold: int = 80) -> None:
        self._threshold = int(threshold)

    def check(self) -> Optional[str]:
        try:
            from app.core.risk_score import compute_risk_score
            score = compute_risk_score()
        except Exception as exc:
            log_warning(f"RiskScoreTrigger: compute failed: {exc}")
            return None
        if score.score >= self._threshold:
            return f"risk score {score.score} >= threshold {self._threshold} ({score.band})"
        return None


class PacketCounterTrigger(KillSwitchTrigger):
    """Fires on sustained packet-drop rate exceeding a threshold.

    Hooks into the live engine via a getter callback to avoid a hard
    dependency. The caller wires up the getter to whichever engine is
    in scope (typically ``disruption_manager``'s active engines).
    """

    type_id = "packet_counter"

    def __init__(
        self,
        get_drop_counters: Callable[[], Dict[str, int]],
        max_drop_per_second: int = 5000,
        sustain_s: float = 5.0,
    ) -> None:
        self._getter = get_drop_counters
        self._max_dps = int(max_drop_per_second)
        self._sustain_s = float(sustain_s)
        self._last_sample: Optional[tuple] = None  # (timestamp, total_drops)
        self._over_since: Optional[float] = None

    def check(self) -> Optional[str]:
        try:
            counters = self._getter() or {}
        except Exception as exc:
            log_warning(f"PacketCounterTrigger: getter raised: {exc}")
            return None
        total = sum(int(v) for v in counters.values())
        now = time.time()
        if self._last_sample is None:
            self._last_sample = (now, total)
            return None
        prev_ts, prev_total = self._last_sample
        dt = max(0.001, now - prev_ts)
        delta = total - prev_total
        self._last_sample = (now, total)
        rate = delta / dt
        if rate >= self._max_dps:
            if self._over_since is None:
                self._over_since = now
            if (now - self._over_since) >= self._sustain_s:
                self._over_since = None  # arm for re-fire after cooldown
                return (
                    f"drop rate {rate:.0f}/s sustained for "
                    f"{self._sustain_s:.1f}s (threshold {self._max_dps}/s)"
                )
        else:
            self._over_since = None
        return None


class ManualTrigger(KillSwitchTrigger):
    """Programmatic trigger — call :meth:`fire` from a button / hotkey."""

    type_id = "manual"

    def __init__(self) -> None:
        self._pending: Optional[str] = None
        self._lock = threading.Lock()

    def fire(self, reason: str = "manual trigger") -> None:
        with self._lock:
            self._pending = reason

    def check(self) -> Optional[str]:
        with self._lock:
            reason, self._pending = self._pending, None
        return reason


# ── Config + orchestrator ────────────────────────────────────────────

@dataclass
class KillSwitchConfig:
    """Settings for the kill switch."""
    enabled: bool = False
    poll_interval_s: float = 1.0
    cooldown_s: float = 30.0
    triggers: List[KillSwitchTrigger] = field(default_factory=list)


class KillSwitch:
    """Orchestrator that polls triggers and invokes a stop callback."""

    def __init__(
        self,
        config: KillSwitchConfig,
        stop_callback: Callable[[str], None],
    ) -> None:
        self._cfg = config
        self._stop_cb = stop_callback
        self._thread: Optional[threading.Thread] = None
        self._running = threading.Event()
        self._last_fire_ts: float = 0.0
        # Allow ManualTrigger to fire even when the kill switch is
        # otherwise disabled — operator pressing the button is an
        # explicit consent signal that overrides config.
        self._manual_overrides_disabled = True

    def start(self) -> None:
        # Guard on is_alive(), not merely non-None: a stale dead
        # reference must not block a restart, and a still-running thread
        # must not be shadowed by a second one.
        if self._thread is not None and self._thread.is_alive():
            return
        self._running.set()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="KillSwitch"
        )
        self._thread.start()
        log_info(
            f"KillSwitch started: enabled={self._cfg.enabled}, "
            f"triggers={[t.type_id for t in self._cfg.triggers]}, "
            f"poll={self._cfg.poll_interval_s}s"
        )

    def stop(self) -> None:
        self._running.clear()
        t = self._thread
        if t is not None:
            t.join(timeout=2.0)
            if t.is_alive():
                # Join timed out — keep the reference so a later start()
                # sees it via is_alive() and does not spawn a second
                # poll thread racing on _last_fire_ts.
                log_warning("KillSwitch thread did not stop within 2s")
            else:
                self._thread = None

    def fire_manual(self, reason: str = "manual trigger") -> None:
        """Convenience: find any ManualTrigger in config and fire it."""
        for t in self._cfg.triggers:
            if isinstance(t, ManualTrigger):
                t.fire(reason)
                return
        # No ManualTrigger configured — fire directly.
        self._invoke_stop(reason)

    def _run(self) -> None:
        while self._running.is_set():
            try:
                self._tick()
            except Exception as exc:
                log_error(f"KillSwitch tick error: {exc}")
            self._running.wait(self._cfg.poll_interval_s)

    def _tick(self) -> None:
        now = time.time()
        in_cooldown = (now - self._last_fire_ts) < self._cfg.cooldown_s

        for t in self._cfg.triggers:
            # Manual trigger short-circuits the disabled check.
            is_manual = isinstance(t, ManualTrigger)
            if not is_manual and not self._cfg.enabled:
                continue
            if in_cooldown and not is_manual:
                continue
            reason = t.check()
            if reason:
                self._invoke_stop(f"{t.type_id}: {reason}")
                self._last_fire_ts = now
                return

    def _invoke_stop(self, reason: str) -> None:
        log_warning(f"KillSwitch FIRED: {reason}")
        try:
            self._stop_cb(reason)
        except Exception as exc:
            log_error(f"KillSwitch stop callback raised: {exc}")
