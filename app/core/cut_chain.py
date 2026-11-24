"""Cut chaining orchestrator (v5.7.1 feature #2).

Sequences N existing presets against a target with operator-configurable
timing gates. Doesn't change the engine — it's a thin coordinator that
calls ``controller.disrupt_device`` / ``controller.stop_disruption`` in
order, waits on the configured gate between stages, optionally consults
the A2S cut verifier for severance confirmation before advancing.

Stage shape::

    {
      "action": "apply_preset",
      "preset": "Red Disconnect",
      "methods": ["drop", "disconnect"],     # optional override
      "params":  {"disconnect_duration_ms": 5000},   # optional override
      "gate":    {"kind": "time", "seconds": 7}
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
        on_failure="halt" | "continue",
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
import json
import os
import tempfile
import threading
import time
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from app.core.builtin_presets import (
    AUTOMATIC_CONNECTION_TEST,
    BUILTIN_PRESETS,
    get_builtin_preset,
)
from app.core.preset_store import (
    CustomPreset,
    get_custom_preset,
    validate_preset,
)
from app.core.validation import (
    VALID_DISRUPTION_METHODS,
    validate_local_target_ip,
)
from app.logs.logger import log_error, log_info, log_warning
from app.utils.helpers import mask_ip


__all__ = [
    "Gate",
    "Stage",
    "ChainConfig",
    "ChainEvent",
    "ChainValidationError",
    "CutChainRunner",
    "SUPPORTED_ACTIONS",
    "SUPPORTED_FAILURE_POLICIES",
    "SUPPORTED_GATE_KINDS",
    "build_automatic_connection_test",
    "chain_config_from_dict",
    "chain_config_to_dict",
    "load_chain_config",
    "save_chain_config",
    "validate_chain_config",
]


_AUTOMATIC_SELECTION_PARAMS = frozenset({
    "_auto_tune_duration",
    "_engine_preference",
    "_force_self_disrupt",
    "_network_local",
})

CHAIN_SCHEMA = "dupez.cut-chain.v1"
SUPPORTED_ACTIONS = frozenset({"apply_preset"})
SUPPORTED_FAILURE_POLICIES = frozenset({"halt", "continue"})
SUPPORTED_GATE_KINDS = frozenset({"time", "severed", "connected", "packets"})
MAX_CHAIN_STAGES = 32
MAX_GATE_SECONDS = 3600.0
MAX_GATE_PACKETS = 10_000_000
MAX_CHAIN_TIMEOUT_SECONDS = 3600.0
MAX_CHAIN_JSON_BYTES = 65_536
MAX_STAGE_PARAMS_BYTES = 16_384
_ALLOWED_DISRUPT_KWARGS = frozenset({
    "target_mac",
    "target_hostname",
    "target_device_type",
})
_ALLOWED_UNDERSCORE_PARAMS = frozenset({"_ports", "_process_scope"})


class ChainValidationError(ValueError):
    """Raised when a cut-chain definition is unsafe or malformed."""


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
    action: str = "apply_preset"


@dataclass
class ChainConfig:
    """Top-level config for a chain run."""
    target_ip: str
    stages: List[Stage] = field(default_factory=list)
    on_failure: str = "halt"          # halt | continue
    global_timeout_s: float = 120.0
    common_params: Dict[str, Any] = field(default_factory=dict)
    disrupt_kwargs: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # A chain runs asynchronously, so caller-owned dictionaries must not
        # be able to mutate a later stage after start().
        if not isinstance(self.stages, list):
            raise ChainValidationError("chain stages must be a list")
        if not isinstance(self.common_params, dict):
            raise ChainValidationError("common_params must be a dictionary")
        if not isinstance(self.disrupt_kwargs, dict):
            raise ChainValidationError("disrupt_kwargs must be a dictionary")
        self.stages = deepcopy(self.stages)
        self.common_params = deepcopy(self.common_params)
        self.disrupt_kwargs = deepcopy(self.disrupt_kwargs)
        self.disrupt_kwargs.pop("_cut_chain_runner", None)
        validate_chain_config(self)


def _strict_number(
    value: Any,
    *,
    name: str,
    minimum: float,
    maximum: float,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ChainValidationError(f"{name} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed) or not minimum <= parsed <= maximum:
        raise ChainValidationError(
            f"{name} must be between {minimum:g} and {maximum:g}"
        )
    return parsed


def _strict_int(
    value: Any,
    *,
    name: str,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ChainValidationError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise ChainValidationError(
            f"{name} must be between {minimum} and {maximum}"
        )
    return value


def _strict_json_object(value: Any, *, name: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ChainValidationError(f"{name} must be a JSON object")
    if any(not isinstance(key, str) for key in value):
        raise ChainValidationError(f"{name} keys must be text")
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ChainValidationError(
            f"{name} must contain finite JSON values"
        ) from exc
    if len(encoded) > MAX_STAGE_PARAMS_BYTES:
        raise ChainValidationError(
            f"{name} exceeds the {MAX_STAGE_PARAMS_BYTES}-byte limit"
        )
    return deepcopy(value)


def _validate_gate(gate: Gate, *, index: int) -> None:
    if not isinstance(gate, Gate):
        raise ChainValidationError(f"stage {index} gate must be a Gate")
    if not isinstance(gate.kind, str) or gate.kind not in SUPPORTED_GATE_KINDS:
        raise ChainValidationError(
            f"stage {index} gate kind is unsupported: {gate.kind!r}"
        )
    _strict_number(
        gate.seconds,
        name=f"stage {index} gate seconds",
        minimum=0.0 if gate.kind == "time" else 0.01,
        maximum=MAX_GATE_SECONDS,
    )
    if gate.kind == "packets":
        _strict_int(
            gate.packets,
            name=f"stage {index} gate packets",
            minimum=1,
            maximum=MAX_GATE_PACKETS,
        )
    elif gate.packets != 0:
        raise ChainValidationError(
            f"stage {index} packets is valid only for a packets gate"
        )


def _validate_stage(
    stage: Stage,
    *,
    index: int,
    common_params: Dict[str, Any],
) -> None:
    if not isinstance(stage, Stage):
        raise ChainValidationError(f"stage {index} must be a Stage")
    if (
        not isinstance(stage.action, str)
        or stage.action not in SUPPORTED_ACTIONS
    ):
        raise ChainValidationError(
            f"stage {index} action is unsupported: {stage.action!r}"
        )
    if not isinstance(stage.preset, str) or not stage.preset:
        raise ChainValidationError(
            f"stage {index} preset is unknown: {stage.preset!r}"
        )
    preset = _resolve_preset(stage.preset, index=index)
    methods = preset.get("methods", []) if stage.methods is None else stage.methods
    if not isinstance(methods, list) or not methods:
        raise ChainValidationError(
            f"stage {index} must resolve to at least one disruption method"
        )
    if len(methods) > len(VALID_DISRUPTION_METHODS):
        raise ChainValidationError(f"stage {index} has too many methods")
    unknown_methods = [
        method
        for method in methods
        if not isinstance(method, str) or method not in VALID_DISRUPTION_METHODS
    ]
    if unknown_methods:
        raise ChainValidationError(
            f"stage {index} methods contain unsupported values: "
            f"{unknown_methods!r}"
        )
    if len(set(methods)) != len(methods):
        raise ChainValidationError(f"stage {index} methods contain duplicates")

    params = deepcopy(dict(preset.get("params", {})))
    params.update(common_params)
    if stage.params is not None:
        params.update(_strict_json_object(
            stage.params,
            name=f"stage {index} params",
        ))
    rogue = sorted(
        key
        for key in params
        if key.startswith("_") and key not in _ALLOWED_UNDERSCORE_PARAMS
    )
    if rogue:
        raise ChainValidationError(
            f"stage {index} params contain protected engine keys: {rogue!r}"
        )
    try:
        validate_preset(CustomPreset(
            name=f"Chain Stage {index + 1}",
            methods=list(methods),
            params=params,
        ), allow_reserved=True)
    except ValueError as exc:
        raise ChainValidationError(
            f"stage {index} disruption configuration is invalid: {exc}"
        ) from exc

    _validate_gate(stage.gate, index=index)
    if not isinstance(stage.halt_on, list) or stage.halt_on:
        raise ChainValidationError(
            f"stage {index} halt_on is unsupported; use a state gate instead"
        )
    if stage.verify_method is not None:
        if (
            not isinstance(stage.verify_method, str)
            or stage.verify_method not in methods
        ):
            raise ChainValidationError(
                f"stage {index} verify_method must name an active method"
            )
    _strict_int(
        stage.verify_minimum,
        name=f"stage {index} verify_minimum",
        minimum=1,
        maximum=MAX_GATE_PACKETS,
    )


def validate_chain_config(config: ChainConfig) -> ChainConfig:
    """Validate a complete chain without silently repairing unsafe input."""
    if not isinstance(config, ChainConfig):
        raise ChainValidationError("chain config must be a ChainConfig")
    try:
        normalized_target = validate_local_target_ip(
            config.target_ip,
            context="cut chain",
        )
    except ValueError as exc:
        raise ChainValidationError(str(exc)) from exc
    if normalized_target != config.target_ip:
        raise ChainValidationError("cut-chain target must be normalized IPv4 text")
    if not isinstance(config.stages, list):
        raise ChainValidationError("chain stages must be a list")
    if not 1 <= len(config.stages) <= MAX_CHAIN_STAGES:
        raise ChainValidationError(
            f"chain must contain between 1 and {MAX_CHAIN_STAGES} stages"
        )
    if (
        not isinstance(config.on_failure, str)
        or config.on_failure not in SUPPORTED_FAILURE_POLICIES
    ):
        raise ChainValidationError(
            f"on_failure is unsupported: {config.on_failure!r}; "
            "supported values are 'halt' and 'continue'"
        )
    _strict_number(
        config.global_timeout_s,
        name="global_timeout_s",
        minimum=0.1,
        maximum=MAX_CHAIN_TIMEOUT_SECONDS,
    )
    common = _strict_json_object(config.common_params, name="common_params")
    rogue_common = sorted(
        key
        for key in common
        if key.startswith("_") and key not in _ALLOWED_UNDERSCORE_PARAMS
    )
    if rogue_common:
        raise ChainValidationError(
            f"common_params contain protected engine keys: {rogue_common!r}"
        )
    if not isinstance(config.disrupt_kwargs, dict):
        raise ChainValidationError("disrupt_kwargs must be a dictionary")
    if any(not isinstance(key, str) for key in config.disrupt_kwargs):
        raise ChainValidationError("disrupt_kwargs keys must be text")
    rogue_kwargs = sorted(set(config.disrupt_kwargs) - _ALLOWED_DISRUPT_KWARGS)
    if rogue_kwargs:
        raise ChainValidationError(
            f"disrupt_kwargs contain unsupported keys: {rogue_kwargs!r}"
        )
    for key, value in config.disrupt_kwargs.items():
        if value is not None and (
            not isinstance(value, str) or len(value) > 255
        ):
            raise ChainValidationError(
                f"disrupt_kwargs.{key} must be null or text up to 255 characters"
            )
    for index, stage in enumerate(config.stages):
        _validate_stage(stage, index=index, common_params=common)
    return config


def _resolve_preset(name: str, *, index: int) -> Dict[str, Any]:
    if name in BUILTIN_PRESETS:
        return get_builtin_preset(name)
    try:
        custom = get_custom_preset(name)
        if custom is None:
            raise ChainValidationError(
                f"stage {index} preset is unknown: {name!r}"
            )
        validate_preset(custom)
    except ChainValidationError:
        raise
    except ValueError as exc:
        raise ChainValidationError(
            f"stage {index} custom preset is invalid"
        ) from exc
    return {
        "methods": deepcopy(custom.methods),
        "params": deepcopy(custom.params),
    }


def _require_exact_keys(
    value: Any,
    *,
    required: frozenset[str],
    context: str,
) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ChainValidationError(f"{context} must be a JSON object")
    if any(not isinstance(key, str) for key in value):
        raise ChainValidationError(f"{context} keys must be text")
    actual = set(value)
    missing = sorted(required - actual)
    unknown = sorted(actual - required)
    if missing:
        raise ChainValidationError(f"{context} is missing keys: {missing!r}")
    if unknown:
        raise ChainValidationError(f"{context} has unknown keys: {unknown!r}")
    return value


def chain_config_to_dict(config: ChainConfig) -> Dict[str, Any]:
    """Return the strict, versioned, shareable JSON representation."""
    validate_chain_config(config)
    stages = []
    for stage in config.stages:
        stages.append({
            "action": stage.action,
            "preset": stage.preset,
            "methods": deepcopy(stage.methods),
            "params": deepcopy(stage.params),
            "gate": {
                "kind": stage.gate.kind,
                "seconds": stage.gate.seconds,
                "packets": stage.gate.packets,
            },
            "verify_method": stage.verify_method,
            "verify_minimum": stage.verify_minimum,
        })
    return {
        "schema": CHAIN_SCHEMA,
        "target_ip": config.target_ip,
        "on_failure": config.on_failure,
        "global_timeout_s": config.global_timeout_s,
        "common_params": deepcopy(config.common_params),
        "stages": stages,
    }


def chain_config_from_dict(data: Any) -> ChainConfig:
    """Parse a strict v1 chain object, rejecting all unknown fields."""
    root = _require_exact_keys(
        data,
        required=frozenset({
            "schema",
            "target_ip",
            "on_failure",
            "global_timeout_s",
            "common_params",
            "stages",
        }),
        context="chain",
    )
    if root["schema"] != CHAIN_SCHEMA:
        raise ChainValidationError(
            f"unsupported chain schema: {root['schema']!r}"
        )
    raw_stages = root["stages"]
    if not isinstance(raw_stages, list):
        raise ChainValidationError("chain.stages must be a list")
    if len(raw_stages) > MAX_CHAIN_STAGES:
        raise ChainValidationError(
            f"chain exceeds the {MAX_CHAIN_STAGES}-stage limit"
        )
    stages: List[Stage] = []
    stage_keys = frozenset({
        "action",
        "preset",
        "methods",
        "params",
        "gate",
        "verify_method",
        "verify_minimum",
    })
    gate_keys = frozenset({"kind", "seconds", "packets"})
    for index, raw_stage in enumerate(raw_stages):
        stage_data = _require_exact_keys(
            raw_stage,
            required=stage_keys,
            context=f"chain.stages[{index}]",
        )
        gate_data = _require_exact_keys(
            stage_data["gate"],
            required=gate_keys,
            context=f"chain.stages[{index}].gate",
        )
        methods = stage_data["methods"]
        if methods is not None and not isinstance(methods, list):
            raise ChainValidationError(
                f"chain.stages[{index}].methods must be a list or null"
            )
        params = stage_data["params"]
        if params is not None and not isinstance(params, dict):
            raise ChainValidationError(
                f"chain.stages[{index}].params must be an object or null"
            )
        stages.append(Stage(
            action=stage_data["action"],
            preset=stage_data["preset"],
            methods=deepcopy(methods),
            params=deepcopy(params),
            gate=Gate(
                kind=gate_data["kind"],
                seconds=gate_data["seconds"],
                packets=gate_data["packets"],
            ),
            verify_method=stage_data["verify_method"],
            verify_minimum=stage_data["verify_minimum"],
        ))
    return ChainConfig(
        target_ip=root["target_ip"],
        stages=stages,
        on_failure=root["on_failure"],
        global_timeout_s=root["global_timeout_s"],
        common_params=deepcopy(root["common_params"]),
    )


def save_chain_config(config: ChainConfig, path: str | os.PathLike[str]) -> None:
    """Durably save one validated chain beside an exclusive temp file."""
    payload = json.dumps(
        chain_config_to_dict(config),
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"
    encoded = payload.encode("utf-8")
    if len(encoded) > MAX_CHAIN_JSON_BYTES:
        raise ChainValidationError(
            f"serialized chain exceeds {MAX_CHAIN_JSON_BYTES} bytes"
        )
    destination = Path(path)
    if not destination.name:
        raise ChainValidationError("chain save path must name a file")
    parent = destination.parent
    if not parent.is_dir():
        raise ChainValidationError("chain save directory does not exist")
    temp_path = ""
    try:
        fd, temp_path = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=str(parent),
            text=False,
        )
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, destination)
        temp_path = ""
    except OSError as exc:
        raise ChainValidationError("chain could not be saved") from exc
    finally:
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass


def load_chain_config(path: str | os.PathLike[str]) -> ChainConfig:
    """Load a bounded v1 chain file and validate it before returning."""
    try:
        with open(path, "rb") as handle:
            encoded = handle.read(MAX_CHAIN_JSON_BYTES + 1)
    except OSError as exc:
        raise ChainValidationError("chain could not be read") from exc
    if len(encoded) > MAX_CHAIN_JSON_BYTES:
        raise ChainValidationError(
            f"chain file exceeds {MAX_CHAIN_JSON_BYTES} bytes"
        )
    try:
        text = encoded.decode("utf-8-sig")
        data = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ChainValidationError("chain file is not valid UTF-8 JSON") from exc
    return chain_config_from_dict(data)


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
        validate_chain_config(config)
        # Freeze caller-owned stages and nested dictionaries for the lifetime
        # of the asynchronous run.  Mutating the editor after Start cannot
        # change an in-flight operation.
        self._cfg = deepcopy(config)
        validate_chain_config(self._cfg)
        self._controller = controller
        self._on_event = on_event or (lambda _e: None)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._started_ts: float = 0.0
        self._active_stage = False
        self._active_lock = threading.Lock()
        self._release_lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def release_confirmed(self) -> bool:
        """Whether this runner owns no unconfirmed active stage."""
        with self._active_lock:
            return not self._active_stage

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
            f"CutChainRunner started: target={mask_ip(self._cfg.target_ip)}, "
            f"stages={len(self._cfg.stages)}, "
            f"timeout={self._cfg.global_timeout_s}s"
        )

    def stop(self) -> bool:
        """Request cancellation and confirm release before reporting success."""
        self._stop.set()
        if (
            self._thread is not None
            and self._thread is not threading.current_thread()
        ):
            self._thread.join(timeout=2.0)
        released = self._release_active_stage()
        return bool(not self.running and released)

    def confirm_external_release(self) -> bool:
        """Acknowledge a successful controller-wide restore after exit."""
        if self.running:
            return False
        with self._release_lock:
            with self._active_lock:
                self._active_stage = False
        return True

    def _emit(self, event: ChainEvent) -> None:
        try:
            self._on_event(event)
        except Exception as exc:
            log_warning(
                "CutChainRunner callback raised "
                f"{type(exc).__name__}"
            )

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
            log_error(f"CutChainRunner crashed ({type(exc).__name__})")
            terminal_event = ChainEvent("error", -1, str(exc))
        finally:
            # Release before reporting the terminal event so a GUI cannot
            # display "complete" while packets are still being intercepted.
            if not self._release_active_stage():
                terminal_event = ChainEvent(
                    "error",
                    -1,
                    "stage release could not be confirmed",
                )
            if terminal_event is not None:
                self._emit(terminal_event)

    def _run_stage(self, idx: int, stage: Stage) -> None:
        # Build the disrupt call's payload — preset wins, overrides
        # layered on top.
        preset_def = _resolve_preset(stage.preset, index=idx)
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
        except Exception as exc:
            log_error(
                f"CutChainRunner stage {idx} disrupt raised "
                f"{type(exc).__name__}"
            )
            self._fail_stage(
                idx,
                f"disruption engine raised {type(exc).__name__}",
                cause=exc,
            )
            return
        if not ok:
            self._fail_stage(idx, "disruption engine refused the stage")
            return
        with self._active_lock:
            self._active_stage = True

        # Honor the gate before advancing.
        gate_ok, gate_detail = self._wait_gate(stage)
        if self._stop.is_set():
            if not self._release_active_stage():
                self._emit(ChainEvent(
                    "stage_end",
                    idx,
                    "operator stop; stage release could not be confirmed",
                ))
                raise RuntimeError(
                    "cut-chain stage release could not be confirmed"
                )
            self._emit(ChainEvent("stage_end", idx, "operator stop"))
            return
        if not gate_ok:
            self._fail_stage(idx, gate_detail)
            return

        verification_detail = gate_detail
        if stage.verify_method and not self._stop.is_set():
            verification, verification_detail = self._verify_stage_effect(
                stage.verify_method,
                max(1, int(stage.verify_minimum)),
            )
            if verification is False:
                self._fail_stage(idx, verification_detail)
                return

        # Always release between stages — the next stage opens a fresh
        # disruption rather than stacking on top of the old one.
        if not self._release_active_stage():
            self._emit(ChainEvent(
                "stage_end",
                idx,
                "stage release could not be confirmed",
            ))
            raise RuntimeError(
                "cut-chain stage release could not be confirmed"
            )
        self._emit(ChainEvent("stage_end", idx, verification_detail))

    def _fail_stage(
        self,
        idx: int,
        detail: str,
        *,
        cause: Optional[BaseException] = None,
    ) -> None:
        """Release and report one failure, then apply the configured policy."""
        if not self._release_active_stage():
            self._emit(ChainEvent(
                "stage_end",
                idx,
                f"{detail}; stage release could not be confirmed",
            ))
            raise RuntimeError(
                "cut-chain stage release could not be confirmed"
            )
        self._emit(ChainEvent("stage_end", idx, detail))
        if self._cfg.on_failure == "halt":
            error = RuntimeError(f"cut-chain stage failed: {detail}")
            if cause is not None:
                raise error from cause
            raise error
        log_warning(f"CutChainRunner stage {idx} failed; continuing: {detail}")

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
            log_warning(
                "stage effect verification failed "
                f"({type(exc).__name__})"
            )
            return None, f"{method} runtime verification unavailable"

    def _release_active_stage(self) -> bool:
        """Release once and clear ownership only after explicit confirmation."""
        with self._release_lock:
            with self._active_lock:
                if not self._active_stage:
                    return True
            try:
                stopped = self._controller.stop_disruption(
                    self._cfg.target_ip,
                    _cut_chain_runner=self,
                )
            except Exception as exc:
                log_error(
                    "CutChainRunner release raised "
                    f"{type(exc).__name__}; ownership retained"
                )
                return False
            if stopped is not True:
                log_error(
                    "CutChainRunner release was not confirmed; "
                    "ownership retained"
                )
                return False
            with self._active_lock:
                self._active_stage = False
            return True

    def _wait_gate(self, stage: Stage) -> tuple[bool, str]:
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
            return True, "advanced"

        if kind in ("severed", "connected"):
            return self._wait_a2s_state(
                kind,
                timeout_s=stage.gate.seconds,
            )

        if kind == "packets":
            return self._wait_packet_count(
                target=stage.gate.packets,
                timeout_s=stage.gate.seconds,
            )

        # Configuration is validated at construction and again at runner
        # ownership.  Keep the execution boundary fail closed if memory is
        # nevertheless corrupted after that point.
        raise ChainValidationError(f"unsupported gate kind: {kind!r}")

    def _wait_a2s_state(
        self,
        want: str,
        timeout_s: float,
    ) -> tuple[bool, str]:
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
                return True, f"a2s reached {want!r}"
            self._stop.wait(min(0.5, max(0.0, end - time.monotonic())))
        if self._stop.is_set():
            return False, "operator stop"
        return False, f"a2s gate {want!r} timed out after {timeout_s:.1f}s"

    def _wait_packet_count(
        self,
        target: int,
        timeout_s: float,
    ) -> tuple[bool, str]:
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
                return True, f"packets gate reached {count}/{target}"
            self._stop.wait(min(0.25, max(0.0, end - time.monotonic())))
        if self._stop.is_set():
            return False, "operator stop"
        return False, (
            f"packets gate {target} timed out after {timeout_s:.1f}s"
        )

    def _global_timed_out(self) -> bool:
        return (
            self._cfg.global_timeout_s > 0
            and time.monotonic() >= self._started_ts + self._cfg.global_timeout_s
        )

    def _global_deadline(self) -> Optional[float]:
        if self._cfg.global_timeout_s <= 0:
            return None
        return self._started_ts + self._cfg.global_timeout_s
