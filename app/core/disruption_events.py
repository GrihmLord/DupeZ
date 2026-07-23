# app/core/disruption_events.py — user-configurable event sequences
"""Toggleable disruption events layered over DupeZ's existing controller.

An event is an operator-owned unit of work: effects plus engine, capture layer,
delay, duration, and failure policy. Events run sequentially on a background
thread and remain bounded by the controller's private-target and operation-
deadline safety policy.

The runner records the manager generation created by each start. Before it
stops a target it checks that generation again, preventing a late timer from
releasing a newer manual disruption on the same target.
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
import uuid
from copy import deepcopy
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Callable, Dict, List, Optional

from app.logs.logger import log_error, log_info, log_warning
from app.utils.helpers import mask_ip

__all__ = [
    "ENGINE_AUTO",
    "ENGINE_CLUMSY",
    "ENGINE_NATIVE",
    "LAYER_AUTO",
    "LAYER_LOCAL",
    "LAYER_REMOTE",
    "FAILURE_HALT",
    "FAILURE_CONTINUE",
    "DisruptionEvent",
    "EventSequence",
    "EventSequenceStatus",
    "EventSequenceRunner",
    "EventSequenceStore",
]

ENGINE_AUTO = "auto"
ENGINE_CLUMSY = "clumsy"
ENGINE_NATIVE = "native"
_VALID_ENGINES = frozenset({ENGINE_AUTO, ENGINE_CLUMSY, ENGINE_NATIVE})

LAYER_AUTO = "auto"
LAYER_LOCAL = "local"
LAYER_REMOTE = "remote"
_VALID_LAYERS = frozenset({LAYER_AUTO, LAYER_LOCAL, LAYER_REMOTE})

FAILURE_HALT = "halt"
FAILURE_CONTINUE = "continue"
_VALID_FAILURE_POLICIES = frozenset({FAILURE_HALT, FAILURE_CONTINUE})

MAX_EVENT_SECONDS = 3600.0
MAX_EVENT_DELAY_SECONDS = 3600.0
MAX_SEQUENCE_EVENTS = 100
MAX_SEQUENCE_REPEATS = 100


def _bounded_float(
    value: Any,
    *,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    if not math.isfinite(parsed):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _safe_identifier(value: Any, prefix: str) -> str:
    text = str(value or "").strip()
    if text and all(character.isalnum() or character in "-_" for character in text):
        return text
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@dataclass
class DisruptionEvent:
    """One toggleable disruption event."""

    event_id: str = ""
    name: str = "Event"
    enabled: bool = True
    methods: List[str] = field(default_factory=list)
    params: Dict[str, Any] = field(default_factory=dict)
    engine_preference: str = ENGINE_AUTO
    network_layer: str = LAYER_AUTO
    start_delay_seconds: float = 0.0
    duration_seconds: float = 10.0
    failure_policy: str = FAILURE_HALT

    def __post_init__(self) -> None:
        self.event_id = _safe_identifier(self.event_id, "event")
        self.name = str(self.name or "Event").strip()[:80] or "Event"
        self.enabled = bool(self.enabled)
        self.methods = list(dict.fromkeys(
            str(method).strip()
            for method in self.methods
            if str(method).strip()
        ))
        self.params = deepcopy(dict(self.params or {}))
        engine = str(self.engine_preference or ENGINE_AUTO).strip().lower()
        self.engine_preference = (
            engine if engine in _VALID_ENGINES else ENGINE_AUTO
        )
        layer = str(self.network_layer or LAYER_AUTO).strip().lower()
        self.network_layer = layer if layer in _VALID_LAYERS else LAYER_AUTO
        self.start_delay_seconds = _bounded_float(
            self.start_delay_seconds,
            default=0.0,
            minimum=0.0,
            maximum=MAX_EVENT_DELAY_SECONDS,
        )
        self.duration_seconds = _bounded_float(
            self.duration_seconds,
            default=10.0,
            minimum=0.1,
            maximum=MAX_EVENT_SECONDS,
        )
        policy = str(self.failure_policy or FAILURE_HALT).strip().lower()
        self.failure_policy = (
            policy if policy in _VALID_FAILURE_POLICIES else FAILURE_HALT
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "DisruptionEvent":
        known = {item.name for item in fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in known})

    def resolved_params(self) -> Dict[str, Any]:
        """Return an isolated engine payload with explicit routing metadata."""

        params = deepcopy(self.params)
        params["_engine_preference"] = self.engine_preference
        if self.network_layer == LAYER_AUTO:
            params.pop("_network_local", None)
            params.pop("_network_layer_explicit", None)
        else:
            params["_network_local"] = self.network_layer == LAYER_LOCAL
            params["_network_layer_explicit"] = True
        return params


@dataclass
class EventSequence:
    """A named ordered collection of disruption events."""

    sequence_id: str = ""
    name: str = "Custom Event Queue"
    events: List[DisruptionEvent] = field(default_factory=list)
    repeat_count: int = 1

    def __post_init__(self) -> None:
        self.sequence_id = _safe_identifier(self.sequence_id, "sequence")
        self.name = (
            str(self.name or "Custom Event Queue").strip()[:80]
            or "Custom Event Queue"
        )
        try:
            repeats = int(self.repeat_count)
        except (TypeError, ValueError):
            repeats = 1
        self.repeat_count = max(1, min(MAX_SEQUENCE_REPEATS, repeats))
        normalized: list[DisruptionEvent] = []
        for event in list(self.events or [])[:MAX_SEQUENCE_EVENTS]:
            normalized.append(
                event
                if isinstance(event, DisruptionEvent)
                else DisruptionEvent.from_dict(dict(event))
            )
        self.events = normalized

    def to_dict(self) -> dict:
        return {
            "sequence_id": self.sequence_id,
            "name": self.name,
            "repeat_count": self.repeat_count,
            "events": [event.to_dict() for event in self.events],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EventSequence":
        return cls(
            sequence_id=data.get("sequence_id", ""),
            name=data.get("name", "Custom Event Queue"),
            repeat_count=data.get("repeat_count", 1),
            events=[
                DisruptionEvent.from_dict(item)
                for item in data.get("events", [])
                if isinstance(item, dict)
            ],
        )


@dataclass(frozen=True)
class EventSequenceStatus:
    """Privacy-safe event transition delivered to UI callbacks."""

    kind: str
    event_index: int = -1
    event_id: str = ""
    event_name: str = ""
    detail: str = ""
    actual_engine: str = ""


class EventSequenceRunner:
    """Execute an EventSequence without blocking the Qt thread."""

    def __init__(
        self,
        sequence: EventSequence,
        controller: Any,
        target_ip: str,
        *,
        disrupt_kwargs: Optional[Dict[str, Any]] = None,
        on_status: Optional[Callable[[EventSequenceStatus], None]] = None,
    ) -> None:
        self._sequence = EventSequence.from_dict(sequence.to_dict())
        self._controller = controller
        self._target_ip = str(target_ip)
        self._disrupt_kwargs = deepcopy(dict(disrupt_kwargs or {}))
        self._on_status = on_status or (lambda _status: None)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._active_generation: Optional[int] = None
        self._active_event_index = -1
        self._state_lock = threading.Lock()

    @property
    def running(self) -> bool:
        return bool(self._thread is not None and self._thread.is_alive())

    def start(self) -> bool:
        if self.running:
            return False
        if not any(event.enabled for event in self._sequence.events):
            self._emit(EventSequenceStatus(
                kind="error",
                detail="No enabled events",
            ))
            return False
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="DupeZEventSequence",
            daemon=True,
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=2.0)
        self._release_owned_event()

    def _emit(self, status: EventSequenceStatus) -> None:
        try:
            self._on_status(status)
        except Exception as exc:
            log_warning(f"Event sequence callback failed: {exc}")

    def _wait(self, seconds: float) -> bool:
        return self._stop_event.wait(max(0.0, float(seconds)))

    def _run(self) -> None:
        terminal = EventSequenceStatus(kind="complete", detail="queue complete")
        try:
            for cycle in range(self._sequence.repeat_count):
                for index, event in enumerate(self._sequence.events):
                    if self._stop_event.is_set():
                        terminal = EventSequenceStatus(
                            kind="stopped",
                            event_index=index,
                            detail="operator stop",
                        )
                        return
                    if not event.enabled:
                        self._emit(EventSequenceStatus(
                            kind="skipped",
                            event_index=index,
                            event_id=event.event_id,
                            event_name=event.name,
                            detail="disabled",
                        ))
                        continue

                    if event.start_delay_seconds and self._wait(
                        event.start_delay_seconds
                    ):
                        terminal = EventSequenceStatus(
                            kind="stopped",
                            event_index=index,
                            event_id=event.event_id,
                            event_name=event.name,
                            detail="stopped during delay",
                        )
                        return

                    self._emit(EventSequenceStatus(
                        kind="starting",
                        event_index=index,
                        event_id=event.event_id,
                        event_name=event.name,
                        detail=f"cycle {cycle + 1}",
                    ))

                    started = bool(self._controller.disrupt_device(
                        self._target_ip,
                        list(event.methods),
                        event.resolved_params(),
                        operation_timeout=event.duration_seconds + 5.0,
                        **deepcopy(self._disrupt_kwargs),
                    ))
                    if not started:
                        detail = self._last_engine_error() or "start returned False"
                        self._emit(EventSequenceStatus(
                            kind="error",
                            event_index=index,
                            event_id=event.event_id,
                            event_name=event.name,
                            detail=detail,
                        ))
                        if event.failure_policy == FAILURE_HALT:
                            terminal = EventSequenceStatus(
                                kind="halted",
                                event_index=index,
                                event_id=event.event_id,
                                event_name=event.name,
                                detail=detail,
                            )
                            return
                        continue

                    status = self._controller.get_disruption_status(
                        self._target_ip
                    ) or {}
                    generation = status.get("generation")
                    with self._state_lock:
                        self._active_generation = (
                            int(generation) if generation is not None else None
                        )
                        self._active_event_index = index
                    actual_engine = str(status.get("engine") or "")
                    self._emit(EventSequenceStatus(
                        kind="active",
                        event_index=index,
                        event_id=event.event_id,
                        event_name=event.name,
                        detail=f"{event.duration_seconds:g}s",
                        actual_engine=actual_engine,
                    ))

                    self._wait(event.duration_seconds)
                    self._release_owned_event()
                    self._emit(EventSequenceStatus(
                        kind="finished",
                        event_index=index,
                        event_id=event.event_id,
                        event_name=event.name,
                        actual_engine=actual_engine,
                    ))

                    if self._stop_event.is_set():
                        terminal = EventSequenceStatus(
                            kind="stopped",
                            event_index=index,
                            event_id=event.event_id,
                            event_name=event.name,
                            detail="operator stop",
                        )
                        return
        except Exception as exc:
            log_error(f"Event sequence crashed: {exc}")
            terminal = EventSequenceStatus(kind="error", detail=str(exc))
        finally:
            self._release_owned_event()
            self._emit(terminal)

    def _last_engine_error(self) -> str:
        try:
            status = self._controller.get_clumsy_status() or {}
            return str(status.get("last_engine_error") or "")
        except Exception:
            return ""

    def _release_owned_event(self) -> None:
        with self._state_lock:
            expected_generation = self._active_generation
            self._active_generation = None
            self._active_event_index = -1
        if expected_generation is None:
            return
        try:
            current = self._controller.get_disruption_status(
                self._target_ip
            ) or {}
            current_generation = current.get("generation")
            if current_generation is None or int(current_generation) != expected_generation:
                log_info(
                    "Event sequence did not stop a newer target generation: "
                    f"{mask_ip(self._target_ip)}"
                )
                return
            self._controller.stop_disruption(self._target_ip)
        except Exception as exc:
            log_error(
                "Event sequence release failed for "
                f"{mask_ip(self._target_ip)}: {exc}"
            )


class EventSequenceStore:
    """Atomic per-user persistence for custom event queues."""

    def __init__(self, data_dir: str = "") -> None:
        if not data_dir:
            from app.core.data_persistence import _resolve_data_directory

            data_dir = _resolve_data_directory()
        self._path = os.path.join(data_dir, "disruption_events.json")
        self._lock = threading.RLock()
        self._sequences: Dict[str, EventSequence] = {}
        self._load()

    def list_sequences(self) -> List[EventSequence]:
        with self._lock:
            return [
                EventSequence.from_dict(sequence.to_dict())
                for sequence in self._sequences.values()
            ]

    def get(self, sequence_id: str) -> Optional[EventSequence]:
        with self._lock:
            sequence = self._sequences.get(sequence_id)
            return (
                EventSequence.from_dict(sequence.to_dict())
                if sequence is not None
                else None
            )

    def save(self, sequence: EventSequence) -> str:
        normalized = EventSequence.from_dict(sequence.to_dict())
        with self._lock:
            self._sequences[normalized.sequence_id] = normalized
            self._persist()
        return normalized.sequence_id

    def delete(self, sequence_id: str) -> bool:
        with self._lock:
            existed = self._sequences.pop(sequence_id, None) is not None
            if existed:
                self._persist()
            return existed

    def _persist(self) -> None:
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        payload = {
            "schema": "dupez.disruption-events.v1",
            "sequences": {
                key: value.to_dict()
                for key, value in self._sequences.items()
            },
        }
        temporary = self._path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as file_handle:
            json.dump(payload, file_handle, indent=2, sort_keys=True)
            file_handle.flush()
            os.fsync(file_handle.fileno())
        os.replace(temporary, self._path)

    def _load(self) -> None:
        try:
            if not os.path.exists(self._path):
                return
            with open(self._path, encoding="utf-8") as file_handle:
                payload = json.load(file_handle)
            if payload.get("schema") != "dupez.disruption-events.v1":
                log_warning("Ignoring unsupported disruption-event schema")
                return
            for key, value in payload.get("sequences", {}).items():
                if isinstance(value, dict):
                    sequence = EventSequence.from_dict(value)
                    self._sequences[key] = sequence
        except Exception as exc:
            log_error(f"Disruption event store load failed: {exc}")
