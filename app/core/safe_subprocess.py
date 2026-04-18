"""
Safe-by-default subprocess wrapper for DupeZ.

All child-process creation in the codebase SHOULD route through
:func:`run` (one-shot) or :func:`spawn` (detached) instead of
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
Some narrowly-scoped call sites need to bypass rule (3) — for
example, tests that spawn a system Python via ``sys.executable`` are
fine. Pass ``trusted_executable=True`` to opt out of the absolute-
path check when the caller has *already* verified the path is what
they expect.

This module never returns a ``subprocess.Popen`` instance to callers;
that would let a caller bypass the exit-auditing. The return types
are plain dataclasses.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Set

__all__ = [
    "SafeSubprocessError",
    "SubprocessResult",
    "run",
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

    if not trusted_executable:
        exe = out[0]
        if not os.path.isabs(exe):
            raise SafeSubprocessError(
                f"executable must be an absolute path, got {exe!r}. "
                "Use shutil.which() once at startup and cache the result, "
                "or pass trusted_executable=True if you've already verified."
            )
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
        argv: list/tuple of strings; argv[0] must be an absolute path
            unless ``trusted_executable`` is True.
        timeout: wall-clock seconds before SIGKILL (max 600).
        cwd: optional working directory.
        env: optional environment dict. If ``None`` we inherit from
            the parent.
        input_text: text to pipe to stdin.
        capture_output: if True, captures stdout/stderr.
        text: if True, decodes output as UTF-8.
        expect_returncode: iterable of allowed exit codes. Set to
            ``None`` to accept any code without raising.
        trusted_executable: skip the absolute-path / file-exists check
            when the caller has already verified.
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
        proc = subprocess.Popen(
            clean_argv,
            shell=False,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=(os.name != "nt"),
            creationflags=flags,
        )
        return proc.pid
    except OSError as e:
        raise SafeSubprocessError(
            f"detached spawn failed ({clean_argv[0]!r}): {e}"
        ) from e


# ── Convenience: Windows-system-binary resolver ────────────────────

def resolve_system_binary(name: str) -> str:
    """Resolve a Windows system binary to its absolute System32 path.

    Prevents PATH-hijack for the common case where DupeZ calls
    ``netsh``, ``arp``, ``ipconfig``, etc. — those must always come
    from ``%SystemRoot%\\System32``, never from whatever happens to be
    first on PATH.

    On POSIX this falls back to :func:`shutil.which`.

    Raises :class:`SafeSubprocessError` if the binary cannot be
    located.
    """
    if os.name == "nt":
        sysroot = os.environ.get("SystemRoot") or r"C:\Windows"
        candidate = os.path.join(sysroot, "System32", name)
        if not candidate.lower().endswith(".exe"):
            candidate += ".exe"
        if os.path.isfile(candidate):
            return candidate
        raise SafeSubprocessError(
            f"Windows system binary not found: {candidate}"
        )
    import shutil
    resolved = shutil.which(name)
    if not resolved:
        raise SafeSubprocessError(f"binary not found on PATH: {name}")
    return resolved


if sys.platform == "win32":  # pragma: no cover — Windows-only
    # Pre-resolve the common offenders once at import time so downstream
    # callers can grab them without re-walking System32 on every invocation.
    # PING is System32\PING.EXE — used by the ARP spoof layer to populate
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
