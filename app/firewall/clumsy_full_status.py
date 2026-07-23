# app/firewall/clumsy_full_status.py — observable full-control metadata
"""Expose verified Clumsy control state through the existing device status API."""

from __future__ import annotations

from app.firewall.direct_clumsy_manager import DirectClumsyNetworkDisruptor

__all__ = ["install_full_clumsy_status"]

_FULL_CONTROL_STATUS_KEYS = (
    "full_control_integration",
    "additional_filter",
    "filter_preset",
    "function_preset",
    "trigger_mode",
    "timer_seconds",
    "bandwidth_unit",
    "module_directions",
    "rst_next_packet_armed",
)


def install_full_clumsy_status() -> None:
    """Forward bounded, non-packet control metadata exactly once."""

    if getattr(
        DirectClumsyNetworkDisruptor,
        "_full_clumsy_status_installed",
        False,
    ):
        return

    original = DirectClumsyNetworkDisruptor.get_device_status_clumsy

    def get_device_status_clumsy(
        manager: DirectClumsyNetworkDisruptor,
        target_ip: str,
    ) -> dict:
        status = dict(original(manager, target_ip))
        if not status.get("disrupted"):
            return status
        with manager._device_lock:
            entry = manager.disrupted_devices.get(target_ip, {})
            engine = entry.get("engine")
        if engine is None or not hasattr(engine, "get_stats"):
            return status
        stats = dict(engine.get_stats() or {})
        for key in _FULL_CONTROL_STATUS_KEYS:
            if key in stats:
                status[key] = stats[key]
        return status

    DirectClumsyNetworkDisruptor.get_device_status_clumsy = (
        get_device_status_clumsy
    )
    DirectClumsyNetworkDisruptor._full_clumsy_status_installed = True
