"""Tests for passive WiFi route diagnostics."""

from __future__ import annotations

import sys
import threading
import time
from types import SimpleNamespace

import pytest

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


def test_watchdog_cancel_interrupts_grace_and_quiesces() -> None:
    results: list[str] = []
    watchdog = wifi_probe.IsolationWatchdog(
        spoofer=SimpleNamespace(_packets_sent=1),
        engine=SimpleNamespace(_running=True, _packets_processed=0),
        on_result=results.append,
        grace_s=30.0,
    )
    watchdog.start()

    started = time.monotonic()
    watchdog.cancel()
    elapsed = time.monotonic() - started

    assert elapsed < 0.5
    assert watchdog._thread is not None
    assert not watchdog._thread.is_alive()
    assert results == [wifi_probe.IsolationResult.ABORTED]


def test_watchdog_cancel_converts_a_pending_isolation_result_to_aborted(
    monkeypatch,
) -> None:
    pending_delivery = threading.Event()
    release_delivery = threading.Event()
    results: list[str] = []
    attempted_results: list[str] = []
    watchdog = wifi_probe.IsolationWatchdog(
        spoofer=SimpleNamespace(_packets_sent=1),
        engine=SimpleNamespace(_running=True, _packets_processed=0),
        on_result=results.append,
        grace_s=0.0,
    )
    original_fire = watchdog._fire

    def _gated_fire(result: str) -> None:
        attempted_results.append(result)
        pending_delivery.set()
        assert release_delivery.wait(timeout=1.0)
        original_fire(result)

    monkeypatch.setattr(watchdog, "_fire", _gated_fire)
    watchdog.start()
    assert pending_delivery.wait(timeout=1.0)

    cancel_errors: list[BaseException] = []

    def _cancel() -> None:
        try:
            watchdog.cancel()
        except BaseException as exc:  # pragma: no cover - assertion aid
            cancel_errors.append(exc)

    cancel_thread = threading.Thread(target=_cancel)
    cancel_thread.start()
    assert watchdog._cancelled.wait(timeout=1.0)
    release_delivery.set()
    cancel_thread.join(timeout=1.0)

    assert not cancel_thread.is_alive()
    assert cancel_errors == []
    assert attempted_results == [wifi_probe.IsolationResult.ISOLATION_DETECTED]
    assert results == [wifi_probe.IsolationResult.ABORTED]


def test_watchdog_cancel_times_out_if_committed_callback_does_not_finish(
    monkeypatch,
) -> None:
    callback_started = threading.Event()
    release_callback = threading.Event()

    def _on_result(_result: str) -> None:
        callback_started.set()
        release_callback.wait(timeout=2.0)

    watchdog = wifi_probe.IsolationWatchdog(
        spoofer=SimpleNamespace(_packets_sent=1),
        engine=SimpleNamespace(_running=True, _packets_processed=1),
        on_result=_on_result,
        grace_s=0.0,
    )
    monkeypatch.setattr(watchdog, "_CANCEL_JOIN_TIMEOUT_S", 0.05)
    watchdog.start()
    assert callback_started.wait(timeout=1.0)

    try:
        with pytest.raises(TimeoutError, match="did not stop"):
            watchdog.cancel()
    finally:
        release_callback.set()
        assert watchdog._thread is not None
        watchdog._thread.join(timeout=1.0)

    assert not watchdog._thread.is_alive()


def test_watchdog_callback_can_cancel_itself_without_self_join() -> None:
    callback_finished = threading.Event()
    results: list[str] = []
    watchdog: wifi_probe.IsolationWatchdog

    def _on_result(result: str) -> None:
        results.append(result)
        watchdog.cancel()
        callback_finished.set()

    watchdog = wifi_probe.IsolationWatchdog(
        spoofer=SimpleNamespace(_packets_sent=1),
        engine=SimpleNamespace(_running=True, _packets_processed=1),
        on_result=_on_result,
        grace_s=0.0,
    )
    watchdog.start()

    assert callback_finished.wait(timeout=1.0)
    assert watchdog._thread is not None
    watchdog._thread.join(timeout=1.0)
    assert not watchdog._thread.is_alive()
    assert results == [wifi_probe.IsolationResult.WORKING]
