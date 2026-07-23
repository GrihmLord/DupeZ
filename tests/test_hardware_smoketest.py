"""Hardware-in-the-loop smoketest for the complete disruption pipeline.

The suite is deliberately opt-in and targets only the exact private IP/MAC pair
supplied by the operator. Protocol-specific modules receive generated eligible
traffic where passive console traffic is insufficient; in particular, the RST
module is exercised with bounded TCP connection probes to the authorized target.
"""

from __future__ import annotations

import ctypes
import ipaddress
import os
import platform
import re
import socket
import sys
import time
from typing import Optional

import pytest

pytestmark = [pytest.mark.hardware, pytest.mark.slow]


def _is_windows() -> bool:
    return sys.platform == "win32" or platform.system().lower() == "windows"


def _is_admin() -> bool:
    if not _is_windows():
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _windivert_bits_present() -> bool:
    firewall_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "app",
        "firewall",
    )
    return all(
        os.path.isfile(os.path.join(firewall_dir, filename))
        for filename in ("WinDivert.dll", "WinDivert64.sys")
    )


@pytest.fixture(scope="module")
def _require_hardware() -> None:
    if os.environ.get("DUPEZ_RUN_HARDWARE_SMOKETEST") != "1":
        pytest.skip(
            "hardware smoketest is opt-in; set "
            "DUPEZ_RUN_HARDWARE_SMOKETEST=1 on a prepared Windows host"
        )
    if not _is_windows():
        pytest.skip("hardware smoketest requires Windows")
    if not _is_admin():
        pytest.skip("hardware smoketest requires Administrator privileges")
    if not _windivert_bits_present():
        pytest.skip("WinDivert.dll / WinDivert64.sys missing from app/firewall/")

    target_ip = os.environ.get("DUPEZ_SMOKETEST_TARGET_IP", "").strip()
    target_mac = os.environ.get("DUPEZ_SMOKETEST_TARGET_MAC", "").strip()
    if not target_ip or not target_mac:
        pytest.skip(
            "hardware disruption requires explicit authorization: set both "
            "DUPEZ_SMOKETEST_TARGET_IP and DUPEZ_SMOKETEST_TARGET_MAC"
        )
    try:
        parsed_ip = ipaddress.ip_address(target_ip)
    except ValueError:
        pytest.fail("DUPEZ_SMOKETEST_TARGET_IP is not a valid IP address")
    if not parsed_ip.is_private:
        pytest.fail("hardware smoketest target must be a private-network IP")
    if not re.fullmatch(
        r"(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}",
        target_mac,
    ):
        pytest.fail("DUPEZ_SMOKETEST_TARGET_MAC is not a valid MAC address")


def _pick_authorized_target(devices: list) -> Optional[dict]:
    target_ip = os.environ["DUPEZ_SMOKETEST_TARGET_IP"].strip()
    target_mac = (
        os.environ["DUPEZ_SMOKETEST_TARGET_MAC"]
        .replace("-", ":")
        .lower()
    )
    for device in devices:
        device_mac = str(device.get("mac", "")).replace("-", ":").lower()
        if str(device.get("ip", "")) == target_ip and device_mac == target_mac:
            return device
    return None


def _aggregate_packets(manager) -> int:
    try:
        stats = manager.get_engine_stats() or {}
    except Exception:
        return 0
    if "packets_processed" in stats:
        return int(stats.get("packets_processed") or 0)
    per_device = stats.get("per_device") or {}
    return sum(
        int(entry.get("packets_processed") or 0)
        for entry in per_device.values()
        if isinstance(entry, dict)
    )


def _device_engine_stats(manager, target_ip: str) -> dict:
    stats = manager.get_engine_stats() or {}
    per_device = stats.get("per_device") or {}
    direct = per_device.get(target_ip)
    if isinstance(direct, dict):
        return direct
    for entry in per_device.values():
        if isinstance(entry, dict) and entry.get("target_ip") == target_ip:
            return entry
    if len(per_device) == 1:
        only = next(iter(per_device.values()))
        return only if isinstance(only, dict) else {}
    return {}


def _generate_authorized_tcp_traffic(target_ip: str) -> None:
    """Generate bounded SYN traffic so the RST module sees eligible packets.

    ``connect_ex`` is intentionally used instead of a port scanner: it probes a
    fixed, small port set on the one explicitly authorized target, does not send
    application data, and closes every socket immediately.
    """

    for port in (80, 443, 3478, 3479, 3480, 9295):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.settimeout(0.075)
            sock.connect_ex((target_ip, port))
        except OSError:
            pass
        finally:
            sock.close()


def test_scan_then_lag_then_stop_pipeline(_require_hardware) -> None:
    from app.firewall_helper.feature_flag import get_disruption_manager
    from app.network.enhanced_scanner import EnhancedNetworkScanner

    network_range = os.environ.get("DUPEZ_SMOKETEST_CIDR") or None
    lag_ms = int(os.environ.get("DUPEZ_SMOKETEST_LAG_MS", "300"))
    duration_s = float(os.environ.get("DUPEZ_SMOKETEST_DURATION", "6.0"))

    devices = EnhancedNetworkScanner().scan_network(
        network_range=network_range,
        quick_scan=True,
    )
    assert devices, (
        "scan returned zero devices — check adapter state, ARP table "
        "population, and network range"
    )
    target = _pick_authorized_target(devices)
    assert target is not None, (
        "the explicitly authorized DUPEZ_SMOKETEST_TARGET_IP/MAC pair "
        f"was not found in {len(devices)} scan result(s)"
    )

    target_ip = target["ip"]
    manager = get_disruption_manager()
    started = manager.disrupt_device(
        target_ip,
        methods=["lag"],
        params={
            "lag_delay": lag_ms,
            "_engine_preference": "native",
        },
        target_mac=target.get("mac"),
        target_hostname=target.get("hostname"),
    )
    assert started, (
        f"disrupt_device returned False for {target_ip} — check admin token, "
        "WinDivert driver, and logs"
    )

    try:
        deadline = time.time() + duration_s
        while time.time() < deadline:
            time.sleep(0.25)
        packets = _aggregate_packets(manager)
        device_stats = _device_engine_stats(manager, target_ip)
    finally:
        manager.stop_device(target_ip)

    assert packets > 0, (
        f"engine processed 0 packets over {duration_s:.1f}s on {target_ip} — "
        "verify the target is actively transmitting"
    )
    assert device_stats.get("telemetry_available") is True
    lag_activity = (device_stats.get("module_activity") or {}).get("lag", {})
    assert lag_activity.get("invoked", 0) > 0, (
        "lag was advertised but its invocation counter stayed at zero: "
        f"{lag_activity}"
    )
    assert lag_activity.get("affected", 0) > 0, (
        "lag received packets but never delayed one: "
        f"{lag_activity}"
    )


def test_each_advertised_module_receives_hardware_traffic(
    _require_hardware,
) -> None:
    """Run every public module alone and prove an observable effect."""

    from app.core.validation import PUBLIC_DIAGNOSTIC_METHODS
    from app.firewall_helper.feature_flag import get_disruption_manager
    from app.network.enhanced_scanner import EnhancedNetworkScanner

    network_range = os.environ.get("DUPEZ_SMOKETEST_CIDR") or None
    per_method_s = float(
        os.environ.get("DUPEZ_SMOKETEST_MODULE_DURATION", "3.0")
    )
    devices = EnhancedNetworkScanner().scan_network(
        network_range=network_range,
        quick_scan=True,
    )
    target = _pick_authorized_target(devices)
    assert target is not None, (
        "the explicitly authorized target is not active for module counters"
    )

    target_ip = target["ip"]
    manager = get_disruption_manager()
    method_params = {
        "lag": {"lag_delay": 50},
        "drop": {"drop_chance": 100},
        "disconnect": {
            "disconnect_chance": 100,
            "disconnect_duration_ms": 500,
        },
        "bandwidth": {"bandwidth_limit": 1, "bandwidth_queue": 16},
        "throttle": {"throttle_chance": 100, "throttle_frame": 100},
        "duplicate": {"duplicate_chance": 100, "duplicate_count": 1},
        "ood": {"ood_chance": 100},
        "corrupt": {"tamper_chance": 100},
        "rst": {"rst_chance": 100},
    }
    failures = []

    for method in PUBLIC_DIAGNOSTIC_METHODS:
        params = {
            "direction": "both",
            "_engine_preference": "native",
            **method_params[method],
        }
        started = manager.disrupt_device(
            target_ip,
            methods=[method],
            params=params,
            target_mac=target.get("mac"),
            target_hostname=target.get("hostname"),
        )
        if not started:
            failures.append(f"{method}: engine did not start")
            continue
        try:
            deadline = time.time() + per_method_s
            activity = {}
            while time.time() < deadline:
                if method == "rst":
                    _generate_authorized_tcp_traffic(target_ip)
                activity = (
                    _device_engine_stats(manager, target_ip)
                    .get("module_activity", {})
                    .get(method, {})
                )
                if activity.get("affected", 0) > 0:
                    break
                time.sleep(0.1)
            if activity.get("affected", 0) <= 0:
                failures.append(
                    f"{method}: affected counter stayed zero ({activity})"
                )
        finally:
            manager.stop_device(target_ip)

    assert not failures, "advertised module counter failures:\n" + "\n".join(
        failures
    )


def test_bundled_clumsy_gui_automation_starts_verified(
    _require_hardware,
) -> None:
    """Exercise the bundled process, layer selection, controls, and Start."""

    from app.firewall_helper.feature_flag import get_disruption_manager
    from app.network.enhanced_scanner import EnhancedNetworkScanner

    network_range = os.environ.get("DUPEZ_SMOKETEST_CIDR") or None
    devices = EnhancedNetworkScanner().scan_network(
        network_range=network_range,
        quick_scan=True,
    )
    target = _pick_authorized_target(devices)
    assert target is not None, "explicitly authorized Clumsy target not found"

    target_ip = target["ip"]
    manager = get_disruption_manager()
    started = manager.disrupt_device(
        target_ip,
        methods=["lag"],
        params={
            "direction": "both",
            "lag_delay": 100,
            "_engine_preference": "clumsy",
        },
        target_mac=target.get("mac"),
        target_hostname=target.get("hostname"),
    )
    status = manager.get_clumsy_status() or {}
    assert started, (
        "bundled Clumsy GUI/layer/control verification failed: "
        f"{status.get('last_engine_error') or status}"
    )
    try:
        stats = _device_engine_stats(manager, target_ip)
        assert stats.get("engine") == "clumsy_compatibility"
        assert stats.get("startup_verified") is True
        assert stats.get("telemetry_available") is False
    finally:
        manager.stop_device(target_ip)


def test_vendor_resolution_resolves_known_oui() -> None:
    from app.network.shared import VENDOR_OUIS, lookup_vendor

    assert (
        lookup_vendor("b4:0a:d8:11:22:33")
        == "Sony Interactive Entertainment"
    )
    candidates = [
        ("08:00:07:11:22:33", "apple"),
        ("00:0d:93:11:22:33", "apple"),
        ("00:1d:0f:11:22:33", "cisco"),
        ("00:0c:29:11:22:33", "vmware"),
        ("00:50:56:11:22:33", "vmware"),
        ("b8:27:eb:11:22:33", "raspberry"),
        ("dc:a6:32:11:22:33", "raspberry"),
        ("3c:5a:b4:11:22:33", "google"),
    ]

    failures = []
    for mac, expected_substring in candidates:
        prefix = ":".join(mac.split(":")[:3]).lower()
        if prefix in VENDOR_OUIS:
            continue
        vendor = lookup_vendor(mac)
        if vendor == "Unknown":
            failures.append(f"{mac} → Unknown")
            continue
        if expected_substring in vendor.lower():
            return
        return

    raise AssertionError(
        "scapy MANUFDB fallback not resolving any tested OUI. "
        f"Tested: {[mac for mac, _ in candidates]}. Failures: {failures}"
    )
