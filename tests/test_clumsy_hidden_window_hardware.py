"""Authorized hardware proof for hidden normal Clumsy operation.

Normal disruption startup must keep the owned IUP window invisible, layered,
off-screen, and absent from Alt+Tab while all controls remain active.  The
explicit diagnostic action is the only operation allowed to restore it.
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
from app.firewall import clumsy_network_disruptor as legacy

pytestmark = [pytest.mark.hardware, pytest.mark.slow]


class _NoopHardwareScheduler:
    def __init__(self, **_kwargs) -> None:
        self.running = False

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False


def _authorized_target() -> tuple[str, dict]:
    if os.environ.get("DUPEZ_RUN_HARDWARE_SMOKETEST") != "1":
        pytest.skip("set DUPEZ_RUN_HARDWARE_SMOKETEST=1 to opt in")
    if not (
        sys.platform == "win32"
        or platform.system().lower() == "windows"
    ):
        pytest.skip("hidden Clumsy hardware test requires Windows")
    try:
        is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        is_admin = False
    if not is_admin:
        pytest.skip("hidden Clumsy hardware test requires Administrator")

    target_ip = os.environ.get("DUPEZ_SMOKETEST_TARGET_IP", "").strip()
    target_mac = os.environ.get("DUPEZ_SMOKETEST_TARGET_MAC", "").strip()
    if not target_ip or not target_mac:
        pytest.skip("explicit private target IP and MAC are required")
    try:
        parsed = ipaddress.ip_address(target_ip)
    except ValueError:
        pytest.fail("DUPEZ_SMOKETEST_TARGET_IP is invalid")
    if not parsed.is_private:
        pytest.fail("hidden Clumsy target must be private/local")
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
            return target_ip, device
    pytest.fail("explicitly authorized target was not found by the DupeZ scanner")


class _Rect(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def _owned_engine(manager, target_ip: str):
    lock = getattr(manager, "_device_lock", None)
    assert lock is not None, "direct manager does not expose its ownership lock"
    with lock:
        entry = dict(manager.disrupted_devices.get(target_ip) or {})
    engine = entry.get("engine")
    assert engine is not None, "active target has no owned engine"
    assert getattr(engine, "alive", False) is True
    return engine


def test_owned_clumsy_is_hidden_until_authenticated_diagnostic_restore() -> None:
    target_ip, target = _authorized_target()

    from app.core.controller import AppController
    from app.firewall.clumsy_diagnostics import install_clumsy_diagnostic_bridge
    from app.firewall.direct_clumsy_manager import DirectClumsyNetworkDisruptor

    # This proof needs direct access to the exact owned HWND. A split-mode IPC
    # proxy intentionally does not expose process locks or window handles, so
    # inject a fresh fully bridged in-process manager for this source hardware
    # test. Split/helper architecture boundaries are validated separately.
    manager = install_clumsy_diagnostic_bridge(DirectClumsyNetworkDisruptor())
    controller = AppController(
        disruption_manager=manager,
        scheduler_factory=lambda **kwargs: _NoopHardwareScheduler(**kwargs),
    )
    statuses = []
    active_event = threading.Event()
    terminal = threading.Event()

    def on_status(status) -> None:
        statuses.append(status)
        if status.kind == "active":
            active_event.set()
        if status.kind in {"complete", "halted", "error", "stopped"}:
            terminal.set()

    sequence = EventSequence(
        name="Authorized hidden Clumsy window proof",
        events=[
            DisruptionEvent(
                name="Hidden owned Lag",
                methods=["lag"],
                params={
                    "direction": "both",
                    "lag_direction": "both",
                    "lag_delay": 100,
                    "_clumsy_filter_predicate": "true",
                    "_clumsy_filter_name": "DupeZ Hidden Target",
                    "_clumsy_function_preset_name": "DupeZ Hidden Proof",
                    "_clumsy_trigger_mode": "toggle",
                    "_clumsy_timer_seconds": 4,
                },
                engine_preference=ENGINE_CLUMSY,
                network_layer=LAYER_AUTO,
                duration_seconds=8.0,
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
        assert active_event.wait(25.0), (
            "hidden Clumsy event never reached ACTIVE; statuses="
            + repr([(item.kind, item.detail) for item in statuses])
        )

        engine = _owned_engine(manager, target_ip)
        hwnd = int(getattr(engine, "_hwnd", 0) or 0)
        assert hwnd > 0, "owned Clumsy engine has no verified HWND"

        user32 = ctypes.windll.user32
        assert bool(user32.IsWindowVisible(hwnd)) is False, (
            "normal Clumsy disruption exposed its native window"
        )
        ex_style = int(user32.GetWindowLongW(hwnd, legacy.GWL_EXSTYLE))
        assert ex_style & legacy.WS_EX_TOOLWINDOW, (
            "hidden Clumsy window remains in normal task switching"
        )
        assert ex_style & legacy.WS_EX_LAYERED, (
            "hidden Clumsy window is not using the transparent policy"
        )
        rect = _Rect()
        assert user32.GetWindowRect(hwnd, ctypes.byref(rect))
        assert rect.left <= -30_000 and rect.top <= -30_000, (
            "hidden Clumsy window was not moved off-screen: "
            f"left={rect.left}, top={rect.top}"
        )

        assert manager.show_clumsy_diagnostic_window(target_ip) is True
        restore_deadline = time.monotonic() + 2.0
        while time.monotonic() < restore_deadline:
            if bool(user32.IsWindowVisible(hwnd)):
                break
            time.sleep(0.05)
        assert bool(user32.IsWindowVisible(hwnd)) is True, (
            "authenticated diagnostic action did not restore the owned window"
        )

        # Return to ordinary no-popup policy before cleanup.
        assert legacy._hide_window(hwnd) is True
        assert bool(user32.IsWindowVisible(hwnd)) is False
    finally:
        runner.stop()
        controller.stop_disruption(target_ip)
        controller.shutdown()
