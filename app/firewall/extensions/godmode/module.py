"""Bounded God Mode Native extension.

This is a deterministic connection-resilience lab, not an invulnerability,
hit-registration, anti-cheat, or public-server evasion feature.
"""

from __future__ import annotations

import ctypes
import time
from typing import Any, Callable, Optional

from app.firewall.extensions.base import ExtensionDescriptor
from app.firewall.extensions.godmode.classifier import (
    PacketClass,
    PacketClassifier,
)
from app.firewall.extensions.godmode.config import GodModeConfig
from app.firewall.extensions.godmode.direction import (
    DirectionResolver,
    PacketDirection,
)
from app.firewall.extensions.godmode.health import HealthPolicy
from app.firewall.extensions.godmode.queue_manager import (
    PacketEnvelope,
    QueueManager,
)
from app.firewall.extensions.godmode.scheduler import ReleaseScheduler
from app.firewall.extensions.godmode.state_machine import (
    GodModeState,
    GodModeStateMachine,
)
from app.firewall.extensions.godmode.telemetry import GodModeTelemetry
from app.firewall.native_divert_engine import DisruptionModule, WINDIVERT_ADDRESS
from app.logs.logger import log_error, log_info

__all__ = ["GODMODE_DESCRIPTOR", "GodModeExtensionModule"]


GODMODE_DESCRIPTOR = ExtensionDescriptor(
    capability_id="dupez.godmode",
    implementation_version="1.0.0",
    minimum_engine_version="6.0.0",
    supported_layers=frozenset({"network", "network_forward"}),
    composable_with=frozenset(),
    required_parameters=frozenset({"_target_ip"}),
    optional_parameters=frozenset({
        "extension_active_ms",
        "extension_block_ms",
        "extension_release_ms",
        "extension_release_batch",
        "extension_queue_max",
        "extension_keepalive_interval_ms",
        "extension_preserve_connection",
        "direction",
    }),
    experimental=True,
)


def _copy_address(addr: WINDIVERT_ADDRESS) -> WINDIVERT_ADDRESS:
    """Own the deferred-send address copy without importing legacy modules."""

    address = WINDIVERT_ADDRESS()
    ctypes.memmove(
        ctypes.byref(address),
        ctypes.byref(addr),
        ctypes.sizeof(WINDIVERT_ADDRESS),
    )
    return address


class GodModeExtensionModule(DisruptionModule):
    """Stateful, bounded packet-pressure extension with fail-open health."""

    _direction_key = ""

    def __init__(self, params: dict) -> None:
        super().__init__(params)
        self.config = GodModeConfig.from_params(params)
        self._state = GodModeStateMachine()
        self._classifier = PacketClassifier()
        self._directions = DirectionResolver()
        self._queue = QueueManager(self.config.queue_max)
        self._health = HealthPolicy()
        self._telemetry = GodModeTelemetry()
        self._send_fn: Optional[
            Callable[[bytearray, WINDIVERT_ADDRESS], bool]
        ] = None
        self._last_keepalive = {
            PacketDirection.INBOUND: 0.0,
            PacketDirection.OUTBOUND: 0.0,
        }
        self._scheduler = ReleaseScheduler(
            self.config,
            self._state,
            self._release_batch,
            self._on_expire,
            self._on_scheduler_failure,
        )

    def start_flush_thread(
        self,
        send_fn: Callable[[bytearray, WINDIVERT_ADDRESS], bool],
        divert_dll: object,
        handle: object,
    ) -> None:
        self._send_fn = send_fn
        self._scheduler.start()
        log_info(
            "God Mode extension 1.0.0 started as a bounded resilience lab "
            f"(active={self.config.active_ms}ms)"
        )

    def _should_pass_keepalive(
        self,
        packet_class: PacketClass,
        direction: PacketDirection,
        now: float,
    ) -> bool:
        if not self.config.preserve_connection:
            return False
        if packet_class not in {
            PacketClass.CONTROL,
            PacketClass.KEEPALIVE_CANDIDATE,
        }:
            return False
        interval = self.config.keepalive_interval_ms / 1000.0
        if now - self._last_keepalive[direction] < interval:
            return False
        self._last_keepalive[direction] = now
        return True

    def process(
        self,
        packet_data: bytearray,
        addr: WINDIVERT_ADDRESS,
        send_fn: Callable[[bytearray, Any], bool],
    ) -> bool:
        if not self._health.healthy or not self._scheduler.blocking:
            self._telemetry.increment("ordinary_passed")
            return False

        now = time.monotonic()
        direction = self._directions.resolve(addr)
        if (
            self.config.direction != "both"
            and direction.value != self.config.direction
        ):
            self._telemetry.increment("ordinary_passed")
            return False
        packet_class = self._classifier.classify(packet_data)
        if self._should_pass_keepalive(packet_class, direction, now):
            self._telemetry.increment("keepalive_passed")
            return False

        envelope = PacketEnvelope(
            captured_at=now,
            packet=bytearray(packet_data),
            address=_copy_address(addr),
            direction=direction,
        )
        if not self._queue.enqueue(envelope):
            self._telemetry.increment("overflow_passed")
            return False
        self._telemetry.increment("queued")
        return True

    def _release_batch(self, limit: Optional[int]) -> None:
        sender = self._send_fn
        if sender is None:
            return
        rows = self._queue.drain(limit)
        if rows:
            self._telemetry.increment("phase_releases")
        for envelope in rows:
            try:
                success = bool(sender(envelope.packet, envelope.address))
            except Exception as exc:
                success = False
                log_error(f"God Mode extension release failed: {exc}")
            self._health.record_send(success)
            self._telemetry.increment(
                "released" if success else "release_failed"
            )

    def _on_expire(self) -> None:
        self._telemetry.increment("expirations")
        log_info("God Mode extension reached its bounded deadline; fail-open")

    def _on_scheduler_failure(self, reason: str) -> None:
        self._health.fail(f"scheduler failure: {reason}")
        log_error(f"God Mode extension scheduler failed open: {reason}")

    def get_stats(self) -> dict:
        counters = self._telemetry.snapshot()
        counters.update({
            "capability_id": GODMODE_DESCRIPTOR.capability_id,
            "extension_version": GODMODE_DESCRIPTOR.implementation_version,
            "experimental": GODMODE_DESCRIPTOR.experimental,
            "lifecycle_state": self._state.state.value,
            "healthy": self._health.healthy,
            "last_error": self._health.reason,
            "queue_depth": self._queue.depth,
            "in_queue_depth": self._queue.depth_for(PacketDirection.INBOUND),
            "out_queue_depth": self._queue.depth_for(PacketDirection.OUTBOUND),
            "block_ms": self.config.block_ms,
            "release_ms": self.config.release_ms,
            "direction": self.config.direction,
            "bounded_max_active_ms": self.config.active_ms,
            "bounded_remaining_ms": max(
                0,
                int((self._scheduler.expires_at - time.monotonic()) * 1000),
            ),
        })
        return counters

    def stop(self) -> None:
        state = self._state.state
        if state not in {GodModeState.STOPPED, GodModeState.STOPPING}:
            try:
                self._state.transition(GodModeState.STOPPING)
            except Exception:
                pass
        self._scheduler.stop()
        self._release_batch(None)
        try:
            if self._state.state is not GodModeState.STOPPED:
                self._state.transition(GodModeState.STOPPED)
        except Exception:
            pass
        self._send_fn = None
