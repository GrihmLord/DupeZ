# app/firewall/clumsy_hidden_window.py — no-flash owned GUI bootstrap
"""Prepare exact-PID Clumsy windows without exposing them to the operator.

The bundled IUP application must technically show its dialog before every native
child control is materialized. Windows ``SW_HIDE`` prevents a startup flash, but
leaving the dialog fully hidden can also leave its control tree empty.

This adapter separates the pre-show cloak from the final hidden-running policy:

* enumerate only top-level windows owned by the exact managed child PID;
* apply tool-window, layered-alpha-zero, and off-screen policy first;
* technically show each candidate with ``SW_SHOWNOACTIVATE``;
* let the staged runtime select the candidate that exposes the complete control
  tree; and
* apply the existing final hide operation only after Start is verified.

The authenticated diagnostic action remains the sole path that deliberately
restores the selected owned window for an operator.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

from app.firewall import clumsy_network_disruptor as legacy
from app.logs.logger import log_info, log_warning

__all__ = [
    "enumerate_owned_clumsy_windows",
    "pre_show_cloak_owned_window",
    "find_and_conceal_owned_clumsy_window",
    "install_hidden_clumsy_window_discovery",
]

_SW_SHOWNOACTIVATE = 4
_SWP_NOSIZE = 0x0001
_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE = 0x0010
_OFFSCREEN = -32_000


def _is_window(user32: Any, hwnd: int) -> bool:
    try:
        return bool(user32.IsWindow(hwnd))
    except AttributeError:
        return int(hwnd) > 0


def enumerate_owned_clumsy_windows(
    pid: int,
    *,
    user32: Any = None,
) -> tuple[int, ...]:
    """Return every live top-level HWND owned by the exact child *pid*."""

    if int(pid) <= 0:
        return ()

    user32 = user32 or legacy.ctypes.windll.user32
    callback_factory = legacy.WNDENUMPROC or (lambda callback: callback)
    results: list[int] = []

    def window_callback(hwnd, _lparam):
        window_pid = legacy.wintypes.DWORD()
        user32.GetWindowThreadProcessId(
            hwnd,
            legacy.ctypes.byref(window_pid),
        )
        candidate = int(hwnd)
        if (
            int(window_pid.value) == int(pid)
            and candidate > 0
            and _is_window(user32, candidate)
        ):
            results.append(candidate)
        return True

    user32.EnumWindows(callback_factory(window_callback), 0)
    return tuple(dict.fromkeys(results))


def pre_show_cloak_owned_window(
    hwnd: int,
    *,
    user32: Any = None,
) -> bool:
    """Cloak *hwnd* before a no-activation technical show.

    The call ordering is security-relevant: the window becomes a transparent,
    off-screen tool window before ``SW_SHOWNOACTIVATE`` is issued. No foreground
    or activation API is used.
    """

    if int(hwnd) <= 0:
        return False

    user32 = user32 or legacy.ctypes.windll.user32
    if not _is_window(user32, int(hwnd)):
        return False

    try:
        style = int(user32.GetWindowLongW(hwnd, legacy.GWL_EXSTYLE))
        user32.SetWindowLongW(
            hwnd,
            legacy.GWL_EXSTYLE,
            style | legacy.WS_EX_TOOLWINDOW | legacy.WS_EX_LAYERED,
        )
        user32.SetLayeredWindowAttributes(
            hwnd,
            0,
            0,
            legacy.LWA_ALPHA,
        )
        user32.SetWindowPos(
            hwnd,
            None,
            _OFFSCREEN,
            _OFFSCREEN,
            0,
            0,
            _SWP_NOSIZE | _SWP_NOZORDER | _SWP_NOACTIVATE,
        )
        user32.ShowWindow(hwnd, _SW_SHOWNOACTIVATE)
        return True
    except Exception as exc:
        log_warning(
            "Could not apply Clumsy pre-show cloak to an owned candidate: "
            f"{type(exc).__name__}"
        )
        return False


def find_and_conceal_owned_clumsy_window(
    pid: int,
    timeout: float = 5.0,
    *,
    user32: Any = None,
    prepare_window: Optional[Callable[[int], bool]] = None,
    # Backward-compatible test seam retained for the previous adapter.
    hide_window: Optional[Callable[[int], bool]] = None,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> Optional[int]:
    """Return the first prepared exact-PID candidate.

    Every candidate discovered in the same enumeration pass is cloaked before
    this function returns. The staged runtime does not permanently trust the
    returned HWND; it re-enumerates candidates and selects the one whose complete
    Clumsy control tree becomes ready.
    """

    if int(pid) <= 0:
        return None

    user32 = user32 or legacy.ctypes.windll.user32
    prepare = prepare_window or hide_window
    if prepare is None:
        prepare = lambda hwnd: pre_show_cloak_owned_window(  # noqa: E731
            hwnd,
            user32=user32,
        )

    deadline = clock() + max(0.0, float(timeout))
    while clock() < deadline:
        candidates = enumerate_owned_clumsy_windows(int(pid), user32=user32)
        prepared: list[int] = []
        for hwnd in candidates:
            if prepare(int(hwnd)):
                prepared.append(int(hwnd))

        if prepared:
            log_info(
                "Clumsy owned candidate windows prepared for no-activate "
                f"control bootstrap: PID={int(pid)}, candidates={len(prepared)}"
            )
            return prepared[0]
        sleeper(0.01)

    return None


def install_hidden_clumsy_window_discovery() -> None:
    """Install exact-PID no-flash bootstrap discovery once per process."""

    if getattr(legacy, "_hidden_owned_window_discovery_installed", False):
        return
    legacy._find_window_by_pid = find_and_conceal_owned_clumsy_window
    legacy._hidden_owned_window_discovery_installed = True
