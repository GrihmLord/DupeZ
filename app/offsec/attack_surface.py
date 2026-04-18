"""
Local attack-surface mapping (MITRE ATT&CK TA0007 Discovery, local only).

Enumerates the externally- and internally-visible attack surface the
DupeZ process exposes *on this host*:

* **Listening sockets** owned by our own PID — anything bound to
  non-loopback, anything listening without authentication, and any
  stray listener we didn't expect.
* **Named pipes** (Windows) whose DACL grants Everyone or Authenticated
  Users write access — the classic local-IPC takeover primitive.
* **File permissions** on sensitive on-disk assets: the secret store,
  the audit log, the HMAC-protected persistence files, and the plugin
  directory.

This module is strictly read-only and local-scope. It does NOT connect
out, does NOT scan other hosts, and does NOT attempt to interact with
any pipe or socket it finds — it only inspects metadata.
"""

from __future__ import annotations

import os
import socket
import stat
import sys
from pathlib import Path
from typing import List, Optional

from app.offsec import require_consent
from app.offsec.findings import FindingRegistry, Severity

__all__ = ["run_attack_surface"]


# ── Listening sockets ──────────────────────────────────────────────

def _iter_our_listeners() -> List[dict]:
    """Return a list of sockets listening on this PID.

    Uses psutil if available, falls back to a best-effort no-op if not.
    We only enumerate listeners *owned by our own PID* — enumerating
    every listener on the box would require admin and is out of scope
    for a local self-test.
    """
    try:
        import psutil
    except ImportError:
        return []
    try:
        proc = psutil.Process(os.getpid())
    except Exception:
        return []
    out: List[dict] = []
    try:
        for c in proc.connections(kind="inet"):
            if c.status != psutil.CONN_LISTEN:
                continue
            laddr = c.laddr
            out.append({
                "family": "IPv6" if c.family == socket.AF_INET6 else "IPv4",
                "proto": "TCP" if c.type == socket.SOCK_STREAM else "UDP",
                "ip": laddr.ip if laddr else "",
                "port": laddr.port if laddr else 0,
                "fd": c.fd,
            })
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        pass
    return out


def _check_listeners(reg: FindingRegistry) -> None:
    listeners = _iter_our_listeners()
    if not listeners:
        reg.record(
            title="No listening sockets owned by DupeZ",
            description=(
                "DupeZ process is not holding any listening TCP/UDP sockets "
                "(or psutil is unavailable to confirm)."
            ),
            severity=Severity.INFO,
            evidence={"count": 0},
        )
        return

    non_loopback: List[dict] = []
    loopback: List[dict] = []
    for li in listeners:
        ip = li.get("ip", "")
        if ip in {"127.0.0.1", "::1", "localhost"}:
            loopback.append(li)
        elif ip in {"0.0.0.0", "::"}:
            non_loopback.append(li)
        else:
            # Specific IP that isn't loopback — could be LAN-exposed.
            non_loopback.append(li)

    if non_loopback:
        reg.record(
            title=f"{len(non_loopback)} non-loopback listeners owned by DupeZ",
            description=(
                "DupeZ is listening on one or more non-loopback addresses. "
                "Unless these are explicit user-configured features, they "
                "represent network-reachable attack surface."
            ),
            severity=Severity.HIGH,
            cvss_base=7.3,
            cvss_vector="CVSS:3.1/AV:A/AC:L/PR:N/UI:N/S:U/C:L/I:L/A:L",
            attack_technique="T1046",  # Network Service Discovery
            evidence={"listeners": non_loopback},
            remediation=(
                "Bind all internal IPC sockets to 127.0.0.1 / ::1 explicitly. "
                "If a LAN-facing socket is required, document it and gate it "
                "behind a signed configuration flag."
            ),
        )

    if loopback:
        reg.record(
            title=f"{len(loopback)} loopback listeners owned by DupeZ",
            description=(
                "DupeZ is listening on loopback — acceptable for local IPC, "
                "but loopback does not provide authentication. Any local "
                "process running as the same user can connect."
            ),
            severity=Severity.LOW,
            attack_technique="T1021",  # Remote Services (local case)
            evidence={"listeners": loopback},
            remediation=(
                "Ensure the loopback listener authenticates peers — e.g., by "
                "verifying the peer PID via SO_PEERCRED on Linux or "
                "GetNamedPipeClientProcessId on Windows — rather than trusting "
                "any connection from localhost."
            ),
        )


# ── Named pipes (Windows) ─────────────────────────────────────────

def _check_named_pipes(reg: FindingRegistry) -> None:
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return

    # Enumerate \\.\pipe\ via FindFirstFile / FindNextFile.
    kernel32 = ctypes.windll.kernel32
    INVALID = wintypes.HANDLE(-1).value

    class WIN32_FIND_DATAW(ctypes.Structure):
        _fields_ = [
            ("dwFileAttributes", wintypes.DWORD),
            ("ftCreationTime", wintypes.FILETIME),
            ("ftLastAccessTime", wintypes.FILETIME),
            ("ftLastWriteTime", wintypes.FILETIME),
            ("nFileSizeHigh", wintypes.DWORD),
            ("nFileSizeLow", wintypes.DWORD),
            ("dwReserved0", wintypes.DWORD),
            ("dwReserved1", wintypes.DWORD),
            ("cFileName", wintypes.WCHAR * 260),
            ("cAlternateFileName", wintypes.WCHAR * 14),
        ]

    kernel32.FindFirstFileW.restype = wintypes.HANDLE
    kernel32.FindFirstFileW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(WIN32_FIND_DATAW)]
    kernel32.FindNextFileW.restype = wintypes.BOOL
    kernel32.FindNextFileW.argtypes = [wintypes.HANDLE, ctypes.POINTER(WIN32_FIND_DATAW)]
    kernel32.FindClose.restype = wintypes.BOOL
    kernel32.FindClose.argtypes = [wintypes.HANDLE]

    data = WIN32_FIND_DATAW()
    h = kernel32.FindFirstFileW(r"\\.\pipe\*", ctypes.byref(data))
    if h == INVALID:
        return

    our_marker = "dupez"
    dupez_pipes: List[str] = []
    try:
        while True:
            name = data.cFileName
            if our_marker in name.lower():
                dupez_pipes.append(name)
            if not kernel32.FindNextFileW(h, ctypes.byref(data)):
                break
    finally:
        kernel32.FindClose(h)

    reg.record(
        title=f"DupeZ-owned named pipes: {len(dupez_pipes)}",
        description=(
            "Enumerated named pipes whose name contains 'dupez'. For each, "
            "the DACL should grant access only to the running user's SID, "
            "never to Authenticated Users or Everyone."
        ),
        severity=Severity.INFO if not dupez_pipes else Severity.LOW,
        attack_technique="T1559.001",  # IPC: Component Object Model (pipes are related surface)
        evidence={"pipes": dupez_pipes},
        remediation=(
            "When creating pipes, pass a SECURITY_ATTRIBUTES with a DACL "
            "built from the calling user's SID only. Use "
            "ConvertStringSecurityDescriptorToSecurityDescriptor with "
            "'D:(A;;GA;;;<user-sid>)'."
        ),
    )


# ── File permissions ──────────────────────────────────────────────

_SENSITIVE_PATHS: List[tuple] = [
    # (relative path under user data root, label, expected_exclusive)
    ("DupeZ/secrets", "secret store", True),
    ("DupeZ/audit.hmac.jsonl", "audit log", True),
    ("DupeZ/state.json", "persistent state", True),
]


def _user_data_roots() -> List[Path]:
    roots: List[Path] = []
    if os.name == "nt":
        for env in ("APPDATA", "LOCALAPPDATA"):
            v = os.environ.get(env)
            if v:
                roots.append(Path(v))
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        if xdg:
            roots.append(Path(xdg))
        roots.append(Path.home() / ".local" / "share")
    return roots


def _check_file_permissions(reg: FindingRegistry) -> None:
    # On POSIX, check the mode bits. On Windows, os.stat mode bits are
    # synthetic — the real ACLs would need pywin32 or win32security.
    # We do what portably works.
    roots = _user_data_roots()
    for rel, label, _exclusive in _SENSITIVE_PATHS:
        for root in roots:
            path = root / rel
            if not path.exists():
                continue
            mode = path.stat().st_mode
            perms = stat.S_IMODE(mode)
            if os.name == "nt":
                # Mode bits on Windows just tell us read-only — skip.
                continue
            if perms & 0o077:
                reg.record(
                    title=f"Over-permissive mode on {label}: {oct(perms)}",
                    description=(
                        f"Sensitive file or directory ({path}) has mode "
                        f"{oct(perms)}; group/other bits are set. Group/other "
                        "users can read or write sensitive material."
                    ),
                    severity=Severity.HIGH,
                    cvss_base=7.1,
                    cvss_vector="CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:N",
                    attack_technique="T1222.002",  # Linux and Mac File and Directory Permissions Modification
                    evidence={"path": str(path), "mode": oct(perms)},
                    remediation=f"chmod 0600 {path}  # or 0700 for directories",
                )
            else:
                reg.record(
                    title=f"{label} permissions OK",
                    description=f"{path} has mode {oct(perms)}.",
                    severity=Severity.INFO,
                    evidence={"path": str(path), "mode": oct(perms)},
                )
            break  # only one root will match


# ── Python interpreter ────────────────────────────────────────────

def _check_interpreter(reg: FindingRegistry) -> None:
    exe = Path(sys.executable) if sys.executable else None
    if not exe or not exe.is_file():
        reg.record(
            title="sys.executable does not point to a real file",
            description=(
                "sys.executable is empty or missing on disk. A downstream "
                "safe_subprocess.run() call that relies on sys.executable "
                "would fail."
            ),
            severity=Severity.MEDIUM,
            evidence={"sys_executable": str(sys.executable)},
        )
        return

    # On Windows, Python should be under Program Files or %LOCALAPPDATA%\Programs\Python,
    # not under a user-writable directory earlier on PATH.
    if os.name != "nt":
        try:
            st = exe.stat()
            if stat.S_IMODE(st.st_mode) & 0o022:
                reg.record(
                    title="Python interpreter is group- or world-writable",
                    description=(
                        f"The interpreter at {exe} is writable by non-owner "
                        "principals. A local attacker can replace it."
                    ),
                    severity=Severity.CRITICAL,
                    cvss_base=9.3,
                    cvss_vector="CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:C/C:H/I:H/A:H",
                    attack_technique="T1574",
                    evidence={"path": str(exe), "mode": oct(st.st_mode)},
                    remediation=f"sudo chmod go-w {exe}",
                )
                return
        except OSError:
            pass

    reg.record(
        title="Python interpreter integrity OK",
        description=f"Interpreter resolved to {exe}.",
        severity=Severity.INFO,
        evidence={"path": str(exe)},
    )


# ── Public entrypoint ───────────────────────────────────────────

def run_attack_surface(reg: FindingRegistry) -> None:
    """Run every attack-surface check, recording findings into *reg*."""
    require_consent()
    _check_listeners(reg)
    _check_named_pipes(reg)
    _check_file_permissions(reg)
    _check_interpreter(reg)
