"""Qt-thread dispatch and explicit ownership for opt-in disruption shortcuts."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QObject, Qt, pyqtSignal, pyqtSlot

from app.core.hotkey_settings import validate_hotkey_settings
from app.logs.logger import log_error


class DisruptionHotkeys(QObject):
    """Route single-action hooks to Qt; never select targets or change presets.

    Registration means the keyboard backend accepted the hook, not that another
    application cannot consume the chord. All actions fire on key release.
    Emergency bindings are independent of Start registration failures.
    """

    _requested = pyqtSignal(int, str, int)
    ACTIONS = ("panic", "stop", "start")

    def __init__(
        self, parent: QObject | None, *, manager: Any,
        callbacks: dict[str, Callable[[], None]], backend_available: bool,
    ) -> None:
        super().__init__(parent)
        self._manager = manager
        self._callbacks = callbacks
        self._backend_available = backend_available and manager is not None
        self._lock = threading.RLock()
        self._generation = 0
        self._start_epoch = 0
        self._allowed: set[str] = set()
        self._listeners: dict[str, Any] = {}
        self._configured: dict[str, str] = {}
        self._states = dict.fromkeys(self.ACTIONS, "Disabled")
        self._errors = dict.fromkeys(self.ACTIONS, "")
        self._requested.connect(self._dispatch, Qt.ConnectionType.QueuedConnection)

    def _callback(self, action: str) -> Callable[[], None]:
        generation = self._generation
        if action == "start":
            start_epoch = self._start_epoch
            return lambda: self._queue(generation, action, start_epoch)
        return lambda: self._queue(generation, action)

    def _advance_start_epoch(self) -> None:
        """Called under the dispatch lock; accepted callbacks keep the old epoch."""
        self._start_epoch += 1
        listener = self._listeners.get("start")
        if listener is not None:
            listener.set_callback(self._callback("start"))

    def _queue(self, generation: int, action: str, start_epoch: int | None = None) -> None:
        with self._lock:
            if generation != self._generation or action not in self._allowed:
                return
            if action == "start" and start_epoch != self._start_epoch:
                return
            if action in ("stop", "panic"):
                self._advance_start_epoch()
            self._requested.emit(generation, action, self._start_epoch)

    @pyqtSlot(int, str, int)
    def _dispatch(self, generation: int, action: str, start_epoch: int) -> None:
        with self._lock:
            if generation != self._generation or action not in self._allowed:
                return
            if action == "start" and start_epoch != self._start_epoch:
                return
            if action in ("stop", "panic"):
                self._advance_start_epoch()
        try:
            self._callbacks[action]()
        except Exception as exc:
            log_error(f"Global {action} hotkey action failed: {exc}")

    def cancel_pending_starts(self) -> None:
        """Let local emergency actions also cancel already-queued Start work."""
        with self._lock:
            self._advance_start_epoch()

    def _invalidate(self) -> None:
        with self._lock:
            self._generation += 1
            self._allowed.clear()

    def _remove(self, action: str) -> bool:
        listener = self._listeners.get(action)
        if listener is None:
            return True
        try:
            if not self._manager.remove_listener(f"disruption_{action}"):
                raise RuntimeError(listener.last_error or "Hook cleanup pending")
        except Exception as exc:
            self._errors[action] = str(exc)
            self._states[action] = "Disarmed; cleanup pending"
            return False
        self._listeners.pop(action, None)
        return True

    def configure(self, settings: Any) -> bool:
        """Apply saved settings with truthful partial-success reporting.

        Start is always disarmed before rebinding. If an emergency rebind fails,
        its previous working chord can remain armed and is reported explicitly.
        Chords still owned by another action cannot be reused until released.
        """
        # Publish bindings and their immutable callback epochs together. A
        # backend emergency callback cannot advance an epoch halfway through
        # construction of the new Start listener.
        with self._lock:
            return self._configure(settings)

    def _configure(self, settings: Any) -> bool:
        self._invalidate()
        self._errors = dict.fromkeys(self.ACTIONS, "")
        self._states = dict.fromkeys(self.ACTIONS, "Disabled")
        try:
            self._configured = validate_hotkey_settings(settings)
        except ValueError as exc:
            self._configured = {}
            self.close()
            for action in self.ACTIONS:
                cleanup_error = self._errors[action]
                if cleanup_error:
                    self._states[action] = "Invalid settings; disarmed; cleanup pending"
                    self._errors[action] = f"{exc}; cleanup pending: {cleanup_error}"
                else:
                    self._states[action] = "Invalid settings; disarmed"
                    self._errors[action] = str(exc)
            return False

        # This also releases its old chord before emergency bindings are staged.
        success = self._remove("start")
        enabled = getattr(settings, "disruption_hotkeys_enabled", False)
        for action in self.ACTIONS:
            wanted = enabled and (
                action != "start" or getattr(settings, "disruption_start_hotkey_enabled", False)
            )
            if not wanted or not self._backend_available:
                success = self._remove(action) and success
                if wanted:
                    self._states[action] = "Unavailable in this session"
                    success = False
                continue
            listener = self._listeners.get(action)
            try:
                if action == "start" and not all(
                    self.active_keys(emergency) for emergency in ("panic", "stop")
                ):
                    raise RuntimeError("Start requires registered Stop All and Panic Stop hooks")
                key = self._configured[action]
                callback = self._callback(action)
                # Snapshot the dispatch generation even when an emergency
                # listener retains its previous working chord after a failure.
                if listener is not None:
                    listener.set_callback(callback)
                for name, other in self._manager.get_all_listeners().items():
                    if name != f"disruption_{action}" and key in other.get_owned_keys():
                        raise RuntimeError(
                            f"{key} is still owned by {name}; choose an unused chord first"
                        )
                if listener is None:
                    listener = self._manager.add_listener(
                        f"disruption_{action}",
                        callback=callback,
                        keys=[key], config={"trigger_on_release": True},
                    )
                    self._listeners[action] = listener
                elif not listener.set_keys([key]):
                    raise RuntimeError(listener.last_error or "Rebinding failed")
                if not listener.start():
                    raise RuntimeError(listener.last_error or "Registration failed")
                self._states[action] = "Registered (key release)"
            except Exception as exc:
                success = False
                self._errors[action] = str(exc)
                self._states[action] = "Registration failed"
                if action == "start":
                    self._remove(action)
                elif listener is not None and listener.is_running:
                    self._states[action] = "Previous chord retained (key release)"
            if listener is not None and listener.is_running and (
                action != "start" or not self._errors[action]
            ):
                with self._lock:
                    self._allowed.add(action)
        return success

    def active_keys(self, action: str) -> list[str]:
        with self._lock:
            listener = self._listeners.get(action)
            if action not in self._allowed or listener is None:
                return []
            return listener.get_active_keys()

    def status(self) -> list[dict[str, Any]]:
        return [
            {
                "action": action,
                "configured": self._configured.get(action, ""),
                "active": self.active_keys(action),
                "state": self._states[action],
                "error": self._errors[action],
            }
            for action in self.ACTIONS
        ]

    def close(self) -> bool:
        """Invalidate queued work before attempting every independent cleanup."""
        self._invalidate()
        success = True
        for action in self.ACTIONS:
            self._states[action] = "Disabled"
            if self._remove(action):
                self._errors[action] = ""
            else:
                success = False
        return success
