"""Safety and target-selection guards for the opt-in hardware CLI."""

from __future__ import annotations

import argparse

import pytest

from tools.smoketest_scan_and_lag import _mac, _pick_target, _private_ip


def test_hardware_cli_requires_private_target() -> None:
    assert _private_ip("192.168.1.42") == "192.168.1.42"
    with pytest.raises(argparse.ArgumentTypeError, match="private"):
        _private_ip("8.8.8.8")


def test_hardware_cli_normalizes_mac() -> None:
    assert _mac("00-11-22-33-44-55") == "00:11:22:33:44:55"
    with pytest.raises(argparse.ArgumentTypeError, match="MAC"):
        _mac("not-a-mac")


def test_hardware_cli_never_falls_back_to_an_unselected_device() -> None:
    devices = [
        {"ip": "192.168.1.10", "mac": "aa:aa:aa:aa:aa:aa"},
        {"ip": "192.168.1.42", "mac": "00:11:22:33:44:55"},
    ]

    assert _pick_target(
        devices,
        "192.168.1.42",
        "00:11:22:33:44:55",
    ) == devices[1]
    assert _pick_target(
        devices,
        "192.168.1.42",
        "ff:ff:ff:ff:ff:ff",
    ) is None
