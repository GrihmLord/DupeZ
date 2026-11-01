# app/gui/map_host/launcher.py — Parent-side child-host controller.
"""Launch an unelevated WebEngine child process and embed its HWND.

The parent DupeZ process runs elevated (for WinDivert), and Chromium's
GPU process refuses to initialize under an admin token. This module
spawns a separate ``python -m app.gui.map_host.host`` process with the
interactive shell's non-elevated primary token, so the child gets real
GPU rasterization. The Win32 process-creation API returns the child's
PID and a process handle; both are retained until the child's window is
authenticated and then through its bounded shutdown.

Parent ↔ child communication is a line-delimited JSON protocol over a
loopback TCP socket. Each launch gets a 32-byte random session nonce,
passed as a distinct child argument. The child sends a ``hello``
containing that nonce, its PID, and its HWND. The parent compares the
nonce in constant time and requires the claimed PID to equal both the
PID returned by process creation, the PID owning the accepted TCP peer,
and the PID that owns the HWND before emitting it for reparenting.
Subsequent commands (``load`` / ``zoom`` / ``quit``) and the child's
strictly validated load/renderer status frames use the same socket.

Non-Windows development uses ``subprocess.Popen`` and retains its PID.
An elevated Windows parent never falls back to an inherited-token spawn: inability to
create a verifiably non-elevated child fails closed.
This child-process mode is experimental and source/development-only;
frozen builds fail closed and use the caller's in-process fallback.
"""
from __future__ import annotations

import hmac
import ipaddress
import json
import os
import secrets
import socket
import struct
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional, Sequence

from PyQt6.QtCore import QByteArray, QObject, QTimer, pyqtSignal
from PyQt6.QtNetwork import QHostAddress, QTcpServer, QTcpSocket

from app.gui.map_host.renderer_tier import child_webengine_environment
from app.logs.logger import log_error, log_info, log_warning


# Resolve the child script path once at import time.
_HOST_SCRIPT: str = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "host.py"
)
_REPO_ROOT: str = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
_SESSION_NONCE_BYTES = 32
_MAX_CHILD_FRAME_BYTES = 4096
_CHILD_HELLO_TIMEOUT_MS = 2000
_CHILD_LAUNCH_TIMEOUT_MS = 10_000
_CHILD_QUIT_FLUSH_TIMEOUT_MS = 250
_CHILD_GRACEFUL_EXIT_TIMEOUT_MS = 1000
_MAX_PENDING_CHILD_CONNECTIONS = 8
_TCP_TABLE_SNAPSHOT_ATTEMPTS = 3
_TCP_TABLE_RESIZE_ATTEMPTS = 3
_MAX_TCP_TABLE_BYTES = 16 * 1024 * 1024


@dataclass
class _SpawnedChild:
    """Identity returned by the process-creation boundary."""

    pid: int
    process_handle: Optional[int] = None
    close_handle: Optional[Callable[[int], None]] = None
    terminate_callback: Optional[Callable[[], None]] = None
    wait_callback: Optional[Callable[[int], bool]] = None
    _terminated: bool = field(default=False, init=False, repr=False)

    @property
    def has_lifecycle_control(self) -> bool:
        """Whether the caller can both observe exit and force termination."""
        return self.wait_callback is not None and self.terminate_callback is not None

    def wait(self, timeout_ms: int) -> bool:
        """Return whether the owned child exits within a bounded interval."""
        if timeout_ms < 0:
            raise ValueError("timeout_ms must be non-negative")
        if self.wait_callback is None:
            raise RuntimeError("spawned child has no wait ownership")
        return bool(self.wait_callback(timeout_ms))

    def close(self) -> None:
        """Release the retained process handle exactly once."""
        handle = self.process_handle
        self.process_handle = None
        if handle and self.close_handle is not None:
            self.close_handle(handle)

    def terminate(self) -> None:
        """Terminate a still-unauthenticated owned child, then release identity."""
        if self._terminated:
            self.close()
            return
        self._terminated = True
        callback = self.terminate_callback
        self.terminate_callback = None
        try:
            if callback is not None:
                callback()
        finally:
            self.close()


class _Win32ShellLaunchApi:
    """Narrow ctypes wrapper for non-elevated child creation."""

    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _TOKEN_ASSIGN_PRIMARY = 0x0001
    _TOKEN_DUPLICATE = 0x0002
    _TOKEN_QUERY = 0x0008
    _TOKEN_ELEVATION = 20
    _CREATE_NEW_PROCESS_GROUP = 0x00000200
    _CREATE_UNICODE_ENVIRONMENT = 0x00000400
    _CREATE_NO_WINDOW = 0x08000000
    _STARTF_USESHOWWINDOW = 0x00000001
    _SW_SHOWNORMAL = 1
    _WAIT_FAILED = 0xFFFFFFFF
    _WAIT_TIMEOUT = 0x00000102
    _TERMINATE_WAIT_MS = 1000

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        self._wintypes = wintypes
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._userenv = ctypes.WinDLL("userenv", use_last_error=True)

        class _TokenElevation(ctypes.Structure):
            _fields_ = [("TokenIsElevated", wintypes.DWORD)]

        class _StartupInfo(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("lpReserved", wintypes.LPWSTR),
                ("lpDesktop", wintypes.LPWSTR),
                ("lpTitle", wintypes.LPWSTR),
                ("dwX", wintypes.DWORD),
                ("dwY", wintypes.DWORD),
                ("dwXSize", wintypes.DWORD),
                ("dwYSize", wintypes.DWORD),
                ("dwXCountChars", wintypes.DWORD),
                ("dwYCountChars", wintypes.DWORD),
                ("dwFillAttribute", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD),
                ("wShowWindow", wintypes.WORD),
                ("cbReserved2", wintypes.WORD),
                ("lpReserved2", ctypes.POINTER(wintypes.BYTE)),
                ("hStdInput", wintypes.HANDLE),
                ("hStdOutput", wintypes.HANDLE),
                ("hStdError", wintypes.HANDLE),
            ]

        class _ProcessInformation(ctypes.Structure):
            _fields_ = [
                ("hProcess", wintypes.HANDLE),
                ("hThread", wintypes.HANDLE),
                ("dwProcessId", wintypes.DWORD),
                ("dwThreadId", wintypes.DWORD),
            ]

        self._TokenElevation = _TokenElevation
        self._StartupInfo = _StartupInfo
        self._ProcessInformation = _ProcessInformation
        self._configure_functions()

    def _configure_functions(self) -> None:
        ctypes = self._ctypes
        wintypes = self._wintypes

        self._user32.GetShellWindow.argtypes = []
        self._user32.GetShellWindow.restype = wintypes.HWND
        self._user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        self._kernel32.OpenProcess.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        self._kernel32.OpenProcess.restype = wintypes.HANDLE
        self._kernel32.GetCurrentProcess.argtypes = []
        self._kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel32.CloseHandle.restype = wintypes.BOOL
        self._kernel32.TerminateProcess.argtypes = [
            wintypes.HANDLE,
            wintypes.UINT,
        ]
        self._kernel32.TerminateProcess.restype = wintypes.BOOL
        self._kernel32.WaitForSingleObject.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
        ]
        self._kernel32.WaitForSingleObject.restype = wintypes.DWORD
        self._advapi32.OpenProcessToken.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.HANDLE),
        ]
        self._advapi32.OpenProcessToken.restype = wintypes.BOOL
        self._advapi32.GetTokenInformation.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._advapi32.GetTokenInformation.restype = wintypes.BOOL
        self._advapi32.CreateProcessWithTokenW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPCWSTR,
            wintypes.LPWSTR,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.LPCWSTR,
            ctypes.POINTER(self._StartupInfo),
            ctypes.POINTER(self._ProcessInformation),
        ]
        self._advapi32.CreateProcessWithTokenW.restype = wintypes.BOOL
        self._userenv.CreateEnvironmentBlock.argtypes = [
            ctypes.POINTER(wintypes.LPVOID),
            wintypes.HANDLE,
            wintypes.BOOL,
        ]
        self._userenv.CreateEnvironmentBlock.restype = wintypes.BOOL
        self._userenv.DestroyEnvironmentBlock.argtypes = [wintypes.LPVOID]
        self._userenv.DestroyEnvironmentBlock.restype = wintypes.BOOL

    def _last_error(self, operation: str) -> OSError:
        return OSError(self._ctypes.get_last_error(), operation)

    def close_handle(self, handle: int) -> None:
        if handle:
            self._kernel32.CloseHandle(self._wintypes.HANDLE(handle))

    def terminate_process(self, process_handle: int) -> None:
        """Terminate an owned pre-authentication child and bound the wait."""
        handle = self._wintypes.HANDLE(process_handle)
        if not self._kernel32.TerminateProcess(handle, 1):
            raise self._last_error("TerminateProcess(map host) failed")
        if not self.wait_process(process_handle, self._TERMINATE_WAIT_MS):
            raise TimeoutError("map-host termination wait timed out")

    def wait_process(self, process_handle: int, timeout_ms: int) -> bool:
        """Wait for a retained process handle without releasing it."""
        if timeout_ms < 0:
            raise ValueError("timeout_ms must be non-negative")
        handle = self._wintypes.HANDLE(process_handle)
        wait_result = int(self._kernel32.WaitForSingleObject(handle, timeout_ms))
        if wait_result == self._WAIT_FAILED:
            raise self._last_error("WaitForSingleObject(map host) failed")
        if wait_result == self._WAIT_TIMEOUT:
            return False
        if wait_result != 0:
            raise RuntimeError(f"unexpected process wait result: {wait_result}")
        return True

    def open_shell_token(self) -> int:
        """Open the primary token of the interactive desktop shell."""
        ctypes = self._ctypes
        wintypes = self._wintypes

        shell_hwnd = self._user32.GetShellWindow()
        if not shell_hwnd:
            raise RuntimeError("interactive Windows shell is unavailable")
        shell_pid = wintypes.DWORD()
        if not self._user32.GetWindowThreadProcessId(
            shell_hwnd,
            ctypes.byref(shell_pid),
        ) or not shell_pid.value:
            raise self._last_error("GetWindowThreadProcessId(shell) failed")

        process_handle = self._kernel32.OpenProcess(
            self._PROCESS_QUERY_LIMITED_INFORMATION,
            False,
            shell_pid.value,
        )
        if not process_handle:
            raise self._last_error("OpenProcess(shell) failed")
        token_handle = wintypes.HANDLE()
        desired_access = (
            self._TOKEN_ASSIGN_PRIMARY
            | self._TOKEN_DUPLICATE
            | self._TOKEN_QUERY
        )
        try:
            if not self._advapi32.OpenProcessToken(
                process_handle,
                desired_access,
                ctypes.byref(token_handle),
            ):
                raise self._last_error("OpenProcessToken(shell) failed")
        finally:
            self.close_handle(int(process_handle))
        if not token_handle.value:
            raise RuntimeError("interactive shell token is unavailable")
        return int(token_handle.value)

    def token_is_elevated(self, token_handle: int) -> bool:
        ctypes = self._ctypes
        wintypes = self._wintypes

        elevation = self._TokenElevation()
        returned = wintypes.DWORD()
        if not self._advapi32.GetTokenInformation(
            wintypes.HANDLE(token_handle),
            self._TOKEN_ELEVATION,
            ctypes.byref(elevation),
            ctypes.sizeof(elevation),
            ctypes.byref(returned),
        ):
            raise self._last_error("GetTokenInformation(TokenElevation) failed")
        if returned.value < ctypes.sizeof(elevation):
            raise RuntimeError("token elevation result is truncated")
        return bool(elevation.TokenIsElevated)

    def current_process_is_elevated(self) -> bool:
        """Return the caller token's elevation state or raise."""
        ctypes = self._ctypes
        wintypes = self._wintypes

        token_handle = wintypes.HANDLE()
        if not self._advapi32.OpenProcessToken(
            self._kernel32.GetCurrentProcess(),
            self._TOKEN_QUERY,
            ctypes.byref(token_handle),
        ):
            raise self._last_error("OpenProcessToken(current) failed")
        if not token_handle.value:
            raise RuntimeError("current process token is unavailable")
        try:
            return self.token_is_elevated(int(token_handle.value))
        finally:
            self.close_handle(int(token_handle.value))

    def _token_environment(self, token_handle: int) -> dict[str, str]:
        """Read a bounded environment block belonging to ``token_handle``."""
        ctypes = self._ctypes
        wintypes = self._wintypes
        raw_environment = wintypes.LPVOID()
        if not self._userenv.CreateEnvironmentBlock(
            ctypes.byref(raw_environment),
            wintypes.HANDLE(token_handle),
            False,
        ):
            raise self._last_error("CreateEnvironmentBlock(map host) failed")
        try:
            if not raw_environment.value:
                raise RuntimeError("map-host token environment is unavailable")
            chars = ctypes.cast(
                raw_environment,
                ctypes.POINTER(ctypes.c_wchar),
            )
            entries: list[str] = []
            current: list[str] = []
            # CreateProcess has a much smaller practical environment limit;
            # this cap also prevents an invalid native block from causing an
            # unbounded read in the privileged parent.
            for index in range(131_072):
                char = chars[index]
                if char:
                    current.append(char)
                    continue
                if not current:
                    break
                entries.append("".join(current))
                current = []
            else:
                raise RuntimeError("map-host token environment is unterminated")

            environment: dict[str, str] = {}
            for entry in entries:
                separator = entry.find("=", 1 if entry.startswith("=") else 0)
                if separator <= 0:
                    continue
                environment[entry[:separator]] = entry[separator + 1:]
            if not environment:
                raise RuntimeError("map-host token environment is empty")
            return child_webengine_environment(environment)
        finally:
            self._userenv.DestroyEnvironmentBlock(raw_environment)

    def _environment_buffer(self, environment: dict[str, str]):
        """Serialize a validated mapping as a Windows Unicode env block."""
        entries: list[str] = []
        for key, value in environment.items():
            if not key or "\x00" in key or "\x00" in value:
                raise ValueError("map-host environment contains an invalid value")
            if "=" in key and not key.startswith("="):
                raise ValueError("map-host environment contains an invalid key")
            entries.append(f"{key}={value}")
        entries.sort(key=str.casefold)
        # create_unicode_buffer appends the second NUL required by an
        # environment block.
        return self._ctypes.create_unicode_buffer("\x00".join(entries) + "\x00")

    def create_process(
        self,
        token_handle: int,
        executable: str,
        argv: Sequence[str],
        cwd: str,
    ) -> _SpawnedChild:
        """Create a process and retain the returned process handle."""
        ctypes = self._ctypes
        wintypes = self._wintypes

        command_line = ctypes.create_unicode_buffer(
            subprocess.list2cmdline([executable, *argv])
        )
        startup = self._StartupInfo()
        startup.cb = ctypes.sizeof(startup)
        startup.dwFlags = self._STARTF_USESHOWWINDOW
        startup.wShowWindow = self._SW_SHOWNORMAL
        process_info = self._ProcessInformation()
        environment = self._environment_buffer(
            self._token_environment(token_handle)
        )
        flags = (
            self._CREATE_NEW_PROCESS_GROUP
            | self._CREATE_UNICODE_ENVIRONMENT
            | self._CREATE_NO_WINDOW
        )
        if not self._advapi32.CreateProcessWithTokenW(
            wintypes.HANDLE(token_handle),
            0,
            executable,
            command_line,
            flags,
            ctypes.cast(environment, wintypes.LPVOID),
            cwd,
            ctypes.byref(startup),
            ctypes.byref(process_info),
        ):
            raise self._last_error("CreateProcessWithTokenW failed")

        process_handle = int(process_info.hProcess or 0)
        thread_handle = int(process_info.hThread or 0)
        try:
            if not process_handle or not process_info.dwProcessId:
                raise RuntimeError("process creation returned no child identity")
            return _SpawnedChild(
                pid=int(process_info.dwProcessId),
                process_handle=process_handle,
                close_handle=self.close_handle,
                terminate_callback=lambda: self.terminate_process(process_handle),
                wait_callback=lambda timeout_ms: self.wait_process(
                    process_handle,
                    timeout_ms,
                ),
            )
        except Exception:
            self.close_handle(process_handle)
            raise
        finally:
            self.close_handle(thread_handle)


def _append_child_frame_bytes(buffer: bytes, incoming: bytes) -> bytes:
    """Append one unauthenticated child frame without unbounded buffering."""
    combined_size = len(buffer) + len(incoming)
    if combined_size > _MAX_CHILD_FRAME_BYTES:
        raise ValueError(
            f"child hello exceeds {_MAX_CHILD_FRAME_BYTES} bytes"
        )
    return buffer + incoming


@dataclass(frozen=True)
class _TcpOwnerRow:
    """Host-order projection of one MIB_TCPROW_OWNER_PID entry."""

    local_address: str
    local_port: int
    remote_address: str
    remote_port: int
    owning_pid: int


def _mib_ipv4_to_text(raw_address: int) -> str:
    """Decode a DWORD stored in the same native layout as ``in_addr``."""
    packed = struct.pack("=I", raw_address & 0xFFFFFFFF)
    return socket.inet_ntoa(packed)


def _mib_port_to_host(raw_port: int) -> int:
    """Decode the low 16 bits of a MIB port from network byte order."""
    return socket.ntohs(raw_port & 0xFFFF)


def _read_windows_tcp_owner_rows() -> tuple[_TcpOwnerRow, ...]:
    """Take one bounded IPv4 owner-PID TCP table snapshot."""
    import ctypes
    from ctypes import wintypes

    error_insufficient_buffer = 122
    tcp_table_owner_pid_connections = 4

    class _MibTcpRowOwnerPid(ctypes.Structure):
        _fields_ = [
            ("dwState", wintypes.DWORD),
            ("dwLocalAddr", wintypes.DWORD),
            ("dwLocalPort", wintypes.DWORD),
            ("dwRemoteAddr", wintypes.DWORD),
            ("dwRemotePort", wintypes.DWORD),
            ("dwOwningPid", wintypes.DWORD),
        ]

    class _MibTcpTableOwnerPid(ctypes.Structure):
        _fields_ = [
            ("dwNumEntries", wintypes.DWORD),
            ("table", _MibTcpRowOwnerPid * 1),
        ]

    get_table = ctypes.WinDLL(
        "iphlpapi",
        use_last_error=True,
    ).GetExtendedTcpTable
    get_table.argtypes = [
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.BOOL,
        wintypes.ULONG,
        ctypes.c_int,
        wintypes.ULONG,
    ]
    get_table.restype = wintypes.DWORD

    table_size = wintypes.DWORD(0)
    result = int(
        get_table(
            None,
            ctypes.byref(table_size),
            False,
            socket.AF_INET,
            tcp_table_owner_pid_connections,
            0,
        )
    )
    if result != error_insufficient_buffer:
        raise OSError(result, "GetExtendedTcpTable sizing failed")

    for _attempt in range(_TCP_TABLE_RESIZE_ATTEMPTS):
        size = int(table_size.value)
        if size <= 0 or size > _MAX_TCP_TABLE_BYTES:
            raise RuntimeError("GetExtendedTcpTable returned an invalid size")
        table_buffer = ctypes.create_string_buffer(size)
        result = int(
            get_table(
                table_buffer,
                ctypes.byref(table_size),
                False,
                socket.AF_INET,
                tcp_table_owner_pid_connections,
                0,
            )
        )
        if result == error_insufficient_buffer:
            continue
        if result != 0:
            raise OSError(result, "GetExtendedTcpTable snapshot failed")

        row_offset = _MibTcpTableOwnerPid.table.offset
        row_size = ctypes.sizeof(_MibTcpRowOwnerPid)
        entry_count = wintypes.DWORD.from_buffer(table_buffer).value
        required_size = row_offset + int(entry_count) * row_size
        if required_size > len(table_buffer):
            raise RuntimeError("GetExtendedTcpTable returned a truncated table")

        rows: list[_TcpOwnerRow] = []
        base_address = ctypes.addressof(table_buffer) + row_offset
        for index in range(int(entry_count)):
            row = _MibTcpRowOwnerPid.from_address(
                base_address + index * row_size
            )
            rows.append(
                _TcpOwnerRow(
                    local_address=_mib_ipv4_to_text(int(row.dwLocalAddr)),
                    local_port=_mib_port_to_host(int(row.dwLocalPort)),
                    remote_address=_mib_ipv4_to_text(int(row.dwRemoteAddr)),
                    remote_port=_mib_port_to_host(int(row.dwRemotePort)),
                    owning_pid=int(row.dwOwningPid),
                )
            )
        return tuple(rows)

    raise RuntimeError("GetExtendedTcpTable changed during bounded retries")


def _canonical_ipv4(address: str) -> str:
    parsed = ipaddress.ip_address(address)
    if isinstance(parsed, ipaddress.IPv6Address):
        if parsed.ipv4_mapped is None:
            raise ValueError("map-host socket endpoint is not IPv4")
        parsed = parsed.ipv4_mapped
    return str(parsed)


def _peer_pid_from_rows(
    rows: Iterable[_TcpOwnerRow],
    peer_address: str,
    peer_port: int,
    server_address: str,
    server_port: int,
) -> Optional[int]:
    """Match the child-side reverse four-tuple in one TCP table snapshot."""
    target = (
        _canonical_ipv4(peer_address),
        int(peer_port),
        _canonical_ipv4(server_address),
        int(server_port),
    )
    matches = [
        row.owning_pid
        for row in rows
        if (
            _canonical_ipv4(row.local_address),
            row.local_port,
            _canonical_ipv4(row.remote_address),
            row.remote_port,
        )
        == target
    ]
    if len(matches) > 1:
        raise RuntimeError("TCP peer owner lookup is ambiguous")
    if not matches:
        return None
    if matches[0] <= 0:
        raise RuntimeError("TCP peer owner PID is unavailable")
    return matches[0]


def _windows_tcp_peer_process_id(
    peer_address: str,
    peer_port: int,
    server_address: str,
    server_port: int,
) -> int:
    """Resolve an accepted socket's client-side owner PID, fail closed."""
    for _attempt in range(_TCP_TABLE_SNAPSHOT_ATTEMPTS):
        owner_pid = _peer_pid_from_rows(
            _read_windows_tcp_owner_rows(),
            peer_address,
            peer_port,
            server_address,
            server_port,
        )
        if owner_pid is not None:
            return owner_pid
    raise RuntimeError("TCP peer owner row was not found")


def _validate_child_socket_peer(
    sock: QTcpSocket,
    expected_pid: int,
    *,
    current_platform: Optional[str] = None,
    peer_pid_lookup: Optional[Callable[[str, int, str, int], int]] = None,
) -> int:
    """Bind a Windows candidate socket to the spawned child's actual PID."""
    platform_name = sys.platform if current_platform is None else current_platform
    if platform_name != "win32":
        return expected_pid
    if expected_pid <= 0:
        raise ValueError("spawned child pid is unavailable")
    lookup = peer_pid_lookup or _windows_tcp_peer_process_id
    try:
        owner_pid = int(
            lookup(
                _canonical_ipv4(sock.peerAddress().toString()),
                int(sock.peerPort()),
                _canonical_ipv4(sock.localAddress().toString()),
                int(sock.localPort()),
            )
        )
    except Exception as exc:
        raise ValueError("child TCP peer owner lookup failed") from exc
    if owner_pid != expected_pid:
        raise ValueError("child TCP peer owner does not match spawned child pid")
    return owner_pid


def _window_process_id(hwnd: int) -> int:
    """Return the OS-reported owner PID for a Windows HWND."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    get_owner = user32.GetWindowThreadProcessId
    get_owner.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    get_owner.restype = wintypes.DWORD

    owner_pid = wintypes.DWORD()
    thread_id = get_owner(wintypes.HWND(hwnd), ctypes.byref(owner_pid))
    if not thread_id or not owner_pid.value:
        raise OSError(
            ctypes.get_last_error(),
            "GetWindowThreadProcessId failed",
        )
    return int(owner_pid.value)


def _validate_child_hello(
    message: object,
    expected_nonce: str,
    expected_pid: int,
    *,
    current_platform: Optional[str] = None,
    window_pid_lookup: Optional[Callable[[int], int]] = None,
) -> tuple[int, int]:
    """Authenticate a child hello and return ``(hwnd, claimed_pid)``.

    The helper is independent of Qt so the privilege boundary can be tested
    without creating sockets or native windows. No caller may emit or reparent
    the returned HWND until this function succeeds.
    """
    if not isinstance(message, dict) or message.get("type") != "hello":
        raise ValueError("child hello must be a JSON object with type 'hello'")
    if not isinstance(expected_nonce, str) or not expected_nonce:
        raise ValueError("parent session nonce is unavailable")
    if (
        not isinstance(expected_pid, int)
        or isinstance(expected_pid, bool)
        or expected_pid <= 0
    ):
        raise ValueError("spawned child pid is unavailable")

    presented_nonce = message.get("session_nonce")
    if not isinstance(presented_nonce, str):
        raise ValueError("child hello has a malformed session nonce")
    try:
        presented_bytes = presented_nonce.encode("ascii")
        expected_bytes = expected_nonce.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("child hello has a malformed session nonce") from exc
    if not hmac.compare_digest(presented_bytes, expected_bytes):
        raise ValueError("child hello session authentication failed")

    claimed_pid = message.get("pid")
    if not isinstance(claimed_pid, int) or isinstance(claimed_pid, bool):
        raise ValueError("child hello has a malformed pid")
    if claimed_pid <= 0:
        raise ValueError("child hello has a malformed pid")
    if claimed_pid != expected_pid:
        raise ValueError("child hello pid does not match spawned child pid")

    hwnd = message.get("hwnd")
    if not isinstance(hwnd, int) or isinstance(hwnd, bool) or hwnd <= 0:
        raise ValueError("child hello has a malformed hwnd")

    platform_name = sys.platform if current_platform is None else current_platform
    if platform_name == "win32":
        lookup = window_pid_lookup or _window_process_id
        try:
            owner_pid = int(lookup(hwnd))
        except Exception as exc:
            raise ValueError("child hello HWND owner lookup failed") from exc
        if owner_pid != expected_pid:
            raise ValueError(
                "child hello HWND owner does not match spawned child pid"
            )

    return hwnd, claimed_pid


def _validate_child_status(message: object) -> tuple[str, object]:
    """Validate one bounded post-authentication browser status frame."""

    if not isinstance(message, dict):
        raise ValueError("child status must be a JSON object")
    kind = message.get("type")
    if kind == "load-started":
        if set(message) != {"type"}:
            raise ValueError("child load-started status has unexpected fields")
        return kind, None
    if kind == "load-finished":
        if set(message) != {"type", "ok"} or type(message.get("ok")) is not bool:
            raise ValueError("child load-finished status is malformed")
        return kind, bool(message["ok"])
    if kind == "renderer-terminated":
        if set(message) != {"type", "status", "exit_code"}:
            raise ValueError("child renderer status has unexpected fields")
        status = message.get("status")
        exit_code = message.get("exit_code")
        if not isinstance(status, str) or not status or len(status) > 64:
            raise ValueError("child renderer status name is malformed")
        if (
            not isinstance(exit_code, int)
            or isinstance(exit_code, bool)
            or not -(2 ** 31) <= exit_code < 2 ** 31
        ):
            raise ValueError("child renderer exit code is malformed")
        return kind, (status, int(exit_code))
    raise ValueError("child sent an unknown browser status")


# ── Win32 HWND reparenting ──────────────────────────────────────────


def _set_parent_result_is_successful(
    previous_parent: int,
    last_error: int,
    actual_parent: int,
    requested_parent: int,
) -> bool:
    """Resolve SetParent's documented NULL success/failure ambiguity."""
    if actual_parent != requested_parent:
        return False
    return previous_parent != 0 or last_error == 0


def _window_long_result_is_successful(value: int, last_error: int) -> bool:
    """Resolve Get/SetWindowLongPtr's documented zero ambiguity."""
    return value != 0 or last_error == 0


class _Win32ReparentApi:
    """Checked Win32 calls used by the HWND embedding transaction."""

    _GWL_STYLE = -16
    _SWP_NOSIZE = 0x0001
    _SWP_NOMOVE = 0x0002
    _SWP_NOZORDER = 0x0004
    _SWP_NOACTIVATE = 0x0010
    _SWP_FRAMECHANGED = 0x0020
    _SW_SHOW = 5
    _STYLE_MASK = 0xFFFFFFFF

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        self._wintypes = wintypes
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)

        if ctypes.sizeof(ctypes.c_void_p) == 8:
            self._get_long = self._user32.GetWindowLongPtrW
            self._set_long = self._user32.SetWindowLongPtrW
            self._style_type = ctypes.c_ssize_t
        else:
            self._get_long = self._user32.GetWindowLongW
            self._set_long = self._user32.SetWindowLongW
            self._style_type = ctypes.c_long
        self._get_long.argtypes = [wintypes.HWND, ctypes.c_int]
        self._get_long.restype = self._style_type
        self._set_long.argtypes = [
            wintypes.HWND,
            ctypes.c_int,
            self._style_type,
        ]
        self._set_long.restype = self._style_type

        self._get_parent = self._user32.GetParent
        self._get_parent.argtypes = [wintypes.HWND]
        self._get_parent.restype = wintypes.HWND
        self._set_parent = self._user32.SetParent
        self._set_parent.argtypes = [wintypes.HWND, wintypes.HWND]
        self._set_parent.restype = wintypes.HWND
        self._set_window_pos = self._user32.SetWindowPos
        self._set_window_pos.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        self._set_window_pos.restype = wintypes.BOOL
        self._show_window = self._user32.ShowWindow
        self._show_window.argtypes = [wintypes.HWND, ctypes.c_int]
        self._show_window.restype = wintypes.BOOL

    def _last_error(self, operation: str, error: Optional[int] = None) -> OSError:
        code = self._ctypes.get_last_error() if error is None else error
        return OSError(code, operation)

    def get_style(self, hwnd: int) -> int:
        """Read GWL_STYLE, disambiguating a valid zero from failure."""
        self._ctypes.set_last_error(0)
        style = int(
            self._get_long(
                self._wintypes.HWND(hwnd),
                self._GWL_STYLE,
            )
        )
        error = int(self._ctypes.get_last_error())
        if not _window_long_result_is_successful(style, error):
            raise self._last_error("GetWindowLongPtrW(GWL_STYLE) failed", error)
        return style & self._STYLE_MASK

    def set_style(self, hwnd: int, style: int) -> None:
        """Set GWL_STYLE with documented zero/last-error handling."""
        normalized = int(style) & self._STYLE_MASK
        self._ctypes.set_last_error(0)
        previous = int(
            self._set_long(
                self._wintypes.HWND(hwnd),
                self._GWL_STYLE,
                self._style_type(normalized),
            )
        )
        error = int(self._ctypes.get_last_error())
        if not _window_long_result_is_successful(previous, error):
            raise self._last_error("SetWindowLongPtrW(GWL_STYLE) failed", error)
        if self.get_style(hwnd) != normalized:
            raise RuntimeError("SetWindowLongPtrW did not apply the requested style")

    def get_parent(self, hwnd: int) -> int:
        """Read the parent/owner, disambiguating a valid NULL result."""
        self._ctypes.set_last_error(0)
        parent = int(self._get_parent(self._wintypes.HWND(hwnd)) or 0)
        error = int(self._ctypes.get_last_error())
        if parent == 0 and error != 0:
            raise self._last_error("GetParent failed", error)
        return parent

    def set_parent(
        self,
        hwnd: int,
        parent_hwnd: int,
        *,
        verify_actual: bool = True,
    ) -> None:
        """Set and verify the parent, including SetParent's NULL ambiguity."""
        self._ctypes.set_last_error(0)
        previous = int(
            self._set_parent(
                self._wintypes.HWND(hwnd),
                self._wintypes.HWND(parent_hwnd),
            )
            or 0
        )
        error = int(self._ctypes.get_last_error())
        if previous == 0 and error != 0:
            raise self._last_error("SetParent failed", error)
        if not verify_actual:
            return
        actual = self.get_parent(hwnd)
        if not _set_parent_result_is_successful(
            previous,
            error,
            actual,
            parent_hwnd,
        ):
            raise RuntimeError(
                "SetParent did not apply the requested parent "
                f"(actual={actual}, requested={parent_hwnd})"
            )

    def resize_and_refresh(self, hwnd: int, width: int, height: int) -> None:
        """Resize the child and apply cached frame/style changes."""
        if not self._set_window_pos(
            self._wintypes.HWND(hwnd),
            self._wintypes.HWND(0),
            0,
            0,
            int(width),
            int(height),
            self._SWP_NOZORDER | self._SWP_FRAMECHANGED | self._SWP_NOACTIVATE,
        ):
            raise self._last_error("SetWindowPos(map host) failed")

    def refresh_frame(self, hwnd: int) -> None:
        """Apply a restored style without changing the original geometry."""
        flags = (
            self._SWP_NOSIZE
            | self._SWP_NOMOVE
            | self._SWP_NOZORDER
            | self._SWP_NOACTIVATE
            | self._SWP_FRAMECHANGED
        )
        if not self._set_window_pos(
            self._wintypes.HWND(hwnd),
            self._wintypes.HWND(0),
            0,
            0,
            0,
            0,
            flags,
        ):
            raise self._last_error("SetWindowPos(map host rollback) failed")

    def show(self, hwnd: int) -> None:
        """Show the embedded window; zero means previously hidden, not failure."""
        self._show_window(self._wintypes.HWND(hwnd), self._SW_SHOW)


def _restore_reparent_state(
    api: object,
    child_hwnd: int,
    original_parent: int,
    original_style: int,
) -> None:
    """Best-effort restoration after a partially applied embed transaction."""
    failures: list[str] = []
    try:
        # With WS_CHILD still set, SetParent(hwnd, NULL) temporarily reports
        # the desktop HWND. Verify only after restoring the original style.
        api.set_parent(
            child_hwnd,
            original_parent,
            verify_actual=False,
        )
    except Exception as exc:  # noqa: BLE001
        failures.append(f"parent restore failed: {exc!r}")
    try:
        api.set_style(child_hwnd, original_style)
    except Exception as exc:  # noqa: BLE001
        failures.append(f"style restore failed: {exc!r}")
    try:
        actual_parent = api.get_parent(child_hwnd)
        if actual_parent != original_parent:
            raise RuntimeError(
                "restored parent mismatch "
                f"(actual={actual_parent}, expected={original_parent})"
            )
    except Exception as exc:  # noqa: BLE001
        failures.append(f"parent verification failed: {exc!r}")
    try:
        api.refresh_frame(child_hwnd)
    except Exception as exc:  # noqa: BLE001
        failures.append(f"frame restore failed: {exc!r}")
    if failures:
        log_error("map-host: reparent rollback incomplete: " + "; ".join(failures))


def _reparent_hwnd_with_api(
    child_hwnd: int,
    parent_hwnd: int,
    width: int,
    height: int,
    api: object,
) -> bool:
    """Apply the Win32 embedding operation as a rollback-safe transaction."""
    try:
        original_parent = api.get_parent(child_hwnd)
        original_style = api.get_style(child_hwnd)
    except Exception as exc:  # noqa: BLE001
        log_error(f"map-host: failed to capture reparent state: {exc!r}")
        return False

    WS_CHILD = 0x40000000
    WS_POPUP = 0x80000000
    WS_CAPTION = 0x00C00000
    WS_THICKFRAME = 0x00040000
    WS_SYSMENU = 0x00080000
    WS_MINIMIZEBOX = 0x00020000
    WS_MAXIMIZEBOX = 0x00010000
    embedded_style = original_style & ~(
        WS_POPUP
        | WS_CAPTION
        | WS_THICKFRAME
        | WS_SYSMENU
        | WS_MINIMIZEBOX
        | WS_MAXIMIZEBOX
    )
    embedded_style |= WS_CHILD

    try:
        api.set_style(child_hwnd, embedded_style)
        api.set_parent(child_hwnd, parent_hwnd)
        api.resize_and_refresh(child_hwnd, width, height)
        api.show(child_hwnd)
    except Exception as exc:  # noqa: BLE001
        _restore_reparent_state(
            api,
            child_hwnd,
            original_parent,
            original_style,
        )
        log_error(f"map-host: reparent transaction failed: {exc!r}")
        return False

    log_info(
        f"map-host: reparented hwnd=0x{child_hwnd:x} into "
        f"parent=0x{parent_hwnd:x} at {width}x{height}"
    )
    return True


def reparent_hwnd_into_container(
    child_hwnd: int,
    parent_hwnd: int,
    width: int,
    height: int,
) -> bool:
    """Embed a foreign top-level HWND inside a parent HWND (Windows).

    Qt's ``QWindow.fromWinId`` + ``createWindowContainer`` path is
    unreliable for foreign HWNDs from another process: it creates a
    Qt-side container widget but does not always call the Win32
    ``SetParent`` that actually moves the native window into our
    client area. The result is that the child's frameless QMainWindow
    stays a floating top-level and covers the screen.

    This helper does the reparent the Windows-native way:

    1. Strip top-level window styles (WS_POPUP / WS_CAPTION /
       WS_THICKFRAME / WS_SYSMENU) and add WS_CHILD.
    2. Call ``SetParent`` to move the HWND under the container.
    3. Call ``SetWindowPos`` with SWP_FRAMECHANGED so the new style
       takes effect.
    4. ``ShowWindow(SW_SHOW)`` so the now-child HWND is visible
       inside the container's client area.

    Returns True on success. Non-Windows platforms return False.
    """
    if sys.platform != "win32":
        return False

    try:
        return _reparent_hwnd_with_api(
            child_hwnd,
            parent_hwnd,
            width,
            height,
            _Win32ReparentApi(),
        )
    except Exception as exc:  # noqa: BLE001
        log_error(f"map-host: reparent_hwnd_into_container failed: {exc!r}")
        return False


def resize_child_hwnd(child_hwnd: int, width: int, height: int) -> None:
    """Resize an embedded child HWND to match its container (Windows)."""
    if sys.platform != "win32" or not child_hwnd:
        return
    try:
        import ctypes

        user32 = ctypes.windll.user32
        # MoveWindow(hWnd, X, Y, nWidth, nHeight, bRepaint)
        user32.MoveWindow(
            ctypes.c_void_p(child_hwnd),
            0,
            0,
            int(width),
            int(height),
            True,
        )
    except Exception as exc:  # noqa: BLE001
        log_warning(f"map-host: resize_child_hwnd failed: {exc!r}")


# ── Verifiable process creation ─────────────────────────────────────


def _validated_spawn(executable: str, argv: Sequence[str]) -> tuple[str, list[str]]:
    """Return a pinned executable and validated, unjoined arguments."""
    resolved = os.path.abspath(executable)
    if not os.path.isabs(executable) or not os.path.isfile(resolved):
        raise ValueError("map-host executable must be an existing absolute file")
    clean: list[str] = []
    for arg in argv:
        if not isinstance(arg, str) or "\x00" in arg:
            raise ValueError("map-host argument is invalid")
        clean.append(arg)
    return resolved, clean


def _spawn_with_shell_token(
    python_exe: str,
    argv: Sequence[str],
    *,
    api: Optional[_Win32ShellLaunchApi] = None,
) -> _SpawnedChild:
    """Create a child with the interactive shell's non-elevated token."""
    executable, clean_argv = _validated_spawn(python_exe, argv)
    win32 = api or _Win32ShellLaunchApi()
    token_handle = win32.open_shell_token()
    try:
        if win32.token_is_elevated(token_handle):
            raise RuntimeError("interactive shell token is elevated")
        child = win32.create_process(
            token_handle,
            executable,
            clean_argv,
            _REPO_ROOT,
        )
    finally:
        win32.close_handle(token_handle)
    if child.pid <= 0:
        child.close()
        raise RuntimeError("process creation returned an invalid child pid")
    return child


def _spawn_unelevated(
    python_exe: str,
    argv: Sequence[str],
    *,
    api: Optional[_Win32ShellLaunchApi] = None,
) -> Optional[_SpawnedChild]:
    """Spawn a child and return its OS-issued process identity.

    An elevated production Windows parent uses ``CreateProcessWithTokenW``
    with the interactive shell token. Failure is terminal: an inherited-token
    fallback could silently start an elevated WebEngine child and is
    therefore forbidden. Non-Windows development keeps the ordinary
    subprocess path.
    """
    if sys.platform != "win32":
        return _spawn_popen(python_exe, argv)

    try:
        win32 = api or _Win32ShellLaunchApi()
        if not win32.current_process_is_elevated():
            child = _spawn_popen(python_exe, argv)
            if child is None:
                return None
            log_info(
                "map-host: parent token is non-elevated; inherited-token "
                f"child pid={child.pid} is safe"
            )
            return child

        child = _spawn_with_shell_token(python_exe, argv, api=win32)
        log_info(
            "map-host: spawned non-elevated child "
            f"with verified pid={child.pid}"
        )
        return child
    except Exception as exc:  # noqa: BLE001
        log_error(
            f"map-host: non-elevated Windows spawn failed ({exc!r}); "
            "refusing inherited-token fallback"
        )
        return None


def _spawn_popen(
    python_exe: str,
    argv: Sequence[str],
) -> Optional[_SpawnedChild]:
    """Managed subprocess spawn when the inherited token is safe.

    Routed through ``safe_subprocess.spawn_managed`` so argv validation,
    CREATE_NO_WINDOW, audit events, and pre-authentication termination all
    apply. The executable is validated normally.
    """
    try:
        from app.core import safe_subprocess as _safe_sp
        executable, clean_argv = _validated_spawn(python_exe, argv)
        managed = _safe_sp.spawn_managed(
            [executable, *clean_argv],
            cwd=_REPO_ROOT,
            env=child_webengine_environment(os.environ),
            trusted_executable=False,
            intent="map_host.spawn_managed_python",
        )
        pid = managed.pid
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            raise RuntimeError("subprocess spawn returned an invalid pid")
        log_info(
            "map-host: spawned development child "
            f"with pid={pid}"
        )

        def _terminate_managed() -> None:
            managed.kill()
            managed.wait(_Win32ShellLaunchApi._TERMINATE_WAIT_MS / 1000)

        return _SpawnedChild(
            pid=pid,
            terminate_callback=_terminate_managed,
            wait_callback=lambda timeout_ms: managed.wait(timeout_ms / 1000),
        )
    except Exception as exc:  # noqa: BLE001
        log_error(f"map-host: subprocess fallback failed: {exc}")
        return None


# ── Parent-side controller ──────────────────────────────────────────


def _is_frozen_runtime() -> bool:
    """Return whether source-module child launching is unavailable."""
    return bool(getattr(sys, "frozen", False))


class MapHostClient(QObject):
    """Controls the lifecycle of an unelevated WebEngine child host.

    Usage:
        client = MapHostClient(self)
        client.hwndReceived.connect(self._embed_host_hwnd)
        client.connectionFailed.connect(self._fall_back_to_inproc)
        client.start()
        # ... later ...
        client.load(url)
        client.set_zoom(0.85)
        client.quit()   # also called in aboutToQuit

    Signals:
        hwndReceived(int)     — child sent its top-level HWND
        connectionFailed(str) — spawn or connect failed; caller should
                                fall back to the in-proc WebEngineView
        disconnected()        — child process exited or dropped socket
        loadStarted()         — authenticated child began navigation
        loadFinished(bool)    — authenticated child completed navigation
        renderProcessTerminated(str, int) — Chromium renderer terminated
    """

    hwndReceived = pyqtSignal(int)
    connectionFailed = pyqtSignal(str)
    disconnected = pyqtSignal()
    loadStarted = pyqtSignal()
    loadFinished = pyqtSignal(bool)
    renderProcessTerminated = pyqtSignal(str, int)

    def __init__(
        self,
        parent: Optional[QObject] = None,
        *,
        peer_pid_lookup: Optional[
            Callable[[str, int, str, int], int]
        ] = None,
    ) -> None:
        super().__init__(parent)
        self._server: QTcpServer = QTcpServer(self)
        self._server.newConnection.connect(self._on_new_connection)
        self._sock: Optional[QTcpSocket] = None
        self._authenticated_buffer = b""
        self._candidate_buffers: dict[QTcpSocket, bytes] = {}
        self._candidate_timers: dict[QTcpSocket, QTimer] = {}
        self._candidate_peer_pids: dict[QTcpSocket, int] = {}
        self._launch_timer = QTimer(self)
        self._launch_timer.setSingleShot(True)
        self._launch_timer.timeout.connect(self._on_launch_timeout)
        self._hwnd: Optional[int] = None
        self._session_nonce: Optional[str] = None
        self._spawned_child: Optional[_SpawnedChild] = None
        self._expected_pid: Optional[int] = None
        self._peer_pid_lookup = peer_pid_lookup
        self._stopping = False
        self._webengine_ready = False

    # ── Lifecycle ───────────────────────────────────────────────

    def start(self) -> bool:
        """Bind the listener and spawn the child.

        Returns ``False`` only on immediate failures (bind error,
        spawn dispatch error). A ``True`` return does NOT guarantee
        the child actually connected — wait for ``hwndReceived`` or
        ``connectionFailed``.
        """
        if self._server.isListening() or self._spawned_child is not None:
            log_warning("map-host: start ignored while a launch is active")
            return False
        if _is_frozen_runtime():
            reason = (
                "map-host child mode is unavailable in frozen builds; "
                "use the in-process map fallback"
            )
            log_warning(reason)
            self.connectionFailed.emit(reason)
            return False
        self._hwnd = None
        self._expected_pid = None
        self._authenticated_buffer = b""
        self._webengine_ready = False
        if not self._server.listen(
            QHostAddress.SpecialAddress.LocalHost, 0
        ):
            err = self._server.errorString()
            log_error(f"map-host: TCP listen failed: {err}")
            self.connectionFailed.emit(err)
            return False

        port = self._server.serverPort()
        session_nonce = secrets.token_hex(_SESSION_NONCE_BYTES)
        self._session_nonce = session_nonce

        # Launch: `python -m app.gui.map_host.host --parent-port N
        # --session-nonce NONCE`. The elevated Windows path uses the
        # interactive shell's verified token with CreateProcessWithTokenW;
        # its returned PID/handle become the handshake trust boundary.
        # Distinct argv elements preserve boundaries through that API.
        args = [
            "-m",
            "app.gui.map_host.host",
            "--parent-port",
            str(port),
            "--session-nonce",
            session_nonce,
        ]
        spawned_child = _spawn_unelevated(sys.executable, args)
        if spawned_child is None:
            self._session_nonce = None
            self._server.close()
            self.connectionFailed.emit("spawn failed")
            return False
        if sys.platform == "win32" and not spawned_child.has_lifecycle_control:
            reason = "map-host child lifecycle ownership is unavailable"
            log_error(reason)
            try:
                if spawned_child.terminate_callback is not None:
                    spawned_child.terminate()
                else:
                    spawned_child.close()
            finally:
                self._session_nonce = None
                self._server.close()
            self.connectionFailed.emit(reason)
            return False
        self._spawned_child = spawned_child
        self._expected_pid = spawned_child.pid
        self._launch_timer.start(_CHILD_LAUNCH_TIMEOUT_MS)

        log_info(
            "map-host: waiting for child "
            f"pid={spawned_child.pid} on 127.0.0.1:{port}"
        )
        return True

    def stop(self) -> None:
        """Gracefully stop an authenticated child, then force it if hung."""
        if self._stopping:
            return
        self._stopping = True
        sock = self._sock
        authenticated = self._hwnd is not None and sock is not None
        try:
            self._launch_timer.stop()
            self._drop_all_candidates("client stopped")
            try:
                self._server.close()
            except Exception:
                pass

            if authenticated:
                try:
                    self.quit()
                    if sock.bytesToWrite() > 0:
                        sock.waitForBytesWritten(_CHILD_QUIT_FLUSH_TIMEOUT_MS)
                except Exception as exc:  # noqa: BLE001
                    log_warning(f"map-host: graceful quit write failed: {exc}")
                self._shutdown_spawned_child(_CHILD_GRACEFUL_EXIT_TIMEOUT_MS)
            else:
                self._terminate_spawned_child()

            if sock is not None:
                self._disconnect_socket(sock)
            self._sock = None
            self._session_nonce = None
            self._expected_pid = None
            self._hwnd = None
            self._authenticated_buffer = b""
            self._webengine_ready = False
        finally:
            self._stopping = False

    @property
    def hwnd(self) -> Optional[int]:
        return self._hwnd

    @property
    def webengine_ready(self) -> bool:
        """Whether the authenticated child completed its latest load."""

        return self._webengine_ready

    # ── Socket handling ─────────────────────────────────────────

    def _on_new_connection(self) -> None:
        """Admit bounded candidates until the spawned child authenticates."""
        while self._server.hasPendingConnections():
            sock = self._server.nextPendingConnection()
            if sock is None:
                return
            sock.setReadBufferSize(_MAX_CHILD_FRAME_BYTES + 1)
            if self._hwnd is not None:
                self._disconnect_socket(sock)
                continue
            try:
                peer_pid = _validate_child_socket_peer(
                    sock,
                    self._expected_pid or 0,
                    peer_pid_lookup=self._peer_pid_lookup,
                )
            except ValueError as exc:
                log_warning(f"map-host: rejected child candidate: {exc}")
                self._disconnect_socket(sock)
                continue
            if len(self._candidate_buffers) >= _MAX_PENDING_CHILD_CONNECTIONS:
                oldest = next(iter(self._candidate_buffers))
                self._drop_candidate(oldest, "candidate limit reached")
            self._candidate_buffers[sock] = b""
            self._candidate_peer_pids[sock] = peer_pid
            timer = QTimer(sock)
            timer.setSingleShot(True)
            timer.timeout.connect(
                lambda candidate=sock: self._on_hello_timeout(candidate)
            )
            self._candidate_timers[sock] = timer
            sock.readyRead.connect(
                lambda candidate=sock: self._on_candidate_ready(candidate)
            )
            sock.disconnected.connect(
                lambda candidate=sock: self._on_socket_disconnected(candidate)
            )
            timer.start(_CHILD_HELLO_TIMEOUT_MS)
            log_info("map-host: child candidate connected")

    def _on_candidate_ready(self, sock: QTcpSocket) -> None:
        if sock not in self._candidate_buffers:
            if sock is self._sock:
                self._on_authenticated_ready(sock)
            return
        try:
            remaining = (
                _MAX_CHILD_FRAME_BYTES
                + 1
                - len(self._candidate_buffers[sock])
            )
            if remaining <= 0:
                raise ValueError(
                    f"child hello exceeds {_MAX_CHILD_FRAME_BYTES} bytes"
                )
            buffer = _append_child_frame_bytes(
                self._candidate_buffers[sock],
                bytes(sock.read(remaining)),
            )
        except ValueError as exc:
            self._drop_candidate(sock, str(exc))
            return
        except Exception:
            return
        self._candidate_buffers[sock] = buffer
        if b"\n" not in buffer:
            return
        line, remainder = buffer.split(b"\n", 1)
        if remainder:
            self._drop_candidate(sock, "unexpected bytes after child hello")
            return
        if not line.strip():
            self._drop_candidate(sock, "empty child hello")
            return
        try:
            msg = json.loads(line.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            log_error(f"map-host: bad frame from child: {exc}")
            self._drop_candidate(sock, "malformed JSON")
            return
        try:
            hwnd, claimed_pid = _validate_child_hello(
                msg,
                self._session_nonce or "",
                self._expected_pid or 0,
            )
        except ValueError as exc:
            self._drop_candidate(sock, str(exc))
            return
        if self._candidate_peer_pids.get(sock) != self._expected_pid:
            self._drop_candidate(sock, "child TCP peer identity was not retained")
            return

        self._accept_authenticated_child(sock, hwnd, claimed_pid)

    def _accept_authenticated_child(
        self,
        sock: QTcpSocket,
        hwnd: int,
        claimed_pid: int,
    ) -> None:
        """Commit one candidate only after all identity checks succeed."""
        if sock.bytesAvailable() > 0:
            self._drop_candidate(sock, "unexpected bytes after child hello")
            return
        timer = self._candidate_timers.pop(sock, None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()
        self._candidate_buffers.pop(sock, None)
        self._candidate_peer_pids.pop(sock, None)
        self._sock = sock
        self._authenticated_buffer = b""
        self._webengine_ready = False
        self._server.close()
        self._launch_timer.stop()
        for candidate in list(self._candidate_buffers):
            self._drop_candidate(candidate, "authenticated child selected")
        self._session_nonce = None
        self._hwnd = hwnd
        log_info(
            f"map-host: authenticated child pid={claimed_pid} "
            f"hwnd=0x{hwnd:x}"
        )
        self.hwndReceived.emit(hwnd)

    def _on_hello_timeout(self, sock: QTcpSocket) -> None:
        if sock in self._candidate_buffers:
            self._drop_candidate(sock, "child hello deadline exceeded")

    def _on_launch_timeout(self) -> None:
        """Fail a launch that never produced an authenticated child hello."""
        if self._hwnd is not None or self._spawned_child is None:
            return
        reason = "map-host launch authentication deadline exceeded"
        log_error(reason)
        self._drop_all_candidates(reason)
        self._server.close()
        self._session_nonce = None
        self._expected_pid = None
        self._terminate_spawned_child()
        self.connectionFailed.emit(reason)

    def _drop_candidate(self, sock: QTcpSocket, reason: str) -> None:
        """Drop one unauthenticated socket while preserving the listener."""
        if sock not in self._candidate_buffers:
            return
        log_warning(f"map-host: rejected child candidate: {reason}")
        self._candidate_buffers.pop(sock, None)
        self._candidate_peer_pids.pop(sock, None)
        timer = self._candidate_timers.pop(sock, None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()
        self._disconnect_socket(sock)

    def _drop_all_candidates(self, reason: str) -> None:
        for candidate in list(self._candidate_buffers):
            self._drop_candidate(candidate, reason)

    @staticmethod
    def _disconnect_socket(sock: QTcpSocket) -> None:
        try:
            sock.abort()
        except Exception:
            try:
                sock.disconnectFromHost()
            except Exception:
                pass
        try:
            sock.deleteLater()
        except Exception:
            pass

    def _on_socket_disconnected(self, sock: QTcpSocket) -> None:
        if sock in self._candidate_buffers:
            self._candidate_buffers.pop(sock, None)
            self._candidate_peer_pids.pop(sock, None)
            timer = self._candidate_timers.pop(sock, None)
            if timer is not None:
                timer.stop()
                timer.deleteLater()
            sock.deleteLater()
            return
        if sock is not self._sock:
            return
        if self._stopping:
            sock.deleteLater()
            return
        self._sock = None
        self._hwnd = None
        self._expected_pid = None
        self._authenticated_buffer = b""
        self._webengine_ready = False
        self._shutdown_spawned_child(0)
        sock.deleteLater()
        log_info("map-host: child disconnected")
        self.disconnected.emit()

    def _on_authenticated_ready(self, sock: QTcpSocket) -> None:
        """Consume only the three reviewed child browser-status frames."""
        try:
            remaining = (
                _MAX_CHILD_FRAME_BYTES + 1 - len(self._authenticated_buffer)
            )
            if remaining <= 0:
                raise ValueError("child browser status exceeds frame limit")
            incoming = bytes(sock.read(remaining))
            self._authenticated_buffer += incoming
            if len(self._authenticated_buffer) > _MAX_CHILD_FRAME_BYTES:
                raise ValueError("child browser status exceeds frame limit")

            while b"\n" in self._authenticated_buffer:
                line, self._authenticated_buffer = self._authenticated_buffer.split(
                    b"\n", 1
                )
                if not line.strip():
                    raise ValueError("child browser status is empty")
                try:
                    message = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ValueError("child browser status is malformed JSON") from exc
                kind, payload = _validate_child_status(message)
                if kind == "load-started":
                    self._webengine_ready = False
                    self.loadStarted.emit()
                elif kind == "load-finished":
                    ready = bool(payload)
                    self._webengine_ready = ready
                    self.loadFinished.emit(ready)
                else:
                    status, exit_code = payload
                    self._webengine_ready = False
                    self.renderProcessTerminated.emit(status, exit_code)
        except (TypeError, ValueError) as exc:
            self._reject_authenticated_input(sock, str(exc))

    def _reject_authenticated_input(
        self,
        sock: QTcpSocket,
        reason: str = "unexpected authenticated child input",
    ) -> None:
        """Abort the authenticated child on any unreviewed status input."""
        log_warning(f"map-host: rejected authenticated child input: {reason}")
        self._sock = None
        self._hwnd = None
        self._expected_pid = None
        self._authenticated_buffer = b""
        self._webengine_ready = False
        self._disconnect_socket(sock)
        self._terminate_spawned_child()
        self.disconnected.emit()

    def _terminate_spawned_child(self) -> None:
        child = self._spawned_child
        self._spawned_child = None
        if child is None:
            return
        try:
            child.terminate()
        except Exception as exc:  # noqa: BLE001
            log_error(f"map-host: failed to terminate unauthenticated child: {exc}")

    def _shutdown_spawned_child(self, graceful_timeout_ms: int) -> None:
        """Wait for graceful exit, then terminate an owned child exactly once."""
        child = self._spawned_child
        self._spawned_child = None
        if child is None:
            return
        exited = False
        try:
            exited = child.wait(graceful_timeout_ms)
        except Exception as exc:  # noqa: BLE001
            log_warning(f"map-host: child exit wait failed: {exc}")
        if exited:
            child.close()
            return
        try:
            child.terminate()
        except Exception as exc:  # noqa: BLE001
            log_error(f"map-host: forced child termination failed: {exc}")

    # ── Commands ────────────────────────────────────────────────

    def _send(self, obj: dict) -> None:
        if self._sock is None:
            return
        try:
            line = (json.dumps(obj) + "\n").encode("utf-8")
            self._sock.write(QByteArray(line))
            self._sock.flush()
        except Exception as exc:  # noqa: BLE001
            log_error(f"map-host: send failed: {exc}")

    def load(self, url: str) -> None:
        self._send({"type": "load", "url": url})

    def set_zoom(self, factor: float) -> None:
        self._send({"type": "zoom", "factor": factor})

    def quit(self) -> None:
        self._send({"type": "quit"})


# ── Prewarm singleton ───────────────────────────────────────────────
#
# DayZMapGUI is created eagerly by the dashboard when the main window
# builds, but that happens *after* the splash pipeline finishes — so
# the map host spawn and iZurvive load time are both on the critical
# path before the user sees the map. prewarm_map_host() spins the
# client up during the splash pipeline, on the main thread, so that
# Chromium, the child process, and the initial tile load all happen
# in parallel with the rest of DupeZ's boot. When DayZMapGUI is
# finally constructed it consumes the prewarmed client instead of
# starting a fresh one.

_PREWARMED_CLIENT: Optional[MapHostClient] = None


def prewarm_map_host(initial_url: str) -> bool:
    """Start the unelevated map host early and begin loading a map.

    Must be called on the main thread (``QTcpServer`` / ``QTcpSocket``
    are thread-affine to their owning thread, and Dashboard will want
    to adopt the client from the main thread later).

    Returns ``True`` if a prewarm was started (or was already
    running). Returns ``False`` on immediate spawn failure — callers
    should fall back to on-demand start inside DayZMapGUI.
    """
    global _PREWARMED_CLIENT
    if _PREWARMED_CLIENT is not None:
        return True

    client = MapHostClient(parent=None)

    def _on_hwnd(_hwnd: int) -> None:
        # Child is up — kick off the initial map load so tiles are
        # downloading while the user watches the splash finish.
        try:
            client.load(initial_url)
            log_info("map-host: prewarm load dispatched")
        except Exception as exc:  # noqa: BLE001
            log_warning(f"map-host: prewarm load failed: {exc}")

    def _on_failed(reason: str) -> None:
        global _PREWARMED_CLIENT
        log_warning(f"map-host: prewarm failed ({reason})")
        _PREWARMED_CLIENT = None

    client.hwndReceived.connect(_on_hwnd)
    client.connectionFailed.connect(_on_failed)

    if not client.start():
        log_warning("map-host: prewarm start() returned False")
        return False

    _PREWARMED_CLIENT = client
    log_info("map-host: prewarm dispatched")
    return True


def consume_prewarmed_client() -> Optional[MapHostClient]:
    """Hand off the prewarmed client to its final owner (DayZMapGUI).

    Returns ``None`` if no prewarm was active or it already failed.
    The caller becomes responsible for the client's lifecycle and
    must re-parent it (``setParent``) so Qt ownership is correct.
    """
    global _PREWARMED_CLIENT
    client = _PREWARMED_CLIENT
    _PREWARMED_CLIENT = None
    return client
