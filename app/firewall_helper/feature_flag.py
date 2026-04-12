# app/firewall_helper/feature_flag.py
"""
Resolves the DUPEZ_ARCH feature flag and provides the disruption-manager
factory that callers use instead of importing `disruption_manager` directly.

Usage in callers (app/core/controller.py is the only production consumer
that needs to change in Day 1):

    from app.firewall_helper.feature_flag import get_disruption_manager
    disruption_manager = get_disruption_manager()

Under DUPEZ_ARCH=inproc (default) this returns the existing singleton from
app.firewall.clumsy_network_disruptor — zero behavioural change from today.

Under DUPEZ_ARCH=split this returns a DisruptionManagerProxy that forwards
every call over a named-pipe IPC to the elevated helper process.
"""

from __future__ import annotations

import os
from typing import Any

ARCH_INPROC = "inproc"
ARCH_SPLIT = "split"

_VALID_ARCHS = frozenset({ARCH_INPROC, ARCH_SPLIT})

_ENV_VAR = "DUPEZ_ARCH"

# Resolve the compiled-in default. Build variants (DupeZ-GPU vs
# DupeZ-Compat) are produced by writing ``_build_default.py`` next
# to this module with ``_BUILD_DEFAULT_ARCH = "split"`` or
# ``"inproc"`` before invoking PyInstaller. If the file is absent
# (dev run from source), we fall back to ``inproc`` so nothing
# changes for developers who haven't opted in.
try:
    from app.firewall_helper._build_default import (  # type: ignore
        _BUILD_DEFAULT_ARCH as _COMPILED_DEFAULT,
    )
    if _COMPILED_DEFAULT not in _VALID_ARCHS:
        _COMPILED_DEFAULT = ARCH_INPROC
except Exception:
    _COMPILED_DEFAULT = ARCH_INPROC

_DEFAULT_ARCH = _COMPILED_DEFAULT


def get_arch() -> str:
    """Return the active architecture mode, validated.

    Resolution order:
      1. ``DUPEZ_ARCH`` environment variable (user override).
      2. Compiled-in default from ``_build_default.py`` (set by
         build variant — split for DupeZ-GPU, inproc for
         DupeZ-Compat).
      3. Hard fallback to ``inproc``.

    Never raises — feature-flag parsing must never prevent app
    startup.
    """
    raw = os.environ.get(_ENV_VAR, _DEFAULT_ARCH).strip().lower()
    if raw in _VALID_ARCHS:
        return raw
    # Silent fallback on bad input; controller can log if it cares.
    return _DEFAULT_ARCH


def is_split_mode() -> bool:
    """Convenience: True if DUPEZ_ARCH=split, else False."""
    return get_arch() == ARCH_SPLIT


def get_disruption_manager() -> Any:
    """Return the active disruption manager instance.

    * inproc mode: the existing in-process singleton. Bit-for-bit identical
      to today's behaviour — no IPC, no helper, no changes.
    * split mode: a DisruptionManagerProxy that forwards calls to the
      elevated helper over a named pipe.

    This indirection is the ONLY production-path touch in Day 1 of the
    ADR-0001 rollout. Under `inproc` the import path is identical to the
    current direct import, so the hot path is unchanged.
    """
    if is_split_mode():
        # Lazy import to avoid pulling named-pipe code into the inproc path.
        from app.firewall_helper.ipc_client import get_proxy_manager
        return get_proxy_manager()

    # Default: return the existing singleton, unchanged.
    from app.firewall.clumsy_network_disruptor import disruption_manager
    return disruption_manager
