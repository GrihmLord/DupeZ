"""Monotonic bounded pulse scheduler with cooperative cancellation."""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from app.firewall.extensions.godmode.config import GodModeConfig
from app.firewall.extensions.godmode.state_machine import (
    GodModeState,
    GodModeStateMachine,
)

__all__ = ["ReleaseScheduler"]


class ReleaseScheduler:
    def __init__(
        self,
        config: GodModeConfig,
        state: GodModeStateMachine,
        release_batch: Callable[[Optional[int]], None],
        on_expire: Callable[[], None],
    ) -> None:
        self._config = config
        self._state = state
        self._release_batch = release_batch
        self._on_expire = on_expire
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._expires_at = 0.0

    @property
    def expires_at(self) -> float:
        return self._expires_at

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._state.transition(GodModeState.ARMED)
        self._expires_at = time.monotonic() + self._config.active_ms / 1000.0
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="GodModeReleaseScheduler",
        )
        self._thread.start()

    def _run(self) -> None:
        try:
            self._state.transition(GodModeState.ACTIVE)
            blocking = True
            phase_deadline = (
                time.monotonic() + self._config.block_ms / 1000.0
            )
            while not self._stop.wait(0.005):
                now = time.monotonic()
                if now >= self._expires_at:
                    self._state.transition(GodModeState.RELEASING)
                    self._release_batch(None)
                    self._on_expire()
                    self._state.transition(GodModeState.STOPPED)
                    return
                if now < phase_deadline:
                    if not blocking:
                        self._release_batch(self._config.release_batch)
                    continue
                blocking = not blocking
                if blocking:
                    self._state.transition(GodModeState.ACTIVE)
                    phase_deadline = now + self._config.block_ms / 1000.0
                else:
                    self._state.transition(GodModeState.RELEASING)
                    phase_deadline = now + self._config.release_ms / 1000.0
                    self._release_batch(self._config.release_batch)
        except Exception:
            try:
                self._state.transition(GodModeState.FAILED)
            except Exception:
                pass

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=max(0.0, timeout))

    @property
    def blocking(self) -> bool:
        return self._state.state is GodModeState.ACTIVE
