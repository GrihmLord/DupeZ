"""
Smoke test: WiFi device discovery → lag disruption → stop.

Run as Administrator on the Windows host where DupeZ will operate.
Requires: Npcap, WinDivert driver installed.

    python tools/smoketest_scan_and_lag.py --target-last-octet 42 --lag-ms 300 --duration 10

If --target-last-octet is omitted, it lags the first console device found
(Xbox/PlayStation/Switch/Nintendo match in the MAC OUI table).

Exit codes:
  0  — scan returned ≥1 device AND lag started AND stopped cleanly
  1  — scan found nothing on the current WiFi subnet
  2  — target not resolvable from scan results
  3  — disruption_manager.disrupt_device returned False
  4  — engine reported zero packets after --duration seconds (lag not landing)
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Optional

# Make the repo root importable whether invoked from repo root or elsewhere.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from app.network.enhanced_scanner import EnhancedNetworkScanner
from app.firewall_helper.feature_flag import get_disruption_manager


def _pick_target(devices: list[dict], last_octet: Optional[int]) -> Optional[dict]:
    if last_octet is not None:
        suffix = f".{last_octet}"
        for d in devices:
            ip = d.get("ip", "")
            if ip.endswith(suffix):
                return d
        return None
    for d in devices:
        if d.get("is_console"):
            return d
    return devices[0] if devices else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--network", default=None,
                    help="Optional CIDR filter (e.g. 192.168.137.0/24). "
                         "Default: no filter — returns every ARP entry.")
    ap.add_argument("--target-last-octet", type=int, default=None,
                    help="Pick device whose IP ends in this octet; else first console")
    ap.add_argument("--lag-ms", type=int, default=300,
                    help="Lag delay in milliseconds")
    ap.add_argument("--duration", type=float, default=10.0,
                    help="Seconds to hold the lag before stopping")
    args = ap.parse_args()

    scanner = EnhancedNetworkScanner()
    print(f"[SCAN] network={args.network or '<all ARP>'}")
    devices = scanner.scan_network(network_range=args.network, quick_scan=True)
    print(f"[SCAN] found {len(devices)} device(s)")
    for d in devices:
        tag = " [console]" if d.get("is_console") else ""
        ip = d.get("ip", "?")
        mac = d.get("mac", "?")
        host = d.get("hostname", "?") or "?"
        vendor = d.get("vendor", "?") or "?"
        print(f"  {ip:<16} {mac:<20} {host:<28} {vendor}{tag}")
    if not devices:
        print("[FAIL] scan empty — check WiFi adapter, ARP table, and network range")
        return 1

    target = _pick_target(devices, args.target_last_octet)
    if not target:
        print(f"[FAIL] no device matched last-octet={args.target_last_octet}")
        return 2
    target_ip = target["ip"]
    print(f"[TARGET] {target_ip}  mac={target.get('mac')}  "
          f"host={target.get('hostname','?')}  vendor={target.get('vendor','?')}")

    manager = get_disruption_manager()
    print(f"[LAG] starting lag={args.lag_ms}ms for {args.duration}s on {target_ip}")
    started = manager.disrupt_device(
        target_ip,
        methods=["lag"],
        params={"lag_delay": args.lag_ms},
        target_mac=target.get("mac"),
        target_hostname=target.get("hostname"),
    )
    if not started:
        print("[FAIL] disrupt_device returned False")
        return 3

    def _packet_count() -> int:
        """Return total packets_processed across active engines.

        get_engine_stats() returns the aggregated totals with keys from
        _STAT_KEYS (packets_processed, packets_dropped, packets_inbound, ...)
        plus a per_device map. Top-level packets_processed is what we want.
        """
        try:
            stats = manager.get_engine_stats() or {}
        except Exception:
            return 0
        if "packets_processed" in stats:
            return int(stats.get("packets_processed") or 0)
        # Fallback: sum per_device if present
        per = stats.get("per_device") or {}
        return sum(int(v.get("packets_processed") or 0)
                   for v in per.values() if isinstance(v, dict))

    t_end = time.time() + args.duration
    while time.time() < t_end:
        time.sleep(0.5)
        elapsed = args.duration - (t_end - time.time())
        print(f"  t={elapsed:4.1f}s packets={_packet_count()}")

    packets = _packet_count()

    print(f"[STOP] stopping lag on {target_ip} (final packets={packets})")
    manager.stop_device(target_ip)
    if packets == 0:
        print(f"[FAIL] engine processed 0 packets — lag did not intercept traffic. "
              f"Verify WinDivert driver and that {target_ip} is actively transmitting.")
        return 4

    print(f"[OK] lag landed: {packets} packets processed; pipeline verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
