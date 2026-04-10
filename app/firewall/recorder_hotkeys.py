#!/usr/bin/env python3
"""
Recorder Hotkeys — Event tagging and recording controls for DupeZ.

Registers keyboard hotkeys for tagging game events during packet recording
and for controlling recording start/stop.

Default key bindings:
  F5:  Toggle recording ON/OFF
  F9:  Tag KILL (you killed someone)
  F10: Tag HIT  (you landed/took a hit)
  F11: Tag DEATH (you died)
  F12: Tag INVENTORY (inventory action)

These bindings work alongside the existing DupeZ hotkey system
(which uses 'w' for disruption toggle).

The hotkeys are registered globally so they work even when DayZ
has focus on the PS5 screen and DupeZ is in the background.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Dict, Optional

from app.logs.logger import log_info, log_error

try:
    import keyboard
    _KB_AVAILABLE = True
except ImportError:
    _KB_AVAILABLE = False

__all__ = ["DEFAULT_BINDINGS", "RecorderHotkeys"]


# Default key bindings
DEFAULT_BINDINGS = {
    "f5": "TOGGLE_RECORDING",
    "f9": "KILL",
    "f10": "HIT",
    "f11": "DEATH",
    "f12": "INVENTORY",
}


class RecorderHotkeys:
    """Registers hotkeys for packet recording event tagging.

    Connects to a GodModeModule instance to call tag_event(),
    start_recording(), and stop_recording().

    Usage:
        hotkeys = RecorderHotkeys(godmode_module)
        hotkeys.start()
        # ... gameplay ...
        hotkeys.stop()
    """

    def __init__(self, godmode_module=None,
                 bindings: Optional[Dict[str, str]] = None) -> None:
        self._godmode = godmode_module
        self._bindings = bindings or dict(DEFAULT_BINDINGS)
        self._handles: Dict[str, object] = {}
        self._running = False
        self._cooldown = 0.3  # seconds between same-key triggers
        self._last_trigger: Dict[str, float] = {}

    def set_godmode(self, godmode_module) -> None:
        """Set or update the GodModeModule reference."""
        self._godmode = godmode_module

    def start(self) -> bool:
        """Register all hotkeys. Returns True if successful."""
        if not _KB_AVAILABLE:
            log_error("[RecorderHotkeys] keyboard module not available")
            return False

        if self._running:
            return True

        try:
            for key, action in self._bindings.items():
                self._register(key, action)
            self._running = True
            log_info(f"[RecorderHotkeys] Active: {self._format_bindings()}")
            return True
        except Exception as exc:
            log_error(f"[RecorderHotkeys] Start failed: {exc}")
            return False

    def stop(self) -> None:
        """Unregister all hotkeys."""
        if not self._running:
            return

        for key, handle in self._handles.items():
            try:
                keyboard.remove_hotkey(handle)
            except Exception:
                pass

        self._handles.clear()
        self._running = False
        log_info("[RecorderHotkeys] Stopped")

    def _register(self, key: str, action: str) -> None:
        """Register a single hotkey."""
        def callback():
            self._on_key(key, action)

        try:
            handle = keyboard.add_hotkey(key, callback, suppress=False)
            self._handles[key] = handle
        except Exception as exc:
            log_error(f"[RecorderHotkeys] Failed to register {key}: {exc}")

    def _on_key(self, key: str, action: str) -> None:
        """Handle a hotkey press with cooldown."""
        now = time.time()
        last = self._last_trigger.get(key, 0.0)
        if now - last < self._cooldown:
            return
        self._last_trigger[key] = now

        if self._godmode is None:
            log_info(f"[RecorderHotkeys] {key}→{action} (no GodMode attached)")
            return

        if action == "TOGGLE_RECORDING":
            self._toggle_recording()
        else:
            # Event tag
            self._godmode.tag_event(action)

    def _toggle_recording(self) -> None:
        """Toggle packet recording on/off."""
        if self._godmode is None:
            return

        if self._godmode.is_recording:
            path = self._godmode.stop_recording()
            if path:
                log_info(f"[RecorderHotkeys] Recording STOPPED → {path}")
            else:
                log_info("[RecorderHotkeys] Recording STOPPED (no output)")
        else:
            name = self._godmode.start_recording()
            log_info(f"[RecorderHotkeys] Recording STARTED: {name}")

    def _format_bindings(self) -> str:
        """Format bindings for logging."""
        parts = []
        for key, action in self._bindings.items():
            parts.append(f"{key.upper()}={action}")
        return ", ".join(parts)

    @property
    def is_running(self) -> bool:
        return self._running

    def get_bindings(self) -> Dict[str, str]:
        return dict(self._bindings)

    def set_binding(self, key: str, action: str) -> None:
        """Change a key binding. Takes effect on next start()."""
        self._bindings[key] = action
