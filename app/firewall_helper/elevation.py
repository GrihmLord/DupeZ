#!/usr/bin/env python
# app/firewall_helper/elevation.py
"""
Helper-process elevation and lifecycle management (ADR-0001 Day 4).

This module spawns `dupez_helper.py` at High IL while the GUI process
itself runs at Medium IL. It supports two elevation strategies:

    B2a  runas            — ShellExecuteW("runas", ...) consent prompt.
                            One UAC dialog per launch. Works on every
                            Windows host without install-time setup.

    B2b  scheduled_task   — ITaskService COM API registers a Task
                            Scheduler entry with "Run with highest
                            privileges". Subsequent launches call
                            IRegisteredTask::Run() which spawns the
                            helper at High IL WITHOUT prompting UAC.
                            Registration itself requires one UAC prompt
                            (to create the task); every launch after
                            that is silent.

Strategy selection is controlled by `DUPEZ_ELEVATION`:
    auto            → prefer scheduled_task if already registered,
                      otherwise runas. Default.
    runas           → always use B2a.
    scheduled_task  → always use B2b; registers the task on first run.

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
import sys
import time
from typing import Optional

log = logging.getLogger(__name__)

# Public API
__all__ = [
    "ensure_helper_running",
    "is_helper_task_registered",
    "register_helper_task",
    "launch_helper_runas",
    "launch_helper_via_task",
    "ElevationError",
    "resolve_elevation_mode",
]

# Task Scheduler registered path — matches folder + task name convention.
TASK_FOLDER = r"\DupeZ"
TASK_NAME = "FirewallHelper"
TASK_PATH = TASK_FOLDER + "\\" + TASK_NAME

# How long to wait for the helper's named pipe to become available after spawn.
HELPER_READY_TIMEOUT_SEC = 15.0


class ElevationError(RuntimeError):
    """Raised when the helper process cannot be elevated or spawned."""


# ── Environment / argv helpers ────────────────────────────────────────

def resolve_elevation_mode() -> str:
    """Return the active elevation mode string: runas | scheduled_task | auto."""
    mode = (os.environ.get("DUPEZ_ELEVATION") or "auto").strip().lower()
    if mode not in ("auto", "runas", "scheduled_task"):
        log.warning("unknown DUPEZ_ELEVATION=%r, defaulting to auto", mode)
        return "auto"
    return mode


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
    script = _helper_script_path()
    argv = [script, "--role", "helper", "--parent-pid", str(parent_pid)]
    if pipe_name:
        argv += ["--pipe", pipe_name]
    return argv


# ── B2a: runas (ShellExecuteW) ────────────────────────────────────────

# ShellExecuteEx constants
_SEE_MASK_NOCLOSEPROCESS = 0x00000040
_SEE_MASK_FLAG_NO_UI = 0x00000400
_SW_HIDE = 0
_SW_SHOWMINNOACTIVE = 7


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
    script_or_exe = argv[0]
    rest = argv[1:]

    # If the helper is a .py file, we need to invoke it through the python
    # interpreter. If it's already a frozen .exe, call it directly.
    if script_or_exe.lower().endswith(".py"):
        lp_file = _python_exe()
        # Quote the script path to survive spaces.
        lp_params = '"' + script_or_exe + '" ' + " ".join(_q(a) for a in rest)
    else:
        lp_file = script_or_exe
        lp_params = " ".join(_q(a) for a in rest)

    sei = _SHELLEXECUTEINFOW()
    sei.cbSize = ctypes.sizeof(_SHELLEXECUTEINFOW)
    sei.fMask = _SEE_MASK_NOCLOSEPROCESS
    sei.hwnd = None
    sei.lpVerb = "runas"
    sei.lpFile = lp_file
    sei.lpParameters = lp_params
    sei.lpDirectory = os.path.dirname(script_or_exe) or None
    sei.nShow = _SW_SHOWMINNOACTIVE
    sei.hInstApp = None

    shell32 = ctypes.windll.shell32
    shell32.ShellExecuteExW.restype = ctypes.c_int
    ok = shell32.ShellExecuteExW(ctypes.byref(sei))
    if not ok or not sei.hProcess:
        err = ctypes.GetLastError()
        # 1223 = ERROR_CANCELLED (UAC declined)
        if err == 1223:
            raise ElevationError("user declined UAC elevation")
        raise ElevationError(f"ShellExecuteExW failed (GetLastError={err})")

    # Extract PID from the returned process handle, then close the handle.
    kernel32 = ctypes.windll.kernel32
    kernel32.GetProcessId.restype = ctypes.c_ulong
    pid = int(kernel32.GetProcessId(ctypes.c_void_p(sei.hProcess)))
    try:
        kernel32.CloseHandle(ctypes.c_void_p(sei.hProcess))
    except Exception:
        pass
    log.info("launch_helper_runas: spawned helper pid=%d via runas", pid)
    return pid


def _q(s: str) -> str:
    """Quote a single argv element for CreateProcess-style command lines."""
    if not s:
        return '""'
    if any(c in s for c in (' ', '\t', '"')):
        return '"' + s.replace('"', '\\"') + '"'
    return s


# ── B2b: scheduled_task (ITaskService COM) ────────────────────────────

def is_helper_task_registered() -> bool:
    """Return True if the `\\DupeZ\\FirewallHelper` task exists."""
    if sys.platform != "win32":
        return False
    try:
        import win32com.client  # type: ignore
    except Exception as e:
        log.debug("win32com unavailable, cannot check task: %s", e)
        return False
    try:
        scheduler = win32com.client.Dispatch("Schedule.Service")
        scheduler.Connect()
        try:
            folder = scheduler.GetFolder(TASK_FOLDER)
        except Exception:
            return False
        try:
            folder.GetTask(TASK_NAME)
            return True
        except Exception:
            return False
    except Exception as e:
        log.debug("task lookup failed: %s", e)
        return False


# Task XML template — "Run with highest privileges", on-demand trigger,
# interactive logon session (S4U would lose desktop access). {argv} is the
# command line that will launch the helper.
_TASK_XML_TEMPLATE = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Author>DupeZ</Author>
    <Description>Elevated firewall helper for DupeZ (ADR-0001 split architecture). Launches dupez_helper.py at High IL without UAC prompts.</Description>
    <URI>{uri}</URI>
  </RegistrationInfo>
  <Triggers />
  <Principals>
    <Principal id="Author">
      <UserId>{user_sid}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>false</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>4</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{command}</Command>
      <Arguments>{arguments}</Arguments>
      <WorkingDirectory>{working_dir}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""

# ITaskFolder::RegisterTaskDefinition flags
_TASK_CREATE_OR_UPDATE = 6
_TASK_LOGON_INTERACTIVE_TOKEN = 3


def _current_user_sid() -> str:
    """Return the caller's SID as a string (S-1-5-21-...)."""
    import ctypes.wintypes as wt
    advapi32 = ctypes.windll.advapi32
    kernel32 = ctypes.windll.kernel32

    TOKEN_QUERY = 0x0008
    TokenUser = 1

    hproc = kernel32.GetCurrentProcess()
    htok = wt.HANDLE()
    if not advapi32.OpenProcessToken(hproc, TOKEN_QUERY, ctypes.byref(htok)):
        raise ElevationError("OpenProcessToken failed")
    try:
        length = wt.DWORD(0)
        advapi32.GetTokenInformation(htok, TokenUser, None, 0, ctypes.byref(length))
        buf = (ctypes.c_byte * length.value)()
        if not advapi32.GetTokenInformation(
            htok, TokenUser, buf, length.value, ctypes.byref(length)
        ):
            raise ElevationError("GetTokenInformation failed")
        # TOKEN_USER { SID_AND_ATTRIBUTES { PSID Sid; DWORD Attributes; } User; }
        psid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]
        str_sid = ctypes.c_wchar_p()
        if not advapi32.ConvertSidToStringSidW(psid, ctypes.byref(str_sid)):
            raise ElevationError("ConvertSidToStringSidW failed")
        result = str_sid.value or ""
        kernel32.LocalFree(str_sid)
        return result
    finally:
        kernel32.CloseHandle(htok)


def register_helper_task() -> None:
    """Register the `\\DupeZ\\FirewallHelper` scheduled task.

    This call triggers a UAC prompt (one time) because creating a task
    with HighestAvailable requires admin. After registration, subsequent
    launches via `launch_helper_via_task()` will run at High IL with no
    further UAC prompts.
    """
    if sys.platform != "win32":
        raise ElevationError("scheduled_task elevation requires Windows")
    try:
        import win32com.client  # type: ignore
    except Exception as e:
        raise ElevationError(f"win32com not available: {e}") from e

    script = _helper_script_path()
    if script.lower().endswith(".py"):
        command = _python_exe()
        arguments = '"' + script + '" --role helper'
    else:
        command = script
        arguments = "--role helper"

    working_dir = os.path.dirname(script) or os.getcwd()

    try:
        user_sid = _current_user_sid()
    except Exception as e:
        log.warning("falling back to empty SID for task registration: %s", e)
        user_sid = ""

    xml = _TASK_XML_TEMPLATE.format(
        uri=TASK_PATH,
        user_sid=user_sid,
        command=_xml_escape(command),
        arguments=_xml_escape(arguments),
        working_dir=_xml_escape(working_dir),
    )

    scheduler = win32com.client.Dispatch("Schedule.Service")
    scheduler.Connect()
    # Get or create the \DupeZ folder.
    root = scheduler.GetFolder("\\")
    try:
        folder = scheduler.GetFolder(TASK_FOLDER)
    except Exception:
        folder = root.CreateFolder(TASK_FOLDER)

    folder.RegisterTask(
        TASK_NAME,
        xml,
        _TASK_CREATE_OR_UPDATE,
        None,  # user
        None,  # password
        _TASK_LOGON_INTERACTIVE_TOKEN,
        None,  # sddl
    )
    log.info("registered scheduled task %s", TASK_PATH)


def _xml_escape(s: str) -> str:
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;"))


def launch_helper_via_task(parent_pid: int) -> int:
    """Run the registered scheduled task. Returns the helper PID.

    NOTE: Task Scheduler doesn't accept arbitrary run-time arguments for
    pre-registered tasks on older Windows versions, so `--parent-pid` is
    written into an environment variable the helper reads at startup.
    We set DUPEZ_HELPER_PARENT_PID in this process's environment block
    — but the task runs in its own session, so we instead use a tiny
    sentinel file that the helper polls on startup.
    """
    if sys.platform != "win32":
        raise ElevationError("scheduled_task elevation requires Windows")
    try:
        import win32com.client  # type: ignore
    except Exception as e:
        raise ElevationError(f"win32com not available: {e}") from e

    # Write parent pid to a sentinel file the helper reads at startup.
    sentinel_path = _parent_pid_sentinel_path()
    try:
        os.makedirs(os.path.dirname(sentinel_path), exist_ok=True)
        with open(sentinel_path, "w", encoding="utf-8") as f:
            f.write(str(parent_pid))
    except Exception as e:
        log.warning("failed to write parent-pid sentinel: %s", e)

    scheduler = win32com.client.Dispatch("Schedule.Service")
    scheduler.Connect()
    folder = scheduler.GetFolder(TASK_FOLDER)
    task = folder.GetTask(TASK_NAME)
    running = task.Run(None)
    # IRunningTask::EnginePID is the High-IL helper PID.
    try:
        pid = int(running.EnginePID)
    except Exception:
        pid = 0
    log.info("launched helper via scheduled task, pid=%d", pid)
    return pid


def _parent_pid_sentinel_path() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "DupeZ", "helper_parent_pid.txt")


# ── Top-level orchestration ───────────────────────────────────────────

def ensure_helper_running(
    pipe_name: Optional[str] = None,
    mode: Optional[str] = None,
) -> int:
    """Spawn the helper using the resolved elevation strategy.

    Returns the helper PID. Raises ElevationError on failure.
    The caller should then connect the PipeClient and wait for the
    handshake — see `DisruptionManagerProxy._ensure_helper()`.
    """
    effective_mode = (mode or resolve_elevation_mode()).lower()
    parent_pid = os.getpid()

    if effective_mode == "auto":
        if is_helper_task_registered():
            effective_mode = "scheduled_task"
        else:
            effective_mode = "runas"
        log.info("auto-resolved elevation mode -> %s", effective_mode)

    if effective_mode == "scheduled_task":
        if not is_helper_task_registered():
            log.info("scheduled task not registered yet, registering now")
            register_helper_task()
        return launch_helper_via_task(parent_pid)

    if effective_mode == "runas":
        return launch_helper_runas(parent_pid, pipe_name=pipe_name)

    raise ElevationError(f"unknown elevation mode: {effective_mode}")
