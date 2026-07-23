"""Focused tests for the native engine's Clumsy-compatible pipeline."""

from __future__ import annotations

import time

from app.firewall.modules.duplicate import DuplicateModule
from app.firewall.native_divert_engine import (
    WINDIVERT_ADDRESS,
    NativeWinDivertEngine,
)


class FakeDivert:
    """Minimal verified-send transport for native engine unit tests."""

    def __init__(self, outcomes: list[str] | None = None) -> None:
        self.outcomes = list(outcomes or [])

    @staticmethod
    def calc_checksums(*_args) -> bool:
        return True

    def send(self, _handle, _buf, packet_len, send_len, _addr) -> bool:
        outcome = self.outcomes.pop(0) if self.outcomes else "success"
        if outcome == "raise":
            raise OSError("synthetic send failure")
        if outcome == "false":
            return False
        if outcome == "short":
            send_len._obj.value = max(0, packet_len - 1)
            return True
        send_len._obj.value = packet_len
        return True


def _engine(
    methods: list[str],
    params: dict | None = None,
    outcomes: list[str] | None = None,
) -> NativeWinDivertEngine:
    engine = NativeWinDivertEngine(
        dll_path=r"C:\fake\WinDivert.dll",
        filter_str="true",
        methods=methods,
        params=params or {},
    )
    engine._handle = 1
    engine._divert = FakeDivert(outcomes)
    return engine


def _outbound_address() -> WINDIVERT_ADDRESS:
    addr = WINDIVERT_ADDRESS()
    addr.Outbound = True
    return addr


def _wait_for(predicate, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    assert predicate(), "condition did not become true before timeout"


def test_public_modules_use_exact_clumsy_order_and_deduplicate() -> None:
    requested = [
        "rst",
        "lag",
        "drop",
        "disconnect",
        "bandwidth",
        "throttle",
        "duplicate",
        "ood",
        "corrupt",
        "rst",
        "lag",
    ]
    engine = _engine(requested)
    assert engine.methods == requested[:-2]

    try:
        engine._init_modules()
        assert [module.__class__.__name__ for module in engine._modules] == [
            "LagModule",
            "DropModule",
            "DisconnectModule",
            "BandwidthModule",
            "ThrottleModule",
            "DuplicateModule",
            "OODModule",
            "CorruptModule",
            "RSTModule",
        ]
        lag = engine._modules[0]
        assert lag._passthrough is False
    finally:
        engine._stop_modules()


def test_high_lag_does_not_implicitly_enable_native_keepalive_bypass() -> None:
    engine = _engine(["lag"], {"lag_delay": 5000})
    try:
        engine._init_modules()
        lag = engine._modules[0]
        assert lag.get_stats()["preserve_connection"] is False
    finally:
        engine._stop_modules()


def test_delayed_lag_release_resumes_at_downstream_duplicate() -> None:
    engine = _engine(
        ["duplicate", "lag"],
        {
            "lag_delay": 20,
            "duplicate_chance": 100,
            "duplicate_count": 1,
        },
    )
    try:
        engine._init_modules()
        consumed, consumer = engine._run_module_chain(
            bytearray(40), _outbound_address()
        )
        assert consumed is True
        assert consumer == "LagModule"

        duplicate = engine._modules[1]
        assert duplicate.get_stats()["attempts"] == 0
        _wait_for(lambda: duplicate.get_stats()["attempts"] == 2)

        lag_stats = engine._modules[0].get_stats()
        assert lag_stats["queued"] == 1
        assert lag_stats["released"] == 1
        assert lag_stats["release_failed"] == 0
        assert duplicate.get_stats() == {
            "attempts": 2,
            "sent": 2,
            "failed": 0,
        }
        assert engine.get_stats()["send_succeeded"] == 2
    finally:
        engine._stop_modules()


def test_delayed_lag_release_reaches_downstream_drop() -> None:
    engine = _engine(
        ["drop", "lag"],
        {"lag_delay": 10, "drop_chance": 100},
    )
    try:
        engine._init_modules()
        consumed, consumer = engine._run_module_chain(
            bytearray(40), _outbound_address()
        )
        assert consumed is True
        assert consumer == "LagModule"

        drop_activity = engine._module_activity[1]
        _wait_for(lambda: drop_activity["handled_outbound"] == 1)
        assert engine._modules[0].get_stats()["released"] == 1
        assert engine.get_stats()["send_attempted"] == 0
    finally:
        engine._stop_modules()


def test_explicit_lag_passthrough_keeps_immediate_copy_path() -> None:
    engine = _engine(
        ["lag", "duplicate"],
        {
            "lag_delay": 60_000,
            "lag_passthrough": True,
            "lag_preserve_connection": False,
            "duplicate_chance": 100,
            "duplicate_count": 1,
        },
    )
    try:
        engine._init_modules()
        consumed, consumer = engine._run_module_chain(
            bytearray(200), _outbound_address()
        )
        assert consumed is True
        assert consumer == "DuplicateModule"
        assert engine._modules[0]._passthrough is True
        assert engine._modules[1].get_stats()["attempts"] == 2
        assert engine._modules[0].get_stats()["queue_depth"] == 1
    finally:
        engine._stop_modules()


def test_stop_drains_lag_through_its_downstream_continuation() -> None:
    engine = _engine(
        ["lag", "duplicate"],
        {
            "lag_delay": 60_000,
            "lag_preserve_connection": False,
            "duplicate_chance": 100,
            "duplicate_count": 1,
        },
    )
    engine._init_modules()
    consumed, _ = engine._run_module_chain(
        bytearray(200), _outbound_address()
    )
    assert consumed is True
    assert engine._modules[0].get_stats()["queue_depth"] == 1

    engine._stop_modules()

    lag_stats = engine._modules[0].get_stats()
    assert lag_stats["queue_depth"] == 0
    assert lag_stats["released"] == 1
    assert engine._modules[1].get_stats()["sent"] == 2
    assert engine.get_stats()["send_succeeded"] == 2


def test_native_send_counts_success_failure_and_short_send() -> None:
    engine = _engine([], outcomes=["success", "false", "short"])
    packet = bytearray(40)
    addr = _outbound_address()

    assert engine._send_packet(packet, addr) is True
    assert engine._send_packet(packet, addr) is False
    assert engine._send_packet(packet, addr) is False

    stats = engine.get_stats()
    assert stats["send_attempted"] == 3
    assert stats["send_succeeded"] == 1
    assert stats["send_failed"] == 2
    assert stats["send_short"] == 1


def test_failed_duplicate_sends_are_reported_as_reached_not_effective() -> None:
    engine = _engine(
        ["duplicate"],
        {"duplicate_chance": 100, "duplicate_count": 1},
        outcomes=["false", "false"],
    )
    try:
        engine._init_modules()
        engine._packets_processed = 1
        engine._packets_outbound = 1
        consumed, consumer = engine._run_module_chain(
            bytearray(40), _outbound_address()
        )
        assert consumed is True
        assert consumer == "DuplicateModule"

        stats = engine.get_stats()
        assert stats["module_stats"]["DuplicateModule"] == {
            "attempts": 2,
            "sent": 0,
            "failed": 2,
        }
        assert stats["module_activity"]["duplicate"]["state"] == "reached"
        assert stats["effective_methods"] == []
    finally:
        engine._stop_modules()


def test_lag_reports_verified_release_failure() -> None:
    engine = _engine(
        ["lag"],
        {"lag_delay": 5},
        outcomes=["false"],
    )
    try:
        engine._init_modules()
        engine._run_module_chain(bytearray(40), _outbound_address())
        lag = engine._modules[0]
        _wait_for(lambda: lag.get_stats()["release_failed"] == 1)
        assert lag.get_stats()["queued"] == 1
        assert lag.get_stats()["released"] == 0
        assert engine.get_stats()["send_failed"] == 1
    finally:
        engine._stop_modules()


def test_duplicate_reports_each_attempt_and_failure() -> None:
    duplicate = DuplicateModule(
        {"duplicate_chance": 100, "duplicate_count": 2}
    )
    outcomes: list[bool | Exception] = [
        True,
        False,
        OSError("synthetic duplicate failure"),
    ]

    def sender(_packet, _addr) -> bool:
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    assert duplicate.process(
        bytearray(40), _outbound_address(), sender
    ) is True
    assert duplicate.get_stats() == {
        "attempts": 3,
        "sent": 1,
        "failed": 2,
    }
