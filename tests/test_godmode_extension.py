"""Behavioral contract for the bounded namespaced God Mode extension."""

from __future__ import annotations

import threading

import pytest

from app.firewall.extensions.godmode.classifier import PacketClass, PacketClassifier
from app.firewall.extensions.godmode.config import GodModeConfig
from app.firewall.extensions.godmode.direction import PacketDirection
from app.firewall.extensions.godmode.module import (
    GODMODE_DESCRIPTOR,
    GodModeExtensionModule,
)
from app.firewall.extensions.godmode.queue_manager import PacketEnvelope, QueueManager
from app.firewall.extensions.godmode.scheduler import ReleaseScheduler
from app.firewall.extensions.godmode.state_machine import (
    GodModeState,
    GodModeStateMachine,
    IllegalTransition,
)
from app.firewall.native_divert_engine import WINDIVERT_ADDRESS


def _ipv4_tcp(payload_size: int, flags: int = 0x10) -> bytearray:
    packet = bytearray(40 + payload_size)
    packet[0] = 0x45
    packet[9] = 6
    packet[20 + 12] = 0x50
    packet[20 + 13] = flags
    return packet


def _ipv4_udp(payload_size: int) -> bytearray:
    packet = bytearray(28 + payload_size)
    packet[0] = 0x45
    packet[9] = 17
    return packet


def _addr(*, outbound: bool) -> WINDIVERT_ADDRESS:
    address = WINDIVERT_ADDRESS()
    address.Outbound = outbound
    return address


def test_descriptor_is_namespaced_bounded_and_noncomposable() -> None:
    assert GODMODE_DESCRIPTOR.capability_id == "dupez.godmode"
    assert GODMODE_DESCRIPTOR.experimental is True
    assert GODMODE_DESCRIPTOR.composable_with == frozenset()


def test_config_clamps_window_and_normalizes_direction() -> None:
    config = GodModeConfig.from_params({
        "extension_active_ms": 999_999,
        "extension_queue_max": 1,
        "direction": "outbound",
    })
    assert config.active_ms == 29_000
    assert config.queue_max == 128
    assert config.direction == "outbound"
    assert GodModeConfig.from_params({"direction": "sideways"}).direction == "both"


def test_classifier_does_not_treat_tcp_application_data_as_control() -> None:
    classifier = PacketClassifier()
    assert classifier.classify(_ipv4_tcp(0)) is PacketClass.CONTROL
    assert classifier.classify(_ipv4_tcp(30)) is PacketClass.DATA
    assert classifier.classify(_ipv4_tcp(30, flags=0x02)) is PacketClass.CONTROL
    assert classifier.classify(_ipv4_udp(96)) is PacketClass.KEEPALIVE_CANDIDATE
    assert classifier.classify(_ipv4_udp(97)) is PacketClass.DATA


def test_queue_is_bounded_directional_and_drains_in_capture_order() -> None:
    queue = QueueManager(2)
    later = PacketEnvelope(2.0, bytearray(b"b"), object(), PacketDirection.OUTBOUND)
    earlier = PacketEnvelope(1.0, bytearray(b"a"), object(), PacketDirection.INBOUND)
    assert queue.enqueue(later)
    assert queue.enqueue(earlier)
    assert not queue.enqueue(later)
    assert queue.depth_for(PacketDirection.INBOUND) == 1
    assert queue.depth_for(PacketDirection.OUTBOUND) == 1
    assert [row.packet for row in queue.drain()] == [bytearray(b"a"), bytearray(b"b")]


def test_state_machine_rejects_illegal_transition_and_can_stop_idle() -> None:
    state = GodModeStateMachine()
    with pytest.raises(IllegalTransition):
        state.transition(GodModeState.RELEASING)
    state.transition(GodModeState.STOPPED)
    assert state.state is GodModeState.STOPPED


def test_module_honors_direction_and_reports_new_schema() -> None:
    module = GodModeExtensionModule({
        "_target_ip": "192.0.2.10",
        "direction": "outbound",
        "extension_preserve_connection": False,
    })
    module._state.transition(GodModeState.ARMED)
    module._state.transition(GodModeState.ACTIVE)

    assert module.process(_ipv4_udp(200), _addr(outbound=False), lambda *_: True) is False
    assert module.process(_ipv4_udp(200), _addr(outbound=True), lambda *_: True) is True
    stats = module.get_stats()
    assert stats["direction"] == "outbound"
    assert stats["in_queue_depth"] == 0
    assert stats["out_queue_depth"] == 1
    module.stop()


def test_scheduler_expiry_releases_and_stops() -> None:
    state = GodModeStateMachine()
    expired = threading.Event()
    releases: list[int | None] = []
    failures: list[str] = []
    scheduler = ReleaseScheduler(
        GodModeConfig(active_ms=30, block_ms=10, release_ms=5),
        state,
        releases.append,
        expired.set,
        failures.append,
    )
    scheduler.start()
    assert expired.wait(1.0)
    assert state.state is GodModeState.STOPPED
    assert None in releases
    assert failures == []
