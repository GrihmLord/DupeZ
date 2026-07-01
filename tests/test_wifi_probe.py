"""Tests for passive WiFi route diagnostics."""

from __future__ import annotations

import sys
from types import SimpleNamespace

from app.network import wifi_probe


class _FakeRouteSocket:
    def __init__(self, local_ip: str = "192.168.7.42", error: Exception | None = None):
        self._local_ip = local_ip
        self._error = error

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def connect(self, _addr):
        if self._error:
            raise self._error

    def getsockname(self):
        return (self._local_ip, 49152)


def _install_fake_route(monkeypatch, local_ip: str = "192.168.7.42") -> None:
    monkeypatch.setattr(
        wifi_probe.socket,
        "socket",
        lambda *_args, **_kwargs: _FakeRouteSocket(local_ip=local_ip),
    )


def _addr(ip: str):
    return SimpleNamespace(address=ip)


def test_get_wifi_route_info_detects_wifi_adapter(monkeypatch) -> None:
    _install_fake_route(monkeypatch)
    fake_psutil = SimpleNamespace(
        net_if_addrs=lambda: {
            "Ethernet": [_addr("10.0.0.10")],
            "Wi-Fi": [_addr("192.168.7.42")],
        }
    )
    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)

    info = wifi_probe.get_wifi_route_info()

    assert info.is_wifi is True
    assert info.adapter_name == "Wi-Fi"
    assert info.masked_local_ip == "192.168.7.x"
    assert info.psutil_available is True
    assert "matched" in info.reason


def test_get_wifi_route_info_reports_non_wifi_adapter(monkeypatch) -> None:
    _install_fake_route(monkeypatch)
    fake_psutil = SimpleNamespace(
        net_if_addrs=lambda: {"Ethernet": [_addr("192.168.7.42")]}
    )
    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)

    info = wifi_probe.get_wifi_route_info()

    assert info.is_wifi is False
    assert info.adapter_name == "Ethernet"
    assert "did not match" in info.reason


def test_get_wifi_route_info_reports_missing_adapter(monkeypatch) -> None:
    _install_fake_route(monkeypatch)
    fake_psutil = SimpleNamespace(
        net_if_addrs=lambda: {"Ethernet": [_addr("10.0.0.10")]}
    )
    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)

    info = wifi_probe.get_wifi_route_info()

    assert info.is_wifi is False
    assert info.adapter_name is None
    assert info.masked_local_ip == "192.168.7.x"
    assert "not found" in info.reason


def test_get_wifi_route_info_reports_route_probe_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        wifi_probe.socket,
        "socket",
        lambda *_args, **_kwargs: _FakeRouteSocket(error=OSError("offline")),
    )
    monkeypatch.setitem(
        sys.modules,
        "psutil",
        SimpleNamespace(net_if_addrs=lambda: {}),
    )

    info = wifi_probe.get_wifi_route_info()

    assert info.is_wifi is False
    assert info.local_ip is None
    assert "probe failed" in info.reason


def test_is_local_adapter_wifi_delegates_to_structured_probe(monkeypatch) -> None:
    monkeypatch.setattr(
        wifi_probe,
        "get_wifi_route_info",
        lambda: wifi_probe.WifiRouteInfo(is_wifi=True),
    )

    assert wifi_probe.is_local_adapter_wifi() is True
