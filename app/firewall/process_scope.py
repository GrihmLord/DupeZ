"""Process-scoped disruption support (v5.6.9 feature #4).

When a preset has ``_process_scope`` set, the engine restricts disruption
to packets originating from a specific process — typically ``DayZ.exe``
or ``DayZ_BE.exe``. This means cuts only affect the game's traffic and
leave Discord voice, browser, Steam, etc. running untouched.

Two scoping modes:

    ``"dayz"``  — always target DayZ regardless of focus
    ``"auto"``  — target whichever DayZ-class process is in the
                  foreground; auto-stop when the operator alt-tabs

Implementation surfaces three things:

    1. ``find_dayz_pids()`` — enumerate live DayZ-class processes
    2. ``get_foreground_pid()`` — Win32 GetForegroundWindow lookup
    3. ``ProcessScopeWatcher`` — daemon thread that polls foreground
       state and emits callbacks when DayZ leaves / regains focus

Filter integration happens via :func:`build_pid_filter_clause`, which
produces a WinDivert filter fragment like
``(processId == 1234 or processId == 5678)`` for an N-PID stack.

Notes:

* WinDivert exposes ``processId`` at the NETWORK_FORWARD and FLOW
  layers but NOT at the NETWORK layer on outbound packets in older
  builds — confirm against your WinDivert.dll version before relying
  on it in production. If unavailable, the filter still compiles but
  the clause is a no-op.
* DayZ ships two executables: ``DayZ.exe`` (default, unprotected) and
  ``DayZ_BE.exe`` (BattlEye launcher). Both are valid process names;
  match either.
* On Linux/macOS the helpers degrade to "no scope" — DupeZ is
  Windows-first, but the imports stay safe everywhere.
"""

from __future__ import annotations

import sys
import threading
from typing import Callable, Iterable, List, Optional, Set

from app.logs.logger import log_info, log_warning, log_error

__all__ = [
    "DAYZ_PROCESS_NAMES",
    "find_dayz_pids",
    "get_foreground_pid",
    "build_pid_filter_clause",
    "ProcessScopeWatcher",
]

# Match either the unprotected DayZ exe or the BattlEye launcher.
DAYZ_PROCESS_NAMES: frozenset = frozenset({
    "DayZ.exe", "dayz.exe",
    "DayZ_BE.exe", "dayz_be.exe",
    "DayZ_x64.exe", "dayz_x64.exe",
})


# ── Process enumeration ────────────────────────────────────────────────

def find_dayz_pids(process_names: Optional[Iterable[str]] = None) -> List[int]:
    """Return PIDs of every DayZ-class process currently running.

    Args:
        process_names: optional override; defaults to
            :data:`DAYZ_PROCESS_NAMES`. Pass a custom set when scoping
            to other games (Rust, ARK) once cross-game profiles land.

    Returns:
        Sorted list of PIDs. Empty if nothing matches or psutil
        unavailable.
    """
    targets: Set[str] = set(
        name.lower() for name in (process_names or DAYZ_PROCESS_NAMES)
    )
    try:
        import psutil  # noqa: WPS433 — optional runtime dep
    except Exception:
        return []
    out: List[int] = []
    try:
        for p in psutil.process_iter(attrs=("pid", "name")):
            try:
                nm = (p.info.get("name") or "").lower()
            except Exception:
                continue
            if nm in targets:
                out.append(int(p.info["pid"]))
    except Exception as exc:
        log_warning(f"find_dayz_pids: process iteration failed: {exc}")
        return []
    return sorted(out)


def get_foreground_pid() -> Optional[int]:
    """Return the PID owning the current foreground window, or None.

    Windows only. Uses GetForegroundWindow + GetWindowThreadProcessId
    via ctypes; no new dependency.
    """
    if not sys.platform.startswith("win"):
        return None
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return None
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value) if pid.value else None
    except Exception as exc:
        log_warning(f"get_foreground_pid failed: {exc}")
        return None


# ── Filter integration ────────────────────────────────────────────────

def build_pid_filter_clause(pids: Iterable[int]) -> str:
    """Build a WinDivert filter fragment scoping to *pids*.

    Returns an empty string for an empty iterable so the caller can
    safely `AND` it onto an existing filter without producing
    ``filter and `` (syntax error).

    Examples::

        >>> build_pid_filter_clause([])
        ''
        >>> build_pid_filter_clause([1234])
        '(processId == 1234)'
        >>> build_pid_filter_clause([1234, 5678])
        '(processId == 1234 or processId == 5678)'
    """
    pid_list = sorted({int(p) for p in pids if int(p) > 0})
    if not pid_list:
        return ""
    clauses = " or ".join(f"processId == {p}" for p in pid_list)
    return f"({clauses})"


def apply_process_scope(
    base_filter: str,
    scope_mode: Optional[str],
    *,
    dayz_pids: Optional[List[int]] = None,
    foreground_pid: Optional[int] = None,
) -> str:
    """Wrap *base_filter* with a process-scope clause based on *scope_mode*.

    Args:
        base_filter: existing filter string (e.g.,
            ``"ip.SrcAddr == 10.0.0.5 or ip.DstAddr == 10.0.0.5"``).
        scope_mode: one of ``None`` / ``""`` (no scoping), ``"dayz"``
            (scope to all DayZ processes), or ``"auto"`` (scope to
            foreground only when it's a DayZ process).
        dayz_pids: pre-computed DayZ PID list. If None, callers should
            call :func:`find_dayz_pids` themselves; this signature
            keeps the function dep-free for testing.
        foreground_pid: pre-computed foreground PID. Same rationale.

    Returns:
        The combined filter string. When scoping yields zero PIDs the
        function returns ``base_filter`` unchanged (rather than
        producing a filter that matches nothing) — the safer default
        is "behave as before scoping was requested" than "silently
        no-op every cut."
    """
    if not scope_mode:
        return base_filter

    if scope_mode == "dayz":
        target_pids = list(dayz_pids or [])
    elif scope_mode == "auto":
        if foreground_pid and dayz_pids and foreground_pid in dayz_pids:
            target_pids = [foreground_pid]
        else:
            target_pids = []
    else:
        log_warning(f"unknown scope_mode {scope_mode!r}; ignoring")
        return base_filter

    clause = build_pid_filter_clause(target_pids)
    if not clause:
        # Honest about the no-PID case: log loud, return base unchanged.
        # Operators want to know "scope had no effect" rather than
        # silently capturing zero packets.
        log_warning(
            f"process scope ({scope_mode}) matched 0 DayZ PIDs; "
            f"falling back to unscoped filter"
        )
        return base_filter

    # Parens around base in case it contains an `or` that would
    # otherwise rebind across the AND. Cheap, safe, no extra parsing.
    if base_filter and base_filter.strip() != "true":
        return f"({base_filter}) and {clause}"
    return clause


# ── Foreground watcher ────────────────────────────────────────────────

class ProcessScopeWatcher:
    """Daemon thread polling foreground state for the ``auto`` scope mode.

    The engine creates one of these per active disruption that uses
    ``_process_scope=auto`` and registers a callback. The watcher
    polls the foreground PID at ``poll_interval_s`` and invokes the
    callback whenever the DayZ-foreground state flips
    (``False → True`` or ``True → False``), so the engine can
    pause/resume packet capture.

    Polling is intentional rather than event-driven: SetWinEventHook
    + EVENT_SYSTEM_FOREGROUND would be lower-latency but requires a
    Windows message pump on a dedicated thread. Polling at 0.5-1s is
    plenty for alt-tab UX.
    """

    def __init__(
        self,
        on_state_change: Callable[[bool, Optional[int]], None],
        poll_interval_s: float = 0.5,
        process_names: Optional[Iterable[str]] = None,
    ) -> None:
        self._cb = on_state_change
        self._interval = max(0.1, float(poll_interval_s))
        self._targets: frozenset = frozenset(
            n.lower() for n in (process_names or DAYZ_PROCESS_NAMES)
        )
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_state: Optional[bool] = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="ProcessScopeWatcher"
        )
        self._thread.start()
        log_info(f"ProcessScopeWatcher started ({self._interval}s poll)")

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                fg_pid = get_foreground_pid()
                is_dayz = self._pid_is_dayz(fg_pid)
                if is_dayz != self._last_state:
                    self._last_state = is_dayz
                    try:
                        self._cb(is_dayz, fg_pid)
                    except Exception as exc:
                        log_error(
                            f"ProcessScopeWatcher callback raised: {exc}"
                        )
            except Exception as exc:
                log_warning(f"ProcessScopeWatcher tick error: {exc}")
            self._stop.wait(self._interval)

    def _pid_is_dayz(self, pid: Optional[int]) -> bool:
        if not pid:
            return False
        try:
            import psutil
            p = psutil.Process(pid)
            return (p.name() or "").lower() in self._targets
        except Exception:
            return False
