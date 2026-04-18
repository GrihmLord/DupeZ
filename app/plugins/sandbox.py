"""
Capability-enforcing sandbox for DupeZ plugins.

Design
------
Every loaded plugin declares a capability set in its signed manifest
(see :mod:`app.plugins.signing`). At activation time, the loader pushes
the plugin's capability set onto a thread-local stack and installs a
process-wide :func:`sys.addaudithook` mediator. The mediator inspects
every audit event raised by the CPython runtime (``socket.connect``,
``subprocess.Popen``, ``os.system``, ``open`` with write flags, …) and
consults the top of the active-plugin stack to decide whether the
event is permitted.

Sandbox mode is **best-effort deterrence**, not a hardened security
boundary: a plugin that imports ``ctypes`` can call into kernel32
directly and bypass everything. The goal is to:

    1. Catch accidental-looking capability escalation (a "scanner"
       plugin that suddenly opens a raw socket).
    2. Force malicious plugins to be *obviously* malicious (they must
       reach for ctypes, which is itself auditable).
    3. Give the user a readable reason when a plugin is rejected.

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
    with plugin_scope(manifest):
        instance.activate(controller)
"""

from __future__ import annotations

import contextlib
import re
import sys
import threading
from dataclasses import dataclass, field
from typing import Iterable, Optional

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
class _PluginContext:
    name: str
    capabilities: frozenset


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
        _, mode, _ = args
    except Exception:
        return False
    if isinstance(mode, str):
        return any(c in mode for c in "waxWAX+")
    return False


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
        pattern=re.compile(r"^os\.(remove|unlink|rename|rmdir|chmod|chown)$"),
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
def plugin_scope(name: str, capabilities: Iterable[str]):
    """Push a plugin capability scope for the current thread."""
    ctx = _PluginContext(name=name, capabilities=frozenset(capabilities))
    s = _stack()
    s.append(ctx)
    try:
        yield ctx
    finally:
        try:
            s.pop()
        except IndexError:  # pragma: no cover — defensive
            pass
