"""Pure and manager-level coverage for complete Clumsy control integration."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core.clumsy_controls import (
    validate_clumsy_control_params,
    normalize_additional_filter,
)
from app.firewall import clumsy_full_controls as controls
from app.firewall.direct_clumsy_manager import ManagedClumsyEngine


def _engine(tmp_path, methods=None, params=None):
    executable = tmp_path / "clumsy.exe"
    executable.write_bytes(b"clumsy-control-contract")
    effective = {
        "direction": "both",
        "lag_delay": 170,
        "drop_chance": 99,
        "bandwidth_queue": 0,
        "bandwidth_limit": 1,
        "bandwidth_size": "kb",
        "throttle_frame": 30,
        "throttle_chance": 10,
        "duplicate_count": 1,
        "duplicate_chance": 10,
        "ood_chance": 10,
        "tamper_chance": 10,
        "rst_chance": 0,
        "_clumsy_filter_name": "DupeZ Target",
        "_clumsy_function_preset_name": "Freeze",
        "_clumsy_trigger_mode": "toggle",
        "_clumsy_timer_seconds": 3,
    }
    effective.update(params or {})
    return ManagedClumsyEngine(
        str(executable),
        str(tmp_path),
        "ip.SrcAddr == 192.168.137.2 or ip.DstAddr == 192.168.137.2",
        list(methods or ["lag"]),
        effective,
    )


def test_additional_filter_defaults_true_and_cannot_escape_scope():
    assert normalize_additional_filter("") == "true"
    assert normalize_additional_filter("udp and udp.DstPort == 3074") == (
        "udp and udp.DstPort == 3074"
    )

    with pytest.raises(ValueError, match="outer scope"):
        normalize_additional_filter("true) or true or (true")
    with pytest.raises(ValueError, match="single line"):
        normalize_additional_filter("true\nanything")
    with pytest.raises(ValueError, match="unsupported characters"):
        normalize_additional_filter("true # comment")


def test_scoped_filter_true_keeps_exact_private_target():
    base = "ip.SrcAddr == 192.168.137.2 or ip.DstAddr == 192.168.137.2"
    assert controls.compose_scoped_filter(base, "192.168.137.2", "true") == base

    narrowed = controls.compose_scoped_filter(
        base,
        "192.168.137.2",
        "udp and udp.DstPort == 3074",
    )
    assert narrowed.startswith(f"({base}) and (")
    assert narrowed.endswith("udp and udp.DstPort == 3074)")

    with pytest.raises(ValueError, match="mandatory exact-target"):
        controls.compose_scoped_filter("true", "192.168.137.2", "true")
    with pytest.raises(ValueError):
        controls.compose_scoped_filter(base, "8.8.8.8", "true")


def test_full_parameter_validation_accepts_per_module_directions():
    reasons = validate_clumsy_control_params(
        ["lag", "drop", "rst"],
        {
            "direction": "both",
            "lag_direction": "inbound",
            "drop_direction": "outbound",
            "rst_direction": "both",
            "lag_delay": 170,
            "drop_chance": 99,
            "rst_chance": 0,
            "_clumsy_filter_predicate": "true",
            "_clumsy_trigger_mode": "timer",
            "_clumsy_timer_seconds": 3,
            "bandwidth_size": "kb",
            "_clumsy_rst_next_packet": True,
        },
    )
    assert reasons == ()


def test_full_parameter_validation_enforces_fork_limits():
    reasons = validate_clumsy_control_params(
        ["lag", "throttle", "duplicate"],
        {
            "lag_delay": 15_001,
            "throttle_frame": 1_001,
            "throttle_chance": 101,
            "duplicate_count": 50,
            "duplicate_chance": 101,
            "_clumsy_trigger_mode": "timer",
            "_clumsy_timer_seconds": 61,
        },
    )
    joined = "; ".join(reasons)
    assert "lag_delay must be from 0 to 15000" in joined
    assert "throttle_frame must be from 0 to 1000" in joined
    assert "duplicate_count must be from 1 to 49" in joined
    assert "1 to 60" in joined


def test_full_preset_writer_round_trips_all_direction_and_unit_values(tmp_path):
    engine = _engine(
        tmp_path,
        methods=[
            "lag",
            "drop",
            "disconnect",
            "bandwidth",
            "throttle",
            "duplicate",
            "ood",
            "corrupt",
            "rst",
        ],
        params={
            "lag_direction": "inbound",
            "drop_direction": "outbound",
            "disconnect_direction": "both",
            "bandwidth_direction": "inbound",
            "throttle_direction": "outbound",
            "duplicate_direction": "both",
            "ood_direction": "inbound",
            "tamper_direction": "outbound",
            "rst_direction": "both",
            "bandwidth_size": "mb",
            "throttle_drop": True,
            "tamper_checksum": False,
            "_clumsy_function_preset_name": "Freeze",
        },
    )

    controls._write_full_presets(engine)
    content = (tmp_path / "presets.ini").read_text(encoding="utf-8")

    assert "PresetName = Freeze" in content
    assert "Lag_Inbound = true" in content
    assert "Lag_Outbound = false" in content
    assert "Drop_Inbound = false" in content
    assert "Drop_Outbound = true" in content
    assert "Disconnect_Inbound = true" in content
    assert "Disconnect_Outbound = true" in content
    assert "BandwidthLimiter_Size = mb" in content
    assert "Throttle_DropThrottled = true" in content
    assert "Tamper_RedoChecksum = false" in content
    assert "SetTCPRST_Inbound = true" in content
    assert "SetTCPRST_Outbound = true" in content
    assert content.count("[Preset") == 5


def test_named_config_writer_sanitizes_record_name(tmp_path):
    engine = _engine(
        tmp_path,
        params={"_clumsy_filter_name": "My:Target\nInjected"},
    )
    controls._write_config_with_named_scope(engine)
    content = (tmp_path / "config.txt").read_text(encoding="utf-8")
    assert content.count("\n") == 1
    assert content.startswith("MyTarget Injected: ip.SrcAddr")


def test_owned_rst_action_requires_live_managed_engine(monkeypatch, tmp_path):
    manager = SimpleNamespace(
        _device_lock=__import__("threading").Lock(),
        disrupted_devices={},
    )
    assert controls.trigger_owned_rst_next_packet(
        manager,
        "192.168.137.2",
    ) is False

    engine = _engine(tmp_path, methods=["rst"])
    engine._proc = SimpleNamespace(poll=lambda: None)
    engine._hwnd = 77
    manager.disrupted_devices["192.168.137.2"] = {"engine": engine}
    click = MagicMock(return_value=True)
    monkeypatch.setattr(controls, "_click_rst_next_packet", click)

    assert controls.trigger_owned_rst_next_packet(
        manager,
        "192.168.137.2",
    ) is True
    click.assert_called_once_with(engine)
