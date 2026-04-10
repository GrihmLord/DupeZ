# app/network/device_scan.py
"""
Network device scanner using native Python methods.

Provides ARP-table lookups, ICMP ping, and TCP port probing for
device discovery on the local /24 subnet.  A thread pool handles
concurrent scanning with conservative resource limits.
"""

from __future__ import annotations

import functools
import platform
import re
import socket
import struct
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from contextlib import contextmanager
from typing import Any, Callable, Dict, List, Optional, TypeVar

from app.logs.logger import log_error, log_info
from app.network.shared import HOSTNAME_VENDORS, lookup_vendor
from app.utils.helpers import _NO_WINDOW, mask_ip

__all__ = [
    "F",
    "handle_network_error",
    "NativeNetworkScanner",
    "ResourceManager",
    "get_executor",
    "cleanup_executor",
    "get_local_ip",
    "ping_host_advanced",
    "get_mac_address_safe",
    "get_vendor_info",
    "scan_arp_table_safe",
    "scan_ip_batch",
    "get_device_info_safe",
    "scan_network_range_advanced",
    "scan_devices",
    "scan_devices_full",
    "get_network_info",
    "clear_cache",
    "cleanup_resources",
    "DeviceScanner",
]

F = TypeVar("F", bound=Callable[..., Any])

# ── Constants ────────────────────────────────────────────────────────
# Common TCP ports probed during host detection.
_PROBE_PORTS: List[int] = [80, 443, 22, 21, 23, 25, 53, 110, 143, 993, 995]
# Duration (seconds) that cached scan results remain valid.
CACHE_DURATION_S: int = 60
# Concurrent scanning limits.
_MAX_SCAN_WORKERS: int = 5
_MAX_CONCURRENT_SOCKETS: int = 10
# Batch size for IP sweep.
_SCAN_BATCH_SIZE: int = 10
# Pause between scan batches (seconds).
_SCAN_BATCH_PAUSE_S: float = 0.2
# ARP-table ping-then-retry delay (seconds).
_ARP_RETRY_DELAY_S: float = 0.1

# ── Error decorator ───────────────────────────────────────────────────

def handle_network_error(func: F) -> F:
    """Decorator: catch exceptions in network scanning functions.

    Logs the error with the function name and returns ``None``.
    """
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except Exception as e:
            log_error(f"Network scan error in {func.__name__}: {e}")
            return None
    return wrapper  # type: ignore[return-value]


# ── Native network scanner ────────────────────────────────────────────

class NativeNetworkScanner:
    """Native Python network scanner — no external tools required."""

    def __init__(self) -> None:
        self.timeout: float = 0.5
        self.port_timeout: float = 0.3
        self.icmp_timeout: float = 0.5

    # ── Host detection ────────────────────────────────────────────

    def ping_host_native(self, ip: str) -> bool:
        """Detect host via TCP port probing, with ICMP fallback on Windows."""
        try:
            for port in _PROBE_PORTS:
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                        sock.settimeout(self.port_timeout)
                        if sock.connect_ex((ip, port)) == 0:
                            return True
                except Exception:
                    continue

            if platform.system().lower() == "windows":
                return self._icmp_ping_windows(ip)

            return False
        except Exception as e:
            log_error(f"Native ping error for {mask_ip(ip)}: {e}")
            return False

    def _icmp_ping_windows(self, ip: str) -> bool:
        """Windows-specific ICMP ping using raw sockets."""
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
            sock.settimeout(self.icmp_timeout)

            icmp_header = struct.pack("!BBHHH", 8, 0, 0, 12345, 1)
            icmp_data = b"DupeZ Ping"
            checksum = self._calculate_checksum(icmp_header + icmp_data)
            icmp_header = struct.pack("!BBHHH", 8, 0, checksum, 12345, 1)

            sock.sendto(icmp_header + icmp_data, (ip, 0))
            sock.recvfrom(1024)
            return True
        except socket.timeout:
            return False
        except Exception as e:
            log_error(f"ICMP ping error for {mask_ip(ip)}: {e}")
            return False
        finally:
            if sock:
                sock.close()

    @staticmethod
    def _calculate_checksum(data: bytes) -> int:
        """Calculate ICMP checksum."""
        if len(data) % 2 == 1:
            data += b"\0"
        checksum = 0
        for i in range(0, len(data), 2):
            checksum += (data[i] << 8) + data[i + 1]
        checksum = (checksum >> 16) + (checksum & 0xFFFF)
        checksum += checksum >> 16
        return ~checksum & 0xFFFF

    # ── MAC address lookup ────────────────────────────────────────

    def get_mac_address_native(self, ip: str) -> Optional[str]:
        """Look up MAC address from the local ARP cache."""
        try:
            mac = self._get_mac_from_arp_cache(ip)
            if mac:
                return mac

            # Ping to populate ARP table, then retry
            if self.ping_host_native(ip):
                time.sleep(_ARP_RETRY_DELAY_S)
                return self._get_mac_from_arp_cache(ip)

            return None
        except Exception as e:
            log_error(f"Native MAC lookup error for {mask_ip(ip)}: {e}")
            return None

    def _get_mac_from_arp_cache(self, ip: str) -> Optional[str]:
        """Read MAC from the OS ARP cache."""
        try:
            if platform.system().lower() == "windows":
                return self._get_mac_from_windows_arp(ip)
            return self._get_mac_from_linux_arp(ip)
        except Exception as e:
            log_error(f"ARP cache read error for {mask_ip(ip)}: {e}")
            return None

    def _get_mac_from_windows_arp(self, ip: str) -> Optional[str]:
        """Windows ARP lookup — returns None (caller falls back to 'arp -a')."""
        return None

    def _get_mac_from_linux_arp(self, ip: str) -> Optional[str]:
        """Read MAC from /proc/net/arp on Linux."""
        try:
            with open("/proc/net/arp", "r") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 4 and parts[0] == ip:
                        mac = parts[3]
                        if mac not in ("00:00:00:00:00:00", "<incomplete>"):
                            return mac
            return None
        except Exception as e:
            log_error(f"Linux ARP lookup error for {mask_ip(ip)}: {e}")
            return None

    # ── ARP table IP enumeration ──────────────────────────────────

    _EXCLUDED_PREFIXES = ("169.254.", "224.", "255.255.255.255", "0.0.0.0")

    def _get_windows_arp_ips(self) -> List[str]:
        """Extract IPs from Windows ``arp -a`` output."""
        try:
            result = subprocess.run(
                ["arp", "-a"],
                capture_output=True, text=True, timeout=5,
                creationflags=_NO_WINDOW,
            )
            ips: List[str] = []
            for m in re.finditer(r"(\d+\.\d+\.\d+\.\d+)", result.stdout):
                ip = m.group(1)
                if not ip.startswith(self._EXCLUDED_PREFIXES):
                    ips.append(ip)
            return ips
        except Exception as e:
            log_error(f"Windows ARP IP scan error: {e}")
            return []

    def _get_linux_arp_ips(self) -> List[str]:
        """Extract IPs from /proc/net/arp on Linux."""
        found: List[str] = []
        try:
            with open("/proc/net/arp", "r") as f:
                for line in f:
                    parts = line.split()
                    if parts and not parts[0].startswith(self._EXCLUDED_PREFIXES):
                        found.append(parts[0])
            return found
        except Exception as e:
            log_error(f"Linux ARP IP scan error: {e}")
            return []


# ── Global scanner instance ───────────────────────────────────────────

_native_scanner = NativeNetworkScanner()


# ── Resource manager ──────────────────────────────────────────────────

class ResourceManager:
    """Manages TCP sockets to prevent resource exhaustion.

    Uses a semaphore to cap concurrent open sockets at *max_concurrent*,
    preventing file-descriptor exhaustion during large subnet scans.
    """

    def __init__(self, max_concurrent: int = 10) -> None:
        self._semaphore = threading.Semaphore(max_concurrent)

    @contextmanager
    def get_socket(self) -> None:
        """Yield a TCP socket, ensuring cleanup.

        Blocks if *max_concurrent* sockets are already open.
        """
        self._semaphore.acquire()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            yield sock
        finally:
            try:
                sock.close()
            except Exception:
                pass
            self._semaphore.release()


_resource_manager = ResourceManager()


# ── Device cache ──────────────────────────────────────────────────────

_device_cache: Dict[str, Dict] = {}
_cache_timestamp: float = 0.0
_cache_lock = threading.RLock()


# ── Thread pool ───────────────────────────────────────────────────────

_executor: Optional[ThreadPoolExecutor] = None
_executor_lock = threading.Lock()


def get_executor() -> ThreadPoolExecutor:
    """Return the shared thread pool, creating it if needed (thread-safe)."""
    global _executor
    if _executor is None:
        with _executor_lock:
            if _executor is None:
                _executor = ThreadPoolExecutor(
                    max_workers=_MAX_SCAN_WORKERS,
                    thread_name_prefix="NetworkScanner",
                )
    return _executor


def cleanup_executor() -> None:
    """Shut down the shared thread pool."""
    global _executor
    with _executor_lock:
        if _executor:
            _executor.shutdown(wait=True, cancel_futures=True)
            _executor = None


# ── Public scanning functions ─────────────────────────────────────────

def get_local_ip() -> str:
    """Return the local IPv4 address."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


@handle_network_error
def ping_host_advanced(ip: str, timeout: float = 0.5) -> bool:
    """Detect whether *ip* is reachable using native methods."""
    return _native_scanner.ping_host_native(ip)


@handle_network_error
def get_mac_address_safe(ip: str) -> Optional[str]:
    """Return MAC address for *ip*, or None."""
    return _native_scanner.get_mac_address_native(ip)


def get_vendor_info(mac: str) -> str:
    """Return vendor name for *mac* via shared OUI table."""
    return lookup_vendor(mac)


@handle_network_error
def scan_arp_table_safe() -> List[str]:
    """Return IPs from the local ARP table."""
    try:
        if platform.system().lower() == "windows":
            found = _native_scanner._get_windows_arp_ips()
        else:
            found = _native_scanner._get_linux_arp_ips()
        log_info(f"Native ARP scan found {len(found)} additional devices")
        return found
    except Exception as e:
        log_error(f"Native ARP scan failed: {e}")
        return []


def scan_ip_batch(ip_list: List[str]) -> List[str]:
    """Scan a batch of IPs concurrently.  Returns reachable IPs."""
    found: List[str] = []
    executor = get_executor()

    try:
        future_to_ip = {
            executor.submit(ping_host_advanced, ip, 0.5): ip
            for ip in ip_list
        }
        for future in as_completed(future_to_ip, timeout=30):
            ip = future_to_ip[future]
            try:
                if future.result():
                    found.append(ip)
            except (TimeoutError, Exception) as e:
                log_error(f"Error scanning {mask_ip(ip)}: {e}")
    except Exception as e:
        log_error(f"Batch scan error: {e}")

    return found


def get_device_info_safe(ip: str, local_ip: str) -> Optional[Dict]:
    """Build a device info dict for *ip*.  Returns None on failure."""
    try:
        mac = get_mac_address_safe(ip)
        vendor = get_vendor_info(mac) if mac else "Unknown"

        hostname = "Unknown"
        try:
            hostname = socket.getfqdn(ip)
            if hostname == ip:
                hostname = "Unknown"
        except Exception:
            pass

        # Override vendor from hostname patterns
        vendor = HOSTNAME_VENDORS.get(hostname.lower(), vendor)

        device: Dict = {
            "ip": ip,
            "mac": mac or "Unknown",
            "vendor": vendor,
            "hostname": hostname,
            "local": ip == local_ip,
            "traffic": 0,
            "last_seen": time.strftime("%H:%M:%S"),
        }

        log_info(f"Found device: {mask_ip(ip)} ({vendor})")
        return device
    except Exception as e:
        log_error(f"Device info error for {mask_ip(ip)}: {e}")
        return None


@handle_network_error
def scan_network_range_advanced(
    network: str, start: int = 1, end: int = 254, quick_scan: bool = False,
) -> List[Dict]:
    """Scan a /24 network range for devices."""
    devices: List[Dict] = []
    local_ip = get_local_ip()
    found_ips: List[str] = []

    try:
        scan_range = list(range(1, 255)) if quick_scan else list(range(start, end + 1))

        # Scan in small batches
        for i in range(0, len(scan_range), _SCAN_BATCH_SIZE):
            batch = scan_range[i : i + _SCAN_BATCH_SIZE]
            batch_ips = [f"{network}.{n}" for n in batch]
            found_ips.extend(scan_ip_batch(batch_ips))
            time.sleep(_SCAN_BATCH_PAUSE_S)

        # Supplement with ARP table
        try:
            arp_ips = scan_arp_table_safe()
            for ip in arp_ips:
                if ip not in found_ips:
                    found_ips.append(ip)
        except Exception as e:
            log_error(f"ARP scan error: {e}")

        # Gather device info in parallel
        executor = get_executor()
        futures = [
            executor.submit(get_device_info_safe, ip, local_ip)
            for ip in found_ips
        ]
        for future in as_completed(futures, timeout=60):
            try:
                device = future.result()
                if device:
                    devices.append(device)
            except (TimeoutError, Exception) as e:
                log_error(f"Device info collection error: {e}")

        devices.sort(key=lambda x: (not x["local"], socket.inet_aton(x["ip"])))

    except Exception as e:
        log_error(f"Advanced network scan error: {e}")

    return devices


@handle_network_error
def scan_devices(quick: bool = True) -> List[Dict]:
    """Main scan entry point with caching."""
    global _device_cache, _cache_timestamp

    try:
        current_time = time.time()
        with _cache_lock:
            if current_time - _cache_timestamp < CACHE_DURATION_S and _device_cache:
                log_info(f"Using cached device list ({len(_device_cache)} devices)")
                return list(_device_cache.values())

        local_ip = get_local_ip()
        network = ".".join(local_ip.split(".")[:-1])

        log_info(f"Scanning network: {network}.0/24")
        devices = scan_network_range_advanced(network, quick_scan=quick)

        with _cache_lock:
            _device_cache = {d["ip"]: d for d in devices}
            _cache_timestamp = time.time()

        log_info(f"Scan complete. Found {len(devices)} device(s)")
        return devices
    except Exception as e:
        log_error(f"Network scan failed: {e}")
        return []


def scan_devices_full() -> List[Dict]:
    """Full network scan (no quick mode)."""
    return scan_devices(quick=False)


def get_network_info() -> Dict:
    """Return basic local network information."""
    try:
        local_ip = get_local_ip()
        network = ".".join(local_ip.split(".")[:-1])
        return {
            "local_ip": local_ip,
            "network": f"{network}.0/24",
            "gateway": f"{network}.1",
        }
    except Exception as e:
        log_error(f"Failed to get network info: {e}")
        return {}


def clear_cache() -> None:
    """Clear the device cache."""
    global _device_cache, _cache_timestamp
    with _cache_lock:
        _device_cache = {}
        _cache_timestamp = 0.0


def cleanup_resources() -> None:
    """Release all scanner resources."""
    try:
        cleanup_executor()
        log_info("Network scan resources cleaned up")
    except Exception as e:
        log_error(f"Error cleaning up resources: {e}")


# ── DeviceScanner class (test compatibility) ──────────────────────────

class DeviceScanner:
    """Wrapper class for compatibility with existing tests."""

    def __init__(self) -> None:
        self.timeout: float = 0.5
        self.max_threads: int = 10

    def scan_network(self, network: str, quick_scan: bool = True) -> List[Dict]:
        """Scan *network* for devices."""
        try:
            if "/" in network:
                network = network.split("/")[0]
            return scan_devices(quick=quick_scan)
        except Exception as e:
            log_error(f"DeviceScanner scan error: {e}", exception=e)
            return []

    def _safe(self, label: str, fn, *args, default=None) -> Any:
        try:
            return fn(*args)
        except Exception as e:
            log_error(f"DeviceScanner {label} error: {e}", exception=e)
            return default

    def get_device_by_ip(self, ip: str) -> Optional[Dict]:
        return self._safe("get_device_by_ip", get_device_info_safe, ip, get_local_ip())

    def ping_host(self, ip: str) -> bool:
        return self._safe("ping", ping_host_advanced, ip, self.timeout, default=False)

    def get_mac_address(self, ip: str) -> Optional[str]:
        return self._safe("MAC lookup", get_mac_address_safe, ip)

    def get_vendor_info(self, mac: str) -> str:
        return self._safe("vendor lookup", get_vendor_info, mac, default="Unknown")

    def clear_cache(self) -> None:
        self._safe("cache clear", clear_cache)

    def cleanup(self) -> None:
        self._safe("cleanup", cleanup_resources)
