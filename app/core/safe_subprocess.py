"""
Safe-by-default subprocess wrapper for DupeZ.

All child-process creation in the codebase SHOULD route through
:func:`run` (one-shot), :func:`spawn_managed` (long-running with a
bounded process handle), or :func:`spawn_detached` (fire-and-forget) instead of
calling :mod:`subprocess` directly. The wrapper enforces a small set
of invariants that, in aggregate, eliminate the most common
command-injection and PATH-hijack bug classes:

    1. ``shell=False`` — always. ``shell=True`` is the single largest
       source of command-injection bugs in Python codebases and has
       zero legitimate use inside DupeZ.
    2. ``args`` must be a list/tuple of strings. Passing a single
       pre-joined string is refused — argument quoting is the OS's
       job, not ours.
    3. The first argv element MUST be an absolute path to a file that
       exists on disk. This kills relative-path PATH hijack (a
       ``netsh`` file in the CWD would otherwise win over the real
       Windows binary).
    4. On Windows, processes are created with ``CREATE_NO_WINDOW``
       (no console flash for each invocation) and without inheriting
       the parent's stdin.
    5. :func:`run` requires a ``timeout`` — no unbounded waits; the
       default is 15 seconds but callers can pass up to 600.
    6. Every invocation emits a ``subprocess_spawn`` audit event with
       the argv, resolved path, and caller intent. Successful and
       failed exits both record a follow-up ``subprocess_exit`` event
       (with return code, stderr snippet, duration).
    7. An optional ``expect_returncode`` set lets call sites assert
       the exit code is in a known-good set; anything else raises
       :class:`SafeSubprocessError`.

Explicit overrides (use sparingly)
----------------------------------
Some narrowly-scoped call sites may pass ``trusted_executable=True`` to
skip a redundant file-existence check after validating a held executable.
The absolute-path requirement is never bypassable.

This module never returns a raw ``subprocess.Popen`` instance to
callers; that would let a caller bypass the exit-auditing. The return
types are plain dataclasses or small audited wrappers.
"""

from __future__ import annotations

import ctypes
import ntpath
import os
import shlex
import stat
import subprocess
import sys
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Set

__all__ = [
    "SafeSubprocessError",
    "ManagedProcess",
    "SubprocessResult",
    "run",
    "spawn_managed",
    "spawn_detached",
]


class SafeSubprocessError(RuntimeError):
    """Raised on any policy violation or non-OK exit code."""


@dataclass(frozen=True)
class SubprocessResult:
    """Result of :func:`run`. Never a live :class:`subprocess.Popen`."""

    argv: tuple
    returncode: int
    stdout: str
    stderr: str
    duration_s: float
    timed_out: bool


class ManagedProcess:
    """Audited wrapper for a long-running child process.

    Exposes only the process operations DupeZ needs for GUI/native
    helper lifecycles. Callers can poll and kill the process, but they
    cannot mutate stdio, replace handles, or bypass the spawn policy.
    """

    def __init__(self, proc: subprocess.Popen, *, intent: str, started_at: float) -> None:
        self._proc = proc
        self._intent = intent or "unspecified"
        self._started_at = started_at
        self._exit_audited = False

    @property
    def pid(self) -> int:
        return int(self._proc.pid)

    @property
    def returncode(self) -> Optional[int]:
        return self._proc.returncode

    def poll(self) -> Optional[int]:
        rc = self._proc.poll()
        if rc is not None:
            self._audit_exit(rc, killed=False)
        return rc

    def wait(self, timeout_s: float) -> bool:
        """Wait at most ``timeout_s`` for exit and audit a completed child."""
        if timeout_s < 0:
            raise ValueError("timeout_s must be non-negative")
        try:
            rc = self._proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            return False
        self._audit_exit(rc, killed=False)
        return True

    def kill(self) -> None:
        try:
            self._proc.kill()
        finally:
            self._audit_exit(self._proc.returncode, killed=True)

    def _audit_exit(self, rc: Optional[int], *, killed: bool) -> None:
        if self._exit_audited:
            return
        self._exit_audited = True
        _audit("subprocess_exit", {
            "intent": self._intent,
            "returncode": rc,
            "duration_s": round(time.monotonic() - self._started_at, 3),
            "timed_out": False,
            "killed": bool(killed),
        })


# ── Policy helpers ───────────────────────────────────────────────

def _validate_argv(argv: Sequence[str], *, trusted_executable: bool) -> List[str]:
    """Validate and normalise an argv list."""
    if isinstance(argv, (str, bytes)):
        raise SafeSubprocessError(
            "argv must be a list/tuple of strings, not a pre-joined string "
            "(that would enable shell-style quoting bugs)"
        )
    if not argv:
        raise SafeSubprocessError("argv is empty")
    out: List[str] = []
    for i, a in enumerate(argv):
        if not isinstance(a, str):
            raise SafeSubprocessError(
                f"argv[{i}] must be str, got {type(a).__name__}"
            )
        if "\x00" in a:
            raise SafeSubprocessError(
                f"argv[{i}] contains NUL byte — refusing"
            )
        out.append(a)

    exe = out[0]
    # ``trusted_executable`` may skip a redundant existence check for a
    # caller-held or otherwise prevalidated file, but it must never re-enable
    # PATH/CWD resolution.  A relative executable at a privilege boundary is
    # unsafe regardless of who supplied it.
    if not os.path.isabs(exe):
        raise SafeSubprocessError(
            f"executable must be an absolute path, got {exe!r}. "
            "Resolve and validate it before spawning."
        )
    if not trusted_executable:
        if not os.path.isfile(exe):
            raise SafeSubprocessError(f"executable does not exist: {exe}")
    return out


def _windows_creation_flags() -> int:
    """Return Windows CreateProcess flags for a silent, uninherited spawn."""
    if os.name != "nt":
        return 0
    CREATE_NO_WINDOW = 0x08000000
    # DETACHED_PROCESS intentionally NOT set for `run` — we want stdout/stderr.
    return CREATE_NO_WINDOW


def _windows_startupinfo():
    """Return a hardened STARTUPINFO for Windows spawns.

    v5.7.6: belt-and-suspenders on top of ``CREATE_NO_WINDOW``. Sets:

      * ``STARTF_USESHOWWINDOW`` + ``wShowWindow = SW_HIDE`` so any
        ancillary window the child might try to show (an old netsh
        confirmation dialog, a console subsystem fallback) is hidden
        rather than briefly flashing on the operator's screen.
      * ``STARTF_USESTDHANDLES`` is NOT forced here because callers
        configure stdio via the subprocess kwargs (DEVNULL / PIPE)
        and setting that flag without supplying matching handles is
        invalid. We just hide the window.

    Returns ``None`` on non-Windows so callers can pass ``startupinfo``
    unconditionally.
    """
    if os.name != "nt":
        return None
    try:
        si = subprocess.STARTUPINFO()
    except AttributeError:
        # Non-Windows Python builds don't expose STARTUPINFO.
        return None
    # Constants — Python's subprocess module exposes these on Windows
    # only, so guard the attribute access.
    STARTF_USESHOWWINDOW = getattr(subprocess, "STARTF_USESHOWWINDOW", 1)
    SW_HIDE = getattr(subprocess, "SW_HIDE", 0)
    si.dwFlags |= STARTF_USESHOWWINDOW
    si.wShowWindow = SW_HIDE
    return si


def _audit(event: str, payload: dict) -> None:
    """Best-effort audit — a subprocess call must NOT fail because the
    audit logger failed."""
    try:
        from app.logs.audit import audit_event
        audit_event(event, payload)
    except Exception:
        pass


def _argv_preview(argv: Sequence[str], limit: int = 8) -> list:
    """Return a bounded, shell-safe preview of argv for logs."""
    out = [shlex.quote(str(a)) for a in argv[:limit]]
    if len(argv) > limit:
        out.append(f"...({len(argv) - limit} more)")
    return out


# ── Public entrypoints ───────────────────────────────────────────

def run(
    argv: Sequence[str],
    *,
    timeout: float = 15.0,
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
    input_text: Optional[str] = None,
    capture_output: bool = True,
    text: bool = True,
    expect_returncode: Optional[Iterable[int]] = (0,),
    trusted_executable: bool = False,
    intent: str = "",
) -> SubprocessResult:
    """Run *argv* to completion with strict invariants.

    Args:
        argv: list/tuple of strings; argv[0] must be an absolute path.
        timeout: wall-clock seconds before SIGKILL (max 600).
        cwd: optional working directory.
        env: optional environment dict. If ``None`` we inherit from
            the parent.
        input_text: text to pipe to stdin.
        capture_output: if True, captures stdout/stderr.
        text: if True, decodes output as UTF-8.
        expect_returncode: iterable of allowed exit codes. Set to
            ``None`` to accept any code without raising.
        trusted_executable: skip only the file-exists check when the
            caller has already verified the absolute executable.
        intent: short free-form label included in the audit event so
            post-hoc analysis can map spawns back to the feature that
            triggered them (e.g. ``"netsh_firewall_rule_add"``).

    Raises:
        SafeSubprocessError: argv invalid, process timed out, or exit
            code not in ``expect_returncode``.
    """
    if timeout <= 0 or timeout > 600:
        raise SafeSubprocessError(f"timeout out of bounds: {timeout}")

    clean_argv = _validate_argv(argv, trusted_executable=trusted_executable)
    creationflags = _windows_creation_flags()
    startupinfo = _windows_startupinfo()

    _audit("subprocess_spawn", {
        "intent": intent or "unspecified",
        "argv_preview": _argv_preview(clean_argv),
        "trusted_executable": trusted_executable,
        "timeout": timeout,
    })

    t0 = time.monotonic()
    timed_out = False
    try:
        completed = subprocess.run(
            clean_argv,
            shell=False,                      # hard rule (1)
            cwd=cwd,
            env=env,
            input=input_text,
            capture_output=capture_output,
            text=text,
            timeout=timeout,
            check=False,
            creationflags=creationflags,
            startupinfo=startupinfo,          # v5.7.6: SW_HIDE belt
            close_fds=True,                   # v5.7.6: don't leak parent handles
        )
        stdout = completed.stdout or "" if capture_output else ""
        stderr = completed.stderr or "" if capture_output else ""
        rc = completed.returncode
    except subprocess.TimeoutExpired as e:
        timed_out = True
        rc = -1
        stdout = (e.stdout or "") if isinstance(e.stdout, str) else (
            e.stdout.decode("utf-8", "replace") if e.stdout else ""
        )
        stderr = (e.stderr or "") if isinstance(e.stderr, str) else (
            e.stderr.decode("utf-8", "replace") if e.stderr else ""
        )
    except OSError as e:
        raise SafeSubprocessError(
            f"subprocess spawn failed ({clean_argv[0]!r}): {e}"
        ) from e

    duration = time.monotonic() - t0
    _audit("subprocess_exit", {
        "intent": intent or "unspecified",
        "returncode": rc,
        "duration_s": round(duration, 3),
        "timed_out": timed_out,
        "stderr_head": (stderr[:200] if isinstance(stderr, str) else ""),
    })

    if timed_out:
        raise SafeSubprocessError(
            f"subprocess timed out after {timeout}s: "
            f"{_argv_preview(clean_argv)}"
        )
    if expect_returncode is not None:
        allowed: Set[int] = set(expect_returncode)
        if rc not in allowed:
            raise SafeSubprocessError(
                f"subprocess exited with unexpected rc={rc} "
                f"(allowed={sorted(allowed)}): "
                f"{_argv_preview(clean_argv)} — stderr head: "
                f"{stderr[:200] if isinstance(stderr, str) else ''!r}"
            )
    return SubprocessResult(
        argv=tuple(clean_argv),
        returncode=rc,
        stdout=stdout if isinstance(stdout, str) else "",
        stderr=stderr if isinstance(stderr, str) else "",
        duration_s=duration,
        timed_out=timed_out,
    )


def spawn_detached(
    argv: Sequence[str],
    *,
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
    trusted_executable: bool = False,
    intent: str = "",
) -> int:
    """Spawn a long-running child without waiting. Returns the PID.

    Used for the installer relaunch path and other fire-and-forget
    launches. Still enforces argv validation and audit-logging, just
    doesn't capture output or wait for exit.
    """
    clean_argv = _validate_argv(argv, trusted_executable=trusted_executable)
    flags = _windows_creation_flags()
    startupinfo = _windows_startupinfo()
    if os.name == "nt":
        # DETACHED_PROCESS + CREATE_NEW_PROCESS_GROUP so the child
        # survives our exit and doesn't receive our Ctrl-C.
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        flags |= DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

    _audit("subprocess_spawn_detached", {
        "intent": intent or "unspecified",
        "argv_preview": _argv_preview(clean_argv),
    })

    try:
        # v5.7.6: ``close_fds=True`` now also on Windows. Python 3.7+
        # supports close_fds on Windows whenever stdin/stdout/stderr
        # are explicitly redirected — which we do (DEVNULL × 3). Pre-
        # v5.7.6 we explicitly opted out on Windows because of a stale
        # Python 3.6 caveat; that's no longer a concern and the opt-
        # out was leaking parent handles into detached children.
        proc = subprocess.Popen(
            clean_argv,
            shell=False,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=flags,
            startupinfo=startupinfo,
        )
        return proc.pid
    except OSError as e:
        raise SafeSubprocessError(
            f"detached spawn failed ({clean_argv[0]!r}): {e}"
        ) from e


# ── Convenience: Windows-system-binary resolver ────────────────────

def spawn_managed(
    argv: Sequence[str],
    *,
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
    trusted_executable: bool = False,
    intent: str = "",
) -> ManagedProcess:
    """Spawn a long-running child and return an audited process handle."""
    clean_argv = _validate_argv(argv, trusted_executable=trusted_executable)
    flags = _windows_creation_flags()
    startupinfo = _windows_startupinfo()
    clean_intent = intent or "unspecified"

    _audit("subprocess_spawn_managed", {
        "intent": clean_intent,
        "argv_preview": _argv_preview(clean_argv),
        "trusted_executable": trusted_executable,
    })

    started_at = time.monotonic()
    try:
        proc = subprocess.Popen(
            clean_argv,
            shell=False,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=flags,
            startupinfo=startupinfo,
        )
        return ManagedProcess(proc, intent=clean_intent, started_at=started_at)
    except OSError as e:
        raise SafeSubprocessError(
            f"managed spawn failed ({clean_argv[0]!r}): {e}"
        ) from e


def _windows_system_directory(*, kernel32=None) -> str:
    """Resolve System32 from the OS, never from an inherited environment."""
    if kernel32 is None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    getter = kernel32.GetSystemDirectoryW
    try:
        getter.argtypes = [wintypes.LPWSTR, wintypes.UINT]
        getter.restype = wintypes.UINT
    except (AttributeError, TypeError):
        pass
    buffer = ctypes.create_unicode_buffer(32768)
    length = int(getter(buffer, len(buffer)))
    if length <= 0 or length >= len(buffer) or not buffer.value:
        raise SafeSubprocessError("Windows system directory is unavailable")
    resolved = os.path.abspath(buffer.value)
    if not os.path.isabs(resolved):
        raise SafeSubprocessError("Windows system directory is not absolute")
    return resolved


def resolve_system_binary(
    name: str,
    *,
    subdirectory: Sequence[str] = (),
) -> str:
    """Resolve a Windows system binary to its absolute System32 path.

    Prevents PATH-hijack for the common case where DupeZ calls
    ``netsh``, ``arp``, ``ipconfig``, etc. — those must always come
    from the System32 directory reported by Windows itself, never from an
    inherited environment variable or whatever happens to be first on PATH.

    On POSIX this searches only fixed, root-controlled system directories.

    Raises :class:`SafeSubprocessError` if the binary cannot be
    located.
    """
    if (
        not isinstance(name, str)
        or not name
        or "\x00" in name
        or ntpath.basename(name) != name
        or name in {".", ".."}
    ):
        raise SafeSubprocessError(f"unsafe system binary name: {name!r}")
    clean_subdirectory: list[str] = []
    for component in subdirectory:
        if (
            not isinstance(component, str)
            or not component
            or "\x00" in component
            or ntpath.basename(component) != component
            or component in {".", ".."}
        ):
            raise SafeSubprocessError(
                f"unsafe system subdirectory component: {component!r}"
            )
        clean_subdirectory.append(component)
    if os.name == "nt":
        system_directory = _windows_system_directory()
        candidate = os.path.join(system_directory, *clean_subdirectory, name)
        parent = os.path.abspath(os.path.dirname(candidate))
        expected_parent = os.path.abspath(
            os.path.join(system_directory, *clean_subdirectory)
        )
        if os.path.normcase(parent) != os.path.normcase(expected_parent):
            raise SafeSubprocessError("system binary path escaped System32")
        if not candidate.lower().endswith(".exe"):
            candidate += ".exe"
        if os.path.isfile(candidate):
            return candidate
        raise SafeSubprocessError(
            f"Windows system binary not found: {candidate}"
        )
    if clean_subdirectory:
        raise SafeSubprocessError(
            "system subdirectories are only supported on Windows"
        )
    return resolve_posix_system_binary(name)


_POSIX_SYSTEM_DIRS = ("/usr/bin", "/usr/sbin", "/bin", "/sbin")


def resolve_posix_system_binary(name: str) -> str:
    """Resolve *name* without consulting caller-controlled ``PATH``.

    Privileged Linux helpers must not inherit executable selection from the
    environment.  Candidates are accepted only from conventional system
    directories and must resolve to a root-owned regular executable that is
    not writable by group or other users.
    """
    if (
        not isinstance(name, str)
        or not name
        or "\x00" in name
        or ntpath.basename(name) != name
        or name in {".", ".."}
    ):
        raise SafeSubprocessError(f"unsafe system binary name: {name!r}")

    trusted_roots = tuple(
        os.path.realpath(root) for root in _POSIX_SYSTEM_DIRS
    )
    for root, trusted_root in zip(_POSIX_SYSTEM_DIRS, trusted_roots):
        candidate = os.path.join(root, name)
        if not os.path.isfile(candidate) or not os.access(candidate, os.X_OK):
            continue
        resolved = os.path.realpath(candidate)
        try:
            contained = any(
                os.path.commonpath((resolved, trusted)) == trusted
                for trusted in trusted_roots
            )
            metadata = os.stat(resolved)
        except (OSError, ValueError):
            continue
        if not contained or not stat.S_ISREG(metadata.st_mode):
            continue
        if metadata.st_uid != 0:
            continue
        if metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            continue
        return resolved
    raise SafeSubprocessError(
        f"trusted POSIX system binary not found: {name}"
    )


if sys.platform == "win32":  # pragma: no cover — Windows-only
    # Pre-resolve the common offenders once at import time so downstream
    # callers can grab them without re-walking System32 on every invocation.
    # PING is System32\PING.EXE — used by the local forwarding layer to populate
    # the local ARP cache before querying it.
    try:
        NETSH = resolve_system_binary("netsh")
        ARP = resolve_system_binary("arp")
        IPCONFIG = resolve_system_binary("ipconfig")
        ROUTE = resolve_system_binary("route")
        PING = resolve_system_binary("PING")
    except SafeSubprocessError:
        # Unusual install — let callers resolve on demand.
        NETSH = ARP = IPCONFIG = ROUTE = PING = ""
else:
    NETSH = ARP = IPCONFIG = ROUTE = PING = ""
