"""Audited launcher for GUI children that must stay hidden while verified.

``safe_subprocess.spawn_managed`` already applies ``STARTF_USESHOWWINDOW`` with
``SW_HIDE``.  This small compatibility wrapper keeps the dedicated Clumsy audit
event and process-handle contract while using that same hidden-window policy.

Clumsy still creates its IUP dialog and child controls, so DupeZ can discover the
PID-owned top-level window and drive it with synchronous Win32 messages.  The
window is never intentionally exposed during ordinary disruption startup; only
the authenticated diagnostic action may restore it for an operator.
"""

from __future__ import annotations

import subprocess
import time
from typing import Optional, Sequence

from app.core import safe_subprocess as _safe

__all__ = ["spawn_managed_gui"]


def spawn_managed_gui(
    argv: Sequence[str],
    *,
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
    trusted_executable: bool = False,
    intent: str = "",
) -> _safe.ManagedProcess:
    """Spawn one hidden GUI child under the standard DupeZ audit policy."""

    clean_argv = _safe._validate_argv(  # noqa: SLF001 - same security boundary
        argv,
        trusted_executable=trusted_executable,
    )
    flags = _safe._windows_creation_flags()  # noqa: SLF001
    startupinfo = _safe._windows_startupinfo()  # noqa: SLF001
    clean_intent = intent or "hidden_gui.unspecified"

    _safe._audit(  # noqa: SLF001
        "subprocess_spawn_managed_gui",
        {
            "intent": clean_intent,
            "argv_preview": _safe._argv_preview(clean_argv),  # noqa: SLF001
            "trusted_executable": trusted_executable,
            "window_policy": "hidden_during_verification",
        },
    )

    started_at = time.monotonic()
    try:
        process = subprocess.Popen(
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
        return _safe.ManagedProcess(
            process,
            intent=clean_intent,
            started_at=started_at,
        )
    except OSError as exc:
        raise _safe.SafeSubprocessError(
            f"managed hidden GUI spawn failed ({clean_argv[0]!r}): {exc}"
        ) from exc
