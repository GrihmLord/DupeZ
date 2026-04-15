"""Hardware-in-the-loop smoketest — mirrors ``tools/smoketest_scan_and_lag.py``.

Runs the full disruption pipeline end-to-end: scan → pick target → start lag
→ poll engine stats → stop. Asserts that every stage produces the expected
side-effects.

This test is gated behind the ``hardware`` marker and requires:
  * Windows host (``sys.platform == 'win32'``)
  * Administrator privileges (WinDivert kernel driver)
  * Npcap installed and operational
  * WinDivert driver present in ``app/firewall/``
  * At least one reachable device on the local network

Skips with a clear reason when any prerequisite is missing so it's safe to
invoke with ``pytest -m hardware`` from any environment.

Opt-in invocations:
    pytest -m hardware                            # run only this
    pytest -m "hardware and not slow"             # fast hardware checks
    pytest                                        # default excludes this

Environment overrides (optional):
    DUPEZ_SMOKETEST_CIDR=192.168.137.0/24
    DUPEZ_SMOKETEST_LAST_OCTET=42
    DUPEZ_SMOKETEST_LAG_MS=300
    DUPEZ_SMOKETEST_DURATION=6.0
"""
from __future__ import annotations

import ctypes
import os
import platform
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
    if not _is_windows():
        pytest.skip("hardware smoketest requires Windows")
    if not _is_admin():
        pytest.skip("hardware smoketest requires Administrator privileges")
    if not _windivert_bits_present():
        pytest.skip("WinDivert.dll / WinDivert64.sys missing from app/firewall/")


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _pick_target(devices: list, last_octet: Optional[int]) -> Optional[dict]:
    """Mirror of ``tools/smoketest_scan_and_lag.py::_pick_target``.

    Kept in sync with the CLI smoketest so failures here surface the same
    issue the CLI runner would hit.
    """
    if last_octet is not None:
        suffix = f".{last_octet}"
        for device in devices:
            if str(device.get("ip", "")).endswith(suffix):
                return device
        return None
    for device in devices:
        if device.get("is_console"):
            return device
    return devices[0] if devices else None


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
    last_octet_env = os.environ.get("DUPEZ_SMOKETEST_LAST_OCTET")
    last_octet = int(last_octet_env) if last_octet_env else None
    lag_ms = int(os.environ.get("DUPEZ_SMOKETEST_LAG_MS", "300"))
    duration_s = float(os.environ.get("DUPEZ_SMOKETEST_DURATION", "6.0"))

    scanner = EnhancedNetworkScanner()
    devices = scanner.scan_network(
        network_range=network_range, quick_scan=True)

    assert devices, (
        "scan returned zero devices — check WiFi adapter state, "
        "ARP table population, and network range")

    target = _pick_target(devices, last_octet)
    assert target is not None, (
        f"no device matched last_octet={last_octet} from "
        f"{len(devices)} scan result(s)")

    target_ip = target["ip"]
    manager = get_disruption_manager()

    started = manager.disrupt_device(
        target_ip,
        methods=["lag"],
        params={"lag_delay": lag_ms},
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
    finally:
        manager.stop_device(target_ip)

    assert packets > 0, (
        f"engine processed 0 packets over {duration_s:.1f}s on {target_ip} "
        f"— verify WinDivert driver is installed and the target is "
        f"actively transmitting")


def test_vendor_resolution_resolves_known_oui() -> None:
    """Vendor lookup resolves an IEEE-registered OUI via the curated table
    OR the scapy MANUFDB fallback. Not hardware-gated — this is a pure unit
    check that protects against the ``vendor=Unknown`` regression that hit
    v5.5 when the curated table was the only source.
    """
    from app.network.shared import lookup_vendor

    assert lookup_vendor("b4:0a:d8:11:22:33") == "Sony Interactive Entertainment", (
        "curated VENDOR_OUIS table must resolve Sony b4:0a:d8")

    apple_vendor = lookup_vendor("9c:76:0e:aa:bb:cc")
    assert apple_vendor != "Unknown", (
        "scapy MANUFDB fallback not loading — curated table alone can't "
        "resolve Apple 9c:76:0e. Check that scapy is installed and "
        "`scapy.data.MANUFDB` imports cleanly.")
