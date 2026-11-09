#!/usr/bin/env python
# app/firewall_helper/elevation.py
"""
Helper-process elevation and lifecycle management (ADR-0001 Day 4).

This module spawns `dupez_helper.py` at High IL while the GUI process
itself runs at Medium IL. It supports one elevation strategy:

    B2a  runas            — ShellExecuteW("runas", ...) consent prompt.
                            One UAC dialog per launch. Works on every
                            Windows host without install-time setup.

Strategy selection is controlled by `DUPEZ_ELEVATION`:
    auto            → runas. Default.
    runas           → always use B2a.
    scheduled_task  → refused. Older releases exposed a persistent
                      highest-privilege task whose static action could not
                      bind a launch to the requesting GUI process. Keeping
                      that path would create a same-user UAC bypass.

Critical invariants:
    * This module MUST be importable from the GUI process at Medium IL.
      No ctypes calls happen at import time — they all live inside
      functions that execute only when elevation is requested.
    * No packet bodies cross any boundary this module sets up. This is
      strictly a spawn / lifetime-binding control plane (ADR-0001 §1.2).
    * Cross-integrity Job binding from the Medium GUI to the High
      helper is BLOCKED by UIPI — research confirmed. Instead, the
      helper process watches its parent (Day 1 interim parent-pid poll;
      Day 4 adds a helper-side Job at High IL that contains the helper
      itself, so that any crash of the helper tears down the whole
      engine cleanly). Parent-death binding is enforced by the helper
      polling the parent PID and exiting when the parent dies.
"""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
from typing import Callable, Optional

log = logging.getLogger(__name__)

_SECOND_FACTOR_SECRET_KINDS = (
    "secondfactor.totp.seed",
    "secondfactor.fido2.creds",
)

# Public API
__all__ = [
    "ensure_helper_running",
    "is_helper_task_registered",
    "register_helper_task",
    "launch_helper_runas",
    "launch_helper_via_task",
    "ElevationError",
    "enforce_second_factor",
    "probe_second_factor_boundary",
    "resolve_elevation_mode",
]

class ElevationError(RuntimeError):
    """Raised when the helper process cannot be elevated or spawned."""


def _audit_second_factor_refusal(failure: str, *, boundary: str) -> None:
    """Record a fixed, non-secret reason for refusing elevation."""
    try:
        from app.logs.audit import audit_event

        audit_event(
            "second_factor_boundary_refused",
            {"boundary": boundary, "failure": failure},
        )
    except Exception:
        # Audit availability must not change the fail-closed decision.
        pass


def _refuse_second_factor(failure: str, *, boundary: str) -> None:
    """Refuse elevation without copying provider errors into logs."""
    log.warning(
        "elevation refused because second-factor authorization failed (%s)",
        failure,
    )
    _audit_second_factor_refusal(failure, boundary=boundary)
    raise ElevationError(
        "second-factor authorization could not be established; elevation refused"
    ) from None


def _second_factor_state(*, boundary: str):
    """Return ``(gate, enrolled)`` or fail closed on indeterminate state."""
    try:
        from app.core.second_factor import get_gate
        from app.core.secret_store import check_store_health, get_secret
    except Exception:
        _refuse_second_factor("dependency_unavailable", boundary=boundary)

    try:
        store_health = check_store_health()
    except Exception:
        _refuse_second_factor("store_probe_failed", boundary=boundary)
    if getattr(store_health, "healthy", None) is not True:
        _refuse_second_factor("store_unavailable", boundary=boundary)

    try:
        gate = get_gate()
    except Exception:
        _refuse_second_factor("gate_unavailable", boundary=boundary)

    try:
        enrolled = gate.is_enrolled()
    except Exception:
        _refuse_second_factor("enrollment_query_failed", boundary=boundary)
    if enrolled is False:
        try:
            stored_enrollment = any(
                get_secret(kind) is not None
                for kind in _SECOND_FACTOR_SECRET_KINDS
            )
        except Exception:
            _refuse_second_factor("store_read_failed", boundary=boundary)
        if stored_enrollment:
            _refuse_second_factor(
                "enrollment_state_inconsistent",
                boundary=boundary,
            )
        return gate, False
    if enrolled is not True:
        _refuse_second_factor("invalid_enrollment_state", boundary=boundary)
    return gate, True


def probe_second_factor_boundary(*, boundary: str = "elevation") -> bool:
    """Validate store/enrollment state without granting privileged access.

    The Medium-IL GUI uses this before it writes the helper sentinel or shows a
    UAC prompt.  This is only a readiness probe: the High-IL helper performs
    the actual verification so direct ``--role helper`` invocation cannot
    bypass an enrolled factor.
    """
    _gate, enrolled = _second_factor_state(boundary=boundary)
    return enrolled


def enforce_second_factor(
    *,
    boundary: str = "elevation",
    prompter: Optional[Callable[[str], str]] = None,
) -> None:
    """Verify an enrolled factor at the privileged boundary or fail closed."""
    gate, enrolled = _second_factor_state(boundary=boundary)
    if not enrolled:
        return

    try:
        require_kwargs = {
            "reason": "authorize privileged firewall engine startup",
            "cache_ttl_sec": 0,
            "bypass_cache": True,
        }
        if prompter is not None:
            require_kwargs["prompter"] = prompter
        verified = gate.require("elevation", **require_kwargs)
    except Exception:
        _refuse_second_factor("verification_failed", boundary=boundary)
    if verified is not True:
        _refuse_second_factor("invalid_verification_result", boundary=boundary)


# ── Environment / argv helpers ────────────────────────────────────────

def resolve_elevation_mode() -> str:
    """Return the active elevation mode string: runas | scheduled_task | auto."""
    mode = (os.environ.get("DUPEZ_ELEVATION") or "auto").strip().lower()
    if mode not in ("auto", "runas", "scheduled_task"):
        log.warning("unknown DUPEZ_ELEVATION=%r, defaulting to auto", mode)
        return "auto"
    return mode


def _parent_create_time(parent_pid: int) -> float:
    """Return the live caller's creation time for PID-reuse protection."""
    if not isinstance(parent_pid, int) or parent_pid <= 0:
        raise ElevationError("invalid helper parent process")
    if parent_pid != os.getpid():
        raise ElevationError("helper must be bound to the calling process")
    try:
        import psutil

        process = psutil.Process(parent_pid)
        created = float(process.create_time())
        if not process.is_running() or created <= 0:
            raise ElevationError("helper parent process is not live")
        return created
    except ElevationError:
        raise
    except Exception as exc:
        raise ElevationError("helper parent identity is unavailable") from exc


def _helper_script_path() -> str:
    """Absolute path to the helper executable or dupez_helper.py script.

    Under a PyInstaller onefile build, there is no separate helper .exe —
    the GUI exe (DupeZ-GPU.exe / DupeZ-Compat.exe) dispatches to
    ``dupez_helper.main()`` when it sees ``--role helper`` in argv (see
    ``_maybe_dispatch_helper_role`` in ``dupez.py``). So for frozen
    builds we return ``sys.executable`` and let ``launch_helper_runas``
    invoke it with ``--role helper --parent-pid N``.

    In the dev path (`python dupez.py`), we return the real
    ``dupez_helper.py`` script next to the repo root and the caller
    will invoke it through the current python interpreter.
    """
    if getattr(sys, "frozen", False):
        # Same exe, re-invoked in helper mode.
        return sys.executable
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(here, "..", ".."))
    return os.path.join(repo_root, "dupez_helper.py")


def _python_exe() -> str:
    """Return the interpreter path to use when launching the .py helper."""
    # When frozen, sys.executable is the GUI exe — we don't want that.
    # In that case the helper should be a separate exe anyway.
    return sys.executable


def _build_helper_argv(parent_pid: int, pipe_name: Optional[str]) -> list[str]:
    if pipe_name is not None:
        raise ElevationError("custom helper pipe names are not supported")
    script = _helper_script_path()
    created = _parent_create_time(parent_pid)
    return [
        script,
        "--role",
        "helper",
        "--parent-pid",
        str(parent_pid),
        "--parent-created",
        repr(created),
    ]


# ── B2a: runas (ShellExecuteW) ────────────────────────────────────────

# ShellExecuteEx constants
_SEE_MASK_NOCLOSEPROCESS = 0x00000040
_SEE_MASK_FLAG_NO_UI = 0x00000400
_SW_HIDE = 0
_SW_SHOWNORMAL = 1


class _SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("fMask", ctypes.c_ulong),
        ("hwnd", ctypes.c_void_p),
        ("lpVerb", ctypes.c_wchar_p),
        ("lpFile", ctypes.c_wchar_p),
        ("lpParameters", ctypes.c_wchar_p),
        ("lpDirectory", ctypes.c_wchar_p),
        ("nShow", ctypes.c_int),
        ("hInstApp", ctypes.c_void_p),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", ctypes.c_wchar_p),
        ("hkeyClass", ctypes.c_void_p),
        ("dwHotKey", ctypes.c_ulong),
        ("hIconOrMonitor", ctypes.c_void_p),
        ("hProcess", ctypes.c_void_p),
    ]


def launch_helper_runas(parent_pid: int, pipe_name: Optional[str] = None) -> int:
    """Spawn the helper elevated via ShellExecuteW("runas", ...).

    Shows exactly one UAC consent dialog. Returns the helper's PID.
    Raises ElevationError if the user cancels or spawn fails.
    """
    if sys.platform != "win32":
        raise ElevationError("runas elevation only available on Windows")

    argv = _build_helper_argv(parent_pid, pipe_name)
    script_or_exe = os.path.abspath(argv[0])
    rest = argv[1:]
    if not os.path.isfile(script_or_exe):
        raise ElevationError("helper launch target is unavailable")

    # If the helper is a .py file, we need to invoke it through the python
    # interpreter. If it's already a frozen .exe, call it directly.
    if script_or_exe.lower().endswith(".py"):
        lp_file = os.path.abspath(_python_exe())
        params_argv = [script_or_exe, *rest]
    else:
        lp_file = script_or_exe
        params_argv = rest
    if not os.path.isfile(lp_file):
        raise ElevationError("helper interpreter is unavailable")
    lp_params = subprocess.list2cmdline(params_argv)

    sei = _SHELLEXECUTEINFOW()
    sei.cbSize = ctypes.sizeof(_SHELLEXECUTEINFOW)
    sei.fMask = _SEE_MASK_NOCLOSEPROCESS | _SEE_MASK_FLAG_NO_UI
    sei.hwnd = None
    sei.lpVerb = "runas"
    sei.lpFile = lp_file
    sei.lpParameters = lp_params
    sei.lpDirectory = os.path.dirname(script_or_exe) or None
    # The helper normally has no window, but an enrolled second factor opens
    # a bounded authorization dialog. Do not inherit a minimized/no-activate
    # startup state that can hide that privileged prompt behind the GUI.
    sei.nShow = _SW_SHOWNORMAL
    sei.hInstApp = None

    shell32 = ctypes.windll.shell32
    try:
        shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(_SHELLEXECUTEINFOW)]
        shell32.ShellExecuteExW.restype = ctypes.c_int
    except (AttributeError, TypeError):
        pass
    ok = shell32.ShellExecuteExW(ctypes.byref(sei))
    if not ok or not sei.hProcess:
        err = ctypes.GetLastError()
        # 1223 = ERROR_CANCELLED (UAC declined)
        if err == 1223:
            raise ElevationError("user declined UAC elevation")
        raise ElevationError(f"ShellExecuteExW failed (GetLastError={err})")

    # Extract PID from the returned process handle, then close the handle.
    kernel32 = ctypes.windll.kernel32
    try:
        kernel32.GetProcessId.argtypes = [ctypes.c_void_p]
        kernel32.GetProcessId.restype = ctypes.c_ulong
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
    except (AttributeError, TypeError):
        pass
    pid = int(kernel32.GetProcessId(ctypes.c_void_p(sei.hProcess)))
    try:
        kernel32.CloseHandle(ctypes.c_void_p(sei.hProcess))
    except Exception:
        pass
    if pid <= 0:
        raise ElevationError("elevated helper returned no process identity")
    log.info("launch_helper_runas: helper dispatched via runas")
    return pid


# ── B2b: scheduled_task (ITaskService COM) ────────────────────────────

def is_helper_task_registered() -> bool:
    """Never discover or invoke legacy persistent helper tasks."""
    return False


def register_helper_task() -> None:
    """Refuse creation of a reusable highest-privilege helper task."""
    raise ElevationError(
        "scheduled-task elevation is disabled because a persistent "
        "highest-privilege task cannot bind a launch to its requesting GUI"
    )


def launch_helper_via_task(parent_pid: int) -> int:
    """Refuse invocation of the legacy reusable scheduled task."""
    del parent_pid
    raise ElevationError(
        "scheduled-task elevation is disabled because a persistent "
        "highest-privilege task cannot bind a launch to its requesting GUI"
    )


# ── Top-level orchestration ───────────────────────────────────────────

def ensure_helper_running(
    pipe_name: Optional[str] = None,
    mode: Optional[str] = None,
    shared_secret: Optional[bytes] = None,
) -> int:
    """Spawn the helper using the resolved elevation strategy.

    Returns the helper PID. Raises ElevationError on failure.

    Auth:
        ``shared_secret`` must be exactly 32 bytes. It is written to the
        user-private sentinel (auth.write_token_sentinel) BEFORE the helper
        is spawned, then read and consumed by the helper at startup.

    The caller must then connect the PipeClient (with the same secret)
    and wait for the handshake — see `DisruptionManagerProxy._ensure_helper()`.

    Second-factor gate (§9.2): a healthy store and an affirmative gate
    decision are required. Explicitly unenrolled first-run installs may
    proceed; unavailable or indeterminate gate state is refused.
    """
    effective_mode = (mode or resolve_elevation_mode()).lower()
    if effective_mode == "auto":
        effective_mode = "runas"
        log.info("auto-resolved elevation mode -> runas")
    if effective_mode == "scheduled_task":
        raise ElevationError(
            "scheduled-task elevation is disabled because a persistent "
            "highest-privilege task cannot bind a launch to its requesting GUI"
        )
    if effective_mode != "runas":
        raise ElevationError(f"unknown elevation mode: {effective_mode}")

    # §9.2: fail early on an unavailable or contradictory factor store.
    # This probe does not grant access.  The elevated helper verifies the
    # factor again inside High IL before importing or initializing its engine.
    probe_second_factor_boundary()

    # Write the auth sentinel BEFORE launching so the helper can read it
    # the instant it starts. Without this, run_helper_server refuses to
    # start on the helper side (by design).
    if not isinstance(shared_secret, (bytes, bytearray)) or len(shared_secret) != 32:
        raise ElevationError("helper elevation requires a 32-byte session secret")
    sentinel_written = False
    try:
        from app.firewall_helper.auth import write_token_sentinel

        write_token_sentinel(bytes(shared_secret))
        sentinel_written = True
        log.debug("wrote helper authentication sentinel")
    except Exception as e:
        raise ElevationError("failed to write helper auth sentinel") from e

    parent_pid = os.getpid()
    try:
        pid = launch_helper_runas(parent_pid, pipe_name=pipe_name)
    except Exception as exc:
        if sentinel_written:
            try:
                from app.firewall_helper.auth import discard_token_sentinel

                discard_token_sentinel()
            except Exception:
                pass
        if isinstance(exc, ElevationError):
            raise
        raise ElevationError("helper launch failed") from None

    try:
        from app.firewall_helper.job_guard import (
            bind_helper_to_parent_lifetime,
        )
        if bind_helper_to_parent_lifetime(pid):
            log.info("helper bound to kill-on-close Job object")
        else:
            log.warning(
                "helper could not be assigned to Job object; "
                "creation-time parent watcher remains active"
            )
    except Exception as exc:
        log.warning("helper Job object binding failed: %s", exc)
    return pid
