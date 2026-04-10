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
        return obj


# ── Scheduler ─────────────────────────────────────────────────────────

class DisruptionScheduler:
    """Background scheduler for timed disruptions and macros.

    Usage::

        scheduler = DisruptionScheduler(disrupt_fn, stop_fn)
        scheduler.add_rule(ScheduledRule(...))
        scheduler.run_macro(DisruptionMacro(...))
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
                           where *event* is ``'start'``, ``'stop'``, or ``'done'``
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
        self._stop_macro_flag = threading.Event()

        self._running = False
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

    def remove_rule(self, rule_id: str) -> None:
        """Remove a scheduled rule by ID."""
        with self._lock:
            self._rules.pop(rule_id, None)
            self._active_rules.pop(rule_id, None)
        self._save()

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

    def run_macro(self, macro_id: str, target_ip: str = "") -> None:
        """Start executing a macro in a background thread."""
        with self._lock:
            macro = self._macros.get(macro_id)
            if not macro:
                log_error(f"Scheduler: macro {macro_id} not found")
                return
            ip = target_ip or macro.target_ip
            if not ip:
                log_error("Scheduler: no target IP for macro")
                return

            self._stop_macro_flag.clear()
            self._active_macro = macro_id
            self._macro_thread = threading.Thread(
                target=self._run_macro_loop, args=(macro, ip), daemon=True,
            )
            self._macro_thread.start()

    def stop_macro(self) -> None:
        """Stop the currently running macro."""
        self._stop_macro_flag.set()
        self._active_macro = None

    def is_macro_running(self) -> bool:
        """Return whether a macro is currently executing."""
        return self._active_macro is not None

    # ── Macro execution loop ──────────────────────────────────────

    def _run_macro_loop(self, macro: DisruptionMacro, ip: str) -> None:
        """Execute macro steps sequentially with wall-clock timing."""
        repeats = macro.repeat_count if macro.repeat_count > 0 else 999_999
        try:
            for cycle in range(repeats):
                if self._stop_macro_flag.is_set():
                    break
                for i, step in enumerate(macro.steps):
                    if self._stop_macro_flag.is_set():
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

                    self._disrupt_fn(ip, step.methods, step.params)
                    self._fire_macro_callback("start", ip, step_info)

                    # Wall-clock wait to avoid drift
                    deadline = time.monotonic() + step.duration_seconds
                    while time.monotonic() < deadline:
                        if self._stop_macro_flag.is_set():
                            break
                        remaining = deadline - time.monotonic()
                        time.sleep(min(0.5, max(0.0, remaining)))

                    self._stop_fn(ip)
                    self._fire_macro_callback("stop", ip, step_info)

                    if not self._stop_macro_flag.is_set():
                        time.sleep(0.3)

        except Exception as e:
            log_error(f"Macro execution error: {e}")
        finally:
            self._stop_fn(ip)
            self._active_macro = None
            self._fire_macro_callback("done", ip, {"macro": macro.name})
            log_info(f"Macro '{macro.name}' finished")

    def _fire_macro_callback(self, event: str, ip: str, step_info: dict) -> None:
        """Safely invoke the optional macro-step callback."""
        if self._on_macro_step:
            try:
                self._on_macro_step(event, ip, step_info)
            except Exception:
                pass

    # ── Scheduler loop ────────────────────────────────────────────

    def start(self) -> None:
        """Start the background scheduler thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._thread.start()
        log_info("Disruption scheduler started")

    def stop(self) -> None:
        """Stop the scheduler and any active disruptions."""
        self._running = False
        self.stop_macro()

        with self._lock:
            for rule_id in list(self._active_rules):
                rule = self._rules.get(rule_id)
                if rule:
                    self._stop_fn(rule.target_ip)
            self._active_rules.clear()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        log_info("Disruption scheduler stopped")

    def _scheduler_loop(self) -> None:
        """Main tick loop — checks rules every second."""
        while self._running:
            try:
                now = time.time()
                current_hhmm = datetime.now().strftime("%H:%M")

                with self._lock:
                    # Expire finished rules
                    expired = [
                        rid for rid, stop_at in self._active_rules.items()
                        if now >= stop_at
                    ]
                    for rid in expired:
                        rule = self._rules.get(rid)
                        if rule:
                            self._stop_fn(rule.target_ip)
                            log_info(f"Scheduler: rule '{rule.name}' expired, stopping")
                        del self._active_rules[rid]

                    # Check triggers
                    for rule_id, rule in self._rules.items():
                        if not rule.enabled or rule_id in self._active_rules:
                            continue

                        should_trigger = False

                        # Time-based trigger (HH:MM match)
                        if rule.start_time and ":" in rule.start_time:
                            if current_hhmm == rule.start_time and now - rule.last_run > 65:
                                should_trigger = True

                        # Epoch-based delayed start
                        if rule.start_time and ":" not in rule.start_time:
                            try:
                                start_epoch = float(rule.start_time)
                                if now >= start_epoch and rule.last_run == 0.0:
                                    should_trigger = True
                            except (ValueError, TypeError):
                                pass

                        # Repeat interval
                        if rule.repeat_interval > 0:
                            if rule.last_run == 0.0:
                                should_trigger = True
                            elif now - rule.last_run >= rule.repeat_interval:
                                should_trigger = True

                        if should_trigger:
                            self._disrupt_fn(rule.target_ip, rule.methods, rule.params)
                            self._active_rules[rule_id] = now + rule.duration_seconds
                            rule.last_run = now
                            log_info(
                                f"Scheduler: triggered rule '{rule.name}' "
                                f"on {mask_ip(rule.target_ip)} for {rule.duration_seconds}s"
                            )

            except Exception as e:
                log_error(f"Scheduler loop error: {e}")

            time.sleep(1)

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
