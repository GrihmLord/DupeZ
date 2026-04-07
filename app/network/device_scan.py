# app/network/device_scan.py

import socket
import threading
import time
import platform
import struct
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from contextlib import contextmanager
from app.logs.logger import log_info, log_error
from app.network.shared import VENDOR_OUIS, HOSTNAME_VENDORS, lookup_vendor

# Global error handler for network scanning
def handle_network_error(func):
    """Decorator to handle errors in network scanning functions"""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            error_msg = f"Network scan error in {func.__name__}: {e}"
            log_error(error_msg)

            return None
    return wrapper

# Professional native networking methods
class NativeNetworkScanner:
    """Professional network scanner using native Python methods"""

    def __init__(self):
        self.timeout = 0.5
        self.port_timeout = 0.3
        self.icmp_timeout = 0.5

    def ping_host_native(self, ip: str) -> bool:
        """Native ping using socket connections to common ports"""
        try:
            # Try common ports first (most reliable)
            common_ports = [80, 443, 22, 21, 23, 25, 53, 110, 143, 993, 995]

            for port in common_ports:
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                        sock.settimeout(self.port_timeout)
                        if sock.connect_ex((ip, port)) == 0:
                            return True
                except Exception:
                    continue

            # Try ICMP ping as fallback (Windows only)
            if platform.system().lower() == "windows":
                return self._icmp_ping_windows(ip)

            return False

        except Exception as e:
            log_error(f"Native ping error for {ip}: {e}")
            return False

    def _icmp_ping_windows(self, ip: str) -> bool:
        """Windows-specific ICMP ping using raw sockets."""
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
            sock.settimeout(self.icmp_timeout)

            # Build ICMP echo request
            icmp_header = struct.pack('!BBHHH', 8, 0, 0, 12345, 1)
            icmp_data = b'DupeZ Ping'
            checksum = self._calculate_checksum(icmp_header + icmp_data)
            icmp_header = struct.pack('!BBHHH', 8, 0, checksum, 12345, 1)

            sock.sendto(icmp_header + icmp_data, (ip, 0))
            sock.recvfrom(1024)
            return True
        except socket.timeout:
            return False
        except Exception as e:
            log_error(f"ICMP ping error for {ip}: {e}")
            return False
        finally:
            if sock:
                sock.close()

    def _calculate_checksum(self, data: bytes) -> int:
        """Calculate ICMP checksum"""
        if len(data) % 2 == 1:
            data += b'\0'

        checksum = 0
        for i in range(0, len(data), 2):
            checksum += (data[i] << 8) + data[i + 1]

        checksum = (checksum >> 16) + (checksum & 0xffff)
        checksum += checksum >> 16
        return ~checksum & 0xffff

    def get_mac_address_native(self, ip: str) -> Optional[str]:
        """Get MAC address using native ARP table lookup"""
        try:
            # Try to get from local ARP cache first
            mac = self._get_mac_from_arp_cache(ip)
            if mac:
                return mac

            # If not in cache, try to ping to populate ARP table
            if self.ping_host_native(ip):
                time.sleep(0.1)  # Give ARP table time to update
                return self._get_mac_from_arp_cache(ip)

            return None

        except Exception as e:
            log_error(f"Native MAC lookup error for {ip}: {e}")
            return None

    def _get_mac_from_arp_cache(self, ip: str) -> Optional[str]:
        """Read MAC address from local ARP cache"""
        try:
            # Read ARP table from /proc/net/arp (Linux) or registry (Windows)
            if platform.system().lower() == "windows":
                return self._get_mac_from_windows_arp(ip)
            else:
                return self._get_mac_from_linux_arp(ip)
        except Exception as e:
            log_error(f"ARP cache read error for {ip}: {e}")
            return None

    def _get_mac_from_windows_arp(self, ip: str) -> Optional[str]:
        """Get MAC from Windows ARP cache. Registry-based lookup not viable;
        the caller falls back to subprocess 'arp -a' when this returns None."""
        return None

    def _get_mac_from_linux_arp(self, ip: str) -> Optional[str]:
        """Get MAC from Linux ARP cache"""
        try:
            with open('/proc/net/arp', 'r') as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 4 and parts[0] == ip:
                        mac = parts[3]
                        if mac != '00:00:00:00:00:00' and mac != '<incomplete>':
                            return mac
            return None
        except Exception as e:
            log_error(f"Linux ARP lookup error for {ip}: {e}")
            return None

    def _get_windows_arp_ips(self) -> List[str]:
        """Get IPs from Windows ARP cache via 'arp -a' subprocess."""
        import subprocess, re, sys
        _NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
        try:
            result = subprocess.run(
                ["arp", "-a"], capture_output=True, text=True,
                timeout=5, creationflags=_NO_WINDOW,
            )
            # Parse lines like "  192.168.1.5          aa-bb-cc-dd-ee-ff     dynamic"
            ips = []
            for m in re.finditer(r'(\d+\.\d+\.\d+\.\d+)', result.stdout):
                ip = m.group(1)
                if not ip.startswith(('169.254.', '224.', '255.255.255.255', '0.0.0.0')):
                    ips.append(ip)
            return ips
        except Exception as e:
            log_error(f"Windows ARP IP scan error: {e}")
            return []

    def _get_linux_arp_ips(self) -> List[str]:
        """Get all IPs from Linux ARP cache"""
        found_ips = []
        try:
            with open('/proc/net/arp', 'r') as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 1:
                        ip = parts[0]
                        # Filter out broadcast and multicast addresses
                        if not ip.startswith(('169.254.', '224.', '255.255.255.255', '0.0.0.0')):
                            found_ips.append(ip)
            return found_ips
        except Exception as e:
            log_error(f"Linux ARP IP scan error: {e}")
            return []

# Global scanner instance
_native_scanner = NativeNetworkScanner()

# Advanced resource management
class ResourceManager:
    """Manages network resources and prevents resource exhaustion."""

    def __init__(self):
        self._semaphore = threading.Semaphore(10)

    @contextmanager
    def get_socket(self):
        """Create a TCP socket, yield it, and ensure cleanup."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            yield sock
        finally:
            try:
                sock.close()
            except Exception:
                pass

# Global resource manager
_resource_manager = ResourceManager()

# Cache for device information with memory management
_device_cache = {}
_cache_timestamp = 0
CACHE_DURATION = 60  # Increased for stability
_cache_lock = threading.RLock()

# Thread management
_executor = None
_executor_lock = threading.Lock()
_max_workers = 5  # Very conservative for stability

def get_executor():
    """Get thread pool executor with proper management (thread-safe)."""
    global _executor
    if _executor is None:
        with _executor_lock:
            if _executor is None:  # Double-check under lock
                _executor = ThreadPoolExecutor(max_workers=_max_workers, thread_name_prefix="NetworkScanner")
    return _executor

def cleanup_executor():
    """Clean up thread pool executor."""
    global _executor
    with _executor_lock:
        if _executor:
            _executor.shutdown(wait=True, cancel_futures=True)
            _executor = None

def get_local_ip() -> str:
    """Get local IP address"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"

@handle_network_error
def ping_host_advanced(ip: str, timeout: float = 0.5) -> bool:
    """Advanced host detection using native methods"""
    return _native_scanner.ping_host_native(ip)

@handle_network_error
def get_mac_address_safe(ip: str) -> Optional[str]:
    """Get MAC address using native methods"""
    return _native_scanner.get_mac_address_native(ip)

def get_vendor_info(mac: str) -> str:
    """Get vendor information from MAC address using shared OUI table."""
    return lookup_vendor(mac)

@handle_network_error
def scan_arp_table_safe() -> List[str]:
    """Scan ARP table using native methods"""
    found_ips = []
    try:
        # Use the native scanner to get ARP table
        if platform.system().lower() == "windows":
            found_ips = _native_scanner._get_windows_arp_ips()
        else:
            found_ips = _native_scanner._get_linux_arp_ips()

        log_info(f"Native ARP scan found {len(found_ips)} additional devices")
        return found_ips
    except Exception as e:
        log_error(f"Native ARP scan failed: {e}")
        return []

def scan_ip_batch(ip_list: List[str]) -> List[str]:
    """Scan a batch of IPs with proper resource management"""
    found_ips = []
    executor = get_executor()

    try:
        # Submit all IPs to thread pool
        future_to_ip = {
            executor.submit(ping_host_advanced, ip, 0.5): ip
            for ip in ip_list
        }

        # Collect results with timeout
        for future in as_completed(future_to_ip, timeout=30):
            ip = future_to_ip[future]
            try:
                if future.result():
                    found_ips.append(ip)
            except (TimeoutError, Exception) as e:
                log_error(f"Error scanning {ip}: {e}")
                continue

    except Exception as e:
        log_error(f"Batch scan error: {e}")

    return found_ips

def get_device_info_safe(ip: str, local_ip: str) -> Optional[Dict]:
    """Get device information with proper error handling"""
    try:
        mac = get_mac_address_safe(ip)
        vendor = get_vendor_info(mac) if mac else "Unknown"

        # Try to get hostname with timeout
        hostname = "Unknown"
        try:
            hostname = socket.getfqdn(ip)
            if hostname == ip:
                hostname = "Unknown"
        except Exception:
            pass

        # Detect gaming devices by hostname patterns
        vendor = HOSTNAME_VENDORS.get(hostname.lower(), vendor)

        device = {
            "ip": ip,
            "mac": mac or "Unknown",
            "vendor": vendor,
            "hostname": hostname,
            "local": ip == local_ip,
            "traffic": 0,
            "last_seen": time.strftime("%H:%M:%S")
        }

        log_info(f"Found device: {ip} ({vendor})")
        return device

    except Exception as e:
        log_error(f"Device info error for {ip}: {e}")
        return None

@handle_network_error
def scan_network_range_advanced(network: str, start: int = 1, end: int = 254, quick_scan: bool = False) -> List[Dict]:
    """Advanced network scanning with proper resource management"""
    devices = []
    local_ip = get_local_ip()
    found_ips = []

    try:
        # Determine scan range
        if quick_scan:
            scan_range = list(range(1, 255))
        else:
            scan_range = list(range(start, end + 1))

        # Scan in small batches to prevent resource exhaustion
        batch_size = 10  # Very small batches
        for i in range(0, len(scan_range), batch_size):
            batch = scan_range[i:i + batch_size]
            batch_ips = [f"{network}.{ip_num}" for ip_num in batch]

            # Scan batch
            batch_results = scan_ip_batch(batch_ips)
            found_ips.extend(batch_results)

            # Small delay between batches
            time.sleep(0.2)

        try:
            arp_ips = scan_arp_table_safe()
            for ip in arp_ips:
                if ip not in found_ips:
                    found_ips.append(ip)
        except Exception as e:
            log_error(f"ARP scan error: {e}")

        # Get device information in parallel with limits
        executor = get_executor()
        device_futures = []

        for ip in found_ips:
            future = executor.submit(get_device_info_safe, ip, local_ip)
            device_futures.append(future)

        # Collect device information with timeout
        for future in as_completed(device_futures, timeout=60):
            try:
                device = future.result()
                if device:
                    devices.append(device)
            except (TimeoutError, Exception) as e:
                log_error(f"Device info collection error: {e}")
                continue

        # Sort devices: local device first, then by IP
        devices.sort(key=lambda x: (not x["local"], socket.inet_aton(x["ip"])))

    except Exception as e:
        log_error(f"Advanced network scan error: {e}")

    return devices

@handle_network_error
def scan_devices(quick: bool = True) -> List[Dict]:
    """Main function to scan for devices on the network (with advanced caching)"""
    global _device_cache, _cache_timestamp

    try:
        current_time = time.time()
        with _cache_lock:
            if current_time - _cache_timestamp < CACHE_DURATION and _device_cache:
                log_info(f"Using cached device list ({len(_device_cache)} devices)")
                return list(_device_cache.values())

        local_ip = get_local_ip()
        network = ".".join(local_ip.split(".")[:-1])

        log_info(f"Scanning network: {network}.0/24")
        devices = scan_network_range_advanced(network, quick_scan=quick)

        with _cache_lock:
            _device_cache = {device["ip"]: device for device in devices}
            _cache_timestamp = time.time()  # Use actual completion time, not start time

        log_info(f"Scan complete. Found {len(devices)} device(s)")
        return devices

    except Exception as e:
        log_error(f"Network scan failed: {e}")
        return []

def scan_devices_full() -> List[Dict]:
    """Full network scan (no quick scan)"""
    return scan_devices(quick=False)

def get_network_info() -> Dict:
    """Get current network information"""
    try:
        local_ip = get_local_ip()
        network = ".".join(local_ip.split(".")[:-1])

        return {
            "local_ip": local_ip,
            "network": f"{network}.0/24",
            "gateway": f"{network}.1"
        }
    except Exception as e:
        log_error(f"Failed to get network info: {e}")
        return {}

def clear_cache():
    """Clear the device cache"""
    global _device_cache, _cache_timestamp
    with _cache_lock:
        _device_cache = {}
        _cache_timestamp = 0

def cleanup_resources():
    """Clean up all resources"""
    try:
        cleanup_executor()
        log_info("Network scan resources cleaned up")
    except Exception as e:
        log_error(f"Error cleaning up resources: {e}")

# DeviceScanner class for compatibility with tests
class DeviceScanner:
    """Device scanner class for compatibility with existing tests"""

    def __init__(self):
        self.timeout = 0.5
        self.max_threads = 10

    def scan_network(self, network: str, quick_scan: bool = True) -> List[Dict]:
        """Scan network for devices"""
        try:
            # Extract network base from CIDR notation
            if '/' in network:
                network = network.split('/')[0]

            # Use existing scan function
            return scan_devices(quick=quick_scan)
        except Exception as e:
            log_error(f"DeviceScanner scan error: {e}", exception=e)
            return []

    def _safe(self, label, fn, *args, default=None):
        try:
            return fn(*args)
        except Exception as e:
            log_error(f"DeviceScanner {label} error: {e}", exception=e)
            return default

    def get_device_by_ip(self, ip):
        return self._safe("get_device_by_ip", get_device_info_safe, ip, get_local_ip())
    def ping_host(self, ip):
        return self._safe("ping", ping_host_advanced, ip, self.timeout, default=False)
    def get_mac_address(self, ip):
        return self._safe("MAC lookup", get_mac_address_safe, ip)
    def get_vendor_info(self, mac):
        return self._safe("vendor lookup", get_vendor_info, mac, default="Unknown")
    def clear_cache(self):
        self._safe("cache clear", clear_cache)
    def cleanup(self):
        self._safe("cleanup", cleanup_resources)

