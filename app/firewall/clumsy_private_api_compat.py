# app/firewall/clumsy_private_api_compat.py — safe private-call compatibility
"""Preserve legacy private selector tests without allowing an unscoped filter.

Normal application code enters through ``disconnect_device_clumsy`` and always
provides ``_target_ip``. A small number of older internal callers invoke the
private ``_start_selected_engine`` method while testing replacement of an
already-active session. When such a call supplies ``true`` and omits the target,
we may safely recover the *one exact private target already owned by the
manager*. All other incomplete calls continue to fail closed.
"""

from __future__ import annotations

from typing import Any

from app.core.clumsy_controls import normalize_additional_filter
from app.core.validation import validate_local_target_ip
from app.firewall.direct_clumsy_manager import DirectClumsyNetworkDisruptor

__all__ = ["install_private_selector_compatibility"]


def install_private_selector_compatibility() -> None:
    """Install the one-active-target compatibility adapter exactly once."""

    if getattr(
        DirectClumsyNetworkDisruptor,
        "_private_selector_compat_installed",
        False,
    ):
        return

    original = DirectClumsyNetworkDisruptor._start_selected_engine

    def scoped_private_selector(
        manager: DirectClumsyNetworkDisruptor,
        *,
        filter_str: str,
        methods: list[str],
        params: dict[str, Any],
    ):
        effective = dict(params or {})
        target = str(effective.get("_target_ip") or "").strip()
        predicate = normalize_additional_filter(
            effective.get("_clumsy_filter_predicate", "true")
        )

        if not target and predicate.lower() == "true":
            with manager._device_lock:
                active_targets = tuple(manager.disrupted_devices)
            if len(active_targets) == 1:
                recovered = validate_local_target_ip(
                    active_targets[0],
                    context="Clumsy private selector compatibility",
                )
                effective["_target_ip"] = recovered
                filter_str = (
                    f"ip.SrcAddr == {recovered} or "
                    f"ip.DstAddr == {recovered}"
                )

        return original(
            manager,
            filter_str=filter_str,
            methods=methods,
            params=effective,
        )

    DirectClumsyNetworkDisruptor._start_selected_engine = (
        scoped_private_selector
    )
    DirectClumsyNetworkDisruptor._private_selector_compat_installed = True
