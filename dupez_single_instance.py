"""Crash-safe, cross-integrity single-instance guard for the DupeZ GUI.

The guard deliberately uses only the Python standard library so the root
launcher can acquire it before importing Qt or the application package.
Windows owns the named-mutex handle, which means an abnormal process exit
releases the lock without a stale file that could brick future launches.

The mutex is scoped to the current Windows user and logon session. Its
security descriptor has a Low mandatory label and a user-only DACL so the
same user sees one GUI instance whether the first process is running at
Medium or High integrity level.
"""

from __future__ import annotations

import atexit
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from enum import Enum
import getpass
import hashlib
import os
import sys
from typing import Sequence

__all__ = [
    "guard_gui_startup",
    "is_non_gui_launch",
    "release_gui_instance",
]

_ERROR_ACCESS_DENIED = 5
_ERROR_ALREADY_EXISTS = 183
_SDDL_REVISION_1 = 1
_TOKEN_QUERY = 0x0008
_TOKEN_USER = 1

_MAINTENANCE_FLAGS = frozenset({"--reset-audit", "--verify-self"})

_ALREADY_RUNNING_MESSAGE = (
    "DupeZ is already running for this Windows user.\n\n"
    "Open the existing DupeZ window. If it is unresponsive, close it in "
    "Task Manager, then launch DupeZ again."
)
_LOCK_ERROR_MESSAGE = (
    "DupeZ could not create its single-instance startup lock (Windows "
    "error {error}).\n\nTo protect the app's state, this launch was stopped. "
    "Close any existing DupeZ process in Task Manager and try again."
)


class _AcquireState(Enum):
    ACQUIRED = "acquired"
    ALREADY_RUNNING = "already_running"
    ERROR = "error"


@dataclass(frozen=True)
class _AcquireResult:
    state: _AcquireState
    handle: int | None = None
    error: int = 0


class _SecurityAttributes(ctypes.Structure):
    _fields_ = (
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", wintypes.LPVOID),
        ("bInheritHandle", wintypes.BOOL),
    )


class _SidAndAttributes(ctypes.Structure):
    _fields_ = (
        ("Sid", wintypes.LPVOID),
        ("Attributes", wintypes.DWORD),
    )


class _TokenUser(ctypes.Structure):
    _fields_ = (("User", _SidAndAttributes),)


_instance_handle: int | None = None
_instance_pid: int | None = None
_release_registered = False


def _role_value(argv: Sequence[str]) -> str | None:
    """Return the value following ``--role``, if it is present."""
    try:
        index = argv.index("--role")
    except ValueError:
        return None
    if index + 1 >= len(argv):
        return None
    return str(argv[index + 1]).strip().lower()


def is_non_gui_launch(argv: Sequence[str] | None = None) -> bool:
    """Return whether *argv* represents a helper or maintenance launch."""
    args = tuple(sys.argv if argv is None else argv)
    if _role_value(args) == "helper":
        return True
    return any(flag in args for flag in _MAINTENANCE_FLAGS)


def _windows_dll(name: str):
    return ctypes.WinDLL(name, use_last_error=True)


def _current_user_sid() -> str | None:
    """Return the current token user's SID without importing pywin32."""
    if sys.platform != "win32":
        return None

    kernel32 = _windows_dll("kernel32")
    advapi32 = _windows_dll("advapi32")

    kernel32.GetCurrentProcess.argtypes = ()
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = (wintypes.HLOCAL,)
    kernel32.LocalFree.restype = wintypes.HLOCAL

    advapi32.OpenProcessToken.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    )
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = (
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.LPWSTR),
    )
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL

    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(),
        _TOKEN_QUERY,
        ctypes.byref(token),
    ):
        return None

    try:
        required = wintypes.DWORD()
        advapi32.GetTokenInformation(
            token,
            _TOKEN_USER,
            None,
            0,
            ctypes.byref(required),
        )
        if required.value == 0:
            return None

        token_info = ctypes.create_string_buffer(required.value)
        if not advapi32.GetTokenInformation(
            token,
            _TOKEN_USER,
            token_info,
            required,
            ctypes.byref(required),
        ):
            return None

        token_user = ctypes.cast(
            token_info,
            ctypes.POINTER(_TokenUser),
        ).contents
        sid_string = wintypes.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(
            token_user.User.Sid,
            ctypes.byref(sid_string),
        ):
            return None
        try:
            return sid_string.value
        finally:
            kernel32.LocalFree(ctypes.cast(sid_string, wintypes.HLOCAL))
    finally:
        kernel32.CloseHandle(token)


def _identity_key(sid: str | None) -> str:
    """Return a stable, non-identifying key for the mutex namespace."""
    if sid:
        identity = sid
    else:
        identity = "\\".join(
            part
            for part in (
                os.environ.get("USERDOMAIN", ""),
                os.environ.get("USERNAME", "") or getpass.getuser(),
            )
            if part
        )
    return hashlib.sha256(identity.casefold().encode("utf-8")).hexdigest()[:24]


def _instance_name(sid: str | None = None) -> str:
    """Build a per-user name in the current logon-session namespace."""
    resolved_sid = _current_user_sid() if sid is None else sid
    return rf"Local\DupeZ.GUI.{_identity_key(resolved_sid)}"


def _security_descriptor_sddl(sid: str) -> str:
    """Return the user-only, cross-integrity security descriptor."""
    return f"D:P(A;;GA;;;{sid})(A;;GA;;;SY)S:(ML;;NW;;;LW)"


def _create_security_attributes(
    advapi32,
    sid: str | None,
) -> tuple[_SecurityAttributes | None, wintypes.LPVOID | None]:
    """Build mutex security attributes; return ``(None, None)`` on failure."""
    if not sid:
        return None, None

    converter = advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW
    converter.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.DWORD),
    )
    converter.restype = wintypes.BOOL

    descriptor = wintypes.LPVOID()
    if not converter(
        _security_descriptor_sddl(sid),
        _SDDL_REVISION_1,
        ctypes.byref(descriptor),
        None,
    ):
        return None, None

    attributes = _SecurityAttributes(
        ctypes.sizeof(_SecurityAttributes),
        descriptor,
        False,
    )
    return attributes, descriptor


def _acquire_windows_mutex(name: str | None = None) -> _AcquireResult:
    """Atomically create/open the named mutex and classify the result."""
    if sys.platform != "win32":
        return _AcquireResult(_AcquireState.ACQUIRED)

    kernel32 = _windows_dll("kernel32")
    advapi32 = _windows_dll("advapi32")
    kernel32.CreateMutexW.argtypes = (
        ctypes.POINTER(_SecurityAttributes),
        wintypes.BOOL,
        wintypes.LPCWSTR,
    )
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.LocalFree.argtypes = (wintypes.HLOCAL,)
    kernel32.LocalFree.restype = wintypes.HLOCAL

    sid = _current_user_sid()
    mutex_name = name or _instance_name(sid)
    attributes, descriptor = _create_security_attributes(advapi32, sid)
    try:
        ctypes.set_last_error(0)
        attributes_ptr = (
            ctypes.byref(attributes) if attributes is not None else None
        )
        handle = kernel32.CreateMutexW(attributes_ptr, False, mutex_name)
        error = ctypes.get_last_error()
    finally:
        if descriptor:
            kernel32.LocalFree(ctypes.cast(descriptor, wintypes.HLOCAL))

    if handle:
        handle_value = int(handle)
        if error == _ERROR_ALREADY_EXISTS:
            _close_windows_handle(handle_value)
            return _AcquireResult(
                _AcquireState.ALREADY_RUNNING,
                error=error,
            )
        return _AcquireResult(
            _AcquireState.ACQUIRED,
            handle=handle_value,
        )

    # A Medium-IL process may receive ACCESS_DENIED if a legacy/default
    # descriptor was used by an already-running High-IL build. Treat that
    # as contention, not a reason to start an unsafe second GUI.
    if error == _ERROR_ACCESS_DENIED:
        return _AcquireResult(
            _AcquireState.ALREADY_RUNNING,
            error=error,
        )
    return _AcquireResult(_AcquireState.ERROR, error=error)


def _close_windows_handle(handle: int) -> None:
    if sys.platform != "win32" or not handle:
        return
    try:
        kernel32 = _windows_dll("kernel32")
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CloseHandle(wintypes.HANDLE(handle))
    except Exception:
        pass


def release_gui_instance() -> None:
    """Release this process's retained mutex handle, if any."""
    global _instance_handle, _instance_pid
    handle = _instance_handle
    _instance_handle = None
    _instance_pid = None
    if handle:
        _close_windows_handle(handle)


def _notify_startup_blocked(message: str) -> None:
    """Show an actionable pre-Qt message and mirror it to stderr."""
    try:
        stream = getattr(sys, "stderr", None)
        if stream is not None:
            stream.write(f"[dupez] {message}\n")
    except Exception:
        pass

    if sys.platform != "win32":
        return
    try:
        user32 = _windows_dll("user32")
        user32.MessageBoxW.argtypes = (
            wintypes.HWND,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.UINT,
        )
        user32.MessageBoxW.restype = ctypes.c_int
        # MB_OK | MB_ICONINFORMATION | MB_SETFOREGROUND
        user32.MessageBoxW(
            None,
            message,
            "DupeZ Startup",
            0x00000000 | 0x00000040 | 0x00010000,
        )
    except Exception:
        pass


def guard_gui_startup(
    argv: Sequence[str] | None = None,
    *,
    notify: bool = True,
) -> bool:
    """Acquire the GUI mutex once for this process.

    Returns ``True`` when startup may continue (including helper and
    maintenance bypasses), and ``False`` when another GUI owns the mutex or
    Windows could not create the lock. Repeated calls in the owning process
    are idempotent.
    """
    global _instance_handle, _instance_pid, _release_registered

    args = tuple(sys.argv if argv is None else argv)
    if is_non_gui_launch(args):
        return True

    pid = os.getpid()
    if _instance_pid == pid and (_instance_handle or sys.platform != "win32"):
        return True

    result = _acquire_windows_mutex()
    if result.state is _AcquireState.ACQUIRED:
        _instance_handle = result.handle
        _instance_pid = pid
        if not _release_registered:
            atexit.register(release_gui_instance)
            _release_registered = True
        return True

    if result.state is _AcquireState.ALREADY_RUNNING:
        message = _ALREADY_RUNNING_MESSAGE
    else:
        message = _LOCK_ERROR_MESSAGE.format(error=result.error or "unknown")
    if notify:
        _notify_startup_blocked(message)
    return False
