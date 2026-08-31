"""
Best-effort capability diagnostics for fully trusted DupeZ plugins.

Design
------
Every loaded plugin declares a capability set in its signed manifest
(see :mod:`app.plugins.signing`). During import and every lifecycle callback,
the loader pushes the plugin's capability set onto a thread-local stack and installs a
process-wide :func:`sys.addaudithook` mediator. The mediator inspects
every audit event raised by the CPython runtime (``socket.connect``,
``subprocess.Popen``, ``os.system``, ``open`` with write flags, …) and
consults the top of the active-plugin stack to decide whether the
event is permitted.

The signing key is the trust boundary. A verified plugin runs arbitrary
in-process Python with the host user's authority; its publisher must therefore
be trusted like an application-code contributor. This module is **best-effort
deterrence and diagnostics**, not a security boundary. Python reflection,
native code, or a child thread can evade a thread-local audit scope. The goal
is to:

    1. Catch accidental-looking capability escalation (a "scanner"
       plugin that suddenly opens a raw socket).
    2. Force malicious plugins to be *obviously* malicious (they must
       reach for ctypes, which is itself auditable).
    3. Give the user a readable reason when a plugin is rejected.

Do not describe manifest capabilities as OS isolation or use them to justify
trusting an otherwise untrusted publisher. A future brokered out-of-process
host is required before capabilities can become an enforceable boundary.

Thread locality
---------------
Python audit hooks fire on ALL threads. A plugin that spawns a thread
and does I/O there will do so outside any "active plugin" scope —
there is no Python-level way to attach our thread-local cleanly to a
child thread without monkey-patching ``threading.Thread``. We opt
against that monkey-patch because it's fragile; spawned-thread I/O
is effectively unsandboxed. This is an acceptable tradeoff: the
signed-manifest requirement still gates the code that *runs*, and
any plugin that wants to evade the sandbox is already outside the
"benign plugin" class.

Usage
-----

::

    from app.plugins.sandbox import (
        activate_sandbox, plugin_scope, SandboxViolation
    )

    activate_sandbox()                # once, at loader init
    with plugin_scope(manifest.name, manifest.capabilities):
        instance.activate(controller)
"""

from __future__ import annotations

import contextlib
import hashlib
import marshal
import os
import re
import sys
import threading
from dataclasses import dataclass
from types import CodeType, MappingProxyType
from typing import Iterable, Mapping, Optional

__all__ = [
    "SandboxViolation",
    "activate_sandbox",
    "plugin_scope",
    "current_plugin_name",
    "snapshot_violations",
]


# ── State ─────────────────────────────────────────────────────────

class SandboxViolation(RuntimeError):
    """Raised when a plugin attempts an operation outside its capabilities."""


@dataclass(frozen=True)
class _AuthorizedCodeRecord:
    source_sha384: bytes
    code_sha384: bytes


@dataclass(frozen=True)
class _VerifiedCodeAuthorization:
    records: Mapping[str, _AuthorizedCodeRecord]


@dataclass(frozen=True)
class _PluginContext:
    name: str
    capabilities: frozenset
    verified_code: Optional[_VerifiedCodeAuthorization] = None


_thread_local = threading.local()

_installed = False
_install_lock = threading.Lock()

# Module-level violation log — used by the loader for diagnostics.
_violations_lock = threading.Lock()
_violations: list[dict] = []


def _stack() -> list:
    s = getattr(_thread_local, "stack", None)
    if s is None:
        s = []
        _thread_local.stack = s
    return s


def current_plugin_name() -> Optional[str]:
    """Return the name of the plugin owning the current thread's top scope."""
    s = _stack()
    return s[-1].name if s else None


def snapshot_violations() -> list[dict]:
    """Return a copy of all recorded sandbox violations since process start."""
    with _violations_lock:
        return list(_violations)


def _canonical_code_path(raw_path: object) -> str:
    """Return a comparison-safe absolute path, or an empty value on failure."""
    try:
        path = os.fsdecode(raw_path)
    except (TypeError, ValueError):
        return ""
    if not path or (path.startswith("<") and path.endswith(">")):
        return ""
    try:
        return os.path.normcase(os.path.realpath(os.path.abspath(path)))
    except (OSError, ValueError):
        return ""


def _code_digest(code: CodeType) -> bytes:
    """Fingerprint the complete compiled code graph for exact exec approval."""
    return hashlib.sha384(marshal.dumps(code)).digest()


def _prepare_verified_code_authorization(
    sources: Mapping[str, tuple[bytes, str]],
) -> _VerifiedCodeAuthorization:
    """Compile only manifest-hash-matched sources into an immutable allowlist.

    This runs before a plugin scope is pushed. The audit hook can therefore
    permit CPython's import-time ``compile``/``exec`` events only when their
    source bytes, canonical filename, and resulting code object all match an
    already verified file from the signed plugin manifest.
    """
    if not sources:
        raise ValueError("verified plugin source set cannot be empty")

    records: dict[str, _AuthorizedCodeRecord] = {}
    for raw_path, source_record in sources.items():
        if (
            not isinstance(source_record, tuple)
            or len(source_record) != 2
            or not isinstance(source_record[0], bytes)
            or not isinstance(source_record[1], str)
        ):
            raise TypeError(
                "verified plugin sources must map paths to (bytes, sha384)"
            )
        source, expected_sha384 = source_record
        actual_sha384 = hashlib.sha384(source).hexdigest()
        if actual_sha384 != expected_sha384:
            raise ValueError("verified plugin source does not match manifest hash")

        filename = os.path.realpath(os.path.abspath(os.fsdecode(raw_path)))
        canonical_path = _canonical_code_path(filename)
        if not canonical_path or canonical_path in records:
            raise ValueError("verified plugin source path is invalid or duplicated")

        code = compile(
            source,
            filename,
            "exec",
            dont_inherit=True,
            optimize=-1,
        )
        records[canonical_path] = _AuthorizedCodeRecord(
            source_sha384=hashlib.sha384(source).digest(),
            code_sha384=_code_digest(code),
        )

    return _VerifiedCodeAuthorization(MappingProxyType(records))


def _authorized_compile(ctx: _PluginContext, args: tuple) -> bool:
    authorization = ctx.verified_code
    if authorization is None or len(args) < 2:
        return False
    source, filename = args[:2]
    if not isinstance(source, bytes):
        return False
    record = authorization.records.get(_canonical_code_path(filename))
    return record is not None and hashlib.sha384(source).digest() == record.source_sha384


def _authorized_exec(ctx: _PluginContext, args: tuple) -> bool:
    authorization = ctx.verified_code
    if authorization is None or not args or not isinstance(args[0], CodeType):
        return False
    code = args[0]
    record = authorization.records.get(_canonical_code_path(code.co_filename))
    return record is not None and _code_digest(code) == record.code_sha384


# ── Event policy ──────────────────────────────────────────────────
#
# Map sys.audit event prefixes to the capability required.
# This list is intentionally conservative — anything not explicitly
# matched here is allowed to pass (the sandbox doesn't exhaustively
# whitelist stdlib behavior). New entries tighten the screws over time.

@dataclass
class _EventRule:
    # Regex on the event name; ``None`` means the arg-based check runs
    # unconditionally (used only for "open").
    pattern: re.Pattern
    # Capability required. If ``None`` the rule always denies when
    # ``condition`` returns True — used for sinks with no legitimate
    # plugin use case (e.g. ``exec`` of compiled bytecode streams).
    capability: Optional[str]
    # Extra per-args predicate; if provided and returns False, the rule
    # doesn't apply to this specific event instance.
    condition: Optional[callable] = None
    # Human-readable reason surfaced in violations.
    reason: str = ""


def _condition_open_write(args: tuple) -> bool:
    """True if the ``open`` audit event looks like a writable open.

    Audit tuple is ``(path, mode, flags)``. Mode is a Python-level
    string like ``"rb"`` / ``"w"``; flags is the OS integer. We treat
    any mode containing ``w``, ``a``, ``x``, ``+`` as writable.
    """
    try:
        _, mode, flags = args
    except Exception:
        # An unrecognised ``open`` event is safer to treat as a mutation while
        # a plugin scope is active.  Read-only CPython events use either a
        # string mode without write characters or integer flags equal to
        # ``O_RDONLY`` (zero on supported platforms).
        return True
    if isinstance(mode, str):
        return any(c in mode for c in "waxWAX+")
    if isinstance(flags, int):
        write_flags = 0
        for flag_name in (
            "O_WRONLY",
            "O_RDWR",
            "O_APPEND",
            "O_CREAT",
            "O_TRUNC",
            "O_EXCL",
            "O_TMPFILE",
        ):
            write_flags |= int(getattr(os, flag_name, 0))
        return bool(flags & write_flags)
    return True


def _condition_unsafe_import(args: tuple) -> bool:
    try:
        module_name = str(args[0])
    except Exception:
        return True
    return module_name == "ctypes" or module_name.startswith("ctypes.")


_RULES: list[_EventRule] = [
    # Raw sockets / WinDivert-level opens.
    _EventRule(
        pattern=re.compile(r"^socket\.(connect|bind|sendto|recvfrom)$"),
        capability="network.scan",
        reason="raw/UDP/TCP socket I/O",
    ),
    # urllib / http.client both raise http.client.send / urllib.Request.
    _EventRule(
        pattern=re.compile(r"^(http\.client|urllib\.Request|ssl\.wrap_socket)"),
        capability="network.http",
        reason="HTTP(S) request",
    ),
    # Process spawn paths.
    _EventRule(
        pattern=re.compile(
            r"^(subprocess\.Popen|os\.(system|popen|exec|spawn))"
        ),
        capability="process.spawn",
        reason="child process creation",
    ),
    # File opens (write side) — read-only opens are permitted.
    _EventRule(
        pattern=re.compile(r"^open$"),
        capability="fs.write_user_data",
        condition=_condition_open_write,
        reason="file open for write",
    ),
    _EventRule(
        pattern=re.compile(
            r"^os\.(remove|unlink|rename|rmdir|chmod|chown|mkdir|link|"
            r"symlink|truncate|utime)$"
        ),
        capability="fs.write_user_data",
        reason="file-system mutation",
    ),
    # Deny outright — no legitimate plugin needs to eval code we
    # didn't vet. ``exec``/``compile`` of arbitrary buffers is the
    # classic loader-of-a-loader RCE ladder.
    _EventRule(
        pattern=re.compile(r"^(exec|compile)$"),
        capability=None,
        reason="dynamic code execution (exec/compile)",
    ),
    _EventRule(
        pattern=re.compile(r"^import$"),
        capability=None,
        condition=_condition_unsafe_import,
        reason="ctypes import can bypass the in-process capability policy",
    ),
    _EventRule(
        pattern=re.compile(r"^ctypes\."),
        capability=None,
        reason="native memory/library access bypasses plugin policy",
    ),
]


# ── Audit hook ────────────────────────────────────────────────────

def _record_violation(event: str, reason: str, plugin: str) -> None:
    with _violations_lock:
        _violations.append({
            "event": event,
            "reason": reason,
            "plugin": plugin,
        })
        # Cap memory — keep the last 1000 entries.
        if len(_violations) > 1000:
            del _violations[:-1000]


def _audit_hook(event: str, args: tuple) -> None:
    """Global audit hook — dispatches to per-plugin capability check.

    The hook runs on every thread. If there's no plugin scope on the
    current thread's stack, it returns without doing anything; the
    normal DupeZ code runs un-interrupted.
    """
    s = getattr(_thread_local, "stack", None)
    if not s:
        return
    ctx: _PluginContext = s[-1]

    # Import machinery compiles and executes source modules. Permit those two
    # events only for exact code prepared from the signed, freshly reverified
    # plugin file set. Dynamic exec/eval and filename spoofing still fall
    # through to the hard-deny rules below.
    if event == "compile" and _authorized_compile(ctx, args):
        return
    if event == "exec" and _authorized_exec(ctx, args):
        return

    for rule in _RULES:
        if not rule.pattern.match(event):
            continue
        if rule.condition is not None:
            try:
                if not rule.condition(args):
                    continue
            except Exception:
                # Rule condition errored — assume it applies (deny).
                pass
        required = rule.capability
        if required is None:
            # Hard deny.
            _record_violation(event, rule.reason, ctx.name)
            raise SandboxViolation(
                f"plugin {ctx.name!r} attempted disallowed op {event!r} "
                f"({rule.reason})"
            )
        if required not in ctx.capabilities:
            _record_violation(event, rule.reason, ctx.name)
            raise SandboxViolation(
                f"plugin {ctx.name!r} lacks capability {required!r} "
                f"(triggered by {event!r} — {rule.reason})"
            )
        # Capability declared — allow.
        return


def activate_sandbox() -> None:
    """Install the audit hook exactly once per process.

    Audit hooks CANNOT be removed once installed — that is intentional
    on the CPython side. We therefore install exactly once and guard
    with a module-level flag.
    """
    global _installed
    if _installed:
        return
    with _install_lock:
        if _installed:
            return
        sys.addaudithook(_audit_hook)
        _installed = True


# ── Scope helpers ─────────────────────────────────────────────────

@contextlib.contextmanager
def plugin_scope(
    name: str,
    capabilities: Iterable[str],
    *,
    verified_code: Optional[_VerifiedCodeAuthorization] = None,
):
    """Push a plugin capability and exact-code scope for this thread."""
    if verified_code is not None and not isinstance(
        verified_code,
        _VerifiedCodeAuthorization,
    ):
        raise TypeError("verified_code must be prepared by the plugin loader")
    ctx = _PluginContext(
        name=name,
        capabilities=frozenset(capabilities),
        verified_code=verified_code,
    )
    s = _stack()
    s.append(ctx)
    try:
        yield ctx
    finally:
        try:
            s.pop()
        except IndexError:  # pragma: no cover — defensive
            pass
