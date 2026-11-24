"""Own a Windows compiler process tree before allowing its first instruction."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import math
import os
from pathlib import Path
import subprocess
import time


class BasicLimits(ctypes.Structure):
    _fields_ = [("user", ctypes.c_longlong), ("job_user", ctypes.c_longlong),
                ("flags", wintypes.DWORD), ("min_working", ctypes.c_size_t),
                ("max_working", ctypes.c_size_t), ("active_limit", wintypes.DWORD),
                ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]


class IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [("basic", BasicLimits), ("io", IoCounters), ("process_memory", ctypes.c_size_t),
                ("job_memory", ctypes.c_size_t), ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]


class Accounting(ctypes.Structure):
    _fields_ = [("user", ctypes.c_longlong), ("kernel", ctypes.c_longlong),
                ("period_user", ctypes.c_longlong), ("period_kernel", ctypes.c_longlong),
                ("faults", wintypes.DWORD), ("total", wintypes.DWORD),
                ("active", wintypes.DWORD), ("terminated", wintypes.DWORD)]


class JobProcessIds(ctypes.Structure):
    _fields_ = [("assigned", wintypes.DWORD), ("count", wintypes.DWORD),
                ("pids", ctypes.c_size_t * 4096)]


class StartupInfo(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("reserved", wintypes.LPWSTR), ("desktop", wintypes.LPWSTR),
                ("title", wintypes.LPWSTR), ("x", wintypes.DWORD), ("y", wintypes.DWORD),
                ("width", wintypes.DWORD), ("height", wintypes.DWORD),
                ("chars_x", wintypes.DWORD), ("chars_y", wintypes.DWORD), ("fill", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("show", wintypes.WORD), ("reserved_size", wintypes.WORD),
                ("reserved_bytes", ctypes.POINTER(wintypes.BYTE)), ("stdin", wintypes.HANDLE),
                ("stdout", wintypes.HANDLE), ("stderr", wintypes.HANDLE)]


class StartupInfoEx(ctypes.Structure):
    _fields_ = [("startup", StartupInfo), ("attributes", ctypes.c_void_p)]


class ProcessInfo(ctypes.Structure):
    _fields_ = [("process", wintypes.HANDLE), ("thread", wintypes.HANDLE),
                ("pid", wintypes.DWORD), ("tid", wintypes.DWORD)]


def kernel_api():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
        "SetInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
        "QueryInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p], wintypes.BOOL),
        "AssignProcessToJobObject": ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
        "TerminateJobObject": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
        "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        "GetCurrentProcess": ([], wintypes.HANDLE),
        "DuplicateHandle": ([wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.BOOL),
        "InitializeProcThreadAttributeList": ([ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_size_t)], wintypes.BOOL),
        "UpdateProcThreadAttribute": ([ctypes.c_void_p, wintypes.DWORD, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p], wintypes.BOOL),
        "DeleteProcThreadAttributeList": ([ctypes.c_void_p], None),
        "CreateProcessW": ([wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, wintypes.BOOL,
                            wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(StartupInfoEx), ctypes.POINTER(ProcessInfo)], wintypes.BOOL),
        "ResumeThread": ([wintypes.HANDLE], wintypes.DWORD),
        "WaitForSingleObject": ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
        "GetExitCodeProcess": ([wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
        "TerminateProcess": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
        "OpenProcess": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
        "IsProcessInJob": ([wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)], wintypes.BOOL),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(kernel, name)
        function.argtypes, function.restype = arguments, result
    return kernel


def checked(ok, operation):
    if not ok:
        raise OSError(ctypes.get_last_error(), operation + " failed")


def drain_job(kernel, job, *, seconds=10):
    """Terminate and observe no active descendants before input locks may unwind."""
    deadline = time.monotonic() + seconds
    handles = {}
    try:
        while True:
            listed = JobProcessIds()
            checked(kernel.QueryInformationJobObject(job, 3, ctypes.byref(listed), ctypes.sizeof(listed), None),
                    "Query job process IDs")
            if listed.count > 4096 or listed.assigned != listed.count:
                raise RuntimeError("Compiler job process list exceeds bounded capacity")
            for pid in listed.pids[:listed.count]:
                if pid in handles:
                    continue
                handle = kernel.OpenProcess(0x100000 | 0x1000, False, pid)  # SYNCHRONIZE + QUERY_LIMITED_INFORMATION
                if not handle and ctypes.get_last_error() == 87:
                    continue  # Already exited before the synchronization handle could be opened.
                checked(handle, "Open job process")
                handles[pid] = handle
                member = wintypes.BOOL()
                checked(kernel.IsProcessInJob(handle, job, ctypes.byref(member)), "Check job process membership")
                if not member.value:
                    raise RuntimeError("Job process identity changed before cleanup")
            checked(kernel.TerminateJobObject(job, 124), "TerminateJobObject")
            for handle in handles.values():
                remaining = max(0, math.ceil((deadline - time.monotonic()) * 1000))
                if kernel.WaitForSingleObject(handle, remaining) != 0:
                    raise RuntimeError("Compiler descendant did not signal termination within cleanup bound")
            accounting = Accounting()
            checked(kernel.QueryInformationJobObject(job, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None),
                    "QueryInformationJobObject")
            if accounting.active == 0:
                return
            if time.monotonic() >= deadline:
                raise RuntimeError("Compiler job did not reach zero active processes after termination")
            time.sleep(0.02)
    finally:
        for handle in handles.values():
            kernel.CloseHandle(handle)


def run_owned(command: list[str], *, cwd: Path, env: dict[str, str], stdout, timeout: float) -> int:
    """Launch suspended, assign a kill-on-close job, then resume; inherit only the log."""
    if os.name != "nt" or not command or not Path(command[0]).is_absolute():
        raise ValueError("A Windows absolute compiler path is required")
    if not math.isfinite(timeout) or not 0 < timeout <= 3600:
        raise ValueError("A finite bounded compiler timeout is required")
    if any(not isinstance(key, str) or not key or "=" in key or "\0" in key
           or not isinstance(value, str) or "\0" in value for key, value in env.items()):
        raise ValueError("Invalid closed environment")
    import msvcrt

    kernel = kernel_api()
    job = kernel.CreateJobObjectW(None, None)
    checked(job, "CreateJobObjectW")
    inherited_log = wintypes.HANDLE()
    process = ProcessInfo()
    attributes = None
    assigned = False
    drained = False
    try:
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE; no breakaway.
        checked(kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)), "SetInformationJobObject")
        owner = kernel.GetCurrentProcess()
        checked(kernel.DuplicateHandle(owner, msvcrt.get_osfhandle(stdout.fileno()), owner,
                                       ctypes.byref(inherited_log), 0, True, 2), "DuplicateHandle")
        size = ctypes.c_size_t()
        kernel.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
        if not 0 < size.value <= 65536:
            raise RuntimeError("Unexpected process attribute buffer size")
        storage = ctypes.create_string_buffer(size.value)
        checked(kernel.InitializeProcThreadAttributeList(storage, 1, 0, ctypes.byref(size)), "InitializeProcThreadAttributeList")
        attributes = ctypes.cast(storage, ctypes.c_void_p)
        handles = (wintypes.HANDLE * 1)(inherited_log.value)
        checked(kernel.UpdateProcThreadAttribute(attributes, 0, 0x00020002, handles, ctypes.sizeof(handles), None, None),
                "UpdateProcThreadAttribute")
        startup = StartupInfoEx()
        startup.startup.cb = ctypes.sizeof(startup)
        startup.startup.flags = 0x100  # STARTF_USESTDHANDLES; stdin intentionally null.
        startup.startup.stdout = startup.startup.stderr = inherited_log.value
        startup.attributes = attributes
        environment = ctypes.create_unicode_buffer("\0".join(key + "=" + env[key] for key in sorted(env, key=str.casefold)) + "\0\0")
        line = ctypes.create_unicode_buffer(subprocess.list2cmdline(command))
        flags = 0x4 | 0x400 | 0x80000 | 0x08000000  # suspended, Unicode env, extended startup, no console.
        checked(kernel.CreateProcessW(command[0], line, None, None, True, flags, environment, str(cwd),
                                      ctypes.byref(startup), ctypes.byref(process)), "CreateProcessW")
        checked(kernel.AssignProcessToJobObject(job, process.process), "AssignProcessToJobObject")
        assigned = True
        checked(kernel.ResumeThread(process.thread) != 0xFFFFFFFF, "ResumeThread")
        waited = kernel.WaitForSingleObject(process.process, math.ceil(timeout * 1000))
        if waited == 0x102:
            raise subprocess.TimeoutExpired(command, timeout)
        if waited != 0:
            raise OSError(ctypes.get_last_error(), "Compiler process wait failed")
        code = wintypes.DWORD()
        checked(kernel.GetExitCodeProcess(process.process, ctypes.byref(code)), "GetExitCodeProcess")
        drain_job(kernel, job)
        drained = True
        return int(code.value)
    finally:
        try:
            if assigned and not drained:
                drain_job(kernel, job)
            elif process.process and not assigned:
                checked(kernel.TerminateProcess(process.process, 124), "Terminate suspended process")
                checked(kernel.WaitForSingleObject(process.process, 10000) == 0, "Wait suspended process termination")
        finally:
            for handle in (process.thread, process.process, inherited_log.value, job):
                if handle:
                    kernel.CloseHandle(handle)
            if attributes is not None:
                kernel.DeleteProcThreadAttributeList(attributes)
