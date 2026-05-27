"""Cut chaining orchestrator (v5.7.1 feature #2).

Sequences N existing presets against a target with operator-configurable
timing gates. Doesn't change the engine — it's a thin coordinator that
calls ``controller.disrupt_device`` / ``controller.stop_disruption`` in
order, waits on the configured gate between stages, optionally consults
the A2S cut verifier for severance confirmation before advancing.

Stage shape::

    {
      "preset": "Red Disconnect",
      "methods": ["drop", "disconnect"],     # optional override
      "params":  {"disconnect_duration_ms": 5000},   # optional override
      "gate":    {"kind": "time", "seconds": 7},
      "halt_on": ["severed", "connected"]   # optional early-exit
    }

Gate kinds:

    ``time``     — wait *seconds*
    ``severed``  — wait until A2S verifier reports severed (timeout)
    ``connected``— wait until A2S verifier reports connected
    ``packets``  — wait until engine processed N packets

A chain is a list of stages plus a top-level config:

    ChainConfig(
        target_ip="192.168.1.50",
        stages=[Stage(...), Stage(...), ...],
        on_failure="halt" | "continue" | "rewind",
        global_timeout_s=120,
    )

Driven by :class:`CutChainRunner` which owns the daemon thread that
walks the stages. ``runner.start()`` returns immediately; the chain
runs in the background and emits a callback per stage transition
(start, stop, advance, halt) so the UI can show progress.

This is the user-facing version of the existing "multi-method preset"
pattern. A single preset can already enable multiple modules
simultaneously; the chain runner is for SEQUENCING different presets
over time — e.g. "Lag 2s, then full Red Disconnect 5s, then verify
severed, then release."
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from app.logs.logger import log_error, log_info, log_warning


__all__ = [
    "Gate",
    "Stage",
    "ChainConfig",
    "ChainEvent",
    "CutChainRunner",
]


# ── Gate types ────────────────────────────────────────────────────────

@dataclass
class Gate:
    """A wait condition between stages."""
    kind: str             # "time" | "severed" | "connected" | "packets"
    seconds: float = 0.0  # for time / fallback timeout for state gates
    packets: int = 0      # for packets gate


@dataclass
class Stage:
    """One step in a chain."""
    preset: str
    methods: Optional[List[str]] = None
    params: Optional[Dict[str, Any]] = None
    gate: Gate = field(default_factory=lambda: Gate(kind="time", seconds=5.0))
    halt_on: List[str] = field(default_factory=list)


@dataclass
class ChainConfig:
    """Top-level config for a chain run."""
    target_ip: str
    stages: List[Stage] = field(default_factory=list)
    on_failure: str = "halt"          # halt | continue | rewind
    global_timeout_s: float = 120.0


@dataclass(frozen=True)
class ChainEvent:
    """Emitted to the runner's callback per state change."""
    kind: str       # "stage_start" | "stage_end" | "halt" | "complete" | "error"
    stage_idx: int
    detail: str = ""


# ── Runner ────────────────────────────────────────────────────────────

class CutChainRunner:
    """Walks a ChainConfig against the live disruption controller."""

    def __init__(
        self,
        config: ChainConfig,
        controller: Any,
        on_event: Optional[Callable[[ChainEvent], None]] = None,
    ) -> None:
        self._cfg = config
        self._controller = controller
        self._on_event = on_event or (lambda _e: None)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._started_ts: float = 0.0

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._started_ts = time.monotonic()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="CutChainRunner"
        )
        self._thread.start()
        log_info(
            f"CutChainRunner started: target={self._cfg.target_ip}, "
            f"stages={len(self._cfg.stages)}, "
            f"timeout={self._cfg.global_timeout_s}s"
        )

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        # Best-effort: release any active disruption on the target.
        try:
            self._controller.stop_disruption(self._cfg.target_ip)
        except Exception:
            pass

    def _emit(self, event: ChainEvent) -> None:
        try:
            self._on_event(event)
        except Exception as exc:
            log_warning(f"CutChainRunner callback raised: {exc}")

    def _run(self) -> None:
        try:
            for idx, stage in enumerate(self._cfg.stages):
                if self._stop.is_set():
                    self._emit(ChainEvent("halt", idx, "operator stop"))
                    return
                if self._global_timed_out():
                    self._emit(ChainEvent(
                        "halt", idx, f"global timeout {self._cfg.global_timeout_s}s"
                    ))
                    return
                self._run_stage(idx, stage)
            self._emit(ChainEvent("complete", len(self._cfg.stages) - 1))
        except Exception as exc:
            log_error(f"CutChainRunner crashed: {exc}")
            self._emit(ChainEvent("error", -1, str(exc)))
        finally:
            # Cleanly stop the disruption when the chain finishes.
            try:
                self._controller.stop_disruption(self._cfg.target_ip)
            except Exception:
                pass

    def _run_stage(self, idx: int, stage: Stage) -> None:
        # Build the disrupt call's payload — preset wins, overrides
        # layered on top.
        try:
            from app.gui.clumsy_control import PRESETS
            preset_def = dict(PRESETS.get(stage.preset, {}))
        except Exception:
            preset_def = {}
        methods = list(stage.methods if stage.methods is not None
                       else preset_def.get("methods", []))
        params = dict(preset_def.get("params", {}))
        if stage.params:
            params.update(stage.params)

        self._emit(ChainEvent(
            "stage_start", idx,
            f"preset={stage.preset!r} methods={methods}"
        ))

        try:
            ok = self._controller.disrupt_device(
                self._cfg.target_ip, methods, params
            )
            if not ok:
                self._emit(ChainEvent(
                    "stage_end", idx, "disrupt_device returned False"
                ))
                if self._cfg.on_failure == "halt":
                    raise RuntimeError("stage failure with on_failure=halt")
                return
        except Exception as exc:
            log_error(f"CutChainRunner stage {idx} disrupt raised: {exc}")
            self._emit(ChainEvent("stage_end", idx, f"raised: {exc}"))
            if self._cfg.on_failure == "halt":
                raise
            return

        # Honor the gate before advancing.
        self._wait_gate(idx, stage)

        # Always release between stages — the next stage opens a fresh
        # disruption rather than stacking on top of the old one.
        try:
            self._controller.stop_disruption(self._cfg.target_ip)
        except Exception:
            pass
        self._emit(ChainEvent("stage_end", idx, "advanced"))

    def _wait_gate(self, idx: int, stage: Stage) -> None:
        kind = stage.gate.kind
        if kind == "time":
            # Deadline on the monotonic clock. The old `elapsed += tick`
            # loop accumulated float error and ignored per-iteration
            # scheduling overhead, so a "7s" gate drifted noticeably
            # long; it also could not see a wall-clock change at all.
            deadline = time.monotonic() + max(0.0, stage.gate.seconds)
            while not self._stop.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._stop.wait(min(0.1, remaining))
            return

        if kind in ("severed", "connected"):
            self._wait_a2s_state(
                idx, kind, timeout_s=stage.gate.seconds or 30.0
            )
            return

        if kind == "packets":
            self._wait_packet_count(
                idx, target=stage.gate.packets,
                timeout_s=stage.gate.seconds or 30.0,
            )
            return

        log_warning(f"unknown gate kind {kind!r} — sleeping 1s instead")
        self._stop.wait(1.0)

    def _wait_a2s_state(self, idx: int, want: str, timeout_s: float) -> None:
        """Poll the engine's max_cut_state until *want* or timeout."""
        end = time.monotonic() + timeout_s
        while time.monotonic() < end and not self._stop.is_set():
            try:
                engines = getattr(self._controller, "disrupted_devices", {})
                info = engines.get(self._cfg.target_ip, {})
                engine = info.get("engine")
                state = getattr(engine, "_max_cut_state", "unknown")
            except Exception:
                state = "unknown"
            if state == want:
                self._emit(ChainEvent(
                    "stage_end", idx, f"a2s reached {want!r}"
                ))
                return
            self._stop.wait(0.5)
        self._emit(ChainEvent(
            "stage_end", idx,
            f"a2s gate {want!r} timed out after {timeout_s:.1f}s"
        ))

    def _wait_packet_count(
        self, idx: int, target: int, timeout_s: float
    ) -> None:
        """Poll the engine's _packets_processed until >= target or timeout."""
        end = time.monotonic() + timeout_s
        while time.monotonic() < end and not self._stop.is_set():
            try:
                engines = getattr(self._controller, "disrupted_devices", {})
                info = engines.get(self._cfg.target_ip, {})
                engine = info.get("engine")
                count = int(getattr(engine, "_packets_processed", 0))
            except Exception:
                count = 0
            if count >= target:
                self._emit(ChainEvent(
                    "stage_end", idx,
                    f"packets gate reached {count}/{target}"
                ))
                return
            self._stop.wait(0.25)
        self._emit(ChainEvent(
            "stage_end", idx,
            f"packets gate {target} timed out after {timeout_s:.1f}s"
        ))

    def _global_timed_out(self) -> bool:
        return (
            self._cfg.global_timeout_s > 0
            and (time.monotonic() - self._started_ts) > self._cfg.global_timeout_s
        )
