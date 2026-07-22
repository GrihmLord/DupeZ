# app/firewall/iup_edit_sync.py — deterministic native EDIT synchronization
"""Synchronize bundled IUP text controls through their Win32 callback path.

IUP does not invoke application callbacks when a value is assigned with
``IupSetAttribute``. The bundled GUI loads numeric preset text that way, so the
visible value alone does not prove its synchronized C field was updated.

This adapter writes the native EDIT value and then sends the standard
``WM_COMMAND / EN_CHANGE`` notification to the control's real parent. That is
the notification consumed by IUP for an interactive text change, but it avoids
focus stealing and global keyboard simulation.
"""

from __future__ import annotations

from typing import Any

from app.firewall import clumsy_network_disruptor as legacy
from app.firewall.direct_clumsy_manager import ManagedClumsyEngine
from app.logs.logger import log_error, log_info

__all__ = ["install_iup_edit_sync"]

_EN_CHANGE = 0x0300


def _set_edit_value_and_notify(
    edit_hwnd: Any,
    value: str,
    *,
    user32: Any = None,
) -> tuple[bool, str]:
    """Set one EDIT, dispatch EN_CHANGE synchronously, and verify its text."""

    user32 = user32 or legacy.ctypes.windll.user32
    expected = str(value)
    try:
        try:
            user32.GetParent.restype = legacy.wintypes.HWND
            user32.GetParent.argtypes = [legacy.wintypes.HWND]
            user32.GetDlgCtrlID.argtypes = [legacy.wintypes.HWND]
        except (AttributeError, TypeError):
            pass

        pointer = legacy.ctypes.c_wchar_p(expected)
        changed = int(user32.SendMessageW(
            edit_hwnd,
            legacy.WM_SETTEXT,
            0,
            pointer,
        ))
        if changed == 0:
            return False, legacy._get_window_text(edit_hwnd)

        parent_hwnd = user32.GetParent(edit_hwnd)
        if not parent_hwnd:
            return False, legacy._get_window_text(edit_hwnd)

        control_id = int(user32.GetDlgCtrlID(edit_hwnd)) & 0xFFFF
        wparam = (_EN_CHANGE << 16) | control_id
        user32.SendMessageW(
            parent_hwnd,
            legacy.WM_COMMAND,
            wparam,
            edit_hwnd,
        )
        actual = legacy._get_window_text(edit_hwnd)
        return actual == expected, actual
    except Exception as exc:
        log_error(
            "IUP EDIT synchronization failed "
            f"(hwnd={edit_hwnd}, value={expected!r}): {exc}"
        )
        return False, legacy._get_window_text(edit_hwnd)


def _set_input_values_with_notifications(engine: ManagedClumsyEngine) -> bool:
    """Synchronize every requested numeric control with detailed diagnostics."""

    edits = legacy._get_edit_controls_sorted(engine._hwnd)
    failures: list[str] = []
    requested = 0

    for index, parameter in legacy.EDIT_INDEX_MAP.items():
        method = legacy._EDIT_PARAM_METHOD.get(parameter)
        if method not in engine.methods:
            continue

        requested += 1
        if index >= len(edits):
            failures.append(
                f"{parameter}: EDIT[{index}] missing (found {len(edits)})"
            )
            continue

        raw_value = engine.params.get(
            parameter,
            legacy._EDIT_PARAM_DEFAULTS[parameter],
        )
        try:
            expected = str(legacy._clumsy_numeric_value(parameter, raw_value))
        except (TypeError, ValueError, OverflowError):
            failures.append(f"{parameter}: invalid value {raw_value!r}")
            continue

        edit_hwnd = edits[index]
        old_text = legacy._get_window_text(edit_hwnd)
        verified, actual = _set_edit_value_and_notify(edit_hwnd, expected)
        log_info(
            "IUP numeric input "
            f"{parameter}: {old_text!r} -> {actual!r} "
            f"(expected={expected!r}, verified={verified})"
        )
        if not verified:
            failures.append(
                f"{parameter}: expected {expected!r}, observed {actual!r}"
            )

    if requested == 0:
        return True
    if failures:
        engine._last_error = (
            "Clumsy numeric input synchronization failed: "
            + "; ".join(failures)
        )
        log_error(engine._last_error)
        return False

    log_info(f"IUP numeric inputs synchronized: {requested}/{requested}")
    return True


def install_iup_edit_sync() -> None:
    """Install the deterministic EDIT adapter once per Python process."""

    if getattr(ManagedClumsyEngine, "_iup_edit_sync_installed", False):
        return
    ManagedClumsyEngine._set_input_values = _set_input_values_with_notifications
    ManagedClumsyEngine._iup_edit_sync_installed = True
