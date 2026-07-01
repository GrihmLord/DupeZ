"""Bind elevated helpers to a kill-on-parent-close Windows Job object."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from typing import Any

JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
PROCESS_TERMINATE = 0x0001
PROCESS_SET_QUOTA = 0x0100

_JOB_HANDLES: list[int] = []


class _BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def bind_helper_to_parent_lifetime(
    pid: int,
    *,
    kernel32: Any = None,
) -> bool:
    """Assign *pid* to a job killed automatically when this process exits."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    if kernel32 is None:
        if os.name != "nt":
            return False
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.OpenProcess.restype = wintypes.HANDLE

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return False

    info = _ExtendedLimitInformation()
    info.BasicLimitInformation.LimitFlags = (
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    )
    configured = kernel32.SetInformationJobObject(
        job,
        JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )
    if not configured:
        kernel32.CloseHandle(job)
        return False

    process = kernel32.OpenProcess(
        PROCESS_TERMINATE | PROCESS_SET_QUOTA,
        False,
        pid,
    )
    if not process:
        kernel32.CloseHandle(job)
        return False
    try:
        assigned = kernel32.AssignProcessToJobObject(job, process)
    finally:
        kernel32.CloseHandle(process)
    if not assigned:
        kernel32.CloseHandle(job)
        return False

    # Deliberately retain the job handle for the GUI process lifetime.
    _JOB_HANDLES.append(int(job))
    return True
