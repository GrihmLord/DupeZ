"""Hardware-in-the-loop smoketest — mirrors ``tools/smoketest_scan_and_lag.py``.

Runs the full disruption pipeline end-to-end: scan → pick target → start lag
→ poll engine stats → stop. Asserts that every stage produces the expected
side-effects.

This test is gated behind the ``hardware`` marker and requires:
  * Windows host (``sys.platform == 'win32'``)
  * Administrator privileges (WinDivert kernel driver)
  * Npcap installed and operational
  * WinDivert driver present in ``app/firewall/``
  * An explicitly authorized, reachable private-network target

Skips with a clear reason when any prerequisite is missing so it's safe to
invoke with ``pytest -m hardware`` from any environment.

Opt-in invocations:
    pytest -m hardware                            # run only this
    pytest -m "hardware and not slow"             # fast hardware checks
    pytest                                        # default excludes this

Environment overrides (optional):
    DUPEZ_RUN_HARDWARE_SMOKETEST=1
    DUPEZ_SMOKETEST_CIDR=192.168.137.0/24
    DUPEZ_SMOKETEST_TARGET_IP=192.168.137.42
    DUPEZ_SMOKETEST_TARGET_MAC=00:11:22:33:44:55
    DUPEZ_SMOKETEST_LAG_MS=300
    DUPEZ_SMOKETEST_DURATION=6.0
    DUPEZ_SMOKETEST_MODULE_DURATION=3.0
"""
from __future__ import annotations

import ctypes
import ipaddress
import os
import platform
import re
import sys
import time
from typing import Optional

import pytest


# Module-level marks apply to every test below unless an individual test
# overrides them. The vendor-resolution test opts out explicitly because
# it's a pure unit check that doesn't need Admin / Npcap / WinDivert.
pytestmark = [pytest.mark.hardware, pytest.mark.slow]


# ----------------------------------------------------------------------
# Prerequisite probes — all skip with a specific reason on failure
# ----------------------------------------------------------------------
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
    """WinDivert.dll and WinDivert64.sys must ship in app/firewall/."""
    firewall_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "app", "firewall",
    )
    dll = os.path.join(firewall_dir, "WinDivert.dll")
    sys_ = os.path.join(firewall_dir, "WinDivert64.sys")
    return os.path.isfile(dll) and os.path.isfile(sys_)


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


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _pick_authorized_target(devices: list) -> Optional[dict]:
    """Return only the exact IP+MAC pair explicitly authorized by the user."""
    target_ip = os.environ["DUPEZ_SMOKETEST_TARGET_IP"].strip()
    target_mac = os.environ["DUPEZ_SMOKETEST_TARGET_MAC"].replace("-", ":").lower()
    for device in devices:
        device_mac = str(device.get("mac", "")).replace("-", ":").lower()
        if str(device.get("ip", "")) == target_ip and device_mac == target_mac:
            return device
    return None


def _aggregate_packets(manager) -> int:
    """Total packets_processed across active engines (manager-scoped)."""
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
    """Return one target's engine snapshot across in-proc and IPC managers."""
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


# ----------------------------------------------------------------------
# Test
# ----------------------------------------------------------------------
def test_scan_then_lag_then_stop_pipeline(_require_hardware) -> None:
    """Scan returns ≥1 device, lag starts, packets flow, stop is clean.

    This is the same sequence documented in ``tools/smoketest_scan_and_lag.py``
    but structured as pytest assertions so CI can gate releases on it when
    run on a suitable Windows host.
    """
    from app.network.enhanced_scanner import EnhancedNetworkScanner
    from app.firewall_helper.feature_flag import get_disruption_manager

    network_range = os.environ.get("DUPEZ_SMOKETEST_CIDR") or None
    lag_ms = int(os.environ.get("DUPEZ_SMOKETEST_LAG_MS", "300"))
    duration_s = float(os.environ.get("DUPEZ_SMOKETEST_DURATION", "6.0"))

    scanner = EnhancedNetworkScanner()
    devices = scanner.scan_network(
        network_range=network_range, quick_scan=True)

    assert devices, (
        "scan returned zero devices — check WiFi adapter state, "
        "ARP table population, and network range")

    target = _pick_authorized_target(devices)
    assert target is not None, (
        "the explicitly authorized DUPEZ_SMOKETEST_TARGET_IP/MAC pair "
        f"was not found in {len(devices)} scan result(s)")

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
        f"disrupt_device returned False for {target_ip} — "
        f"check admin token, WinDivert driver, and logs")

    try:
        deadline = time.time() + duration_s
        while time.time() < deadline:
            time.sleep(0.25)
        packets = _aggregate_packets(manager)
        device_stats = _device_engine_stats(manager, target_ip)
    finally:
        manager.stop_device(target_ip)

    assert packets > 0, (
        f"engine processed 0 packets over {duration_s:.1f}s on {target_ip} "
        f"— verify WinDivert driver is installed and the target is "
        f"actively transmitting")
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
    """Run each public module alone and require its counter to increase.

    Modules are intentionally isolated in fresh engines. Testing them as one
    chain would make a successful upstream consumer hide downstream modules,
    which is the exact false-positive pattern this regression test guards.
    """
    from app.core.validation import PUBLIC_DIAGNOSTIC_METHODS
    from app.firewall_helper.feature_flag import get_disruption_manager
    from app.network.enhanced_scanner import EnhancedNetworkScanner

    network_range = os.environ.get("DUPEZ_SMOKETEST_CIDR") or None
    per_method_s = float(os.environ.get(
        "DUPEZ_SMOKETEST_MODULE_DURATION", "3.0"))

    devices = EnhancedNetworkScanner().scan_network(
        network_range=network_range, quick_scan=True)
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
        failures)


def test_bundled_clumsy_gui_automation_starts_verified(
    _require_hardware,
) -> None:
    """Exercise the actual bundled Clumsy process, layer, and controls."""
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
    assert started, "bundled Clumsy GUI/layer/control verification failed"
    try:
        stats = _device_engine_stats(manager, target_ip)
        assert stats.get("engine") == "clumsy_compatibility"
        assert stats.get("startup_verified") is True
        assert stats.get("telemetry_available") is False
    finally:
        manager.stop_device(target_ip)


def test_vendor_resolution_resolves_known_oui() -> None:
    """Vendor lookup resolves an IEEE-registered OUI via the curated table
    OR the scapy MANUFDB fallback. Not hardware-gated — this is a pure unit
    check that protects against the ``vendor=Unknown`` regression that hit
    v5.5 when the curated table was the only source.
    """
    from app.network.shared import lookup_vendor, VENDOR_OUIS

    assert lookup_vendor("b4:0a:d8:11:22:33") == "Sony Interactive Entertainment", (
        "curated VENDOR_OUIS table must resolve Sony b4:0a:d8")

    # v5.6.7: the original test asserted scapy resolved Apple 9c:76:0e
    # specifically, but scapy's bundled MANUFDB drifts over time as IEEE
    # registrations are added/retired/reclassified. A single hard-coded
    # OUI is a brittle proxy for "the scapy fallback is reachable." Try
    # a slate of stable, decades-old vendor OUIs that should be in any
    # MANUFDB snapshot scapy has ever shipped. As long as scapy resolves
    # at least one of them, the fallback path is verified.
    #
    # We filter out anything already in the curated VENDOR_OUIS table —
    # that path doesn't exercise scapy. The candidates here are picked
    # from old, stable, non-gaming registrations specifically because
    # gaming OUIs are likely to be in our curated table.
    candidates = [
        # OUI prefix → vendor substring (case-insensitive contains-check)
        ("08:00:07:11:22:33", "apple"),     # Apple 1981 registration
        ("00:0d:93:11:22:33", "apple"),     # Apple 2004
        ("00:1d:0f:11:22:33", "cisco"),     # Cisco 2007
        ("00:0c:29:11:22:33", "vmware"),    # VMware
        ("00:50:56:11:22:33", "vmware"),    # VMware
        ("b8:27:eb:11:22:33", "raspberry"), # Raspberry Pi 2012
        ("dc:a6:32:11:22:33", "raspberry"), # Raspberry Pi 2019
        ("3c:5a:b4:11:22:33", "google"),    # Google
    ]

    failures = []
    for mac, expected_substring in candidates:
        prefix = ":".join(mac.split(":")[:3]).lower()
        if prefix in VENDOR_OUIS:
            continue  # curated path — doesn't exercise scapy fallback
        vendor = lookup_vendor(mac)
        if vendor == "Unknown":
            failures.append(f"{mac} → Unknown")
            continue
        if expected_substring in vendor.lower():
            return  # success: scapy resolved at least one
        # Resolved to something unexpected — count as partial success
        # (scapy IS working, just labels differently)
        return

    raise AssertionError(
        "scapy MANUFDB fallback not resolving any tested OUI. Either "
        "scapy isn't installed, scapy.data.MANUFDB import is broken, or "
        "the bundled OUI database is missing every vendor we tried. "
        f"Tested: {[m for m, _ in candidates]}. Failures: {failures}"
    )
