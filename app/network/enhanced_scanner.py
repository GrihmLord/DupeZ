#!/usr/bin/env python3
"""
Enhanced Network Scanner for DupeZ.

Provides ARP-first device discovery with MAC deduplication, console
detection (PlayStation, Xbox, Nintendo), and Qt signal integration
for real-time GUI updates.

NOTE: ``EnhancedNetworkScanner`` inherits ``QObject`` to expose Qt
signals.  This means it cannot be instantiated without a running
``QApplication``.  For headless/test use, call the module-level
scanning functions in ``device_scan.py`` instead.
"""

from __future__ import annotations

import ipaddress
import platform
import re
import socket
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from PyQt6.QtCore import QObject, pyqtSignal

from app.logs.logger import (
    log_device_detection,
    log_error,
    log_info,
    log_network_scan,
)
from app.network.shared import lookup_vendor
from app.utils.helpers import _NO_WINDOW, mask_ip

# RFC 1918 private ranges — module-level to avoid recreation per call
_PRIVATE_RANGES = [
    ipaddress.IPv4Network("192.168.0.0/16"),
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
]

_MAC_RE = re.compile(r"^([0-9a-fA-F]{2}[:-]){5}([0-9a-fA-F]{2})$")

__all__ = ["NetworkDevice", "EnhancedNetworkScanner"]


# ── Hostname enrichment helpers ─────────────────────────────────────
#
# These fire as the last-resort fallbacks when reverse DNS, getfqdn,
# and NetBIOS have all failed to return a usable name for a device.
# The goal is that the GUI "Hostname" column is NEVER blank or the
# literal string "Unknown" — every device shows SOMETHING the user
# can visually disambiguate, even if the label is synthesized.

def _mdns_lookup(ip: str, timeout: float = 0.6) -> str:
    """Best-effort mDNS / zeroconf reverse lookup.

    Many modern consumer devices — PS5, Xbox Series, Apple TV, HomePod,
    Chromecast, smart TVs — never answer traditional reverse DNS but
    DO answer mDNS on a local hotspot. If the optional ``zeroconf``
    library isn't installed, this returns "" silently so scans still
    work on minimal installs.
    """
    try:
        from zeroconf import Zeroconf  # type: ignore
    except Exception:
        return ""

    try:
        zc = Zeroconf()
        try:
            # Reverse PTR via zeroconf's address resolver
            info = zc.get_service_info("_services._dns-sd._udp.local.", ip)
            if info and info.server:
                name = info.server.rstrip(".")
                if name and name != ip:
                    return name
        finally:
            zc.close()
    except Exception:
        pass
    return ""


def _synthesize_hostname(ip: str, mac: str, vendor: str) -> str:
    """Build a readable fallback label when no real hostname resolved.

    Prefers ``<vendor-slug>-<mac-suffix>`` (e.g. ``Sony-abcdef`` for a
    PS5), falls back to ``<vendor-slug>-<last-ip-octet>``, and only
    uses a bare IP-derived label when vendor is also unknown. The
    label is ASCII-safe and short enough for a table column.
    """
    vendor_slug = ""
    if vendor and vendor.lower() not in ("unknown", ""):
        # First word of the vendor string, alphanumeric only.
        first = re.split(r"[\s,()./-]+", vendor.strip(), maxsplit=1)[0]
        vendor_slug = re.sub(r"[^A-Za-z0-9]", "", first)[:16]

    mac_suffix = ""
    if mac and _MAC_RE.match(mac):
        # Last 6 hex chars of the MAC, no separators.
        mac_suffix = re.sub(r"[^0-9a-fA-F]", "", mac).lower()[-6:]

    if vendor_slug and mac_suffix:
        return f"{vendor_slug}-{mac_suffix}"
    if vendor_slug:
        last_octet = ip.rsplit(".", 1)[-1] if "." in ip else ip
        return f"{vendor_slug}-{last_octet}"
    if mac_suffix:
        return f"device-{mac_suffix}"
    # Last resort: derive from IP. Not ideal but beats an empty cell.
    return f"device-{ip.replace('.', '-')}"


@dataclass
class NetworkDevice:
    """Rich network device descriptor."""

    ip: str
    mac: str
    hostname: str
    vendor: str
    device_type: str
    is_console: bool
    is_local: bool
    response_time: float
    ports: List[int]
    services: List[str]
    last_seen: float
    traffic_level: int
    connection_count: int
    status: str  # online, offline, blocked, suspicious


# ── Console / device-type lookup tables ───────────────────────────────

_CONSOLE_MAC_PREFIXES = [
    "b4:0a:d8", "b4:0a:d9", "b4:0a:da", "b4:0a:db",  # Sony PlayStation
    "0c:fe:45", "f8:d0:ac",                              # Sony PlayStation
    "7c:ed:8d", "98:de:d0", "60:45:bd",                  # Microsoft Xbox
]
_HOSTNAME_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [r"ps5", r"ps4", r"playstation", r"sony", r"psn",
              r"xbox", r"xboxone", r"nintendo", r"switch"]
]
_VENDOR_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [r"sony", r"playstation", r"microsoft.*xbox", r"nintendo"]
]

_CONSOLE_KW: Dict[str, str] = {
    "ps5": "PlayStation", "ps4": "PlayStation", "playstation": "PlayStation",
    "sony": "PlayStation", "xbox": "Xbox", "nintendo": "Nintendo",
    "switch": "Nintendo",
}

_DEVICE_KW: List[Tuple[List[str], str]] = [
    (["router", "gateway", "modem"], "Router/Gateway"),
    (["phone", "mobile", "android", "iphone"], "Mobile Device"),
    (["laptop", "desktop", "pc", "computer"], "Computer"),
    (["tv", "television", "smarttv"], "Smart TV"),
    (["xbox", "playstation", "nintendo", "switch"], "Gaming Console"),
    (["printer", "scanner"], "Printer/Scanner"),
    (["camera", "webcam"], "Camera"),
]

_SERVICE_NAMES: Dict[int, str] = {
    21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP",
    53: "DNS", 80: "HTTP", 110: "POP3", 143: "IMAP",
    443: "HTTPS", 993: "IMAPS", 995: "POP3S", 8080: "HTTP-Alt",
}


class EnhancedNetworkScanner(QObject):
    """ARP-first network scanner with Qt signal integration.

    Inherits QObject to expose pyqtSignals for GUI progress updates.
    """

    # Qt signals
    device_found = pyqtSignal(dict)
    scan_progress = pyqtSignal(int, int)
    scan_complete = pyqtSignal(list)
    scan_error = pyqtSignal(str)
    status_update = pyqtSignal(str)

    def __init__(self, max_threads: int = 20, timeout: int = 1) -> None:
        super().__init__()
        self.max_threads = max_threads
        self.timeout = timeout
        self.scan_results: List[Dict] = []
        self._scan_event = threading.Event()
        self.last_scan_time: float = 0.0

    # ── Scan-in-progress flag (thread-safe) ───────────────────────

    @property
    def scan_in_progress(self) -> bool:
        return self._scan_event.is_set()

    @scan_in_progress.setter
    def scan_in_progress(self, value: bool) -> None:
        self._scan_event.set() if value else self._scan_event.clear()

    # ── Main scan entry point ─────────────────────────────────────

    def scan_network(
        self,
        network_range: str = "192.168.1.0/24",
        quick_scan: bool = True,
    ) -> List[Dict]:
        """Scan network for devices with ARP-first strategy."""
        try:
            if sys.is_finalizing():
                log_error("Cannot scan during interpreter shutdown")
                return []

            self.scan_in_progress = True
            start_time = time.time()
            log_info("Starting enhanced network scan",
                     network_range=network_range, quick_scan=quick_scan)

            # ARP table is authoritative and instant
            arp_devices = self._scan_arp_table()
            log_info(f"ARP table: {len(arp_devices)} unique devices")

            # IP sweep only if ARP found nothing (avoids hotspot ghost IPs)
            if not arp_devices:
                log_info("ARP empty — falling back to IP sweep")
                ip_list = self._generate_ip_list(network_range)
                ip_devices = self._scan_ips(ip_list, quick_scan=True)
                all_devices = self._combine_device_lists([], ip_devices)
            else:
                all_devices = arp_devices

            all_devices = self._deduplicate_by_mac(all_devices)
            self._detect_console_devices(all_devices)

            scan_duration = time.time() - start_time
            console_count = sum(1 for d in all_devices if d.get("is_console"))

            log_network_scan(len(all_devices), scan_duration,
                             network_range=network_range, quick_scan=quick_scan)
            log_device_detection(console_count, len(all_devices),
                                 scan_duration=scan_duration)

            self.scan_results = all_devices
            self.last_scan_time = time.time()
            self.scan_in_progress = False

            try:
                self.scan_complete.emit(all_devices)
            except RuntimeError:
                pass

            return all_devices

        except Exception as e:
            self.scan_in_progress = False
            log_error("Network scan failed", exception=e,
                      network_range=network_range)
            try:
                self.scan_error.emit(str(e))
            except RuntimeError:
                pass
            return []

    # ── IP generation ─────────────────────────────────────────────

    def _get_local_ip(self) -> Optional[str]:
        """Return the local IPv4 address."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception as e:
            log_error("Failed to get local IP", exception=e)
            return None

    def _generate_ip_list(self, network_range: str) -> List[str]:
        """Generate host IPs from a CIDR range."""
        try:
            network = ipaddress.IPv4Network(network_range, strict=False)
            return [str(ip) for ip in network.hosts()]
        except Exception as e:
            log_error("Failed to generate IP list", exception=e)
            local_ip = self._get_local_ip()
            if local_ip:
                base = ".".join(local_ip.split(".")[:-1])
                return [f"{base}.{i}" for i in range(1, 255)]
            return []

    # ── IP scanning ───────────────────────────────────────────────

    def _scan_ips(self, ip_addresses: List[str], quick_scan: bool) -> List[Dict]:
        """Scan IPs via thread pool."""
        devices: List[Dict] = []
        try:
            if sys.is_finalizing():
                return devices

            with ThreadPoolExecutor(max_workers=self.max_threads) as executor:
                future_to_ip = {
                    executor.submit(self._scan_single_ip, ip, quick_scan): ip
                    for ip in ip_addresses
                }
                for future in as_completed(future_to_ip):
                    try:
                        result = future.result()
                        if result:
                            devices.append(result)
                    except Exception as e:
                        log_error(f"IP scan error: {e}")
        except RuntimeError as e:
            if "interpreter shutdown" in str(e):
                log_error("Thread pool failed: interpreter shutting down")
            else:
                log_error("Thread pool failed", exception=e)
        except Exception as e:
            log_error("Thread pool failed", exception=e)

        return devices

    def _scan_single_ip(self, ip: str, quick_scan: bool) -> Optional[Dict]:
        """Probe a single IP using multiple detection methods."""
        try:
            if not (self._ping_host(ip) or self._check_arp_table_for_ip(ip)
                    or self._quick_port_scan(ip) or self._check_dns_resolution(ip)):
                return None

            mac, hostname = self._get_device_info(ip)
            device = self._make_device_info(ip, mac, hostname, "multi_method")

            if not quick_scan:
                ports, services = self._scan_ports(ip)
                device["ports"] = ports
                device["services"] = services

            return device
        except Exception as e:
            log_error(f"Single IP scan error for {mask_ip(ip)}", exception=e)
            return None

    # ── Device info construction ──────────────────────────────────

    def _make_device_info(
        self, ip: str, mac: str = "Unknown",
        hostname: str = "Unknown", detection_method: str = "unknown",
    ) -> Dict:
        """Build a standard device-info dict with vendor/type enrichment."""
        vendor = lookup_vendor(mac)

        # Final hostname fallback: if reverse DNS, NetBIOS, and mDNS all
        # came up empty, synthesize a readable label from vendor + MAC
        # suffix (or IP as last resort) so the GUI Hostname column is
        # never blank or "Unknown". This is what lets PS5/Xbox/random
        # IoT boxes — which almost never answer reverse DNS on a
        # hotspot subnet — still show something meaningful to the user.
        if not hostname or hostname == "Unknown":
            hostname = _synthesize_hostname(ip, mac, vendor)

        info: Dict = {
            "ip": ip,
            "mac": mac,
            "hostname": hostname,
            "vendor": vendor,
            "device_type": "Unknown",
            "is_console": False,
            "is_local": self._is_local_device(ip),
            "response_time": 0.0,
            "ports": [],
            "services": [],
            "last_seen": time.time(),
            "traffic_level": 0,
            "connection_count": 0,
            "status": "online",
            "detection_method": detection_method,
        }
        info["is_console"] = self._is_console_device(info)
        info["device_type"] = self._determine_device_type(info)
        return info

    # ── Host detection helpers ────────────────────────────────────

    def _ping_host(self, ip: str) -> bool:
        """Ping *ip* using the system ping command."""
        try:
            if platform.system().lower() == "windows":
                cmd = ["ping", "-n", "1", "-w", str(self.timeout * 1000), ip]
                result = subprocess.run(
                    cmd, capture_output=True, text=True,
                    timeout=self.timeout + 1, creationflags=_NO_WINDOW,
                )
            else:
                cmd = ["ping", "-c", "1", "-W", str(self.timeout), ip]
                result = subprocess.run(
                    cmd, capture_output=True, text=True,
                    timeout=self.timeout + 1,
                )
            return result.returncode == 0
        except Exception:
            return False

    def _get_device_info(self, ip: str) -> Tuple[str, str]:
        """Return (mac, hostname) for *ip*.

        Hostname resolution is attempted through multiple channels in
        order; the first non-empty result wins. "" / "Unknown" / an IP
        literal are all treated as misses so later fallbacks can fire.

            1. ``socket.gethostbyaddr`` — reverse DNS via system resolver
            2. ``socket.getfqdn``       — alternate resolver code path
            3. NetBIOS (Windows)        — ``nbtstat -a`` <00> UNIQUE
            4. mDNS / zeroconf          — answers PS5/Xbox/Apple hotspots

        If all four miss, ``_make_device_info`` will synthesize a label
        from vendor + MAC suffix so the GUI column is never empty.
        """
        mac = "Unknown"
        hostname = "Unknown"

        try:
            # ARP lookup
            if platform.system().lower() == "windows":
                result = subprocess.run(
                    ["arp", "-a", ip], capture_output=True, text=True,
                    timeout=5, creationflags=_NO_WINDOW,
                )
            else:
                result = subprocess.run(
                    ["arp", "-n", ip], capture_output=True, text=True, timeout=5,
                )
            if result.returncode == 0:
                m = re.search(r"([0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}", result.stdout)
                if m:
                    mac = m.group(0)

            # 1. Reverse DNS
            try:
                name = socket.gethostbyaddr(ip)[0]
                if name and name != ip:
                    hostname = name
            except Exception:
                pass

            # 2. getfqdn (different resolver path — sometimes succeeds
            #    when gethostbyaddr fails on captive / hotspot subnets).
            if hostname == "Unknown":
                try:
                    name = socket.getfqdn(ip)
                    if name and name != ip and "." in name:
                        hostname = name
                except Exception:
                    pass

            # 3. NetBIOS fallback (Windows)
            if hostname == "Unknown" and platform.system().lower() == "windows":
                try:
                    nbt = subprocess.run(
                        ["nbtstat", "-a", ip], capture_output=True, text=True,
                        timeout=3, creationflags=_NO_WINDOW,
                    )
                    if nbt.returncode == 0:
                        for line in nbt.stdout.splitlines():
                            line = line.strip()
                            if "<00>" in line and "UNIQUE" in line:
                                name = line.split()[0].strip()
                                if name and name != ip:
                                    hostname = name
                                    break
                except Exception:
                    pass

            # 4. mDNS / zeroconf fallback — best effort, no-op if lib
            #    isn't installed. Consoles on a hotspot subnet (PS5,
            #    Xbox, Apple TV) announce themselves here even when
            #    reverse DNS / NetBIOS are silent.
            if hostname == "Unknown":
                name = _mdns_lookup(ip)
                if name:
                    hostname = name

        except Exception as e:
            log_error(f"Device info lookup failed for {mask_ip(ip)}", exception=e)

        return mac, hostname

    # ── Console detection ─────────────────────────────────────────

    def _is_console_device(self, device_info: Dict) -> bool:
        """Detect gaming consoles via MAC OUI, hostname, and vendor patterns."""
        try:
            mac_lower = device_info.get("mac", "").lower()
            hostname_lower = device_info.get("hostname", "").lower()
            vendor_lower = device_info.get("vendor", "").lower()

            for prefix in _CONSOLE_MAC_PREFIXES:
                if mac_lower.startswith(prefix):
                    return True
            for pat in _HOSTNAME_PATTERNS:
                if pat.search(hostname_lower):
                    return True
            for pat in _VENDOR_PATTERNS:
                if pat.search(vendor_lower):
                    return True
            return False
        except Exception:
            return False

    def _determine_device_type(self, device_info: Dict) -> str:
        """Classify device type from hostname/vendor keywords."""
        try:
            hostname = device_info.get("hostname", "").lower()
            vendor = device_info.get("vendor", "").lower()
            combined = hostname + " " + vendor

            if device_info.get("is_console"):
                for kw, dtype in _CONSOLE_KW.items():
                    if kw in combined:
                        return dtype
                return "Gaming Console"

            for words, dtype in _DEVICE_KW:
                if any(w in hostname for w in words):
                    return dtype

            return "Unknown Device"
        except Exception:
            return "Unknown Device"

    def _is_local_device(self, ip: str) -> bool:
        """Return True if *ip* is in a private RFC 1918 range."""
        try:
            return any(ipaddress.IPv4Address(ip) in net for net in _PRIVATE_RANGES)
        except Exception:
            return False

    def _detect_console_devices(self, devices: List[Dict]) -> List[Dict]:
        """Tag console devices in-place and return the console subset."""
        consoles: List[Dict] = []
        for d in devices:
            if self._is_console_device(d):
                d["is_console"] = True
                d["device_type"] = self._determine_device_type(d)
                consoles.append(d)
        return consoles

    # ── Port scanning ─────────────────────────────────────────────

    def _scan_ports(self, ip: str) -> Tuple[List[int], List[str]]:
        """Probe common ports on *ip*."""
        ports: List[int] = []
        services: List[str] = []
        for port in [21, 22, 23, 25, 53, 80, 110, 143, 443, 993, 995, 8080]:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(1)
                    if sock.connect_ex((ip, port)) == 0:
                        ports.append(port)
                        services.append(_SERVICE_NAMES.get(port, f"Unknown-{port}"))
            except Exception:
                pass
        return ports, services

    def _quick_port_scan(self, ip: str) -> bool:
        """Return True if any common port is open on *ip*."""
        for port in [80, 443, 22, 21, 23, 25, 53, 110, 143, 993, 995, 8080, 8443]:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(1)
                    if sock.connect_ex((ip, port)) == 0:
                        return True
            except Exception:
                continue
        return False

    def _check_dns_resolution(self, ip: str) -> bool:
        """Return True if *ip* has a reverse DNS entry."""
        try:
            return socket.gethostbyaddr(ip)[0] != ip
        except Exception:
            return False

    @staticmethod
    def _get_traffic_info(ip: str) -> Tuple[int, int]:
        """Placeholder for traffic monitoring (not yet implemented)."""
        return 0, 0

    # ── ARP table scanning ────────────────────────────────────────

    def _scan_arp_table(self) -> List[Dict]:
        """Parse ARP table, deduplicate by MAC (keep highest last-octet)."""
        mac_best: Dict[str, Tuple[str, str, int]] = {}  # mac_lower -> (ip, mac_raw, last_octet)

        try:
            if platform.system().lower() == "windows":
                result = subprocess.run(
                    ["arp", "-a"], capture_output=True, text=True,
                    timeout=5, creationflags=_NO_WINDOW,
                )
            else:
                result = subprocess.run(
                    ["arp", "-n"], capture_output=True, text=True, timeout=5,
                )

            if result.returncode != 0:
                return []

            for line in result.stdout.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("Interface:") or "---" in stripped:
                    continue
                if any(kw in stripped for kw in ("Internet", "Physical", "Address")):
                    continue

                parts = stripped.split()
                if len(parts) < 2:
                    continue

                if platform.system().lower() == "windows":
                    ip, mac_raw = parts[0], parts[1]
                else:
                    ip = parts[0]
                    mac_raw = parts[2] if len(parts) > 2 else "Unknown"

                if not self._is_valid_ip(ip) or not self._is_valid_mac(mac_raw):
                    continue

                mac_lower = mac_raw.replace("-", ":").lower()
                if mac_lower == "ff:ff:ff:ff:ff:ff":
                    continue
                # Skip multicast MACs
                try:
                    if int(mac_lower.split(":")[0], 16) & 1:
                        continue
                except (ValueError, IndexError):
                    pass

                try:
                    last_octet = int(ip.rsplit(".", 1)[1])
                except (ValueError, IndexError):
                    last_octet = 0

                if mac_lower not in mac_best or last_octet > mac_best[mac_lower][2]:
                    mac_best[mac_lower] = (ip, mac_raw, last_octet)

        except Exception as e:
            log_error("ARP table scan failed", exception=e)
            return []

        devices: List[Dict] = []
        for ip, mac_raw, _ in mac_best.values():
            try:
                dev = self._make_device_info(ip, mac_raw, detection_method="arp_table_fast")
                if dev:
                    devices.append(dev)
            except Exception as e:
                log_error(f"Failed to create device info for {mask_ip(ip)}", exception=e)

        log_info(f"ARP scan: {len(devices)} unique devices (deduped by MAC)")
        return devices

    # ── Deduplication ─────────────────────────────────────────────

    def _deduplicate_by_mac(self, devices: List[Dict]) -> List[Dict]:
        """Keep one entry per physical MAC address."""
        seen: set[str] = set()
        result: List[Dict] = []
        for d in devices:
            mac_raw = d.get("mac", "Unknown")
            if mac_raw == "Unknown":
                result.append(d)
                continue
            mac_lower = mac_raw.replace("-", ":").lower()
            if mac_lower in seen:
                continue
            seen.add(mac_lower)
            result.append(d)
        return result

    def _combine_device_lists(
        self, arp_devices: List[Dict], ip_devices: List[Dict],
    ) -> List[Dict]:
        """Merge two device lists, deduplicating by IP and MAC."""
        by_ip: Dict[str, Dict] = {}
        seen_macs: Dict[str, str] = {}

        def _add(device: Dict) -> None:
            ip = device.get("ip")
            if not ip:
                return
            mac_raw = device.get("mac", "Unknown")
            mac_lower = mac_raw.replace("-", ":").lower() if mac_raw != "Unknown" else None

            if mac_lower and mac_lower != "unknown" and mac_lower in seen_macs:
                if seen_macs[mac_lower] != ip:
                    return  # duplicate MAC under a different IP

            if ip not in by_ip:
                by_ip[ip] = device
                if mac_lower and mac_lower != "unknown":
                    seen_macs[mac_lower] = ip
            else:
                existing = by_ip[ip]
                for key, val in device.items():
                    if val != "Unknown" and existing.get(key) == "Unknown":
                        existing[key] = val

        for d in arp_devices:
            _add(d)
        for d in ip_devices:
            _add(d)
        return list(by_ip.values())

    # ── Validation helpers ────────────────────────────────────────

    @staticmethod
    def _is_valid_ip(ip: str) -> bool:
        try:
            socket.inet_aton(ip)
            return True
        except Exception:
            return False

    @staticmethod
    def _is_valid_mac(mac: str) -> bool:
        return bool(_MAC_RE.match(mac))

    # ── ARP cache (avoids per-IP subprocess) ──────────────────────

    _arp_cache_output: str = ""
    _arp_cache_time: float = 0.0
    _arp_cache_lock = threading.Lock()
    _ARP_CACHE_TTL: float = 10.0

    def _check_arp_table_for_ip(self, ip: str) -> bool:
        """Check if *ip* appears in the cached ARP output."""
        try:
            now = time.time()
            with self._arp_cache_lock:
                if now - self._arp_cache_time > self._ARP_CACHE_TTL or not self._arp_cache_output:
                    if platform.system().lower() == "windows":
                        result = subprocess.run(
                            ["arp", "-a"], capture_output=True, text=True,
                            timeout=5, creationflags=_NO_WINDOW,
                        )
                    else:
                        result = subprocess.run(
                            ["arp", "-n"], capture_output=True, text=True, timeout=5,
                        )
                    self._arp_cache_output = result.stdout if result.returncode == 0 else ""
                    self._arp_cache_time = now
                return ip in self._arp_cache_output
        except Exception:
            return False

    # ── GUI compatibility methods ─────────────────────────────────

    def start(self) -> None:
        """Start a scan in a background thread (GUI compat)."""
        try:
            self.scan_in_progress = True
            self.status_update.emit("Starting network scan...")
            t = threading.Thread(target=self._run_scan, daemon=True)
            t.start()
        except Exception as e:
            log_error(f"Error starting scan: {e}")
            self.scan_error.emit(f"Error starting scan: {e}")

    def stop_scan(self) -> None:
        """Stop the current scan."""
        self.scan_in_progress = False
        try:
            self.status_update.emit("Scan stopped")
        except RuntimeError:
            pass

    def _run_scan(self) -> None:
        """Background thread target for ``start()``."""
        try:
            devices = self.scan_network()
            if self.scan_in_progress:
                self.scan_complete.emit(devices)
                self.status_update.emit(f"Scan completed: {len(devices)} devices found")
        except Exception as e:
            log_error(f"Scan thread error: {e}")
            try:
                self.scan_error.emit(f"Scan error: {e}")
            except RuntimeError:
                pass
        finally:
            self.scan_in_progress = False

    # ── Query methods ─────────────────────────────────────────────

    def get_console_devices(self) -> List[Dict]:
        """Return console devices from last scan."""
        return [d for d in self.scan_results if d.get("is_console")]

    get_ps5_devices = get_console_devices  # legacy alias

    def get_device_by_ip(self, ip: str) -> Optional[Dict]:
        """Look up a device from last scan results."""
        return next((d for d in self.scan_results if d.get("ip") == ip), None)

    def is_scanning(self) -> bool:
        return self.scan_in_progress

    def get_scan_stats(self) -> Dict:
        """Return a stats summary of the last scan."""
        return {
            "total_devices": len(self.scan_results),
            "console_devices": len(self.get_console_devices()),
            "local_devices": sum(1 for d in self.scan_results if d.get("is_local")),
            "last_scan_time": self.last_scan_time,
            "scan_in_progress": self.scan_in_progress,
        }
