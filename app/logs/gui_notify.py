# app/logs/gui_notify.py — Cross-layer GUI toast hook.
"""Backend code can call :func:`gui_toast(level, message)` without
importing Qt. The GUI registers a callback at startup and receives the
notifications on the main thread.

Levels: "info" | "warn" | "error"
"""

from __future__ import annotations

from threading import Lock
from typing import Callable, Optional

_Callback = Callable[[str, str], None]

_lock = Lock()
_callback: Optional[_Callback] = None

__all__ = ["gui_toast", "register_gui_toast", "clear_gui_toast"]


def register_gui_toast(cb: _Callback) -> None:
    """Register the GUI callback. Called once at app startup."""
    global _callback
    with _lock:
        _callback = cb


def clear_gui_toast() -> None:
    """Remove the registered callback (on shutdown)."""
    global _callback
    with _lock:
        _callback = None


def gui_toast(level: str, message: str) -> None:
    """Emit a toast if a GUI is registered. Silent in headless contexts."""
    with _lock:
        cb = _callback
    if cb is None:
        return
    try:
        cb(level, message)
    except Exception:
        # A broken GUI hook must never crash the backend.
        pass
