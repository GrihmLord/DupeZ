# app/firewall_helper/feature_flag.py
"""
Resolves the DUPEZ_ARCH feature flag and provides the disruption-manager
factory that callers use instead of importing a manager singleton directly.

Usage::

    from app.firewall_helper.feature_flag import get_disruption_manager
    disruption_manager = get_disruption_manager()

Under ``DUPEZ_ARCH=inproc`` this returns the owned direct-Clumsy manager from
``app.firewall.direct_clumsy_manager``. Under ``DUPEZ_ARCH=split`` it returns a
``DisruptionManagerProxy`` that forwards every call over authenticated named-
pipe IPC to the elevated helper. The helper imports the same direct manager, so
engine selection, contention handling, and graceful process ownership remain
identical across both build variants.
"""

from __future__ import annotations

import os
from typing import Any

ARCH_INPROC = "inproc"
ARCH_SPLIT = "split"

_VALID_ARCHS = frozenset({ARCH_INPROC, ARCH_SPLIT})
_ENV_VAR = "DUPEZ_ARCH"

# Build variants write _build_default.py next to this module before invoking
# PyInstaller. Source checkouts fall back to inproc.
try:
    from app.firewall_helper._build_default import (  # type: ignore
        _BUILD_DEFAULT_ARCH as _COMPILED_DEFAULT,
    )
    if _COMPILED_DEFAULT not in _VALID_ARCHS:
        _COMPILED_DEFAULT = ARCH_INPROC
except Exception:
    _COMPILED_DEFAULT = ARCH_INPROC

_DEFAULT_ARCH = _COMPILED_DEFAULT


def _detect_gpu_available() -> bool:
    """Best-effort GPU detection for ambiguous development builds."""

    import sys

    if sys.platform != "win32":
        return False

    try:
        from app.core.gpu_probe import probe_gpu_usable

        usable, _reason = probe_gpu_usable()
        return usable
    except Exception:
        pass

    try:
        from app.core import safe_subprocess as safe_subprocess

        system_root = os.environ.get("SystemRoot") or r"C:\Windows"
        wmic_path = os.path.join(
            system_root,
            "System32",
            "wbem",
            "wmic.exe",
        )
        if not os.path.isfile(wmic_path):
            return False
        result = safe_subprocess.run(
            [wmic_path, "path", "win32_videocontroller", "get", "name"],
            timeout=5.0,
            expect_returncode=None,
            intent="feature_flag.gpu_probe_wmic",
        )
        lines = [
            line
            for line in (raw.strip() for raw in result.stdout.splitlines())
            if line and line.lower() != "name"
        ]
        for line in lines:
            lowered = line.lower()
            if (
                "microsoft basic" not in lowered
                and "standard vga" not in lowered
            ):
                return True
        return False
    except Exception:
        return False


def get_arch() -> str:
    """Return the validated active architecture mode.

    Resolution order:
      1. explicit ``DUPEZ_ARCH`` environment override;
      2. compiled build default;
      3. GPU auto-detection fallback;
      4. hard ``inproc`` fallback.
    """

    environment_value = os.environ.get(_ENV_VAR, "").strip().lower()
    if environment_value in _VALID_ARCHS:
        return environment_value

    if _DEFAULT_ARCH in _VALID_ARCHS:
        return _DEFAULT_ARCH

    try:
        if _detect_gpu_available():
            return ARCH_SPLIT
    except Exception:
        pass

    return ARCH_INPROC


def is_split_mode() -> bool:
    """Return whether the GUI uses the elevated-helper architecture."""

    return get_arch() == ARCH_SPLIT


def get_disruption_manager() -> Any:
    """Return the active direct-Clumsy-aware manager or IPC proxy."""

    if is_split_mode():
        from app.firewall_helper.ipc_client import get_proxy_manager

        return get_proxy_manager()

    from app.firewall.direct_clumsy_manager import disruption_manager

    return disruption_manager
