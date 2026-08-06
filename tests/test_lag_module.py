"""Behavioral tests for the bounded connection-resilience lag mode."""

from __future__ import annotations

import threading

from app.firewall.modules import lag as lag_module
from app.firewall.modules.lag import LagModule
from app.firewall.native_divert_engine import WINDIVERT_ADDRESS


def _addr(*, outbound: bool) -> WINDIVERT_ADDRESS:
    address = WINDIVERT_ADDRESS()
    address.Outbound = outbound
    return address


def test_connection_preservation_tracks_each_capture_direction() -> None:
    module = LagModule({
        "lag_delay": 1000,
        "lag_preserve_connection": True,
        "lag_keepalive_interval_ms": 1000,
    })

    assert module.process(bytearray(20), _addr(outbound=False), lambda *_: True) is False
    assert module.process(bytearray(20), _addr(outbound=True), lambda *_: True) is False
    # A second immediate inbound packet is delayed; its direction already used
    # its cadence allowance. The outbound packet did not consume it.
    assert module.process(bytearray(20), _addr(outbound=False), lambda *_: True) is True
    assert module.get_stats()["keepalive_passed"] == 2


def test_bounded_mode_fails_open_and_flushes_backlog_at_expiry() -> None:
    released = threading.Event()
    module = LagModule({
        "lag_delay": 5000,
        "lag_max_active_ms": 25000,
    })
    assert module.process(bytearray(200), _addr(outbound=True), lambda *_: True) is True

    def _send(_packet, _address) -> bool:
        released.set()
        return True

    module.start_flush_thread(_send, object(), object())
    module._expires_at = lag_module.time.monotonic() - 1.0

    # New traffic is no longer held after the hard window.
    assert module.process(bytearray(200), _addr(outbound=True), _send) is False
    assert released.wait(1.0)
    stats = module.get_stats()
    assert stats["bounded_expired"] is True
    assert stats["queue_depth"] == 0
    assert stats["expired_backlog_released"] == 1
    module.stop()


def test_queue_overflow_passes_current_packet_without_evicting_oldest(
    monkeypatch,
) -> None:
    monkeypatch.setattr(lag_module, "_MAX_QUEUE_SIZE", 1)
    module = LagModule({"lag_delay": 1000})

    assert module.process(bytearray(200), _addr(outbound=True), lambda *_: True) is True
    assert module.process(bytearray(200), _addr(outbound=True), lambda *_: True) is False
    stats = module.get_stats()
    assert stats["queue_depth"] == 1
    assert stats["queue_overflow_passed"] == 1


def test_bounded_window_is_clamped_below_thirty_seconds() -> None:
    module = LagModule({"lag_max_active_ms": 999999})
    assert module.get_stats()["bounded_max_active_ms"] == 29000
