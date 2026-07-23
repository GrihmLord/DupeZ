"""Authorized hardware gate for every bundled Clumsy 0.3.4 control.

The test uses one explicitly authorized private IP/MAC and a bounded four-second
Timer event. All probabilistic effects are configured at zero or harmless
limits; Disconnect intentionally creates the short observable cut required to
prove that row is active. The RST one-shot is armed only after the owned process
is verified and is consumed with a small fixed TCP probe set against that same
authorized target.
"""

from __future__ import annotations

import ctypes
import ipaddress
import os
import platform
import re
import socket
import sys
import threading
import time

import pytest

from app.core.disruption_events import (
    ENGINE_CLUMSY,
    LAYER_AUTO,
    DisruptionEvent,
    EventSequence,
    EventSequenceRunner,
)

pytestmark = [pytest.mark.hardware, pytest.mark.slow]


class _NoopHardwareScheduler:
    def __init__(self, **_kwargs) -> None:
        self.running = False

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False


def _authorized_target() -> tuple[str, str, dict]:
    if os.environ.get("DUPEZ_RUN_HARDWARE_SMOKETEST") != "1":
        pytest.skip("set DUPEZ_RUN_HARDWARE_SMOKETEST=1 to opt in")
    if not (
        sys.platform == "win32"
        or platform.system().lower() == "windows"
    ):
        pytest.skip("full Clumsy controls hardware test requires Windows")
    try:
        is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        is_admin = False
    if not is_admin:
        pytest.skip("full Clumsy controls hardware test requires Administrator")

    target_ip = os.environ.get("DUPEZ_SMOKETEST_TARGET_IP", "").strip()
    target_mac = os.environ.get("DUPEZ_SMOKETEST_TARGET_MAC", "").strip()
    if not target_ip or not target_mac:
        pytest.skip("explicit private target IP and MAC are required")
    try:
        parsed = ipaddress.ip_address(target_ip)
    except ValueError:
        pytest.fail("DUPEZ_SMOKETEST_TARGET_IP is invalid")
    if not parsed.is_private:
        pytest.fail("full Clumsy controls target must be private/local")
    if not re.fullmatch(
        r"(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}",
        target_mac,
    ):
        pytest.fail("DUPEZ_SMOKETEST_TARGET_MAC is invalid")

    normalized_mac = target_mac.replace("-", ":").lower()
    from app.network.enhanced_scanner import EnhancedNetworkScanner

    devices = EnhancedNetworkScanner().scan_network(
        network_range=os.environ.get("DUPEZ_SMOKETEST_CIDR") or None,
        quick_scan=True,
    )
    for device in devices:
        candidate_mac = str(device.get("mac", "")).replace("-", ":").lower()
        if str(device.get("ip", "")) == target_ip and candidate_mac == normalized_mac:
            return target_ip, normalized_mac, device
    pytest.fail("explicitly authorized target was not found by the DupeZ scanner")


def _consume_authorized_rst_one_shot(target_ip: str) -> None:
    for port in (80, 443, 3478, 3479, 3480, 9295):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.settimeout(0.075)
            sock.connect_ex((target_ip, port))
        except OSError:
            pass
        finally:
            sock.close()


def test_every_clumsy_control_runs_on_one_owned_private_target() -> None:
    target_ip, _target_mac, target = _authorized_target()

    from app.core.controller import AppController

    controller = AppController(
        scheduler_factory=lambda **kwargs: _NoopHardwareScheduler(**kwargs),
    )
    statuses = []
    terminal = threading.Event()

    def on_status(status) -> None:
        statuses.append(status)
        if status.kind in {"complete", "halted", "error", "stopped"}:
            terminal.set()

    timer_seconds = int(
        os.environ.get("DUPEZ_SMOKETEST_FULL_TIMER_SECONDS", "4")
    )
    timer_seconds = max(2, min(10, timer_seconds))
    sequence = EventSequence(
        name="Authorized full Clumsy control matrix",
        events=[
            DisruptionEvent(
                name="All bundled Clumsy controls",
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
                    "direction": "both",
                    "lag_direction": "inbound",
                    "drop_direction": "outbound",
                    "disconnect_direction": "both",
                    "bandwidth_direction": "inbound",
                    "throttle_direction": "outbound",
                    "duplicate_direction": "both",
                    "ood_direction": "inbound",
                    "tamper_direction": "outbound",
                    "corrupt_direction": "outbound",
                    "rst_direction": "both",
                    "lag_delay": 0,
                    "drop_chance": 0,
                    "disconnect_chance": 100,
                    "disconnect_arm_delay_ms": 0,
                    "disconnect_duration_ms": 0,
                    "bandwidth_queue": 4,
                    "bandwidth_limit": 99_999,
                    "bandwidth_size": "mb",
                    "throttle_frame": 10,
                    "throttle_chance": 0,
                    "throttle_drop": True,
                    "duplicate_count": 1,
                    "duplicate_chance": 0,
                    "ood_chance": 0,
                    "tamper_chance": 0,
                    "tamper_checksum": False,
                    "rst_chance": 0,
                    "_clumsy_filter_predicate": "true",
                    "_clumsy_filter_name": "DupeZ Hardware Target",
                    "_clumsy_function_preset_name": "DupeZ Full Matrix",
                    "_clumsy_trigger_mode": "timer",
                    "_clumsy_timer_seconds": timer_seconds,
                    "_clumsy_rst_next_packet": False,
                },
                engine_preference=ENGINE_CLUMSY,
                network_layer=LAYER_AUTO,
                # Keep the queue alive beyond the fork/manager Timer so the test
                # proves generation-owned auto-release before runner cleanup.
                duration_seconds=float(timer_seconds + 2),
            )
        ],
    )
    runner = EventSequenceRunner(
        sequence,
        controller,
        target_ip,
        disrupt_kwargs={
            "target_mac": target.get("mac"),
            "target_hostname": target.get("hostname"),
            "target_device_type": target.get("device_type"),
        },
        on_status=on_status,
    )

    try:
        assert runner.start() is True
        deadline = time.monotonic() + 25.0
        while time.monotonic() < deadline:
            if any(status.kind == "active" for status in statuses):
                break
            if terminal.is_set():
                break
            time.sleep(0.05)

        active = next(
            (status for status in statuses if status.kind == "active"),
            None,
        )
        assert active is not None, (
            "full control event never reached ACTIVE; statuses="
            + repr([(item.kind, item.detail) for item in statuses])
        )
        assert active.actual_engine in {"clumsy", "clumsy_compatibility"}

        runtime = controller.get_disruption_status(target_ip) or {}
        assert runtime.get("disrupted") is True
        assert runtime.get("startup_verified") is True
        assert runtime.get("owned_process") is True
        assert runtime.get("full_control_integration") is True
        assert runtime.get("additional_filter") == "true"
        assert runtime.get("filter_preset") == "DupeZ Hardware Target"
        assert runtime.get("function_preset") == "DupeZ Full Matrix"
        assert runtime.get("trigger_mode") == "timer"
        assert runtime.get("timer_seconds") == timer_seconds
        assert runtime.get("bandwidth_unit") == "mb"
        assert runtime.get("module_directions") == {
            "lag": "inbound",
            "drop": "outbound",
            "disconnect": "both",
            "bandwidth": "inbound",
            "throttle": "outbound",
            "duplicate": "both",
            "ood": "inbound",
            "corrupt": "outbound",
            "rst": "both",
        }

        manager = getattr(controller, "disruption_manager", None)
        if manager is None:
            manager = controller._disruption_manager
        assert manager.show_clumsy_diagnostic_window(target_ip) is True
        assert manager.hotkey_trigger(
            "clumsy_rst_next_packet",
            {"target_ip": target_ip},
        ) is True
        _consume_authorized_rst_one_shot(target_ip)

        release_deadline = time.monotonic() + timer_seconds + 5.0
        while time.monotonic() < release_deadline:
            current = controller.get_disruption_status(target_ip) or {}
            if current.get("disrupted") is not True:
                break
            time.sleep(0.1)
        released = controller.get_disruption_status(target_ip) or {}
        assert released.get("disrupted") is not True, (
            "Clumsy Timer did not release the owned generation"
        )

        assert terminal.wait(20.0), "full control event queue did not complete"
        assert statuses[-1].kind == "complete"
    finally:
        runner.stop()
        controller.stop_disruption(target_ip)
        controller.shutdown()
