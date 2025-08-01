# app/network/enhanced_scanner.py

import subprocess
import re
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
from typing import List, Dict, Optional, Set, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from contextlib import contextmanager
from PyQt6.QtCore import QThread, pyqtSignal, QObject
from app.logs.logger import log_info, log_error

class EnhancedNetworkScanner(QThread):
    """Enhanced network scanner with Angry IP Scanner-like features"""
    
    # Signals for GUI updates
    device_found = pyqtSignal(dict)  # Device info
    scan_progress = pyqtSignal(int, int)  # Current, Total
    scan_complete = pyqtSignal(list)  # All devices
    scan_error = pyqtSignal(str)  # Error message
    status_update = pyqtSignal(str)  # Status message
    
    def __init__(self):
        super().__init__()
        self.running = False
        self.devices = []
        self.scan_methods = []
        self.max_threads = 50  # Angry IP Scanner default
        self.timeout = 1.0
        self.executor = None
        
    def run(self):
        """Main scanning thread"""
        self.running = True
        self.devices = []
        
        try:
            # Get network information
            network_info = self.get_network_info()
            if not network_info:
                self.scan_error.emit("Failed to get network information")
                return
            
            self.status_update.emit(f"Scanning network: {network_info['network']}")
            
            # Determine scan methods based on platform and permissions
            self.scan_methods = self.get_available_scan_methods()
            
            # Generate IP list
            ip_list = self.generate_ip_list(network_info['network'])
            total_ips = len(ip_list)
            
            self.status_update.emit(f"Starting scan of {total_ips} IP addresses...")
            
            # Start scanning with progress updates
            found_devices = self.scan_network_advanced(ip_list, total_ips)
            
            # Process and enrich device information
            enriched_devices = self.enrich_device_info(found_devices)
            
            # Sort devices (local first, then by IP)
            enriched_devices.sort(key=lambda x: (not x.get('local', False), 
                                               socket.inet_aton(x['ip'])))
            
            self.devices = enriched_devices
            self.scan_complete.emit(enriched_devices)
            
            self.status_update.emit(f"Scan complete! Found {len(enriched_devices)} devices")
            
        except Exception as e:
            error_msg = f"Scan error: {e}"
            log_error(error_msg)
            self.scan_error.emit(error_msg)
        finally:
            self.cleanup()
    
    def get_network_info(self) -> Optional[Dict]:
        """Get comprehensive network information"""
        try:
            # Get local IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            
            # Extract network information
            network_parts = local_ip.split('.')
            network_base = '.'.join(network_parts[:-1])
            
            # Get gateway (usually .1)
            gateway = f"{network_base}.1"
            
            # Get subnet mask (assume /24 for now)
            subnet_mask = "255.255.255.0"
            
            return {
                'local_ip': local_ip,
                'network': f"{network_base}.0/24",
                'gateway': gateway,
                'subnet_mask': subnet_mask,
                'network_base': network_base
            }
        except Exception as e:
            log_error(f"Failed to get network info: {e}")
            return None
    
    def get_available_scan_methods(self) -> List[str]:
        """Get available scanning methods based on platform and permissions"""
        methods = []
        
        # Always available methods
        methods.append('tcp_connect')
        methods.append('ping')
        
        # Platform-specific methods
        if platform.system().lower() == "windows":
            methods.append('arp_scan')
            methods.append('netstat')
        else:
            methods.append('arp_scan')
            methods.append('ping_icmp')
        
        # Advanced methods (if available)
        try:
            # Test if we can create raw sockets (requires admin/root)
            test_socket = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
            test_socket.close()
            methods.append('raw_icmp')
        except:
            pass
        
        log_info(f"Available scan methods: {methods}")
        return methods
    
    def generate_ip_list(self, network: str) -> List[str]:
        """Generate list of IPs to scan"""
        try:
            # Extract network base
            network_base = network.split('/')[0].rsplit('.', 1)[0]
            
            # Generate IP list (exclude .0 and .255)
            ip_list = []
            for i in range(1, 255):
                ip = f"{network_base}.{i}"
                ip_list.append(ip)
            
            return ip_list
        except Exception as e:
            log_error(f"Failed to generate IP list: {e}")
            return []
    
    def scan_network_advanced(self, ip_list: List[str], total_ips: int) -> List[Dict]:
        """Advanced network scanning with multiple methods"""
        found_devices = []
        scanned_count = 0
        
        try:
            # Create thread pool
            self.executor = ThreadPoolExecutor(max_workers=self.max_threads)
            
            # Submit all IPs for scanning
            future_to_ip = {}
            for ip in ip_list:
                if not self.running:
                    break
                future = self.executor.submit(self.scan_single_ip, ip)
                future_to_ip[future] = ip
            
            # Collect results with progress updates
            for future in as_completed(future_to_ip, timeout=300):  # 5 minute timeout
                if not self.running:
                    break
                
                ip = future_to_ip[future]
                scanned_count += 1
                
                try:
                    device_info = future.result(timeout=2.0)
                    if device_info:
                        found_devices.append(device_info)
                        self.device_found.emit(device_info)
                except (TimeoutError, Exception) as e:
                    log_error(f"Error scanning {ip}: {e}")
                
                # Update progress
                self.scan_progress.emit(scanned_count, total_ips)
                
                # Status update every 10 IPs
                if scanned_count % 10 == 0:
                    self.status_update.emit(f"Scanned {scanned_count}/{total_ips} IPs, found {len(found_devices)} devices")
            
        except Exception as e:
            log_error(f"Advanced scan error: {e}")
        finally:
            if self.executor:
                self.executor.shutdown(wait=False)
        
        return found_devices
    
    def scan_single_ip(self, ip: str) -> Optional[Dict]:
        """Scan a single IP using multiple methods"""
        try:
            # Try different scan methods
            for method in self.scan_methods:
                if not self.running:
                    break
                
                is_alive = False
                
                if method == 'tcp_connect':
                    is_alive = self.tcp_connect_scan(ip)
                elif method == 'ping':
                    is_alive = self.ping_scan(ip)
                elif method == 'arp_scan':
                    is_alive = self.arp_scan(ip)
                elif method == 'raw_icmp':
                    is_alive = self.raw_icmp_scan(ip)
                
                if is_alive:
                    # Get detailed device information
                    device_info = self.get_detailed_device_info(ip)
                    return device_info
            
            return None
            
        except Exception as e:
            log_error(f"Error scanning {ip}: {e}")
            return None
    
    def tcp_connect_scan(self, ip: str) -> bool:
        """TCP connect scan (most reliable)"""
        try:
            # Common ports to check
            ports = [80, 443, 22, 21, 23, 25, 53, 110, 143, 993, 995, 8080]
            
            for port in ports:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(self.timeout)
                    result = sock.connect_ex((ip, port))
                    sock.close()
                    
                    if result == 0:
                        return True
                except:
                    continue
            
            return False
        except:
            return False
    
    def ping_scan(self, ip: str) -> bool:
        """Ping scan using system ping command"""
        try:
            if platform.system().lower() == "windows":
                result = subprocess.run(
                    ["ping", "-n", "1", "-w", "1000", ip],
                    capture_output=True, text=True, timeout=2.0
                )
            else:
                result = subprocess.run(
                    ["ping", "-c", "1", "-W", "1", ip],
                    capture_output=True, text=True, timeout=2.0
                )
            
            return result.returncode == 0 and "TTL=" in result.stdout
        except:
            return False
    
    def arp_scan(self, ip: str) -> bool:
        """ARP table scan"""
        try:
            # First ping to populate ARP table
            self.ping_scan(ip)
            
            # Check ARP table
            if platform.system().lower() == "windows":
                result = subprocess.run(
                    ["arp", "-a", ip], capture_output=True, text=True, timeout=2.0
                )
            else:
                result = subprocess.run(
                    ["arp", "-n", ip], capture_output=True, text=True, timeout=2.0
                )
            
            if result.returncode == 0:
                # Look for MAC address in output
                mac_pattern = r'([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})'
                return bool(re.search(mac_pattern, result.stdout))
            
            return False
        except:
            return False
    
    def raw_icmp_scan(self, ip: str) -> bool:
        """Raw ICMP scan (requires admin/root)"""
        try:
            # Create ICMP socket
            icmp_socket = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
            icmp_socket.settimeout(self.timeout)
            
            # Create ICMP echo request
            icmp_type = 8  # Echo request
            icmp_code = 0
            icmp_checksum = 0
            icmp_id = 1
            icmp_seq = 1
            
            # Build ICMP header
            icmp_header = struct.pack('!BBHHH', icmp_type, icmp_code, icmp_checksum, icmp_id, icmp_seq)
            
            # Calculate checksum
            checksum = self.calculate_checksum(icmp_header)
            icmp_header = struct.pack('!BBHHH', icmp_type, icmp_code, checksum, icmp_id, icmp_seq)
            
            # Send packet
            icmp_socket.sendto(icmp_header, (ip, 0))
            
            # Wait for response
            try:
                data, addr = icmp_socket.recvfrom(1024)
                return True
            except socket.timeout:
                return False
            finally:
                icmp_socket.close()
                
        except:
            return False
    
    def calculate_checksum(self, data: bytes) -> int:
        """Calculate ICMP checksum"""
        if len(data) % 2 == 1:
            data += b'\0'
        
        words = struct.unpack('!%dH' % (len(data) // 2), data)
        checksum = sum(words)
        
        while checksum >> 16:
            checksum = (checksum & 0xFFFF) + (checksum >> 16)
        
        return ~checksum & 0xFFFF
    
    def get_detailed_device_info(self, ip: str) -> Dict:
        """Get comprehensive device information"""
        try:
            # Get MAC address
            mac = self.get_mac_address(ip)
            
            # Get hostname
            hostname = self.get_hostname(ip)
            
            # Get vendor information
            vendor = self.get_vendor_info(mac) if mac else "Unknown"
            
            # Detect device type
            device_type = self.detect_device_type(ip, hostname, vendor)
            
            # Get open ports
            open_ports = self.get_open_ports(ip)
            
            # Get response time
            response_time = self.get_response_time(ip)
            
            device_info = {
                'ip': ip,
                'mac': mac or "Unknown",
                'hostname': hostname,
                'vendor': vendor,
                'device_type': device_type,
                'open_ports': open_ports,
                'response_time': response_time,
                'local': ip == self.get_local_ip(),
                'last_seen': time.strftime("%H:%M:%S"),
                'status': 'Online'
            }
            
            return device_info
            
        except Exception as e:
            log_error(f"Error getting device info for {ip}: {e}")
            return {
                'ip': ip,
                'mac': "Unknown",
                'hostname': "Unknown",
                'vendor': "Unknown",
                'device_type': "Unknown",
                'open_ports': [],
                'response_time': 0,
                'local': ip == self.get_local_ip(),
                'last_seen': time.strftime("%H:%M:%S"),
                'status': 'Online'
            }
    
    def get_mac_address(self, ip: str) -> Optional[str]:
        """Get MAC address from ARP table"""
        try:
            if platform.system().lower() == "windows":
                result = subprocess.run(
                    ["arp", "-a", ip], capture_output=True, text=True, timeout=2.0
                )
            else:
                result = subprocess.run(
                    ["arp", "-n", ip], capture_output=True, text=True, timeout=2.0
                )
            
            if result.returncode == 0:
                mac_pattern = r'([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})'
                match = re.search(mac_pattern, result.stdout)
                return match.group(0) if match else None
            
            return None
        except:
            return None
    
    def get_hostname(self, ip: str) -> str:
        """Get hostname for IP"""
        try:
            hostname = socket.getfqdn(ip)
            return hostname if hostname != ip else "Unknown"
        except:
            return "Unknown"
    
    def get_vendor_info(self, mac: str) -> str:
        """Get vendor information from MAC address"""
        if not mac:
            return "Unknown"
        
        # Extract OUI (first 6 characters)
        oui = mac.replace(":", "").replace("-", "")[:6].upper()
        
        # Common vendor OUIs
        vendors = {
            "000C29": "VMware",
            "001A11": "Google",
            "002272": "American Micro-Fuel Device Corp",
            "00037F": "Tektronix",
            "000C41": "Cisco",
            "001122": "Xerox",
            # Gaming devices
            "001B63": "Sony PlayStation",
            "001B64": "Microsoft Xbox",
            "001B65": "Nintendo Switch",
        }
        
        return vendors.get(oui, "Unknown")
    
    def detect_device_type(self, ip: str, hostname: str, vendor: str) -> str:
        """Detect device type based on various indicators"""
        hostname_lower = hostname.lower()
        vendor_lower = vendor.lower()
        
        # Gaming devices
        if any(keyword in hostname_lower for keyword in ["ps5", "playstation", "sony"]):
            return "Gaming Console (PlayStation)"
        elif any(keyword in hostname_lower for keyword in ["xbox", "microsoft"]):
            return "Gaming Console (Xbox)"
        elif any(keyword in hostname_lower for keyword in ["nintendo", "switch"]):
            return "Gaming Console (Nintendo)"
        
        # Network devices
        elif any(keyword in hostname_lower for keyword in ["router", "gateway", "modem"]):
            return "Network Device"
        elif any(keyword in vendor_lower for keyword in ["cisco", "netgear", "tp-link"]):
            return "Network Device"
        
        # Mobile devices
        elif any(keyword in hostname_lower for keyword in ["iphone", "android", "mobile"]):
            return "Mobile Device"
        
        # Computers
        elif any(keyword in hostname_lower for keyword in ["pc", "computer", "laptop", "desktop"]):
            return "Computer"
        
        # IoT devices
        elif any(keyword in hostname_lower for keyword in ["camera", "thermostat", "smart"]):
            return "IoT Device"
        
        return "Unknown"
    
    def get_open_ports(self, ip: str) -> List[int]:
        """Get list of open ports"""
        open_ports = []
        common_ports = [21, 22, 23, 25, 53, 80, 110, 143, 443, 993, 995, 8080]
        
        for port in common_ports:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(0.5)
                result = sock.connect_ex((ip, port))
                sock.close()
                
                if result == 0:
                    open_ports.append(port)
            except:
                continue
        
        return open_ports
    
    def get_response_time(self, ip: str) -> float:
        """Get response time in milliseconds"""
        try:
            start_time = time.time()
            
            # Use ping for response time
            if platform.system().lower() == "windows":
                result = subprocess.run(
                    ["ping", "-n", "1", "-w", "1000", ip],
                    capture_output=True, text=True, timeout=2.0
                )
            else:
                result = subprocess.run(
                    ["ping", "-c", "1", "-W", "1", ip],
                    capture_output=True, text=True, timeout=2.0
                )
            
            if result.returncode == 0:
                # Extract time from ping output
                time_pattern = r'time[=<](\d+(?:\.\d+)?)'
                match = re.search(time_pattern, result.stdout)
                if match:
                    return float(match.group(1))
            
            return (time.time() - start_time) * 1000
            
        except:
            return 0.0
    
    def get_local_ip(self) -> str:
        """Get local IP address"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            return local_ip
        except:
            return "192.168.1.1"
    
    def enrich_device_info(self, devices: List[Dict]) -> List[Dict]:
        """Enrich device information with additional data"""
        for device in devices:
            # Add traffic information (placeholder)
            device['traffic'] = 0
            
            # Add risk score based on device type
            risk_score = self.calculate_risk_score(device)
            device['risk_score'] = risk_score
            
            # Add blocking status
            device['blocked'] = False
        
        return devices
    
    def calculate_risk_score(self, device: Dict) -> int:
        """Calculate risk score for device"""
        score = 0
        
        # Gaming devices get higher risk score
        if "Gaming Console" in device.get('device_type', ''):
            score += 50
        
        # Unknown devices get medium risk
        if device.get('vendor') == "Unknown":
            score += 20
        
        # Devices with many open ports get higher risk
        open_ports = device.get('open_ports', [])
        if len(open_ports) > 5:
            score += 30
        
        return min(score, 100)  # Cap at 100
    
    def stop_scan(self):
        """Stop the scanning process"""
        self.running = False
        if self.executor:
            self.executor.shutdown(wait=False)
    
    def cleanup(self):
        """Clean up resources"""
        try:
            if self.executor:
                self.executor.shutdown(wait=False)
        except Exception as e:
            log_error(f"Error during cleanup: {e}")

# Global scanner instance
_enhanced_scanner = None

def get_enhanced_scanner() -> EnhancedNetworkScanner:
    """Get or create enhanced scanner instance"""
    global _enhanced_scanner
    if _enhanced_scanner is None:
        _enhanced_scanner = EnhancedNetworkScanner()
    return _enhanced_scanner

def cleanup_enhanced_scanner():
    """Clean up enhanced scanner"""
    global _enhanced_scanner
    if _enhanced_scanner:
        _enhanced_scanner.stop_scan()
        _enhanced_scanner = None 