# app/firewall/clumsy_diagnostics.py — diagnostic control adapter
"""Install the small diagnostic action shared by both architectures."""

from __future__ import annotations

from typing import Any, Optional

from app.core.validation import validate_local_target_ip
from app.logs.logger import log_error

__all__ = ["install_clumsy_diagnostic_bridge"]

_ACTION_SHOW_WINDOW = "show_clumsy_diagnostic_window"


def install_clumsy_diagnostic_bridge(manager: Any) -> Any:
    """Attach a hotkey/control-plane diagnostic bridge to *manager*.

    The split helper already exposes an authenticated, allow-listed generic
    control opcode for small operator actions. Reusing it avoids widening the
    privileged protocol. Existing hotkey behavior is preserved for all other
    actions.
    """

    if getattr(manager, "_clumsy_diagnostic_bridge_installed", False):
        return manager

    original = getattr(manager, "hotkey_trigger", None)

    def hotkey_trigger(action: str, payload: Optional[dict] = None) -> bool:
        if action == _ACTION_SHOW_WINDOW:
            target_ip = str((payload or {}).get("target_ip") or "")
            try:
                target_ip = validate_local_target_ip(
                    target_ip,
                    context="Clumsy diagnostic window",
                )
            except ValueError as exc:
                log_error(f"Clumsy diagnostic request rejected: {exc}")
                return False
            show = getattr(manager, "show_clumsy_diagnostic_window", None)
            return bool(callable(show) and show(target_ip))
        if callable(original):
            return bool(original(action, payload or {}))
        return False

    manager.hotkey_trigger = hotkey_trigger
    manager._clumsy_diagnostic_bridge_installed = True
    return manager
