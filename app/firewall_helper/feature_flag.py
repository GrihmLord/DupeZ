# app/firewall_helper/feature_flag.py
"""Resolve the DupeZ firewall architecture and return its manager façade.

Both architectures expose the same direct-Clumsy-aware surface. In split mode,
the diagnostic-window action rides the existing authenticated generic control
opcode rather than widening the privileged protocol. The Clumsy-specific status
name aliases the existing overall status opcode, whose helper implementation
already returns the direct manager's complete Clumsy status dictionary.
"""

from __future__ import annotations

import os
from typing import Any

ARCH_INPROC = "inproc"
ARCH_SPLIT = "split"

_VALID_ARCHS = frozenset({ARCH_INPROC, ARCH_SPLIT})
_ENV_VAR = "DUPEZ_ARCH"

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
    """Return the validated active architecture mode."""

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
    return get_arch() == ARCH_SPLIT


def _install_proxy_direct_clumsy_methods(manager: Any) -> Any:
    """Expose direct-Clumsy convenience methods over existing IPC opcodes."""

    if not hasattr(manager, "show_clumsy_diagnostic_window"):
        def show_clumsy_diagnostic_window(target_ip: str) -> bool:
            return bool(manager.hotkey_trigger(
                "show_clumsy_diagnostic_window",
                {"target_ip": target_ip},
            ))

        manager.show_clumsy_diagnostic_window = show_clumsy_diagnostic_window

    if not hasattr(manager, "get_clumsy_status"):
        # OP_GET_STATUS dispatches to manager.get_status(), whose direct-manager
        # implementation delegates to get_clumsy_status(). No new privileged
        # opcode or wider helper attack surface is needed.
        manager.get_clumsy_status = manager.get_status

    return manager


def get_disruption_manager() -> Any:
    """Return the direct-Clumsy-aware manager or authenticated IPC proxy."""

    if is_split_mode():
        from app.firewall_helper.ipc_client import get_proxy_manager

        return _install_proxy_direct_clumsy_methods(get_proxy_manager())

    from app.firewall.clumsy_diagnostics import (
        install_clumsy_diagnostic_bridge,
    )
    from app.firewall.direct_clumsy_manager import disruption_manager

    return install_clumsy_diagnostic_bridge(disruption_manager)
