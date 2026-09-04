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

import math
import ntpath
import re
import threading
import time
from dataclasses import dataclass, field
from collections.abc import Mapping, Sequence
from typing import Any, Callable, Dict, List, Optional, Set

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
    "KillSwitchConfigurationError",
    "build_kill_switch_config",
    "sanitize_process_basenames",
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

POLL_INTERVAL_MIN_S = 0.05
POLL_INTERVAL_MAX_S = 60.0
COOLDOWN_MIN_S = 0.0
COOLDOWN_MAX_S = 3600.0
RISK_THRESHOLD_MIN = 1
RISK_THRESHOLD_MAX = 100
PACKET_DROP_CEILING_MIN = 1
PACKET_DROP_CEILING_MAX = 10_000_000
PACKET_SUSTAIN_MIN_S = 0.05
PACKET_SUSTAIN_MAX_S = 60.0
MAX_PROCESS_NAMES = 64
MAX_PROCESS_BASENAME_LENGTH = 128
_PROCESS_BASENAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._ ()+\-]*")


class KillSwitchConfigurationError(ValueError):
    """Raised when persisted automatic kill-switch settings are unsafe."""


def _setting(settings: object, name: str, default: Any) -> Any:
    if isinstance(settings, Mapping):
        return settings.get(name, default)
    return getattr(settings, name, default)


def _bounded_bool(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise KillSwitchConfigurationError(f"{name} must be true or false")
    return value


def _bounded_int(value: object, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise KillSwitchConfigurationError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise KillSwitchConfigurationError(
            f"{name} must be between {minimum} and {maximum}"
        )
    return value


def _bounded_float(
    value: object,
    name: str,
    minimum: float,
    maximum: float,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise KillSwitchConfigurationError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise KillSwitchConfigurationError(
            f"{name} must be between {minimum:g} and {maximum:g}"
        )
    return result


def sanitize_process_basenames(values: object) -> List[str]:
    """Return unique, lowercase process basenames from persisted settings.

    Full Windows or POSIX-like paths are reduced to their basename. Wildcards,
    control characters, path-only values, and oversized lists are rejected so
    the process watcher can never become an unbounded pattern matcher.
    """
    if values is None:
        return []
    if (
        isinstance(values, (str, bytes, bytearray))
        or not isinstance(values, Sequence)
    ):
        raise KillSwitchConfigurationError(
            "kill_switch_process_names must be a list"
        )
    if len(values) > MAX_PROCESS_NAMES:
        raise KillSwitchConfigurationError(
            f"kill_switch_process_names may contain at most {MAX_PROCESS_NAMES} entries"
        )

    sanitized: List[str] = []
    seen: Set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise KillSwitchConfigurationError(
                "kill_switch_process_names entries must be text"
            )
        candidate = value.strip()
        if not candidate or any(ord(char) < 32 for char in candidate):
            raise KillSwitchConfigurationError(
                "kill_switch_process_names contains an invalid entry"
            )
        basename = ntpath.basename(candidate.replace("/", "\\")).strip().lower()
        if (
            not basename
            or basename in {".", ".."}
            or len(basename) > MAX_PROCESS_BASENAME_LENGTH
            or _PROCESS_BASENAME_RE.fullmatch(basename) is None
        ):
            raise KillSwitchConfigurationError(
                "kill_switch_process_names contains an invalid basename"
            )
        if basename not in seen:
            seen.add(basename)
            sanitized.append(basename)
    return sanitized


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
        names = (
            sorted(KNOWN_ANTICHEAT_PROCESSES)
            if processes is None
            else sanitize_process_basenames(processes)
        )
        self._names: Set[str] = set(names)

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
        self._threshold = _bounded_int(
            threshold,
            "kill_switch_risk_threshold",
            RISK_THRESHOLD_MIN,
            RISK_THRESHOLD_MAX,
        )

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
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not callable(get_drop_counters):
            raise KillSwitchConfigurationError(
                "packet drop counter getter must be callable"
            )
        self._getter = get_drop_counters
        self._max_dps = _bounded_int(
            max_drop_per_second,
            "kill_switch_packet_drop_ceiling",
            PACKET_DROP_CEILING_MIN,
            PACKET_DROP_CEILING_MAX,
        )
        self._sustain_s = _bounded_float(
            sustain_s,
            "kill_switch_packet_sustain_seconds",
            PACKET_SUSTAIN_MIN_S,
            PACKET_SUSTAIN_MAX_S,
        )
        self._clock = clock
        self._last_sample: Optional[tuple[float, int]] = None
        self._over_since: Optional[float] = None

    def check(self) -> Optional[str]:
        try:
            counters = self._getter()
        except Exception as exc:
            log_warning(f"PacketCounterTrigger: getter raised: {exc}")
            return None
        if not isinstance(counters, Mapping):
            log_warning("PacketCounterTrigger: getter returned invalid counters")
            return None
        values = list(counters.values())
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values):
            log_warning("PacketCounterTrigger: getter returned invalid counters")
            return None
        total = sum(values)
        now = self._clock()
        if self._last_sample is None:
            self._last_sample = (now, total)
            return None
        prev_ts, prev_total = self._last_sample
        if total < prev_total:
            # Engines may reset their cumulative counters on restart. Treat the
            # first post-reset sample as a fresh baseline rather than a rate.
            self._last_sample = (now, total)
            self._over_since = None
            return None
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

    def __post_init__(self) -> None:
        self.enabled = _bounded_bool(self.enabled, "kill_switch_enabled")
        self.poll_interval_s = _bounded_float(
            self.poll_interval_s,
            "kill_switch_poll_interval_seconds",
            POLL_INTERVAL_MIN_S,
            POLL_INTERVAL_MAX_S,
        )
        self.cooldown_s = _bounded_float(
            self.cooldown_s,
            "kill_switch_cooldown_seconds",
            COOLDOWN_MIN_S,
            COOLDOWN_MAX_S,
        )
        if not isinstance(self.triggers, list):
            raise KillSwitchConfigurationError("kill-switch triggers must be a list")
        self.triggers = list(self.triggers)
        if not any(isinstance(trigger, ManualTrigger) for trigger in self.triggers):
            self.triggers.append(ManualTrigger())


def build_kill_switch_config(
    settings: object,
    *,
    get_drop_counters: Callable[[], Dict[str, int]],
) -> KillSwitchConfig:
    """Build a bounded runtime config from persisted application settings.

    Every persisted value is parsed even when automation is disabled. This
    prevents malformed dormant settings from becoming active after a later
    toggle. The returned config always contains a manual trigger.
    """
    enabled = _bounded_bool(
        _setting(settings, "kill_switch_enabled", False),
        "kill_switch_enabled",
    )
    process_watch_enabled = _bounded_bool(
        _setting(settings, "kill_switch_process_watch_enabled", True),
        "kill_switch_process_watch_enabled",
    )
    process_names = sanitize_process_basenames(
        _setting(settings, "kill_switch_process_names", [])
    )
    risk_threshold = _bounded_int(
        _setting(settings, "kill_switch_risk_threshold", 80),
        "kill_switch_risk_threshold",
        RISK_THRESHOLD_MIN,
        RISK_THRESHOLD_MAX,
    )
    drop_ceiling = _bounded_int(
        _setting(settings, "kill_switch_packet_drop_ceiling", 5000),
        "kill_switch_packet_drop_ceiling",
        PACKET_DROP_CEILING_MIN,
        PACKET_DROP_CEILING_MAX,
    )
    sustain_s = _bounded_float(
        _setting(settings, "kill_switch_packet_sustain_seconds", 5.0),
        "kill_switch_packet_sustain_seconds",
        PACKET_SUSTAIN_MIN_S,
        PACKET_SUSTAIN_MAX_S,
    )
    poll_interval_s = _bounded_float(
        _setting(settings, "kill_switch_poll_interval_seconds", 1.0),
        "kill_switch_poll_interval_seconds",
        POLL_INTERVAL_MIN_S,
        POLL_INTERVAL_MAX_S,
    )
    cooldown_s = _bounded_float(
        _setting(settings, "kill_switch_cooldown_seconds", 30.0),
        "kill_switch_cooldown_seconds",
        COOLDOWN_MIN_S,
        COOLDOWN_MAX_S,
    )

    triggers: List[KillSwitchTrigger] = []
    if process_watch_enabled:
        triggers.append(
            AntiCheatProcessTrigger(process_names if process_names else None)
        )
    triggers.extend(
        [
            RiskScoreTrigger(risk_threshold),
            PacketCounterTrigger(
                get_drop_counters,
                max_drop_per_second=drop_ceiling,
                sustain_s=sustain_s,
            ),
            ManualTrigger(),
        ]
    )
    return KillSwitchConfig(
        enabled=enabled,
        poll_interval_s=poll_interval_s,
        cooldown_s=cooldown_s,
        triggers=triggers,
    )


class KillSwitch:
    """Orchestrator that polls triggers and invokes a stop callback."""

    def __init__(
        self,
        config: KillSwitchConfig,
        stop_callback: Callable[[str], object],
    ) -> None:
        self._cfg = config
        self._stop_cb = stop_callback
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._thread_lock = threading.Lock()
        self._last_fire_ts: Optional[float] = None

    @property
    def is_running(self) -> bool:
        with self._thread_lock:
            return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        """Start one poll worker; return False when it was already running."""
        with self._thread_lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._stop_event.clear()
            thread = threading.Thread(
                target=self._run, daemon=True, name="KillSwitch"
            )
            self._thread = thread
            thread.start()
        log_info(
            f"KillSwitch started: enabled={self._cfg.enabled}, "
            f"triggers={[t.type_id for t in self._cfg.triggers]}, "
            f"poll={self._cfg.poll_interval_s}s"
        )
        return True

    def stop(self) -> bool:
        """Interrupt the worker promptly and report whether it stopped."""
        self._stop_event.set()
        with self._thread_lock:
            thread = self._thread
        if thread is None:
            return True
        if thread is threading.current_thread():
            return False
        if thread.ident is None:
            with self._thread_lock:
                if self._thread is thread:
                    self._thread = None
            return True
        thread.join(timeout=2.0)
        if thread.is_alive():
            log_warning("KillSwitch thread did not stop within 2s")
            return False
        with self._thread_lock:
            if self._thread is thread:
                self._thread = None
        return True

    def fire_manual(self, reason: str = "manual trigger") -> bool:
        """Invoke the panic stop immediately, even when automation is off."""
        return self._invoke_stop(f"manual: {reason}")

    def _run(self) -> None:
        try:
            while not self._stop_event.is_set():
                try:
                    self._tick()
                except Exception as exc:
                    log_error(f"KillSwitch tick error: {exc}")
                if self._stop_event.wait(self._cfg.poll_interval_s):
                    break
        finally:
            with self._thread_lock:
                if self._thread is threading.current_thread():
                    self._thread = None

    def _tick(self) -> None:
        now = time.monotonic()
        in_cooldown = (
            self._last_fire_ts is not None
            and (now - self._last_fire_ts) < self._cfg.cooldown_s
        )

        for t in self._cfg.triggers:
            # Manual trigger short-circuits the disabled check.
            is_manual = isinstance(t, ManualTrigger)
            if not is_manual and not self._cfg.enabled:
                continue
            if in_cooldown and not is_manual:
                continue
            reason = t.check()
            if reason:
                if self._invoke_stop(f"{t.type_id}: {reason}"):
                    # Cooldown represents a confirmed restoration, not merely
                    # an attempted callback.  Failed releases must be retried
                    # on the next poll instead of being suppressed.
                    self._last_fire_ts = now
                return

    def _invoke_stop(self, reason: str) -> bool:
        log_warning(f"KillSwitch FIRED: {reason}")
        try:
            result = self._stop_cb(reason)
        except Exception as exc:
            log_error(f"KillSwitch stop callback raised: {exc}")
            return False
        if result is False:
            log_error("KillSwitch stop callback did not confirm restoration")
            return False
        # Legacy callbacks return None after completing successfully.  Keep
        # that contract while reserving explicit False for failed cleanup.
        return True
