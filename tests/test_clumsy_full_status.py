"""Status API coverage for verified full-control metadata."""

from __future__ import annotations

from types import SimpleNamespace

from app.firewall.clumsy_full_status import install_full_clumsy_status
from app.firewall.direct_clumsy_manager import DirectClumsyNetworkDisruptor


def test_device_status_forwards_only_full_control_metadata(monkeypatch):
    install_full_clumsy_status()
    manager = DirectClumsyNetworkDisruptor()
    engine = SimpleNamespace(
        alive=True,
        get_stats=lambda: {
            "full_control_integration": True,
            "additional_filter": "true",
            "filter_preset": "DupeZ Target",
            "function_preset": "Freeze",
            "trigger_mode": "timer",
            "timer_seconds": 4,
            "bandwidth_unit": "mb",
            "module_directions": {"lag": "inbound"},
            "rst_next_packet_armed": True,
            "filter_expression": "must not be added by this adapter",
        },
    )
    manager.disrupted_devices["192.168.1.20"] = {
        "engine": engine,
        "generation": 7,
        "engine_name": "clumsy",
        "engine_preference": "clumsy",
        "methods": ["lag"],
        "params": {},
        "start_time": 1.0,
    }

    status = manager.get_device_status("192.168.1.20")

    assert status["full_control_integration"] is True
    assert status["additional_filter"] == "true"
    assert status["filter_preset"] == "DupeZ Target"
    assert status["function_preset"] == "Freeze"
    assert status["trigger_mode"] == "timer"
    assert status["timer_seconds"] == 4
    assert status["bandwidth_unit"] == "mb"
    assert status["module_directions"] == {"lag": "inbound"}
    assert status["rst_next_packet_armed"] is True
    assert "filter_expression" not in status
