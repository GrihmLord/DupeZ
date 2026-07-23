# app/firewall/iup_toggle_sync.py — deterministic native toggle synchronization
"""Synchronize bundled IUP toggle controls through their Win32 callback path.

The Clumsy preset callback assigns toggle ``VALUE`` attributes programmatically.
IUP documents and the pinned fork source demonstrate that such assignments do
not invoke the application's ``ACTION`` callback, so the visible check mark can
disagree with the synchronized C direction/sub-option field.

``BM_CLICK`` is not a reliable cross-process remedy for an off-focus dialog.
This adapter sets the exact native state and then sends the standard
``WM_COMMAND / BN_CLICKED`` notification synchronously to the control's real
parent—the same notification path Windows delivers after a user click.
"""

from __future__ import annotations

import time
from typing import Any

from app.firewall import clumsy_network_disruptor as legacy
from app.logs.logger import log_error, log_info

__all__ = [
    "install_iup_toggle_sync",
    "set_toggle_state_and_notify",
]

_BM_GETCHECK = 0x00F0
_BM_SETCHECK = 0x00F1
_BN_CLICKED = 0
_BST_CHECKED = 1
_BST_UNCHECKED = 0
_VERIFY_TIMEOUT_SECONDS = 0.30
_VERIFY_POLL_SECONDS = 0.01


def set_toggle_state_and_notify(
    toggle_hwnd: Any,
    desired: bool,
    *,
    user32: Any = None,
) -> tuple[bool, int, int]:
    """Set one IUP toggle, dispatch BN_CLICKED, and verify its native state."""

    user32 = user32 or legacy.ctypes.windll.user32
    expected = _BST_CHECKED if desired else _BST_UNCHECKED
    try:
        try:
            user32.GetParent.restype = legacy.wintypes.HWND
            user32.GetParent.argtypes = [legacy.wintypes.HWND]
            user32.GetDlgCtrlID.argtypes = [legacy.wintypes.HWND]
        except (AttributeError, TypeError):
            pass

        before = int(user32.SendMessageW(
            toggle_hwnd,
            _BM_GETCHECK,
            0,
            0,
        ))
        parent_hwnd = user32.GetParent(toggle_hwnd)
        if not parent_hwnd:
            return False, before, before

        control_id = int(user32.GetDlgCtrlID(toggle_hwnd)) & 0xFFFF
        user32.SendMessageW(
            toggle_hwnd,
            _BM_SETCHECK,
            expected,
            0,
        )
        wparam = (_BN_CLICKED << 16) | control_id
        user32.SendMessageW(
            parent_hwnd,
            legacy.WM_COMMAND,
            wparam,
            toggle_hwnd,
        )

        deadline = time.monotonic() + _VERIFY_TIMEOUT_SECONDS
        actual = before
        while time.monotonic() < deadline:
            actual = int(user32.SendMessageW(
                toggle_hwnd,
                _BM_GETCHECK,
                0,
                0,
            ))
            if actual == expected:
                return True, before, actual
            time.sleep(_VERIFY_POLL_SECONDS)
        return False, before, actual
    except Exception as exc:
        log_error(
            "IUP toggle synchronization failed "
            f"(hwnd={toggle_hwnd}, desired={desired}): {exc}"
        )
        return False, -1, -1


def _force_toggle_callback(toggle_hwnd: Any, desired: bool) -> bool:
    verified, before, actual = set_toggle_state_and_notify(
        toggle_hwnd,
        desired,
    )
    log_info(
        "IUP toggle synchronized: "
        f"hwnd={toggle_hwnd}, before={before}, desired={int(desired)}, "
        f"actual={actual}, verified={verified}"
    )
    return verified


def install_iup_toggle_sync() -> None:
    """Replace the full-control toggle helper exactly once per process."""

    from app.firewall import clumsy_full_controls

    if getattr(clumsy_full_controls, "_iup_toggle_sync_installed", False):
        return
    clumsy_full_controls._force_toggle_callback = _force_toggle_callback
    clumsy_full_controls._iup_toggle_sync_installed = True
