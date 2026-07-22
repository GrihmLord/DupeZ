"""Authorized hardware gate for the direct Clumsy event queue.

This proves the exact product path requested by operators:
AppController -> EventSequenceRunner -> explicit Clumsy event -> verified owned
Clumsy process -> generation-safe automatic stop.

Persisted local scheduler rules are stopped before the event starts. Hardware
validation must exercise only the event defined by this test, never an unrelated
saved timed rule from the operator's normal DupeZ configuration.
"""

from __future__ import annotations

import ctypes
import ipaddress
import os
import platform
import re
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


def _require_authorized_hardware() -> tuple[str, str]:
    if os.environ.get("DUPEZ_RUN_HARDWARE_SMOKETEST") != "1":
        pytest.skip("set DUPEZ_RUN_HARDWARE_SMOKETEST=1 to opt in")
    if not (
        sys.platform == "win32"
        or platform.system().lower() == "windows"
    ):
        pytest.skip("direct Clumsy event hardware test requires Windows")
    try:
        is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        is_admin = False
    if not is_admin:
        pytest.skip("direct Clumsy event hardware test requires Administrator")

    target_ip = os.environ.get("DUPEZ_SMOKETEST_TARGET_IP", "").strip()
    target_mac = os.environ.get("DUPEZ_SMOKETEST_TARGET_MAC", "").strip()
    if not target_ip or not target_mac:
        pytest.skip("explicit DUPEZ_SMOKETEST_TARGET_IP and MAC are required")

    try:
        parsed = ipaddress.ip_address(target_ip)
    except ValueError:
        pytest.fail("DUPEZ_SMOKETEST_TARGET_IP is invalid")
    if not parsed.is_private:
        pytest.fail("direct Clumsy event target must be private/local")
    if not re.fullmatch(
        r"(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}",
        target_mac,
    ):
        pytest.fail("DUPEZ_SMOKETEST_TARGET_MAC is invalid")
    return target_ip, target_mac.replace("-", ":").lower()


def _find_authorized_target(target_ip: str, target_mac: str) -> dict:
    from app.network.enhanced_scanner import EnhancedNetworkScanner

    devices = EnhancedNetworkScanner().scan_network(
        network_range=os.environ.get("DUPEZ_SMOKETEST_CIDR") or None,
        quick_scan=True,
    )
    for device in devices:
        candidate_mac = str(device.get("mac", "")).replace("-", ":").lower()
        if str(device.get("ip", "")) == target_ip and candidate_mac == target_mac:
            return device
    pytest.fail(
        "explicitly authorized target was not found by the DupeZ scanner"
    )


def test_explicit_direct_clumsy_event_runs_and_releases_cleanly() -> None:
    target_ip, target_mac = _require_authorized_hardware()
    target = _find_authorized_target(target_ip, target_mac)

    from app.core.controller import AppController

    controller = AppController()
    # AppController intentionally loads and starts the user's persisted
    # scheduler. Stop it immediately so an old timed rule cannot overlap this
    # single-purpose hardware event or mutate the same target generation.
    controller.scheduler.stop()

    statuses = []
    complete = threading.Event()

    def on_status(status) -> None:
        statuses.append(status)
        if status.kind in {"complete", "halted", "error", "stopped"}:
            complete.set()

    sequence = EventSequence(
        name="Authorized direct Clumsy event smoke",
        events=[
            DisruptionEvent(
                name="Verified direct Clumsy lag",
                methods=["lag"],
                params={
                    "direction": "both",
                    "lag_delay": int(
                        os.environ.get("DUPEZ_SMOKETEST_LAG_MS", "100")
                    ),
                },
                engine_preference=ENGINE_CLUMSY,
                network_layer=LAYER_AUTO,
                duration_seconds=float(
                    os.environ.get("DUPEZ_SMOKETEST_DURATION", "3.0")
                ),
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
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            if any(status.kind == "active" for status in statuses):
                break
            if complete.is_set():
                break
            time.sleep(0.05)

        active = next(
            (status for status in statuses if status.kind == "active"),
            None,
        )
        assert active is not None, (
            "event never reached ACTIVE; statuses="
            + repr([(item.kind, item.detail) for item in statuses])
        )
        assert active.actual_engine in {"clumsy", "clumsy_compatibility"}

        runtime = controller.get_disruption_status(target_ip)
        assert runtime.get("disrupted") is True
        assert runtime.get("startup_verified") is True
        assert runtime.get("owned_process") is True
        assert runtime.get("generation") is not None

        assert complete.wait(20.0), "event queue did not complete within bound"
        runner.stop()
        assert not runner.running
        final_status = controller.get_disruption_status(target_ip)
        assert final_status.get("disrupted") is not True
        assert statuses[-1].kind == "complete"
    finally:
        runner.stop()
        controller.stop_disruption(target_ip)
        controller.shutdown()
