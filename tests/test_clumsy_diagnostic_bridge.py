"""Tests for Clumsy diagnostic controls in both architectures."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.firewall.clumsy_diagnostics import install_clumsy_diagnostic_bridge
from app.firewall_helper.feature_flag import _install_proxy_diagnostic_method


def test_inproc_bridge_restores_owned_window_for_private_target():
    manager = SimpleNamespace(
        show_clumsy_diagnostic_window=MagicMock(return_value=True),
    )

    install_clumsy_diagnostic_bridge(manager)
    result = manager.hotkey_trigger(
        "show_clumsy_diagnostic_window",
        {"target_ip": "192.168.1.20"},
    )

    assert result is True
    manager.show_clumsy_diagnostic_window.assert_called_once_with(
        "192.168.1.20"
    )


def test_diagnostic_bridge_rejects_public_target():
    manager = SimpleNamespace(
        show_clumsy_diagnostic_window=MagicMock(return_value=True),
    )
    install_clumsy_diagnostic_bridge(manager)

    result = manager.hotkey_trigger(
        "show_clumsy_diagnostic_window",
        {"target_ip": "8.8.8.8"},
    )

    assert result is False
    manager.show_clumsy_diagnostic_window.assert_not_called()


def test_bridge_preserves_existing_generic_actions():
    original = MagicMock(return_value=True)
    manager = SimpleNamespace(
        hotkey_trigger=original,
        show_clumsy_diagnostic_window=MagicMock(return_value=False),
    )
    install_clumsy_diagnostic_bridge(manager)

    assert manager.hotkey_trigger("record_marker", {"value": 1}) is True
    original.assert_called_once_with("record_marker", {"value": 1})


def test_split_proxy_maps_show_window_to_authenticated_control_action():
    proxy = SimpleNamespace(hotkey_trigger=MagicMock(return_value=True))

    _install_proxy_diagnostic_method(proxy)
    result = proxy.show_clumsy_diagnostic_window("10.0.0.9")

    assert result is True
    proxy.hotkey_trigger.assert_called_once_with(
        "show_clumsy_diagnostic_window",
        {"target_ip": "10.0.0.9"},
    )


def test_helper_installs_bridge_before_starting_server():
    source = open("dupez_helper.py", encoding="utf-8").read()

    install_index = source.index("install_clumsy_diagnostic_bridge(")
    server_index = source.index("run_helper_server(")
    assert install_index < server_index
