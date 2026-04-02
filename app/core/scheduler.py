#!/usr/bin/env python3
"""
Disruption Scheduler + Macro Engine

Scheduler — Timer-based disruption rules:
  "Start disruption on 192.168.1.50 at 20:00, stop at 20:30, repeat daily"

Macros — Sequential profile chains with timing:
  "Light Lag 30s → Heavy Lag 10s → Disconnect 5s → repeat 3x"

Both are driven by a single background scheduler thread.
"""

import json
import os
import time
import threading
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional, Callable
from datetime import datetime, timedelta

from app.logs.logger import log_info, log_error


# ======================================================================
# Scheduled Disruption
# ======================================================================
@dataclass
class ScheduledRule:
    """A timer-based disruption rule."""
    rule_id: str = ""
    name: str = ""
    target_ip: str = ""
    methods: List[str] = field(default_factory=list)
    params: Dict = field(default_factory=dict)
    start_time: str = ""       # HH:MM (24h) or epoch float
    duration_seconds: int = 60
    repeat_interval: int = 0   # 0 = one-shot, else seconds between repeats
    enabled: bool = True
    last_run: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'ScheduledRule':
        known = {f.name for f in __import__('dataclasses').fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


# ======================================================================
# Disruption Macro
# ======================================================================
@dataclass
class MacroStep:
    """A single step in a disruption macro."""
    methods: List[str] = field(default_factory=list)
    params: Dict = field(default_factory=dict)
    duration_seconds: int = 10
    profile_name: str = ""     # optional: load from saved profile

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'MacroStep':
        known = {f.name for f in __import__('dataclasses').fields(cls)}
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
        d['steps'] = [s.to_dict() if isinstance(s, MacroStep) else s for s in self.steps]
        return d

    @classmethod
    def from_dict(cls, data: dict) -> 'DisruptionMacro':
        steps_data = data.pop('steps', [])
        known = {f.name for f in __import__('dataclasses').fields(cls)}
        obj = cls(**{k: v for k, v in data.items() if k in known and k != 'steps'})
        obj.steps = [MacroStep.from_dict(s) if isinstance(s, dict) else s for s in steps_data]
        return obj


# ======================================================================
# Scheduler Engine
# ======================================================================
class DisruptionScheduler:
    """Background scheduler for timed disruptions and macros.

    Usage:
        scheduler = DisruptionScheduler(disrupt_fn, stop_fn)
        scheduler.add_rule(ScheduledRule(...))
        scheduler.run_macro(DisruptionMacro(...))
        scheduler.start()
        ...
        scheduler.stop()
    """

    def __init__(self, disrupt_fn: Callable, stop_fn: Callable,
                 data_dir: str = ""):
        if not data_dir:
            from app.core.data_persistence import _resolve_data_directory
            data_dir = _resolve_data_directory()
        self._disrupt_fn = disrupt_fn   # (ip, methods, params) -> bool
        self._stop_fn = stop_fn         # (ip) -> bool
        self._data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)

        self._rules: Dict[str, ScheduledRule] = {}
        self._macros: Dict[str, DisruptionMacro] = {}
        self._active_rules: Dict[str, float] = {}    # rule_id -> stop_at epoch
        self._active_macro: Optional[str] = None
        self._macro_thread: Optional[threading.Thread] = None
        self._stop_macro_flag = threading.Event()

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        self._load()

    # ------------------------------------------------------------------
    # Rule Management
    # ------------------------------------------------------------------
    def add_rule(self, rule: ScheduledRule) -> str:
        if not rule.rule_id:
            rule.rule_id = f"rule_{int(time.time() * 1000)}"
        with self._lock:
            self._rules[rule.rule_id] = rule
        self._save()
        log_info(f"Scheduler: added rule '{rule.name}' ({rule.rule_id})")
        return rule.rule_id

    def remove_rule(self, rule_id: str):
        with self._lock:
            self._rules.pop(rule_id, None)
            self._active_rules.pop(rule_id, None)
        self._save()

    def get_rules(self) -> List[ScheduledRule]:
        return list(self._rules.values())

    def toggle_rule(self, rule_id: str) -> bool:
        with self._lock:
            rule = self._rules.get(rule_id)
            if rule:
                rule.enabled = not rule.enabled
                self._save()
                return rule.enabled
        return False

    # ------------------------------------------------------------------
    # Macro Management
    # ------------------------------------------------------------------
    def add_macro(self, macro: DisruptionMacro) -> str:
        if not macro.macro_id:
            macro.macro_id = f"macro_{int(time.time() * 1000)}"
        if not macro.created:
            macro.created = time.time()
        with self._lock:
            self._macros[macro.macro_id] = macro
        self._save()
        log_info(f"Scheduler: added macro '{macro.name}' ({macro.macro_id})")
        return macro.macro_id

    def remove_macro(self, macro_id: str):
        with self._lock:
            self._macros.pop(macro_id, None)
        self._save()

    def get_macros(self) -> List[DisruptionMacro]:
        return list(self._macros.values())

    def run_macro(self, macro_id: str, target_ip: str = None):
        """Start executing a macro in a background thread."""
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
            target=self._run_macro_loop, args=(macro, ip), daemon=True)
        self._macro_thread.start()

    def stop_macro(self):
        """Stop the currently running macro."""
        self._stop_macro_flag.set()
        self._active_macro = None

    def is_macro_running(self) -> bool:
        return self._active_macro is not None

    def _run_macro_loop(self, macro: DisruptionMacro, ip: str):
        """Execute macro steps sequentially with timing."""
        repeats = macro.repeat_count if macro.repeat_count > 0 else 999999
        try:
            for cycle in range(repeats):
                if self._stop_macro_flag.is_set():
                    break
                for i, step in enumerate(macro.steps):
                    if self._stop_macro_flag.is_set():
                        break
                    methods = step.methods
                    params = step.params
                    log_info(f"Macro '{macro.name}' step {i+1}/{len(macro.steps)} "
                             f"(cycle {cycle+1}): {methods} for {step.duration_seconds}s")

                    self._disrupt_fn(ip, methods, params)

                    # Wait for step duration, checking stop flag every 0.5s
                    elapsed = 0.0
                    while elapsed < step.duration_seconds:
                        if self._stop_macro_flag.is_set():
                            break
                        time.sleep(min(0.5, step.duration_seconds - elapsed))
                        elapsed += 0.5

                    self._stop_fn(ip)

                    # Brief pause between steps
                    if not self._stop_macro_flag.is_set():
                        time.sleep(0.3)

        except Exception as e:
            log_error(f"Macro execution error: {e}")
        finally:
            self._stop_fn(ip)
            self._active_macro = None
            log_info(f"Macro '{macro.name}' finished")

    # ------------------------------------------------------------------
    # Scheduler Loop
    # ------------------------------------------------------------------
    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._thread.start()
        log_info("Disruption scheduler started")

    def stop(self):
        self._running = False
        self.stop_macro()
        # Stop any active scheduled disruptions
        with self._lock:
            for rule_id, stop_at in list(self._active_rules.items()):
                rule = self._rules.get(rule_id)
                if rule:
                    self._stop_fn(rule.target_ip)
            self._active_rules.clear()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        log_info("Disruption scheduler stopped")

    def _scheduler_loop(self):
        while self._running:
            try:
                now = time.time()
                current_time = datetime.now().strftime("%H:%M")

                with self._lock:
                    # Check active rules for expiry
                    expired = []
                    for rule_id, stop_at in self._active_rules.items():
                        if now >= stop_at:
                            rule = self._rules.get(rule_id)
                            if rule:
                                self._stop_fn(rule.target_ip)
                                log_info(f"Scheduler: rule '{rule.name}' expired, stopping")
                            expired.append(rule_id)
                    for rid in expired:
                        del self._active_rules[rid]

                    # Check rules for trigger
                    for rule_id, rule in self._rules.items():
                        if not rule.enabled or rule_id in self._active_rules:
                            continue

                        should_trigger = False

                        # Time-based trigger (HH:MM match)
                        if rule.start_time and ':' in rule.start_time:
                            if current_time == rule.start_time:
                                # Prevent re-trigger in same minute
                                if now - rule.last_run > 65:
                                    should_trigger = True

                        # Repeat interval trigger
                        if rule.repeat_interval > 0 and rule.last_run > 0:
                            if now - rule.last_run >= rule.repeat_interval:
                                should_trigger = True

                        if should_trigger:
                            self._disrupt_fn(rule.target_ip, rule.methods, rule.params)
                            stop_at = now + rule.duration_seconds
                            self._active_rules[rule_id] = stop_at
                            rule.last_run = now
                            log_info(f"Scheduler: triggered rule '{rule.name}' on {rule.target_ip} "
                                     f"for {rule.duration_seconds}s")

            except Exception as e:
                log_error(f"Scheduler loop error: {e}")

            time.sleep(1)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _save(self):
        try:
            with self._lock:
                data = {
                    'rules': {k: v.to_dict() for k, v in self._rules.items()},
                    'macros': {k: v.to_dict() for k, v in self._macros.items()},
                }
            path = os.path.join(self._data_dir, "scheduler.json")
            tmp = path + ".tmp"
            with open(tmp, 'w') as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except Exception as e:
            log_error(f"Scheduler save error: {e}")

    def _load(self):
        try:
            path = os.path.join(self._data_dir, "scheduler.json")
            if not os.path.exists(path):
                return
            with open(path, 'r') as f:
                data = json.load(f)
            for k, v in data.get('rules', {}).items():
                self._rules[k] = ScheduledRule.from_dict(v)
            for k, v in data.get('macros', {}).items():
                self._macros[k] = DisruptionMacro.from_dict(v)
            log_info(f"Scheduler: loaded {len(self._rules)} rules, {len(self._macros)} macros")
        except Exception as e:
            log_error(f"Scheduler load error: {e}")
