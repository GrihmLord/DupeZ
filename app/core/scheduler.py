#!/usr/bin/env python3
"""
Disruption Scheduler + Macro Engine

Scheduler — Timer-based disruption rules:
  "Start disruption on 198.51.100.5 at 20:00, stop at 20:30, repeat daily"

Macros — Sequential profile chains with timing:
  "Light Lag 30s -> Heavy Lag 10s -> Disconnect 5s -> repeat 3x"

Both are driven by a single background scheduler thread.
"""

from __future__ import annotations

import json
import os
import time
import threading
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from typing import Callable, Dict, List, Optional

from app.logs.logger import log_error, log_info
from app.utils.helpers import mask_ip

__all__ = [
    "ScheduledRule",
    "MacroStep",
    "DisruptionMacro",
    "DisruptionScheduler",
]

MAX_RULE_DURATION_SECONDS = 3600
MAX_REPEAT_INTERVAL_SECONDS = 24 * 60 * 60
MAX_MACRO_STEPS = 100
MAX_MACRO_REPEATS = 100
MACRO_STOP_TIMEOUT_SECONDS = 3.0


# ── Data models ───────────────────────────────────────────────────────

@dataclass
class ScheduledRule:
    """A timer-based disruption rule."""

    rule_id: str = ""
    name: str = ""
    target_ip: str = ""
    methods: List[str] = field(default_factory=list)
    params: Dict = field(default_factory=dict)
    start_time: str = ""       # HH:MM (24h) or epoch float as string
    duration_seconds: int = 60
    repeat_interval: int = 0   # 0 = one-shot, else seconds between repeats
    enabled: bool = True
    last_run: float = 0.0

    def __post_init__(self) -> None:
        self.duration_seconds = max(
            1,
            min(MAX_RULE_DURATION_SECONDS, int(self.duration_seconds)),
        )
        self.repeat_interval = max(
            0,
            min(MAX_REPEAT_INTERVAL_SECONDS, int(self.repeat_interval)),
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ScheduledRule":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class MacroStep:
    """A single step in a disruption macro."""

    methods: List[str] = field(default_factory=list)
    params: Dict = field(default_factory=dict)
    duration_seconds: int = 10
    profile_name: str = ""

    def __post_init__(self) -> None:
        self.duration_seconds = max(
            1,
            min(MAX_RULE_DURATION_SECONDS, int(self.duration_seconds)),
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "MacroStep":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class DisruptionMacro:
    """A named sequence of disruption steps with repeat control."""

    macro_id: str = ""
    name: str = ""
    steps: List[MacroStep] = field(default_factory=list)
    repeat_count: int = 1      # 0 = infinite
    target_ip: str = ""
    created: float = 0.0

    def __post_init__(self) -> None:
        self.repeat_count = max(
            1,
            min(MAX_MACRO_REPEATS, int(self.repeat_count)),
        )
        self.steps = list(self.steps[:MAX_MACRO_STEPS])

    def to_dict(self) -> dict:
        d = asdict(self)
        d["steps"] = [
            s.to_dict() if isinstance(s, MacroStep) else s
            for s in self.steps
        ]
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "DisruptionMacro":
        # Extract steps without mutating the caller's dict
        steps_raw = data.get("steps", [])
        known = {f.name for f in fields(cls)}
        obj = cls(**{k: v for k, v in data.items() if k in known and k != "steps"})
        obj.steps = [
            MacroStep.from_dict(s) if isinstance(s, dict) else s
            for s in steps_raw
        ]
        obj.__post_init__()
        return obj


@dataclass
class _MacroRun:
    """Private ownership record for one macro execution.

    A cancellation event belongs to exactly one worker.  Keeping the record
    after a failed release is intentional: a later ``stop_macro`` call can
    retry the release, and a replacement macro cannot take over a target that
    may still be disrupted.
    """

    macro_id: str
    macro_name: str
    ip: str
    generation: int
    cancel_event: threading.Event = field(default_factory=threading.Event)
    thread: Optional[threading.Thread] = None
    owns_disruption: bool = False
    last_step_info: Dict = field(default_factory=dict)


# ── Scheduler ─────────────────────────────────────────────────────────

class DisruptionScheduler:
    """Background scheduler for timed disruptions and macros.

    Usage::

        scheduler = DisruptionScheduler(disrupt_fn, stop_fn)
        scheduler.add_rule(ScheduledRule(...))
        macro_id = scheduler.add_macro(DisruptionMacro(...))
        scheduler.run_macro(macro_id)
        scheduler.start()
        ...
        scheduler.stop()
    """

    def __init__(
        self,
        disrupt_fn: Callable,
        stop_fn: Callable,
        data_dir: str = "",
        on_macro_step: Optional[Callable] = None,
    ) -> None:
        """
        Args:
            disrupt_fn: ``(ip, methods, params) -> bool``
            stop_fn: ``(ip) -> bool``
            on_macro_step: optional ``(event, ip, step_info)`` callback
                           where *event* is ``'start'``, ``'stop'``, ``'done'``,
                           ``'cancelled'``, or ``'failed'``
        """
        if not data_dir:
            from app.core.data_persistence import _resolve_data_directory
            data_dir = _resolve_data_directory()

        self._disrupt_fn = disrupt_fn
        self._stop_fn = stop_fn
        self._on_macro_step = on_macro_step
        self._data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)

        self._rules: Dict[str, ScheduledRule] = {}
        self._macros: Dict[str, DisruptionMacro] = {}
        self._active_rules: Dict[str, float] = {}   # rule_id -> stop_at epoch
        self._active_macro: Optional[str] = None
        self._macro_thread: Optional[threading.Thread] = None
        self._macro_run: Optional[_MacroRun] = None
        self._macro_generation = 0
        # Compatibility alias for code that inspected the old field.  Each
        # new run replaces the alias, but workers retain their private event.
        self._stop_macro_flag = threading.Event()

        self._running = False
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()  # reentrant — _save nests inside callers

        self._load()

    # ── Rule management ───────────────────────────────────────────

    def add_rule(self, rule: ScheduledRule) -> str:
        """Register a scheduled rule.  Returns the rule ID."""
        if not rule.rule_id:
            rule.rule_id = f"rule_{int(time.time() * 1000)}"
        with self._lock:
            self._rules[rule.rule_id] = rule
        self._save()
        log_info(f"Scheduler: added rule '{rule.name}' ({rule.rule_id})")
        return rule.rule_id

    def remove_rule(self, rule_id: str) -> bool:
        """Remove a scheduled rule by ID.

        An active rule is released first.  Failed releases retain the rule and
        its ownership record so callers can retry instead of silently losing
        control of a live disruption.
        """
        with self._lock:
            rule = self._rules.get(rule_id)
            if rule is None:
                return False
            if rule_id in self._active_rules:
                if not self._invoke_stop(rule.target_ip, f"rule '{rule.name}'"):
                    return False
                self._active_rules.pop(rule_id, None)
            self._rules.pop(rule_id, None)
        self._save()
        return True

    def get_rules(self) -> List[ScheduledRule]:
        """Return a snapshot of all rules."""
        with self._lock:
            return list(self._rules.values())

    def toggle_rule(self, rule_id: str) -> bool:
        """Toggle a rule's enabled flag.  Returns the new state."""
        with self._lock:
            rule = self._rules.get(rule_id)
            if rule:
                rule.enabled = not rule.enabled
                self._save()
                return rule.enabled
        return False

    # ── Macro management ──────────────────────────────────────────

    def add_macro(self, macro: DisruptionMacro) -> str:
        """Register a macro.  Returns the macro ID."""
        macro.__post_init__()
        if not macro.macro_id:
            macro.macro_id = f"macro_{int(time.time() * 1000)}"
        if not macro.created:
            macro.created = time.time()
        with self._lock:
            self._macros[macro.macro_id] = macro
        self._save()
        log_info(f"Scheduler: added macro '{macro.name}' ({macro.macro_id})")
        return macro.macro_id

    def remove_macro(self, macro_id: str) -> None:
        """Remove a macro by ID."""
        with self._lock:
            self._macros.pop(macro_id, None)
        self._save()

    def get_macros(self) -> List[DisruptionMacro]:
        """Return a snapshot of all macros."""
        with self._lock:
            return list(self._macros.values())

    def run_macro(self, macro_id: str, target_ip: str = "") -> bool:
        """Start executing a macro in a background thread.

        Only one macro may own the scheduler at a time.  Callers must stop and
        fully release the current run before starting a replacement.
        """
        with self._lock:
            macro = self._macros.get(macro_id)
            if not macro:
                log_error(f"Scheduler: macro {macro_id} not found")
                return False
            ip = target_ip or macro.target_ip
            if not ip:
                log_error("Scheduler: no target IP for macro")
                return False
            if self._macro_run is not None:
                log_error(
                    "Scheduler: cannot start a macro while another macro "
                    "still owns a disruption"
                )
                return False

            # Execute an immutable snapshot.  Editing/removing a registered
            # macro while it runs must not mutate the live execution plan.
            macro_snapshot = DisruptionMacro.from_dict(macro.to_dict())
            self._macro_generation += 1
            run = _MacroRun(
                macro_id=macro_id,
                macro_name=macro_snapshot.name,
                ip=ip,
                generation=self._macro_generation,
            )
            thread = threading.Thread(
                target=self._run_macro_loop,
                args=(run, macro_snapshot),
                daemon=True,
            )
            run.thread = thread
            self._macro_run = run
            self._active_macro = macro_id
            self._macro_thread = thread
            self._stop_macro_flag = run.cancel_event
            try:
                thread.start()
            except Exception as exc:
                self._clear_macro_run_locked(run)
                log_error(f"Scheduler: could not start macro worker: {exc}")
                return False
            return True

    def stop_macro(self, timeout: float = MACRO_STOP_TIMEOUT_SECONDS) -> bool:
        """Cancel and release the active macro, returning confirmed success.

        If the worker cannot finish within *timeout*, or the disruption's
        ``stop_fn`` returns false, ownership is retained and replacement runs
        remain blocked.  Calling this method again retries a failed release.
        """
        with self._lock:
            run = self._macro_run
            if run is None:
                return True
            run.cancel_event.set()
            thread = run.thread
            worker_was_alive = bool(thread and thread.is_alive())

        if worker_was_alive:
            if thread is threading.current_thread():
                # The worker will observe its private event immediately after
                # the callback returns; it cannot synchronously join itself.
                return False
            thread.join(timeout=max(0.0, float(timeout)))
            if thread.is_alive():
                log_error("Scheduler: macro cancellation timed out")
                return False

            # A completed worker clears its record after a confirmed release.
            # If the record remains, its own stop attempt failed; do not issue
            # a second concurrent/ambiguous stop in the same call.
            with self._lock:
                return self._macro_run is not run

        # A dead worker with retained ownership represents a prior failed
        # release.  This explicit subsequent call is the safe retry path.
        with self._lock:
            if self._macro_run is not run:
                return True
            if not run.owns_disruption:
                self._clear_macro_run_locked(run)
                return True
            step_info = dict(run.last_step_info)

        if not self._invoke_stop(run.ip, f"macro '{run.macro_name}' retry"):
            return False

        with self._lock:
            if self._macro_run is run:
                run.owns_disruption = False
                self._clear_macro_run_locked(run)
        if step_info:
            self._fire_macro_callback("stop", run.ip, step_info)
        return True

    def is_macro_running(self) -> bool:
        """Return whether a macro is executing or retains target ownership."""
        with self._lock:
            return self._macro_run is not None

    # ── Macro execution loop ──────────────────────────────────────

    def _run_macro_loop(self, run: _MacroRun, macro: DisruptionMacro) -> None:
        """Execute one macro snapshot with per-run cancellation state."""
        ip = run.ip
        repeats = macro.repeat_count
        outcome = "done"
        terminal_info: Dict = {"macro": macro.name}
        release_failed = False
        try:
            for cycle in range(repeats):
                if run.cancel_event.is_set():
                    outcome = "cancelled"
                    break
                for i, step in enumerate(macro.steps):
                    if run.cancel_event.is_set():
                        outcome = "cancelled"
                        break

                    step_info = {
                        "macro": macro.name,
                        "step": i + 1,
                        "total_steps": len(macro.steps),
                        "cycle": cycle + 1,
                        "methods": step.methods,
                        "duration": step.duration_seconds,
                    }
                    log_info(
                        f"Macro '{macro.name}' step {i + 1}/{len(macro.steps)} "
                        f"(cycle {cycle + 1}): {step.methods} for {step.duration_seconds}s"
                    )

                    if not self._invoke_disrupt(
                        ip,
                        step.methods,
                        step.params,
                        f"macro '{macro.name}' step {i + 1}",
                    ):
                        outcome = "failed"
                        terminal_info = {
                            **step_info,
                            "outcome": "failed",
                            "reason": "start_failed",
                        }
                        break
                    with self._lock:
                        if self._macro_run is run:
                            run.owns_disruption = True
                            run.last_step_info = dict(step_info)
                    self._fire_macro_callback("start", ip, step_info)

                    cancelled = run.cancel_event.wait(step.duration_seconds)
                    if not self._invoke_stop(
                        ip,
                        f"macro '{macro.name}' step {i + 1}",
                    ):
                        outcome = "failed"
                        release_failed = True
                        terminal_info = {
                            **step_info,
                            "outcome": "failed",
                            "reason": "stop_failed",
                        }
                        break
                    with self._lock:
                        if self._macro_run is run:
                            run.owns_disruption = False
                    self._fire_macro_callback("stop", ip, step_info)

                    if cancelled:
                        outcome = "cancelled"
                        break
                    if run.cancel_event.wait(0.3):
                        outcome = "cancelled"
                        break

                if outcome != "done":
                    break

        except Exception as e:
            log_error(f"Macro execution error: {e}")
            outcome = "failed"
            terminal_info = {
                **terminal_info,
                "outcome": "failed",
                "reason": "execution_error",
            }
        finally:
            # Unexpected failures after a successful start still require a
            # release attempt.  A known failed release is not retried here;
            # ownership remains explicit for stop_macro().
            with self._lock:
                owns_disruption = (
                    self._macro_run is run and run.owns_disruption
                )
                step_info = dict(run.last_step_info)
            if owns_disruption and not release_failed:
                if self._invoke_stop(ip, f"macro '{macro.name}' cleanup"):
                    with self._lock:
                        if self._macro_run is run:
                            run.owns_disruption = False
                    if step_info:
                        self._fire_macro_callback("stop", ip, step_info)
                else:
                    release_failed = True
                    outcome = "failed"
                    terminal_info = {
                        **(step_info or terminal_info),
                        "outcome": "failed",
                        "reason": "stop_failed",
                    }

            with self._lock:
                retained = self._macro_run is run and run.owns_disruption
                if self._macro_run is run and not retained:
                    self._clear_macro_run_locked(run)

            if outcome == "cancelled":
                terminal_info = {
                    **terminal_info,
                    "outcome": "cancelled",
                    "reason": "cancelled",
                }
            elif outcome == "done":
                terminal_info = {**terminal_info, "outcome": "done"}
            self._fire_macro_callback(outcome, ip, terminal_info)
            if retained:
                log_error(
                    f"Macro '{macro.name}' failed and retained disruption ownership"
                )
            else:
                log_info(f"Macro '{macro.name}' {outcome}")

    def _clear_macro_run_locked(self, run: _MacroRun) -> None:
        """Clear *run* only when it is still the current ownership record."""
        if self._macro_run is not run:
            return
        self._macro_run = None
        self._active_macro = None
        self._macro_thread = None
        self._stop_macro_flag = threading.Event()

    def _invoke_disrupt(
        self,
        ip: str,
        methods: List[str],
        params: Dict,
        context: str,
    ) -> bool:
        """Invoke ``disrupt_fn`` and normalize exceptions/false results."""
        try:
            success = bool(self._disrupt_fn(ip, methods, params))
        except Exception as exc:
            log_error(f"Scheduler: {context} start raised: {exc}")
            return False
        if not success:
            log_error(f"Scheduler: {context} start was not confirmed")
        return success

    def _invoke_stop(self, ip: str, context: str) -> bool:
        """Invoke ``stop_fn`` and normalize exceptions/false results."""
        try:
            success = bool(self._stop_fn(ip))
        except Exception as exc:
            log_error(f"Scheduler: {context} stop raised: {exc}")
            return False
        if not success:
            log_error(f"Scheduler: {context} stop was not confirmed")
        return success

    def _fire_macro_callback(self, event: str, ip: str, step_info: dict) -> None:
        """Safely invoke the optional macro-step callback."""
        if self._on_macro_step:
            try:
                self._on_macro_step(event, ip, step_info)
            except Exception as exc:
                log_error(f"Scheduler: macro callback error: {exc}")

    # ── Scheduler loop ────────────────────────────────────────────

    def start(self) -> bool:
        """Start the background scheduler thread and report acceptance."""
        with self._lock:
            if self._running:
                return True
            self._running = True
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._scheduler_loop,
                daemon=True,
            )
            try:
                self._thread.start()
            except Exception as exc:
                self._thread = None
                self._running = False
                self._stop_event.set()
                log_error(f"Disruption scheduler failed to start: {exc}")
                return False
        log_info("Disruption scheduler started")
        return True

    def stop(self) -> bool:
        """Stop the scheduler and return whether every release succeeded."""
        self._running = False
        self._stop_event.set()
        macro_stopped = self.stop_macro()

        thread_stopped = True
        if self._thread and self._thread.is_alive():
            if self._thread is threading.current_thread():
                thread_stopped = False
            else:
                self._thread.join(timeout=3)
                thread_stopped = not self._thread.is_alive()

        rules_stopped = True
        with self._lock:
            for rule_id in list(self._active_rules):
                rule = self._rules.get(rule_id)
                if rule and self._invoke_stop(
                    rule.target_ip,
                    f"rule '{rule.name}' shutdown",
                ):
                    self._active_rules.pop(rule_id, None)
                else:
                    rules_stopped = False

        stopped = macro_stopped and rules_stopped and thread_stopped
        if stopped:
            log_info("Disruption scheduler stopped")
        else:
            log_error(
                "Disruption scheduler stopped with one or more retained owners"
            )
        return stopped

    def _scheduler_loop(self) -> None:
        """Main tick loop — checks rules every second."""
        while not self._stop_event.is_set():
            try:
                now = time.time()
                current_hhmm = datetime.now().strftime("%H:%M")
                self._scheduler_tick(now, current_hhmm)

            except Exception as e:
                log_error(f"Scheduler loop error: {e}")

            self._stop_event.wait(1)

    def _scheduler_tick(self, now: float, current_hhmm: str) -> None:
        """Process one deterministic rule tick.

        The helper is separate from the sleeping loop so callback-result
        ownership behavior can be regression tested without timing races.
        """
        with self._lock:
            expired = [
                rid for rid, stop_at in self._active_rules.items()
                if now >= stop_at
            ]
            for rid in expired:
                rule = self._rules.get(rid)
                if rule is None:
                    # Never discard an owner merely because its configuration
                    # disappeared unexpectedly; retain it for shutdown review.
                    log_error(
                        f"Scheduler: active rule {rid} has no release metadata"
                    )
                    continue
                if self._invoke_stop(rule.target_ip, f"rule '{rule.name}'"):
                    self._active_rules.pop(rid, None)
                    log_info(f"Scheduler: rule '{rule.name}' expired, stopped")

            for rule_id, rule in self._rules.items():
                if not rule.enabled or rule_id in self._active_rules:
                    continue

                should_trigger = False

                if rule.start_time and ":" in rule.start_time:
                    if current_hhmm == rule.start_time and now - rule.last_run > 65:
                        should_trigger = True

                if rule.start_time and ":" not in rule.start_time:
                    try:
                        start_epoch = float(rule.start_time)
                        if now >= start_epoch and rule.last_run == 0.0:
                            should_trigger = True
                    except (ValueError, TypeError):
                        pass

                if rule.repeat_interval > 0:
                    if rule.last_run == 0.0:
                        should_trigger = True
                    elif now - rule.last_run >= rule.repeat_interval:
                        should_trigger = True

                if not should_trigger:
                    continue
                if not self._invoke_disrupt(
                    rule.target_ip,
                    rule.methods,
                    rule.params,
                    f"rule '{rule.name}'",
                ):
                    continue
                self._active_rules[rule_id] = now + rule.duration_seconds
                rule.last_run = now
                log_info(
                    f"Scheduler: triggered rule '{rule.name}' "
                    f"on {mask_ip(rule.target_ip)} for {rule.duration_seconds}s"
                )

    # ── Persistence ───────────────────────────────────────────────

    def _save(self) -> None:
        """Persist rules and macros to JSON (atomic write)."""
        try:
            with self._lock:
                data = {
                    "rules": {k: v.to_dict() for k, v in self._rules.items()},
                    "macros": {k: v.to_dict() for k, v in self._macros.items()},
                }
            path = os.path.join(self._data_dir, "scheduler.json")
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except Exception as e:
            log_error(f"Scheduler save error: {e}")

    def _load(self) -> None:
        """Load rules and macros from disk."""
        try:
            path = os.path.join(self._data_dir, "scheduler.json")
            if not os.path.exists(path):
                return
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in data.get("rules", {}).items():
                self._rules[k] = ScheduledRule.from_dict(v)
            for k, v in data.get("macros", {}).items():
                self._macros[k] = DisruptionMacro.from_dict(v)
            log_info(f"Scheduler: loaded {len(self._rules)} rules, {len(self._macros)} macros")
        except Exception as e:
            log_error(f"Scheduler load error: {e}")
