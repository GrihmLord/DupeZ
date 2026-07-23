"""Regression tests for split-mode direct Clumsy convenience contracts."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.firewall_helper.feature_flag import (
    _install_proxy_direct_clumsy_methods,
)


def test_split_proxy_clumsy_status_uses_existing_status_opcode():
    expected = {
        "direct_clumsy_integration": True,
        "last_engine_error": "diagnostic",
    }
    get_status = MagicMock(return_value=expected)
    proxy = SimpleNamespace(
        get_status=get_status,
        hotkey_trigger=MagicMock(return_value=True),
    )

    result = _install_proxy_direct_clumsy_methods(proxy)

    assert result is proxy
    assert proxy.get_clumsy_status() is expected
    get_status.assert_called_once_with()


def test_split_proxy_diagnostic_method_uses_authenticated_hotkey_opcode():
    hotkey = MagicMock(return_value=True)
    proxy = SimpleNamespace(
        get_status=MagicMock(return_value={}),
        hotkey_trigger=hotkey,
    )

    _install_proxy_direct_clumsy_methods(proxy)

    assert proxy.show_clumsy_diagnostic_window("192.168.1.20") is True
    hotkey.assert_called_once_with(
        "show_clumsy_diagnostic_window",
        {"target_ip": "192.168.1.20"},
    )


def test_hardware_event_injects_scheduler_before_controller_start():
    source = open(
        "tests/test_direct_clumsy_event_hardware.py",
        encoding="utf-8",
    ).read()

    constructor = source.index("controller = AppController(")
    injection = source.index("scheduler_factory=", constructor)
    assert injection > constructor
    assert "controller.scheduler.stop()" not in source
    assert "class _NoopHardwareScheduler" in source
