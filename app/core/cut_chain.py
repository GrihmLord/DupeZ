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

import math
import threading
import time
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from app.core.builtin_presets import (
    AUTOMATIC_CONNECTION_TEST,
    get_builtin_preset,
)
from app.logs.logger import log_error, log_info, log_warning


__all__ = [
    "Gate",
    "Stage",
    "ChainConfig",
    "ChainEvent",
    "CutChainRunner",
    "build_automatic_connection_test",
]


_AUTOMATIC_SELECTION_PARAMS = frozenset({
    "_auto_tune_duration",
    "_engine_preference",
    "_force_self_disrupt",
    "_network_local",
})


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
    # If native telemetry is available, advancing this stage requires a
    # counter-backed packet effect from the named module.  The compatibility
    # process has no runtime counters and is reported as unobservable.
    verify_method: Optional[str] = None
    verify_minimum: int = 1


@dataclass
class ChainConfig:
    """Top-level config for a chain run."""
    target_ip: str
    stages: List[Stage] = field(default_factory=list)
    on_failure: str = "halt"          # halt | continue | rewind
    global_timeout_s: float = 120.0
    common_params: Dict[str, Any] = field(default_factory=dict)
    disrupt_kwargs: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # A chain runs asynchronously, so caller-owned dictionaries must not
        # be able to mutate a later stage after start().
        self.common_params = deepcopy(dict(self.common_params or {}))
        self.disrupt_kwargs = deepcopy(dict(self.disrupt_kwargs or {}))
        self.disrupt_kwargs.pop("_cut_chain_runner", None)


def _bounded_number(value: Any, default: float, minimum: float,
                    maximum: float) -> float:
    """Return a finite float clamped to the supplied inclusive bounds."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    if not math.isfinite(parsed):
        parsed = default
    return max(minimum, min(maximum, parsed))


def build_automatic_connection_test(
    target_ip: str,
    *,
    common_params: Optional[Dict[str, Any]] = None,
    disrupt_kwargs: Optional[Dict[str, Any]] = None,
) -> ChainConfig:
    """Build the deterministic Lag -> Disconnect -> release workflow.

    Lag is capped at five seconds.  Its stage remains active for the full
    delay plus another second, which gives delayed packets time to mature
    before the disconnect stage replaces it.  The runner owns the bounded
    five-second disconnect so either native WinDivert or a verified Clumsy
    fallback receives the same representable, untimed Disconnect behavior.
    """
    definition = get_builtin_preset(AUTOMATIC_CONNECTION_TEST)
    workflow = dict(definition.get("workflow", {}))
    supplied_params = deepcopy(dict(common_params or {}))
    for key in _AUTOMATIC_SELECTION_PARAMS:
        supplied_params.pop(key, None)

    default_delay_ms = definition.get("params", {}).get("lag_delay", 2500)
    max_delay_ms = _bounded_number(
        workflow.get("max_lag_delay_ms", 5000), 5000, 1, 5000
    )
    lag_delay_ms = _bounded_number(
        supplied_params.get("lag_delay", default_delay_ms),
        float(default_delay_ms),
        1,
        max_delay_ms,
    )
    mature_window_ms = _bounded_number(
        workflow.get("lag_mature_window_ms", 1000), 1000, 1000, 5000
    )
    disconnect_ms = _bounded_number(
        workflow.get("disconnect_duration_ms", 5000), 5000, 1, 5000
    )

    lag_hold_s = (lag_delay_ms + mature_window_ms) / 1000.0
    disconnect_hold_s = disconnect_ms / 1000.0
    minimum_timeout_s = lag_hold_s + disconnect_hold_s + 2.0
    configured_timeout_s = _bounded_number(
        workflow.get("global_timeout_s", 20.0), 20.0,
        minimum_timeout_s, 120.0,
    )

    return ChainConfig(
        target_ip=target_ip,
        stages=[
            Stage(
                preset="Lag",
                methods=["lag"],
                params={
                    "lag_delay": int(round(lag_delay_ms)),
                    "lag_passthrough": False,
                    "lag_preserve_connection": False,
                    "direction": "both",
                },
                gate=Gate(kind="time", seconds=lag_hold_s),
                verify_method="lag",
            ),
            Stage(
                preset="Red Disconnect",
                methods=["disconnect"],
                params={
                    "disconnect_chance": 100,
                    "disconnect_arm_delay_ms": 0,
                    # The stage gate below supplies the duration.  Keeping
                    # this at zero preserves standalone Clumsy equivalence
                    # and still remains bounded by runner cancellation.
                    "disconnect_duration_ms": 0,
                    "direction": "both",
                },
                gate=Gate(kind="time", seconds=disconnect_hold_s),
                verify_method="disconnect",
            ),
        ],
        on_failure="halt",
        global_timeout_s=configured_timeout_s,
        common_params=supplied_params,
        disrupt_kwargs=deepcopy(dict(disrupt_kwargs or {})),
    )


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
        self._active_stage = False
        self._active_lock = threading.Lock()

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
        if (
            self._thread is not None
            and self._thread is not threading.current_thread()
        ):
            self._thread.join(timeout=2.0)
        # Best-effort release if a controller call left the worker stuck.
        self._release_active_stage()

    def _emit(self, event: ChainEvent) -> None:
        try:
            self._on_event(event)
        except Exception as exc:
            log_warning(f"CutChainRunner callback raised: {exc}")

    def _run(self) -> None:
        terminal_event: Optional[ChainEvent] = None
        try:
            for idx, stage in enumerate(self._cfg.stages):
                if self._stop.is_set():
                    terminal_event = ChainEvent("halt", idx, "operator stop")
                    break
                if self._global_timed_out():
                    terminal_event = ChainEvent(
                        "halt", idx, f"global timeout {self._cfg.global_timeout_s}s"
                    )
                    break
                self._run_stage(idx, stage)
                if self._stop.is_set():
                    terminal_event = ChainEvent("halt", idx, "operator stop")
                    break
                if self._global_timed_out():
                    terminal_event = ChainEvent(
                        "halt", idx,
                        f"global timeout {self._cfg.global_timeout_s}s",
                    )
                    break
            else:
                terminal_event = ChainEvent(
                    "complete", len(self._cfg.stages) - 1,
                    "connection released",
                )
        except Exception as exc:
            log_error(f"CutChainRunner crashed: {exc}")
            terminal_event = ChainEvent("error", -1, str(exc))
        finally:
            # Release before reporting the terminal event so a GUI cannot
            # display "complete" while packets are still being intercepted.
            self._release_active_stage()
            if terminal_event is not None:
                self._emit(terminal_event)

    def _run_stage(self, idx: int, stage: Stage) -> None:
        # Build the disrupt call's payload — preset wins, overrides
        # layered on top.
        preset_def = get_builtin_preset(stage.preset)
        methods = list(stage.methods if stage.methods is not None
                       else preset_def.get("methods", []))
        params = deepcopy(dict(preset_def.get("params", {})))
        params.update(deepcopy(self._cfg.common_params))
        if stage.params:
            params.update(deepcopy(stage.params))

        self._emit(ChainEvent(
            "stage_start", idx,
            f"preset={stage.preset!r} methods={methods}"
        ))

        try:
            ok = self._controller.disrupt_device(
                self._cfg.target_ip,
                methods,
                params,
                _cut_chain_runner=self,
                **deepcopy(self._cfg.disrupt_kwargs),
            )
            if not ok:
                self._emit(ChainEvent(
                    "stage_end", idx, "disrupt_device returned False"
                ))
                if self._cfg.on_failure == "halt":
                    raise RuntimeError("stage failure with on_failure=halt")
                return
            with self._active_lock:
                self._active_stage = True
        except Exception as exc:
            log_error(f"CutChainRunner stage {idx} disrupt raised: {exc}")
            self._emit(ChainEvent("stage_end", idx, f"raised: {exc}"))
            if self._cfg.on_failure == "halt":
                raise
            return

        # Honor the gate before advancing.
        self._wait_gate(idx, stage)

        verification_detail = "advanced"
        if stage.verify_method and not self._stop.is_set():
            verification, verification_detail = self._verify_stage_effect(
                stage.verify_method,
                max(1, int(stage.verify_minimum)),
            )
            if verification is False:
                raise RuntimeError(verification_detail)

        # Always release between stages — the next stage opens a fresh
        # disruption rather than stacking on top of the old one.
        self._release_active_stage()
        self._emit(ChainEvent("stage_end", idx, verification_detail))

    def _verify_stage_effect(
        self,
        method: str,
        minimum: int,
    ) -> tuple[Optional[bool], str]:
        """Verify a native module effect without inventing fallback data.

        ``True`` is counter-backed proof, ``False`` is a definitive native
        miss, and ``None`` means this engine/controller cannot expose runtime
        counters.  A verified Clumsy GUI setup therefore remains explicitly
        runtime-unobservable instead of being mislabeled as packet proof.
        """
        get_stats = getattr(self._controller, "get_engine_stats", None)
        if not callable(get_stats):
            return None, f"{method} runtime verification unavailable"
        try:
            aggregate = get_stats() or {}
            per_device = aggregate.get("per_device") or {}
            device = per_device.get(self._cfg.target_ip)
            if not isinstance(device, dict):
                return None, f"{method} runtime verification unavailable"
            if device.get("telemetry_available") is False:
                startup = bool(device.get("startup_verified"))
                suffix = "startup verified" if startup else "startup unverified"
                return None, f"{method} runtime unobservable ({suffix})"

            activity = device.get("module_activity") or {}
            module = activity.get(method)
            if not isinstance(module, dict):
                return False, f"{method} telemetry missing after active stage"
            affected = int(module.get("affected", 0) or 0)
            state = str(module.get("state", "pending"))
            if state == "effective" and affected >= minimum:
                return True, f"{method} verified ({affected} packet effects)"
            return False, (
                f"{method} produced no verified packet effect "
                f"(state={state}, affected={affected})"
            )
        except Exception as exc:
            log_warning(f"stage effect verification failed: {exc}")
            return None, f"{method} runtime verification unavailable"

    def _release_active_stage(self) -> None:
        """Release the current stage once, including cancellation paths."""
        with self._active_lock:
            if not self._active_stage:
                return
            self._active_stage = False
        try:
            self._controller.stop_disruption(
                self._cfg.target_ip,
                _cut_chain_runner=self,
            )
        except TypeError:
            # Keep CutChainRunner usable with small legacy/test controllers
            # whose stop_disruption surface accepts only the target IP.
            try:
                self._controller.stop_disruption(self._cfg.target_ip)
            except Exception:
                pass
        except Exception:
            pass

    def _wait_gate(self, idx: int, stage: Stage) -> None:
        kind = stage.gate.kind
        if kind == "time":
            # Deadline on the monotonic clock. The old `elapsed += tick`
            # loop accumulated float error and ignored per-iteration
            # scheduling overhead, so a "7s" gate drifted noticeably
            # long; it also could not see a wall-clock change at all.
            deadline = time.monotonic() + max(0.0, stage.gate.seconds)
            global_deadline = self._global_deadline()
            if global_deadline is not None:
                deadline = min(deadline, global_deadline)
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
        wait_s = 1.0
        global_deadline = self._global_deadline()
        if global_deadline is not None:
            wait_s = max(0.0, min(wait_s, global_deadline - time.monotonic()))
        self._stop.wait(wait_s)

    def _wait_a2s_state(self, idx: int, want: str, timeout_s: float) -> None:
        """Poll the engine's max_cut_state until *want* or timeout."""
        end = time.monotonic() + timeout_s
        global_deadline = self._global_deadline()
        if global_deadline is not None:
            end = min(end, global_deadline)
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
        global_deadline = self._global_deadline()
        if global_deadline is not None:
            end = min(end, global_deadline)
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
            and time.monotonic() >= self._started_ts + self._cfg.global_timeout_s
        )

    def _global_deadline(self) -> Optional[float]:
        if self._cfg.global_timeout_s <= 0:
            return None
        return self._started_ts + self._cfg.global_timeout_s
