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
import psutil
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
            # Get all network interfaces including Ethernet
            network_interfaces = self.get_all_network_interfaces()
            if not network_interfaces:
                self.scan_error.emit("Failed to get network interfaces")
                return
            
            self.status_update.emit(f"Found {len(network_interfaces)} network interfaces")
            
            # Determine scan methods based on platform and permissions
            self.scan_methods = self.get_available_scan_methods()
            
            # Scan each interface
            all_devices = []
            total_ips = 0
            
            for interface in network_interfaces:
                if not self.running:
                    break
                
                self.status_update.emit(f"Scanning interface: {interface['name']} ({interface['ip']})")
                
                # Generate IP list for this interface
                ip_list = self.generate_ip_list_for_interface(interface)
                total_ips += len(ip_list)
                
                # Scan this interface
                interface_devices = self.scan_network_advanced(ip_list, len(ip_list), interface)
                all_devices.extend(interface_devices)
            
            # Process and enrich device information
            enriched_devices = self.enrich_device_info(all_devices)
            
            # Remove duplicates based on IP
            unique_devices = self.remove_duplicate_devices(enriched_devices)
            
            # Sort devices (local first, then by IP)
            unique_devices.sort(key=lambda x: (not x.get('local', False), 
                                             socket.inet_aton(x['ip'])))
            
            self.devices = unique_devices
            self.scan_complete.emit(unique_devices)
            
            self.status_update.emit(f"Scan complete! Found {len(unique_devices)} devices across {len(network_interfaces)} interfaces")
            
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
    
    def get_all_network_interfaces(self) -> List[Dict]:
        """Get all network interfaces including Ethernet"""
        interfaces = []
        
        try:
            # Get all network interfaces using psutil
            for interface_name, addrs in psutil.net_if_addrs().items():
                for addr in addrs:
                    if addr.family == socket.AF_INET:  # IPv4 only
                        # Skip loopback interfaces
                        if interface_name.startswith('Loopback') or addr.address.startswith('127.'):
                            continue
                        
                        # Determine interface type
                        interface_type = self.detect_interface_type(interface_name)
                        
                        interface_info = {
                            'name': interface_name,
                            'ip': addr.address,
                            'netmask': addr.netmask,
                            'broadcast': addr.broadcast,
                            'type': interface_type,
                            'network': self.calculate_network_address(addr.address, addr.netmask)
                        }
                        
                        interfaces.append(interface_info)
                        log_info(f"Found interface: {interface_name} ({interface_type}) - {addr.address}")
            
            # Sort interfaces: Ethernet first, then WiFi, then others
            interfaces.sort(key=lambda x: self.get_interface_priority(x['type']))
            
            return interfaces
            
        except Exception as e:
            log_error(f"Failed to get network interfaces: {e}")
            # Fallback to basic network detection
            return [self.get_network_info()]
    
    def detect_interface_type(self, interface_name: str) -> str:
        """Detect the type of network interface"""
        name_lower = interface_name.lower()
        
        # Ethernet interfaces
        if any(keyword in name_lower for keyword in ['ethernet', 'eth', 'lan', 'wired']):
            return 'Ethernet'
        elif name_lower.startswith('ethernet'):
            return 'Ethernet'
        
        # WiFi interfaces
        elif any(keyword in name_lower for keyword in ['wifi', 'wireless', 'wlan', 'wi-fi']):
            return 'WiFi'
        elif name_lower.startswith('wlan'):
            return 'WiFi'
        
        # Virtual interfaces
        elif any(keyword in name_lower for keyword in ['virtual', 'vpn', 'tunnel', 'tap', 'tun']):
            return 'Virtual'
        
        # Default to Unknown
        return 'Unknown'
    
    def get_interface_priority(self, interface_type: str) -> int:
        """Get priority for interface sorting (lower = higher priority)"""
        priorities = {
            'Ethernet': 0,
            'WiFi': 1,
            'Unknown': 2,
            'Virtual': 3
        }
        return priorities.get(interface_type, 4)
    
    def calculate_network_address(self, ip: str, netmask: str) -> str:
        """Calculate network address from IP and netmask"""
        try:
            # Convert IP and netmask to integers
            ip_parts = [int(x) for x in ip.split('.')]
            mask_parts = [int(x) for x in netmask.split('.')]
            
            # Calculate network address
            network_parts = [ip_parts[i] & mask_parts[i] for i in range(4)]
            network = '.'.join(map(str, network_parts))
            
            # Calculate CIDR notation
            cidr = sum(bin(int(x)).count('1') for x in mask_parts)
            
            return f"{network}/{cidr}"
        except Exception as e:
            log_error(f"Failed to calculate network address: {e}")
            # Fallback to /24
            network_base = '.'.join(ip.split('.')[:-1])
            return f"{network_base}.0/24"
    
    def generate_ip_list_for_interface(self, interface: Dict) -> List[str]:
        """Generate IP list for a specific interface"""
        try:
            network = interface['network']
            network_base = network.split('/')[0]
            cidr = int(network.split('/')[1])
            
            # Calculate number of hosts based on CIDR
            num_hosts = 2 ** (32 - cidr) - 2  # Subtract 2 for network and broadcast
            
            # Limit to reasonable range for scanning
            if num_hosts > 254:
                num_hosts = 254
            
            ip_list = []
            network_parts = [int(x) for x in network_base.split('.')]
            
            for i in range(1, num_hosts + 1):
                # Calculate IP address
                ip_parts = network_parts.copy()
                ip_parts[3] = (ip_parts[3] + i) % 256
                if ip_parts[3] == 0:
                    ip_parts[2] = (ip_parts[2] + 1) % 256
                if ip_parts[2] == 0:
                    ip_parts[1] = (ip_parts[1] + 1) % 256
                
                ip = '.'.join(map(str, ip_parts))
                ip_list.append(ip)
            
            return ip_list
            
        except Exception as e:
            log_error(f"Failed to generate IP list for interface {interface['name']}: {e}")
            # Fallback to basic range
            network_base = '.'.join(interface['ip'].split('.')[:-1])
            return [f"{network_base}.{i}" for i in range(1, 255)]
    
    def remove_duplicate_devices(self, devices: List[Dict]) -> List[Dict]:
        """Remove duplicate devices based on IP address"""
        seen_ips = set()
        unique_devices = []
        
        for device in devices:
            ip = device.get('ip')
            if ip and ip not in seen_ips:
                seen_ips.add(ip)
                unique_devices.append(device)
        
        return unique_devices
    
    def scan_network_advanced(self, ip_list: List[str], total_ips: int, interface: Dict = None) -> List[Dict]:
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
                future = self.executor.submit(self.scan_single_ip, ip, interface)
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
    
    def scan_single_ip(self, ip: str, interface: Dict = None) -> Optional[Dict]:
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
                    device_info = self.get_detailed_device_info(ip, interface)
                    return device_info
            
            # Fallback: Try a simple socket connection to common ports
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(0.5)
                result = sock.connect_ex((ip, 80))
                sock.close()
                if result == 0:
                    device_info = self.get_detailed_device_info(ip, interface)
                    return device_info
            except:
                pass
            
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
        """Enhanced ping scan with multiple methods for maximum device detection"""
        try:
            # Method 1: TCP connection scan to common ports
            common_ports = [80, 443, 22, 21, 23, 25, 53, 110, 143, 993, 995, 8080, 8443, 3000, 5000, 8000, 9000]
            for port in common_ports:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(0.5)  # Faster timeout
                    result = sock.connect_ex((ip, port))
                    sock.close()
                    if result == 0:
                        return True
                except:
                    continue
            
            # Method 2: ICMP ping (Windows only)
            if platform.system().lower() == "windows":
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
                    sock.settimeout(1.0)
                    
                    # Create ICMP echo request
                    icmp_type = 8
                    icmp_code = 0
                    icmp_checksum = 0
                    icmp_id = 12345
                    icmp_seq = 1
                    
                    # Build ICMP packet
                    icmp_header = struct.pack('!BBHHH', icmp_type, icmp_code, icmp_checksum, icmp_id, icmp_seq)
                    icmp_data = b'PulseDropPro Ping'
                    
                    # Calculate checksum
                    packet = icmp_header + icmp_data
                    checksum = self.calculate_checksum(packet)
                    icmp_header = struct.pack('!BBHHH', icmp_type, icmp_code, checksum, icmp_id, icmp_seq)
                    packet = icmp_header + icmp_data
                    
                    # Send packet
                    sock.sendto(packet, (ip, 0))
                    
                    # Try to receive response
                    try:
                        sock.settimeout(1.0)
                        data, addr = sock.recvfrom(1024)
                        sock.close()
                        return True
                    except socket.timeout:
                        pass
                    sock.close()
                except:
                    pass
            
            # Method 3: UDP scan for gaming devices (PS5, Xbox, etc.)
            gaming_ports = [3074, 3075, 3076, 3659, 14000, 14001, 14002, 14003, 14004, 14005, 14006, 14007, 14008, 14009, 14010]
            for port in gaming_ports:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    sock.settimeout(0.5)
                    sock.sendto(b'ping', (ip, port))
                    sock.close()
                    return True  # Assume device is there if we can send UDP packet
                except:
                    continue
            
            return False
        except:
            return False
    
    def arp_scan(self, ip: str) -> bool:
        """ARP table scan using native Python implementation"""
        try:
            # First try to ping to populate ARP table
            if not self.ping_scan(ip):
                return False
            
            # Use native Python to check ARP table
            if platform.system().lower() == "windows":
                # On Windows, try to get MAC using socket
                try:
                    # Try to connect to get MAC
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(0.5)
                    sock.connect((ip, 80))
                    sock.close()
                    return True
                except:
                    return False
            else:
                # On Linux, read /proc/net/arp
                try:
                    with open('/proc/net/arp', 'r') as f:
                        arp_table = f.read()
                    
                    # Look for the IP in ARP table
                    lines = arp_table.split('\n')
                    for line in lines:
                        if ip in line and '00:00:00:00:00:00' not in line:
                            return True
                    
                    return False
                except:
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
    
    def get_detailed_device_info(self, ip: str, interface: Dict = None) -> Dict:
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
            
            # Add interface information
            interface_info = {
                'name': interface['name'] if interface else 'Unknown',
                'type': interface['type'] if interface else 'Unknown',
                'network': interface['network'] if interface else 'Unknown'
            }
            
            device_info = {
                'ip': ip,
                'mac': mac or "Unknown",
                'hostname': hostname,
                'vendor': vendor,
                'device_type': device_type,
                'open_ports': open_ports,
                'local': ip == self.get_local_ip(),
                'last_seen': time.strftime("%H:%M:%S"),
                'status': 'Online',
                'interface': interface_info
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
                'local': ip == self.get_local_ip(),
                'last_seen': time.strftime("%H:%M:%S"),
                'status': 'Online'
            }
    
    def get_mac_address(self, ip: str) -> Optional[str]:
        """Get MAC address using native Python implementation"""
        try:
            # Use socket-based approach instead of subprocess
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            
            # Try to connect to populate ARP table
            try:
                sock.connect((ip, 80))
                sock.close()
            except:
                pass
            
            # For now, return a placeholder MAC since we can't easily get it without subprocess
            # In a real implementation, you'd need to parse the ARP table
            return "00:00:00:00:00:00"  # Placeholder
            
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
            # Gaming devices - Sony PlayStation
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
            # Microsoft Xbox
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
            # Nintendo
            "001B7B": "Nintendo Switch",
            "001B7C": "Nintendo Switch",
            "001B7D": "Nintendo Switch",
            "001B7E": "Nintendo Switch",
            "001B7F": "Nintendo Switch",
            # Additional gaming console OUIs
            "00:1B:63": "Sony PlayStation",
            "00:1B:64": "Microsoft Xbox",
            "00:1B:65": "Nintendo Switch",
            "00:1B:66": "Sony PlayStation",
            "00:1B:67": "Microsoft Xbox",
            "00:1B:68": "Nintendo Switch",
        }
        
        return vendors.get(oui, "Unknown")
    
    def detect_device_type(self, ip: str, hostname: str, vendor: str) -> str:
        """Enhanced device type detection with gaming console focus"""
        hostname_lower = hostname.lower()
        vendor_lower = vendor.lower()
        
        # Gaming Console Detection (Priority)
        if any(keyword in hostname_lower for keyword in ["ps5", "playstation", "sony", "ps4", "ps3"]):
            return "Gaming Console (PlayStation)"
        elif any(keyword in hostname_lower for keyword in ["xbox", "microsoft", "xboxone", "xbox360"]):
            return "Gaming Console (Xbox)"
        elif any(keyword in hostname_lower for keyword in ["nintendo", "switch", "wii", "3ds"]):
            return "Gaming Console (Nintendo)"
        elif any(keyword in vendor_lower for keyword in ["sony", "playstation"]):
            return "Gaming Console (PlayStation)"
        elif any(keyword in vendor_lower for keyword in ["microsoft", "xbox"]):
            return "Gaming Console (Xbox)"
        elif any(keyword in vendor_lower for keyword in ["nintendo"]):
            return "Gaming Console (Nintendo)"
        
        # Network Device Detection
        elif any(keyword in hostname_lower for keyword in ["router", "gateway", "modem", "ap", "accesspoint"]):
            return "Network Device (Router/Gateway)"
        elif any(keyword in vendor_lower for keyword in ["cisco", "netgear", "tp-link", "asus", "linksys"]):
            return "Network Device (Router/Gateway)"
        
        # Mobile Device Detection
        elif any(keyword in hostname_lower for keyword in ["phone", "mobile", "android", "iphone", "ipad", "tablet"]):
            return "Mobile Device"
        elif any(keyword in vendor_lower for keyword in ["apple", "samsung", "lg", "motorola", "huawei"]):
            return "Mobile Device"
        
        # Computer Detection
        elif any(keyword in hostname_lower for keyword in ["laptop", "notebook", "macbook"]):
            return "Laptop"
        elif any(keyword in hostname_lower for keyword in ["desktop", "pc", "computer", "workstation"]):
            return "Desktop Computer"
        elif any(keyword in vendor_lower for keyword in ["dell", "hp", "lenovo", "acer", "asus"]):
            return "Desktop Computer"
        
        # Smart TV Detection
        elif any(keyword in hostname_lower for keyword in ["tv", "television", "smarttv", "androidtv"]):
            return "Smart TV"
        elif any(keyword in vendor_lower for keyword in ["samsung", "lg", "sony", "philips"]):
            return "Smart TV"
        
        # Other Device Types
        elif any(keyword in hostname_lower for keyword in ["printer", "print", "hp", "canon", "epson"]):
            return "Printer"
        elif any(keyword in hostname_lower for keyword in ["camera", "webcam", "ipcam"]):
            return "Camera"
        elif any(keyword in hostname_lower for keyword in ["nas", "storage", "server", "synology", "qnap"]):
            return "Storage Device"
        elif any(keyword in hostname_lower for keyword in ["amazon", "echo", "alexa"]):
            return "Smart Home Device"
        elif any(keyword in hostname_lower for keyword in ["google", "nest", "chromecast"]):
            return "Smart Home Device"
        else:
            return "Unknown Device"
    
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
            
            # Add blocking status
            device['blocked'] = False
        
        return devices
    

    
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