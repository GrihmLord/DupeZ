# app/network/device_scan.py

import socket
import threading
import time
import platform
import queue
import weakref
import sys
import traceback
import struct
import select
from typing import List, Dict, Optional, Set
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from contextlib import contextmanager
from app.logs.logger import log_info, log_error

# Global error handler for network scanning
def handle_network_error(func):
    """Decorator to handle errors in network scanning functions"""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            error_msg = f"Network scan error in {func.__name__}: {e}"
            log_error(error_msg)
            
            # Write to network error log
            try:
                with open('logs/network_errors.log', 'a', encoding='utf-8') as f:
                    f.write(f"\n{'='*60}\n")
                    f.write(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write(f"Function: {func.__name__}\n")
                    f.write(f"Error: {e}\n")
                    f.write(f"Traceback:\n{traceback.format_exc()}\n")
                    f.write(f"{'='*60}\n")
            except Exception as log_error:
                pass  # Don't let logging errors cause more issues
            
            # Return safe defaults
            if func.__name__ in ['ping_host_advanced', 'get_mac_address_safe']:
                return None
            elif func.__name__ in ['scan_network_range_advanced', 'scan_devices']:
                return []
            elif func.__name__ in ['get_network_info']:
                return {}
            else:
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
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(self.port_timeout)
                    result = sock.connect_ex((ip, port))
                    sock.close()
                    if result == 0:
                        return True
                except:
                    continue
            
            # Try ICMP ping as fallback (Windows only)
            if platform.system().lower() == "windows":
                return self._icmp_ping_windows(ip)
            
            return False
            
        except Exception as e:
            log_error(f"Native ping error for {ip}: {e}")
            return False
    
    def _icmp_ping_windows(self, ip: str) -> bool:
        """Windows-specific ICMP ping using raw sockets"""
        try:
            # Create raw socket for ICMP
            sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
            sock.settimeout(self.icmp_timeout)
            
            # Create ICMP echo request packet
            icmp_type = 8  # Echo request
            icmp_code = 0
            icmp_checksum = 0
            icmp_id = 12345
            icmp_seq = 1
            
            # Build ICMP header
            icmp_header = struct.pack('!BBHHH', icmp_type, icmp_code, icmp_checksum, icmp_id, icmp_seq)
            icmp_data = b'DupeZ Ping'
            
            # Calculate checksum
            icmp_checksum = self._calculate_checksum(icmp_header + icmp_data)
            icmp_header = struct.pack('!BBHHH', icmp_type, icmp_code, icmp_checksum, icmp_id, icmp_seq)
            
            # Send packet
            sock.sendto(icmp_header + icmp_data, (ip, 0))
            
            # Wait for response
            try:
                data, addr = sock.recvfrom(1024)
                sock.close()
                return True
            except socket.timeout:
                sock.close()
                return False
                
        except Exception as e:
            log_error(f"ICMP ping error for {ip}: {e}")
            return False
    
    def _calculate_checksum(self, data: bytes) -> int:
        """Calculate ICMP checksum"""
        if len(data) % 2 == 1:
            data += b'\0'
        
        sum = 0
        for i in range(0, len(data), 2):
            sum += (data[i] << 8) + data[i + 1]
        
        sum = (sum >> 16) + (sum & 0xffff)
        sum += sum >> 16
        return ~sum & 0xffff
    
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
        """Get MAC from Windows ARP cache using registry or WMI"""
        try:
            # Try to read from registry first
            import winreg
            try:
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, 
                                   r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces")
                
                for i in range(winreg.QueryInfoKey(key)[0]):
                    try:
                        subkey_name = winreg.EnumKey(key, i)
                        subkey = winreg.OpenKey(key, subkey_name)
                        
                        # Look for ARP entries
                        try:
                            arp_data, _ = winreg.QueryValueEx(subkey, "ArpCacheLife")
                            # Parse ARP data for the target IP
                            # This is simplified - in practice you'd need to parse the binary data
                        except:
                            pass
                        finally:
                            winreg.CloseKey(subkey)
                    except:
                        continue
                winreg.CloseKey(key)
            except:
                pass
            
            # Fallback: return None (will be handled by caller)
            return None
            
        except Exception as e:
            log_error(f"Windows ARP lookup error for {ip}: {e}")
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
        """Get all IPs from Windows ARP cache"""
        found_ips = []
        try:
            # Try to get from registry or use a simple network scan
            # For now, return empty list to avoid complexity
            # In a full implementation, you'd parse the Windows ARP cache
            return found_ips
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
    """Manages network resources and prevents resource exhaustion"""
    
    def __init__(self):
        self._socket_pool = queue.Queue(maxsize=50)
        self._active_sockets = weakref.WeakSet()
        self._lock = threading.RLock()
        self._max_concurrent = 10
        self._semaphore = threading.Semaphore(10)
    
    @contextmanager
    def get_socket(self):
        """Get a socket from pool or create new one"""
        socket_obj = None
        try:
            # Try to get from pool
            try:
                socket_obj = self._socket_pool.get_nowait()
            except queue.Empty:
                socket_obj = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            
            self._active_sockets.add(socket_obj)
            yield socket_obj
        except Exception as e:
            log_error(f"Socket error: {e}")
            raise
        finally:
            if socket_obj:
                try:
                    socket_obj.close()
                except:
                    pass
                self._active_sockets.discard(socket_obj)

# Global resource manager
_resource_manager = ResourceManager()

# Cache for device information with memory management
_device_cache = {}
_cache_timestamp = 0
CACHE_DURATION = 60  # Increased for stability
_cache_lock = threading.RLock()

# Thread management
_executor = None
_max_workers = 5  # Very conservative for stability

def get_executor():
    """Get thread pool executor with proper management"""
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=_max_workers, thread_name_prefix="NetworkScanner")
    return _executor

def cleanup_executor():
    """Clean up thread pool executor"""
    global _executor
    if _executor:
        _executor.shutdown(wait=False)
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
    """Get vendor information from MAC address (simplified)"""
    if not mac:
        return "Unknown"
    
    # Extract OUI (first 6 characters)
    oui = mac.replace(":", "").replace("-", "")[:6].upper()
    
    # Common vendor OUIs (including gaming devices)
    vendors = {
        "000C29": "VMware",
        "001A11": "Google",
        "002272": "American Micro-Fuel Device Corp",
        "00037F": "Tektronix",
        "000C41": "Cisco",
        "001122": "Xerox",
        "AABBCC": "Unknown",
        # Gaming devices
        "001B63": "Sony PlayStation",
        "001B64": "Sony PlayStation",
        "001B65": "Sony PlayStation",
        "001B66": "Sony PlayStation",
        "001B67": "Sony PlayStation",
        "001B68": "Sony PlayStation",
        "001B69": "Sony PlayStation",
        "001B6A": "Sony PlayStation",
        "001B6B": "Sony PlayStation",
        "001B6C": "Sony PlayStation",
        "001B6D": "Sony PlayStation",
        "001B6E": "Sony PlayStation",
        "001B6F": "Sony PlayStation",
        "001B70": "Sony PlayStation",
        "001B71": "Sony PlayStation",
        "001B72": "Sony PlayStation",
        "001B73": "Sony PlayStation",
        "001B74": "Sony PlayStation",
        "001B75": "Sony PlayStation",
        "001B76": "Sony PlayStation",
        "001B77": "Sony PlayStation",
        "001B78": "Sony PlayStation",
        "001B79": "Sony PlayStation",
        "001B7A": "Sony PlayStation",
        "001B7B": "Sony PlayStation",
        "001B7C": "Sony PlayStation",
        "001B7D": "Sony PlayStation",
        "001B7E": "Sony PlayStation",
        "001B7F": "Sony PlayStation",
        "001B80": "Sony PlayStation",
        "001B81": "Sony PlayStation",
        "001B82": "Sony PlayStation",
        "001B83": "Sony PlayStation",
        "001B84": "Sony PlayStation",
        "001B85": "Sony PlayStation",
        "001B86": "Sony PlayStation",
        "001B87": "Sony PlayStation",
        "001B88": "Sony PlayStation",
        "001B89": "Sony PlayStation",
        "001B8A": "Sony PlayStation",
        "001B8B": "Sony PlayStation",
        "001B8C": "Sony PlayStation",
        "001B8D": "Sony PlayStation",
        "001B8E": "Sony PlayStation",
        "001B8F": "Sony PlayStation",
        "001B90": "Sony PlayStation",
        "001B91": "Sony PlayStation",
        "001B92": "Sony PlayStation",
        "001B93": "Sony PlayStation",
        "001B94": "Sony PlayStation",
        "001B95": "Sony PlayStation",
        "001B96": "Sony PlayStation",
        "001B97": "Sony PlayStation",
        "001B98": "Sony PlayStation",
        "001B99": "Sony PlayStation",
        "001B9A": "Sony PlayStation",
        "001B9B": "Sony PlayStation",
        "001B9C": "Sony PlayStation",
        "001B9D": "Sony PlayStation",
        "001B9E": "Sony PlayStation",
        "001B9F": "Sony PlayStation",
        "001BA0": "Sony PlayStation",
        "001BA1": "Sony PlayStation",
        "001BA2": "Sony PlayStation",
        "001BA3": "Sony PlayStation",
        "001BA4": "Sony PlayStation",
        "001BA5": "Sony PlayStation",
        "001BA6": "Sony PlayStation",
        "001BA7": "Sony PlayStation",
        "001BA8": "Sony PlayStation",
        "001BA9": "Sony PlayStation",
        "001BAA": "Sony PlayStation",
        "001BAB": "Sony PlayStation",
        "001BAC": "Sony PlayStation",
        "001BAD": "Sony PlayStation",
        "001BAE": "Sony PlayStation",
        "001BAF": "Sony PlayStation",
        "001BB0": "Sony PlayStation",
        "001BB1": "Sony PlayStation",
        "001BB2": "Sony PlayStation",
        "001BB3": "Sony PlayStation",
        "001BB4": "Sony PlayStation",
        "001BB5": "Sony PlayStation",
        "001BB6": "Sony PlayStation",
        "001BB7": "Sony PlayStation",
        "001BB8": "Sony PlayStation",
        "001BB9": "Sony PlayStation",
        "001BBA": "Sony PlayStation",
        "001BBB": "Sony PlayStation",
        "001BBC": "Sony PlayStation",
        "001BBD": "Sony PlayStation",
        "001BBE": "Sony PlayStation",
        "001BBF": "Sony PlayStation",
        "001BC0": "Sony PlayStation",
        "001BC1": "Sony PlayStation",
        "001BC2": "Sony PlayStation",
        "001BC3": "Sony PlayStation",
        "001BC4": "Sony PlayStation",
        "001BC5": "Sony PlayStation",
        "001BC6": "Sony PlayStation",
        "001BC7": "Sony PlayStation",
        "001BC8": "Sony PlayStation",
        "001BC9": "Sony PlayStation",
        "001BCA": "Sony PlayStation",
        "001BCB": "Sony PlayStation",
        "001BCC": "Sony PlayStation",
        "001BCD": "Sony PlayStation",
        "001BCE": "Sony PlayStation",
        "001BCF": "Sony PlayStation",
        "001BD0": "Sony PlayStation",
        "001BD1": "Sony PlayStation",
        "001BD2": "Sony PlayStation",
        "001BD3": "Sony PlayStation",
        "001BD4": "Sony PlayStation",
        "001BD5": "Sony PlayStation",
        "001BD6": "Sony PlayStation",
        "001BD7": "Sony PlayStation",
        "001BD8": "Sony PlayStation",
        "001BD9": "Sony PlayStation",
        "001BDA": "Sony PlayStation",
        "001BDB": "Sony PlayStation",
        "001BDC": "Sony PlayStation",
        "001BDD": "Sony PlayStation",
        "001BDE": "Sony PlayStation",
        "001BDF": "Sony PlayStation",
        "001BE0": "Sony PlayStation",
        "001BE1": "Sony PlayStation",
        "001BE2": "Sony PlayStation",
        "001BE3": "Sony PlayStation",
        "001BE4": "Sony PlayStation",
        "001BE5": "Sony PlayStation",
        "001BE6": "Sony PlayStation",
        "001BE7": "Sony PlayStation",
        "001BE8": "Sony PlayStation",
        "001BE9": "Sony PlayStation",
        "001BEA": "Sony PlayStation",
        "001BEB": "Sony PlayStation",
        "001BEC": "Sony PlayStation",
        "001BED": "Sony PlayStation",
        "001BEE": "Sony PlayStation",
        "001BEF": "Sony PlayStation",
        "001BF0": "Sony PlayStation",
        "001BF1": "Sony PlayStation",
        "001BF2": "Sony PlayStation",
        "001BF3": "Sony PlayStation",
        "001BF4": "Sony PlayStation",
        "001BF5": "Sony PlayStation",
        "001BF6": "Sony PlayStation",
        "001BF7": "Sony PlayStation",
        "001BF8": "Sony PlayStation",
        "001BF9": "Sony PlayStation",
        "001BFA": "Sony PlayStation",
        "001BFB": "Sony PlayStation",
        "001BFC": "Sony PlayStation",
        "001BFD": "Sony PlayStation",
        "001BFE": "Sony PlayStation",
        "001BFF": "Sony PlayStation",
        # Microsoft Xbox
        "001B63": "Microsoft Xbox",
        "001B64": "Microsoft Xbox",
        "001B65": "Microsoft Xbox",
        "001B66": "Microsoft Xbox",
        "001B67": "Microsoft Xbox",
        "001B68": "Microsoft Xbox",
        "001B69": "Microsoft Xbox",
        "001B6A": "Microsoft Xbox",
        "001B6B": "Microsoft Xbox",
        "001B6C": "Microsoft Xbox",
        "001B6D": "Microsoft Xbox",
        "001B6E": "Microsoft Xbox",
        "001B6F": "Microsoft Xbox",
        "001B70": "Microsoft Xbox",
        "001B71": "Microsoft Xbox",
        "001B72": "Microsoft Xbox",
        "001B73": "Microsoft Xbox",
        "001B74": "Microsoft Xbox",
        "001B75": "Microsoft Xbox",
        "001B76": "Microsoft Xbox",
        "001B77": "Microsoft Xbox",
        "001B78": "Microsoft Xbox",
        "001B79": "Microsoft Xbox",
        "001B7A": "Microsoft Xbox",
        "001B7B": "Microsoft Xbox",
        "001B7C": "Microsoft Xbox",
        "001B7D": "Microsoft Xbox",
        "001B7E": "Microsoft Xbox",
        "001B7F": "Microsoft Xbox",
        "001B80": "Microsoft Xbox",
        "001B81": "Microsoft Xbox",
        "001B82": "Microsoft Xbox",
        "001B83": "Microsoft Xbox",
        "001B84": "Microsoft Xbox",
        "001B85": "Microsoft Xbox",
        "001B86": "Microsoft Xbox",
        "001B87": "Microsoft Xbox",
        "001B88": "Microsoft Xbox",
        "001B89": "Microsoft Xbox",
        "001B8A": "Microsoft Xbox",
        "001B8B": "Microsoft Xbox",
        "001B8C": "Microsoft Xbox",
        "001B8D": "Microsoft Xbox",
        "001B8E": "Microsoft Xbox",
        "001B8F": "Microsoft Xbox",
        "001B90": "Microsoft Xbox",
        "001B91": "Microsoft Xbox",
        "001B92": "Microsoft Xbox",
        "001B93": "Microsoft Xbox",
        "001B94": "Microsoft Xbox",
        "001B95": "Microsoft Xbox",
        "001B96": "Microsoft Xbox",
        "001B97": "Microsoft Xbox",
        "001B98": "Microsoft Xbox",
        "001B99": "Microsoft Xbox",
        "001B9A": "Microsoft Xbox",
        "001B9B": "Microsoft Xbox",
        "001B9C": "Microsoft Xbox",
        "001B9D": "Microsoft Xbox",
        "001B9E": "Microsoft Xbox",
        "001B9F": "Microsoft Xbox",
        "001BA0": "Microsoft Xbox",
        "001BA1": "Microsoft Xbox",
        "001BA2": "Microsoft Xbox",
        "001BA3": "Microsoft Xbox",
        "001BA4": "Microsoft Xbox",
        "001BA5": "Microsoft Xbox",
        "001BA6": "Microsoft Xbox",
        "001BA7": "Microsoft Xbox",
        "001BA8": "Microsoft Xbox",
        "001BA9": "Microsoft Xbox",
        "001BAA": "Microsoft Xbox",
        "001BAB": "Microsoft Xbox",
        "001BAC": "Microsoft Xbox",
        "001BAD": "Microsoft Xbox",
        "001BAE": "Microsoft Xbox",
        "001BAF": "Microsoft Xbox",
        "001BB0": "Microsoft Xbox",
        "001BB1": "Microsoft Xbox",
        "001BB2": "Microsoft Xbox",
        "001BB3": "Microsoft Xbox",
        "001BB4": "Microsoft Xbox",
        "001BB5": "Microsoft Xbox",
        "001BB6": "Microsoft Xbox",
        "001BB7": "Microsoft Xbox",
        "001BB8": "Microsoft Xbox",
        "001BB9": "Microsoft Xbox",
        "001BBA": "Microsoft Xbox",
        "001BBB": "Microsoft Xbox",
        "001BBC": "Microsoft Xbox",
        "001BBD": "Microsoft Xbox",
        "001BBE": "Microsoft Xbox",
        "001BBF": "Microsoft Xbox",
        "001BC0": "Microsoft Xbox",
        "001BC1": "Microsoft Xbox",
        "001BC2": "Microsoft Xbox",
        "001BC3": "Microsoft Xbox",
        "001BC4": "Microsoft Xbox",
        "001BC5": "Microsoft Xbox",
        "001BC6": "Microsoft Xbox",
        "001BC7": "Microsoft Xbox",
        "001BC8": "Microsoft Xbox",
        "001BC9": "Microsoft Xbox",
        "001BCA": "Microsoft Xbox",
        "001BCB": "Microsoft Xbox",
        "001BCC": "Microsoft Xbox",
        "001BCD": "Microsoft Xbox",
        "001BCE": "Microsoft Xbox",
        "001BCF": "Microsoft Xbox",
        "001BD0": "Microsoft Xbox",
        "001BD1": "Microsoft Xbox",
        "001BD2": "Microsoft Xbox",
        "001BD3": "Microsoft Xbox",
        "001BD4": "Microsoft Xbox",
        "001BD5": "Microsoft Xbox",
        "001BD6": "Microsoft Xbox",
        "001BD7": "Microsoft Xbox",
        "001BD8": "Microsoft Xbox",
        "001BD9": "Microsoft Xbox",
        "001BDA": "Microsoft Xbox",
        "001BDB": "Microsoft Xbox",
        "001BDC": "Microsoft Xbox",
        "001BDD": "Microsoft Xbox",
        "001BDE": "Microsoft Xbox",
        "001BDF": "Microsoft Xbox",
        "001BE0": "Microsoft Xbox",
        "001BE1": "Microsoft Xbox",
        "001BE2": "Microsoft Xbox",
        "001BE3": "Microsoft Xbox",
        "001BE4": "Microsoft Xbox",
        "001BE5": "Microsoft Xbox",
        "001BE6": "Microsoft Xbox",
        "001BE7": "Microsoft Xbox",
        "001BE8": "Microsoft Xbox",
        "001BE9": "Microsoft Xbox",
        "001BEA": "Microsoft Xbox",
        "001BEB": "Microsoft Xbox",
        "001BEC": "Microsoft Xbox",
        "001BED": "Microsoft Xbox",
        "001BEE": "Microsoft Xbox",
        "001BEF": "Microsoft Xbox",
        "001BF0": "Microsoft Xbox",
        "001BF1": "Microsoft Xbox",
        "001BF2": "Microsoft Xbox",
        "001BF3": "Microsoft Xbox",
        "001BF4": "Microsoft Xbox",
        "001BF5": "Microsoft Xbox",
        "001BF6": "Microsoft Xbox",
        "001BF7": "Microsoft Xbox",
        "001BF8": "Microsoft Xbox",
        "001BF9": "Microsoft Xbox",
        "001BFA": "Microsoft Xbox",
        "001BFB": "Microsoft Xbox",
        "001BFC": "Microsoft Xbox",
        "001BFD": "Microsoft Xbox",
        "001BFE": "Microsoft Xbox",
        "001BFF": "Microsoft Xbox",
    }
    
    return vendors.get(oui, "Unknown")

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
        except:
            pass
        
        # Detect gaming devices by hostname patterns
        if hostname.lower() in ["ps5", "playstation", "playstation5", "sony"]:
            vendor = "Sony PlayStation"
        elif hostname.lower() in ["xbox", "xboxone", "xboxseries", "microsoft"]:
            vendor = "Microsoft Xbox"
        elif hostname.lower() in ["nintendo", "switch"]:
            vendor = "Nintendo Switch"
        
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
        
        # Add devices found via ARP table
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
        # Check cache first with proper locking
        with _cache_lock:
            current_time = time.time()
            if current_time - _cache_timestamp < CACHE_DURATION and _device_cache:
                log_info(f"Using cached device list ({len(_device_cache)} devices)")
                return list(_device_cache.values())
        
        local_ip = get_local_ip()
        network = ".".join(local_ip.split(".")[:-1])
        
        log_info(f"Scanning network: {network}.0/24")
        devices = scan_network_range_advanced(network, quick_scan=quick)
        
        # Update cache with proper locking
        with _cache_lock:
            _device_cache = {device["ip"]: device for device in devices}
            _cache_timestamp = current_time
        
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
