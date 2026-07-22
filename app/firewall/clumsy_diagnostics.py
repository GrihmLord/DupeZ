# app/firewall/clumsy_diagnostics.py — diagnostic and runtime adapter
"""Install direct-Clumsy runtime controls and authenticated actions.

Clumsy is hidden by making its window transparent, removing it from normal
application switching, moving it to ``(-32000, -32000)``, and finally calling
``ShowWindow(SW_HIDE)``. A useful diagnostic action must reverse every one of
those changes; simply calling ``ShowWindow`` leaves the process invisible and
off-screen.

The same bridge is installed in both in-process and elevated-helper modes. It
is therefore the single installation point for staged control-tree readiness,
deterministic IUP numeric/toggle synchronization, the complete 0.3.4 control
adapter, and owned diagnostic/RST actions.
"""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Optional

from app.core.validation import validate_local_target_ip
from app.logs.logger import log_error, log_info

__all__ = ["install_clumsy_diagnostic_bridge"]

_ACTION_SHOW_WINDOW = "show_clumsy_diagnostic_window"
_ACTION_RST_NEXT_PACKET = "clumsy_rst_next_packet"
_SW_RESTORE = 9
_SWP_NOSIZE = 0x0001
_SWP_NOZORDER = 0x0004
_SWP_SHOWWINDOW = 0x0040
_SM_CXSCREEN = 0
_SM_CYSCREEN = 1


def _restore_owned_window(manager: Any, target_ip: str) -> bool:
    """Restore and center the exact Clumsy window owned by *target_ip*."""

    try:
        from app.firewall import clumsy_network_disruptor as legacy

        lock = getattr(manager, "_device_lock", None)
        context = lock if lock is not None else nullcontext()
        with context:
            entry = getattr(manager, "disrupted_devices", {}).get(target_ip)
            engine = entry.get("engine") if entry else None

        hwnd = getattr(engine, "_hwnd", None)
        if not hwnd or not getattr(engine, "alive", False):
            return False

        user32 = legacy.ctypes.windll.user32
        style = int(user32.GetWindowLongW(hwnd, legacy.GWL_EXSTYLE))

        user32.SetLayeredWindowAttributes(
            hwnd,
            0,
            255,
            legacy.LWA_ALPHA,
        )
        user32.SetWindowLongW(
            hwnd,
            legacy.GWL_EXSTYLE,
            style & ~legacy.WS_EX_LAYERED & ~legacy.WS_EX_TOOLWINDOW,
        )

        screen_width = max(1, int(user32.GetSystemMetrics(_SM_CXSCREEN)))
        screen_height = max(1, int(user32.GetSystemMetrics(_SM_CYSCREEN)))

        class RECT(legacy.ctypes.Structure):
            _fields_ = [
                ("left", legacy.ctypes.c_long),
                ("top", legacy.ctypes.c_long),
                ("right", legacy.ctypes.c_long),
                ("bottom", legacy.ctypes.c_long),
            ]

        rect = RECT()
        width = 900
        height = 650
        if user32.GetWindowRect(hwnd, legacy.ctypes.byref(rect)):
            measured_width = int(rect.right - rect.left)
            measured_height = int(rect.bottom - rect.top)
            if measured_width > 0:
                width = measured_width
            if measured_height > 0:
                height = measured_height

        x = max(0, (screen_width - width) // 2)
        y = max(0, (screen_height - height) // 2)
        user32.SetWindowPos(
            hwnd,
            None,
            x,
            y,
            0,
            0,
            _SWP_NOSIZE | _SWP_NOZORDER | _SWP_SHOWWINDOW,
        )
        user32.ShowWindow(hwnd, _SW_RESTORE)
        try:
            user32.BringWindowToTop(hwnd)
        except AttributeError:
            pass
        user32.SetForegroundWindow(hwnd)
        log_info(
            "Clumsy diagnostic window restored and centered for the selected "
            "private target"
        )
        return True
    except Exception as exc:
        log_error(f"Clumsy diagnostic window restore failed: {exc}")
        return False


def install_clumsy_diagnostic_bridge(manager: Any) -> Any:
    """Install the full runtime and authenticated owned-process actions."""

    from app.firewall.clumsy_full_controls import (
        install_clumsy_full_controls,
        trigger_owned_rst_next_packet,
    )
    from app.firewall.clumsy_full_status import install_full_clumsy_status
    from app.firewall.clumsy_preset_wire import (
        install_clumsy_preset_wire_compatibility,
    )
    from app.firewall.clumsy_private_api_compat import (
        install_private_selector_compatibility,
    )
    from app.firewall.direct_clumsy_runtime import (
        install_direct_clumsy_runtime,
    )
    from app.firewall.iup_edit_sync import install_iup_edit_sync
    from app.firewall.iup_toggle_sync import install_iup_toggle_sync

    # Order matters: full-controls installs the non-numeric control bridge,
    # then deterministic toggle and preset-wire adapters replace the fragile
    # callback/name paths. Numeric and toggle callbacks use synchronous parent
    # notifications in Compat and elevated-helper modes, while display labels
    # remain separate from the fork's unquoted IUP attribute wire names. Status
    # forwards only bounded control metadata. The final compatibility adapter
    # never accepts unscoped input; it can only recover the one private target
    # the manager already owns.
    install_direct_clumsy_runtime()
    install_iup_edit_sync()
    install_clumsy_full_controls()
    install_iup_toggle_sync()
    install_clumsy_preset_wire_compatibility()
    install_full_clumsy_status()
    install_private_selector_compatibility()

    if getattr(manager, "_clumsy_diagnostic_bridge_installed", False):
        return manager

    original_hotkey = getattr(manager, "hotkey_trigger", None)
    original_show = getattr(manager, "show_clumsy_diagnostic_window", None)

    def show_clumsy_diagnostic_window(target_ip: str) -> bool:
        try:
            validated = validate_local_target_ip(
                str(target_ip or ""),
                context="Clumsy diagnostic window",
            )
        except ValueError as exc:
            log_error(f"Clumsy diagnostic request rejected: {exc}")
            return False

        if hasattr(manager, "disrupted_devices"):
            return _restore_owned_window(manager, validated)
        return bool(callable(original_show) and original_show(validated))

    def hotkey_trigger(action: str, payload: Optional[dict] = None) -> bool:
        target_ip = str((payload or {}).get("target_ip") or "")
        if action == _ACTION_SHOW_WINDOW:
            return show_clumsy_diagnostic_window(target_ip)
        if action == _ACTION_RST_NEXT_PACKET:
            return trigger_owned_rst_next_packet(manager, target_ip)
        if callable(original_hotkey):
            return bool(original_hotkey(action, payload or {}))
        return False

    manager.show_clumsy_diagnostic_window = show_clumsy_diagnostic_window
    manager.hotkey_trigger = hotkey_trigger
    manager._clumsy_diagnostic_bridge_installed = True
    return manager
