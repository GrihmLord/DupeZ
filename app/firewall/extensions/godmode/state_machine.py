"""Legal lifecycle transitions for the God Mode extension."""

from __future__ import annotations

import threading
from enum import Enum

__all__ = ["GodModeState", "GodModeStateMachine", "IllegalTransition"]


class GodModeState(str, Enum):
    IDLE = "idle"
    ARMED = "armed"
    ACTIVE = "active"
    RELEASING = "releasing"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class IllegalTransition(RuntimeError):
    pass


_LEGAL = {
    GodModeState.IDLE: {GodModeState.ARMED, GodModeState.FAILED},
    GodModeState.ARMED: {
        GodModeState.ACTIVE,
        GodModeState.STOPPING,
        GodModeState.FAILED,
    },
    GodModeState.ACTIVE: {
        GodModeState.RELEASING,
        GodModeState.STOPPING,
        GodModeState.FAILED,
    },
    GodModeState.RELEASING: {
        GodModeState.ACTIVE,
        GodModeState.STOPPING,
        GodModeState.STOPPED,
        GodModeState.FAILED,
    },
    GodModeState.STOPPING: {GodModeState.STOPPED, GodModeState.FAILED},
    GodModeState.STOPPED: set(),
    GodModeState.FAILED: {GodModeState.STOPPING, GodModeState.STOPPED},
}


class GodModeStateMachine:
    def __init__(self) -> None:
        self._state = GodModeState.IDLE
        self._lock = threading.RLock()

    @property
    def state(self) -> GodModeState:
        with self._lock:
            return self._state

    def transition(self, target: GodModeState) -> None:
        with self._lock:
            if target is self._state:
                return
            if target not in _LEGAL[self._state]:
                raise IllegalTransition(
                    f"illegal God Mode transition {self._state.value} -> "
                    f"{target.value}"
                )
            self._state = target
