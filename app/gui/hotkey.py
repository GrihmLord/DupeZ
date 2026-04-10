# app/gui/hotkey.py — Global Hotkey Listener for DupeZ
"""
Keyboard hotkey registration and lifecycle management.

Provides ``HotkeyListener`` for registering global hotkeys with
configurable cooldown and per-key callback support.  A companion
``HotkeyManager`` tracks multiple named listeners.

The ``keyboard`` package is optional — if unavailable, listeners
degrade gracefully and ``HotkeyListener.start()`` returns ``False``.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Dict, List, Optional

from app.logs.logger import log_error, log_info

try:
    import keyboard
    _KEYBOARD_AVAILABLE: bool = True
except ImportError:
    _KEYBOARD_AVAILABLE = False
    log_error("keyboard module not available — hotkeys disabled")

__all__ = ["HotkeyListener", "HotkeyManager", "KEYBOARD_AVAILABLE"]

# Re-export for legacy imports
KEYBOARD_AVAILABLE: bool = _KEYBOARD_AVAILABLE


class HotkeyListener:
    """Register one or more global hotkeys that invoke a shared callback.

    Parameters:
        callback:  Callable invoked when any registered key is pressed.
        keys:      Key names recognised by the ``keyboard`` library.
                   Defaults to ``["w"]``.
        config:    Optional overrides — ``cooldown`` (float, seconds between
                   triggers, default 0.5) and ``enabled`` (bool, default True).

    Usage::

        listener = HotkeyListener(controller.toggle_lag)
        listener.start()
        # … later …
        listener.stop()
    """

    def __init__(
        self,
        callback: Callable[[], None],
        keys: Optional[List[str]] = None,
        config: Optional[Dict] = None,
    ) -> None:
        self._callback = callback
        self._keys: List[str] = list(keys) if keys else ["w"]
        self._config: Dict = config or {}
        self._running: bool = False
        self._thread: Optional[threading.Thread] = None
        self._hotkey_handles: Dict[str, object] = {}

        # Cooldown prevents rapid re-triggers (e.g. held key)
        self._cooldown: float = max(0.1, float(self._config.get("cooldown", 0.5)))
        self._last_trigger: float = 0.0
        self._enabled: bool = bool(self._config.get("enabled", True))

        if not _KEYBOARD_AVAILABLE:
            log_error("Hotkey functionality disabled — keyboard module missing")
            self._enabled = False

    # ── Lifecycle ────────────────────────────────────────────────────

    def start(self) -> bool:
        """Register hotkeys and begin listening.  Returns ``True`` on success."""
        if not self._enabled:
            log_info("Hotkeys disabled — skipping start")
            return False

        if self._running:
            log_info("Hotkey listener already running")
            return True

        try:
            self._running = True
            self._thread = threading.Thread(
                target=self._listen_loop, daemon=True, name="HotkeyListener",
            )
            self._thread.start()
            log_info(f"Hotkey listener started: {', '.join(self._keys)}")
            return True
        except Exception as exc:
            log_error(f"Failed to start hotkey listener: {exc}")
            self._running = False
            return False

    def stop(self) -> None:
        """Unregister all hotkeys and join the listener thread."""
        if not self._running:
            return

        self._running = False

        for key, handle in self._hotkey_handles.items():
            try:
                keyboard.remove_hotkey(handle)
            except Exception as exc:
                log_error(f"Error removing hotkey '{key}': {exc}")

        self._hotkey_handles.clear()

        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

        log_info("Hotkey listener stopped")

    # ── Internal ─────────────────────────────────────────────────────

    def _listen_loop(self) -> None:
        """Worker thread: register hotkeys then keep alive until stopped."""
        try:
            for key in self._keys:
                self._register(key)
            while self._running:
                time.sleep(0.1)
        except Exception as exc:
            log_error(f"Hotkey listener error: {exc}")
        finally:
            self._running = False

    def _register(self, key: str) -> None:
        """Register a single global hotkey.  ``suppress=False`` avoids
        stealing keystrokes from other applications."""
        try:
            handle = keyboard.add_hotkey(
                key, lambda k=key: self._on_trigger(k), suppress=False,
            )
            self._hotkey_handles[key] = handle
            log_info(f"Registered hotkey: {key}")
        except Exception as exc:
            log_error(f"Failed to register hotkey '{key}': {exc}")

    def _on_trigger(self, key: str) -> None:
        """Handle a hotkey press with cooldown protection."""
        if not self._running:
            return
        now = time.time()
        if now - self._last_trigger < self._cooldown:
            return
        self._last_trigger = now
        try:
            log_info(f"Hotkey triggered: {key}")
            self._callback()
        except Exception as exc:
            log_error(f"Hotkey callback error: {exc}")

    # ── Key management ───────────────────────────────────────────────

    def add_key(self, key: str) -> None:
        """Add and optionally register a new hotkey at runtime."""
        if key in self._keys:
            return
        self._keys.append(key)
        if self._running:
            self._register(key)
        log_info(f"Added hotkey: {key}")

    def remove_key(self, key: str) -> None:
        """Remove and unregister a hotkey."""
        if key not in self._keys:
            return
        self._keys.remove(key)
        handle = self._hotkey_handles.pop(key, None)
        if handle is not None:
            try:
                keyboard.remove_hotkey(handle)
            except Exception as exc:
                log_error(f"Error removing hotkey '{key}': {exc}")
        log_info(f"Removed hotkey: {key}")

    def set_keys(self, keys: List[str]) -> None:
        """Replace the entire key set.  Active registrations are updated."""
        for key in list(self._keys):
            self.remove_key(key)
        for key in keys:
            self.add_key(key)

    # ── Queries ──────────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        """Whether the listener thread is active."""
        return self._running

    def get_active_keys(self) -> List[str]:
        """Return a copy of the registered key list."""
        return list(self._keys)

    # ── Configuration ────────────────────────────────────────────────

    def set_cooldown(self, cooldown: float) -> None:
        """Set the minimum interval between triggers (seconds)."""
        self._cooldown = max(0.1, cooldown)
        log_info(f"Hotkey cooldown set to {self._cooldown:.2f}s")

    def enable(self) -> None:
        """Enable hotkey functionality (does not auto-start)."""
        self._enabled = True
        log_info("Hotkeys enabled")

    def disable(self) -> None:
        """Disable hotkeys and stop the listener if running."""
        self._enabled = False
        self.stop()
        log_info("Hotkeys disabled")


class HotkeyManager:
    """Named-listener registry for managing multiple ``HotkeyListener`` instances.

    Usage::

        mgr = HotkeyManager()
        mgr.add_listener("toggle_lag", controller.toggle_lag, keys=["w"])
        mgr.start_all()
        # … later …
        mgr.stop_all()
    """

    def __init__(self) -> None:
        self._listeners: Dict[str, HotkeyListener] = {}

    def add_listener(
        self,
        name: str,
        callback: Callable[[], None],
        keys: Optional[List[str]] = None,
        config: Optional[Dict] = None,
    ) -> HotkeyListener:
        """Create and register a named listener."""
        listener = HotkeyListener(callback, keys, config)
        self._listeners[name] = listener
        return listener

    def remove_listener(self, name: str) -> None:
        """Stop and remove a named listener."""
        listener = self._listeners.pop(name, None)
        if listener is not None:
            listener.stop()
            log_info(f"Removed hotkey listener: {name}")

    def start_all(self) -> None:
        """Start every registered listener."""
        for listener in self._listeners.values():
            listener.start()

    def stop_all(self) -> None:
        """Stop every registered listener."""
        for listener in self._listeners.values():
            listener.stop()

    def get_listener(self, name: str) -> Optional[HotkeyListener]:
        """Look up a listener by name."""
        return self._listeners.get(name)

    def get_all_listeners(self) -> Dict[str, HotkeyListener]:
        """Return a shallow copy of the listener registry."""
        return dict(self._listeners)


# ── Module-level convenience ─────────────────────────────────────────

# Global singleton — lazily used by dashboard.py and main.py
hotkey_manager = HotkeyManager()


def create_hotkey_listener(
    callback: Callable[[], None],
    keys: Optional[List[str]] = None,
    config: Optional[Dict] = None,
) -> HotkeyListener:
    """Factory function for one-off listeners."""
    return HotkeyListener(callback, keys, config)


def get_hotkey_manager() -> HotkeyManager:
    """Return the global HotkeyManager singleton."""
    return hotkey_manager
