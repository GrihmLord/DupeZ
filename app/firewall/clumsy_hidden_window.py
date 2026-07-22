# app/firewall/clumsy_hidden_window.py — no-flash owned GUI discovery
"""Discover the exact owned Clumsy dialog without requiring it to be visible.

The bundled IUP application must construct a real dialog and child-control tree
before DupeZ can verify its settings.  Windows ``SW_HIDE`` prevents that dialog
from flashing, but the legacy finder rejected every hidden top-level window.
This adapter searches by the exact child PID instead, immediately reapplies the
transparent/off-screen/tool-window policy, and returns only that owned HWND.

The authenticated diagnostic action remains the sole path that reverses this
policy and deliberately restores the window for an operator.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

from app.firewall import clumsy_network_disruptor as legacy
from app.logs.logger import log_info

__all__ = [
    "find_and_conceal_owned_clumsy_window",
    "install_hidden_clumsy_window_discovery",
]


def find_and_conceal_owned_clumsy_window(
    pid: int,
    timeout: float = 5.0,
    *,
    user32: Any = None,
    hide_window: Optional[Callable[[int], bool]] = None,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> Optional[int]:
    """Return and conceal the top-level HWND owned by *pid*.

    Visibility is intentionally not part of the match.  The process was created
    by DupeZ and the PID is held by ``ManagedProcess``, so matching the exact PID
    is the ownership boundary.  The first matching top-level window is hidden
    again before this function returns.
    """

    if int(pid) <= 0:
        return None

    user32 = user32 or legacy.ctypes.windll.user32
    conceal = hide_window or legacy._hide_window
    callback_factory = legacy.WNDENUMPROC or (lambda callback: callback)
    deadline = clock() + max(0.0, float(timeout))

    while clock() < deadline:
        result: list[Optional[int]] = [None]

        def window_callback(hwnd, _lparam):
            window_pid = legacy.wintypes.DWORD()
            user32.GetWindowThreadProcessId(
                hwnd,
                legacy.ctypes.byref(window_pid),
            )
            if int(window_pid.value) != int(pid):
                return True

            owned_hwnd = int(hwnd)
            conceal(owned_hwnd)
            result[0] = owned_hwnd
            return False

        user32.EnumWindows(callback_factory(window_callback), 0)
        if result[0]:
            log_info(
                "Clumsy owned window discovered and concealed before control "
                f"automation: PID={int(pid)}, hwnd={result[0]}"
            )
            return result[0]
        sleeper(0.01)

    return None


def install_hidden_clumsy_window_discovery() -> None:
    """Install hidden PID-owned window discovery once per runtime process."""

    if getattr(legacy, "_hidden_owned_window_discovery_installed", False):
        return
    legacy._find_window_by_pid = find_and_conceal_owned_clumsy_window
    legacy._hidden_owned_window_discovery_installed = True
