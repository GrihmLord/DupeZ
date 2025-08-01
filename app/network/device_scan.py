# app/network/device_scan.py

import subprocess
import re
import socket
import threading
import time
import platform
from typing import List, Dict, Optional
from app.logs.logger import log_info, log_error

# Cache for device information
_device_cache = {}
_cache_timestamp = 0
CACHE_DURATION = 30  # Reduced cache duration for faster updates

def get_local_ip() -> str:
    """Get the local IP address of this machine"""
    try:
        # Create a socket to get local IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception as e:
        log_error(f"Failed to get local IP: {e}")
        return "192.168.1.1"  # Fallback

def ping_host(ip: str, timeout: float = 0.05) -> bool:  # Ultra-fast timeout
    """Ping a single host to check if it's alive (optimized)"""
    try:
        if platform.system().lower() == "windows":
            result = subprocess.run(
                ["ping", "-n", "1", "-w", str(int(timeout * 1000)), ip],
                capture_output=True, text=True, timeout=timeout + 0.1
            )
        else:
            result = subprocess.run(
                ["ping", "-c", "1", "-W", str(int(timeout)), ip],
                capture_output=True, text=True, timeout=timeout + 0.1
            )
        return result.returncode == 0
    except Exception:
        return False

def get_mac_address(ip: str) -> Optional[str]:
    """Get MAC address for a given IP using ARP (optimized)"""
    try:
        if platform.system().lower() == "windows":
            result = subprocess.run(
                ["arp", "-a", ip], capture_output=True, text=True, timeout=1
            )
        else:
            result = subprocess.run(
                ["arp", "-n", ip], capture_output=True, text=True, timeout=1
            )
        
        # Parse MAC address from ARP output
        mac_pattern = r'([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})'
        match = re.search(mac_pattern, result.stdout)
        return match.group(0) if match else None
    except Exception:
        return None

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

def scan_network_range_fast(network: str, start: int = 1, end: int = 254, quick_scan: bool = False) -> List[Dict]:
    """Ultra-fast network scanning with optimized threading"""
    devices = []
    local_ip = get_local_ip()
    found_ips = []
    
    def scan_ip(ip: str):
        if ping_host(ip, timeout=0.05):  # Ultra-fast timeout for maximum speed
            found_ips.append(ip)
    
    # Use maximum concurrent threads for fastest scanning
    max_threads = 100  # Increased from 50
    threads = []
    
    # For quick scan, scan more comprehensive ranges to catch gaming devices
    if quick_scan:
        # Include more ranges to catch gaming devices like PS5, Xbox, etc.
        scan_range = list(range(1, 101)) + list(range(100, 201)) + list(range(200, 255))
    else:
        scan_range = range(start, end + 1)
    
    for i in scan_range:
        ip = f"{network}.{i}"
        thread = threading.Thread(target=scan_ip, args=(ip,))
        threads.append(thread)
        thread.start()
        
        # Limit concurrent threads
        if len(threads) >= max_threads:
            for t in threads:
                t.join()
            threads = []
    
    # Wait for remaining threads
    for thread in threads:
        thread.join()
    
    # Now get MAC addresses for found devices (parallel)
    def get_device_info(ip: str):
        mac = get_mac_address(ip)
        vendor = get_vendor_info(mac) if mac else "Unknown"
        
        # Try to get hostname with timeout
        try:
            hostname = socket.getfqdn(ip)
            if hostname == ip:  # If hostname is same as IP, try reverse DNS
                hostname = "Unknown"
        except:
            hostname = "Unknown"
        
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
        devices.append(device)
        log_info(f"Found device: {ip} ({vendor})")
    
    # Get device info in parallel with increased concurrency
    info_threads = []
    for ip in found_ips:
        thread = threading.Thread(target=get_device_info, args=(ip,))
        info_threads.append(thread)
        thread.start()
        
        if len(info_threads) >= 20:  # Increased from 10
            for t in info_threads:
                t.join()
            info_threads = []
    
    for thread in info_threads:
        thread.join()
    
    return devices

def scan_devices(quick: bool = True) -> List[Dict]:
    """Main function to scan for devices on the network (with caching)"""
    global _device_cache, _cache_timestamp
    
    try:
        # Check cache first
        current_time = time.time()
        if current_time - _cache_timestamp < CACHE_DURATION and _device_cache:
            log_info(f"Using cached device list ({len(_device_cache)} devices)")
            return list(_device_cache.values())
        
        local_ip = get_local_ip()
        network = ".".join(local_ip.split(".")[:-1])
        
        log_info(f"Scanning network: {network}.0/24")
        devices = scan_network_range_fast(network, quick_scan=quick)
        
        # Sort devices: local device first, then by IP
        devices.sort(key=lambda x: (not x["local"], socket.inet_aton(x["ip"])))
        
        # Update cache
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
    _device_cache = {}
    _cache_timestamp = 0
