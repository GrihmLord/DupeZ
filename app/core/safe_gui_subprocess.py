"""Audited launcher for GUI processes that must be visible for verification.

``safe_subprocess.spawn_managed`` deliberately applies ``STARTF_USESHOWWINDOW``
with ``SW_HIDE`` to every managed child. That is correct for helpers and command
line tools, but it makes cross-process GUI verification impossible: Clumsy's
window is born hidden while the integration searches only visible top-level
windows.

This narrowly scoped launcher retains the existing subprocess security policy:
absolute-path validation, ``shell=False``, no inherited standard handles,
``CREATE_NO_WINDOW`` for console suppression, close-on-exec handles, and audit
records. Its only difference is that it does not pass an SW_HIDE STARTUPINFO,
allowing the GUI to appear briefly until DupeZ verifies and hides it itself.
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
    """Spawn one visible GUI child under the standard DupeZ audit policy."""

    clean_argv = _safe._validate_argv(  # noqa: SLF001 - same security boundary
        argv,
        trusted_executable=trusted_executable,
    )
    flags = _safe._windows_creation_flags()  # noqa: SLF001
    clean_intent = intent or "visible_gui.unspecified"

    _safe._audit(  # noqa: SLF001
        "subprocess_spawn_managed_gui",
        {
            "intent": clean_intent,
            "argv_preview": _safe._argv_preview(clean_argv),  # noqa: SLF001
            "trusted_executable": trusted_executable,
            "window_policy": "visible_until_verified",
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
            # Deliberately no STARTUPINFO/SW_HIDE. The caller must verify and
            # hide its exact owned window after startup succeeds.
            startupinfo=None,
        )
        return _safe.ManagedProcess(
            process,
            intent=clean_intent,
            started_at=started_at,
        )
    except OSError as exc:
        raise _safe.SafeSubprocessError(
            f"managed GUI spawn failed ({clean_argv[0]!r}): {exc}"
        ) from exc
