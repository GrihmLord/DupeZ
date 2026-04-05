#!/usr/bin/env python3
"""
Enhanced Network Scanner for DupeZ
Provides advanced network scanning with device identification and error handling
"""

import subprocess
import socket
import threading
import time
import ipaddress
from typing import List, Dict, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import platform
import re

from app.logs.logger import log_info, log_error, log_performance, log_network_scan, log_device_detection
from PyQt6.QtCore import QObject, pyqtSignal

@dataclass
class NetworkDevice:
    """Enhanced network device information"""
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

class EnhancedNetworkScanner(QObject):
    """Enhanced network scanner with device identification and error handling"""
    
    # Signals for GUI compatibility
    device_found = pyqtSignal(dict)
    scan_progress = pyqtSignal(int, int)
    scan_complete = pyqtSignal(list)
    scan_error = pyqtSignal(str)
    status_update = pyqtSignal(str)
    
    def __init__(self, max_threads: int = 20, timeout: int = 1):
        super().__init__()
        self.max_threads = max_threads  # Reduced from 50 to 20 for better performance
        self.timeout = timeout  # Reduced from 3 to 1 second for faster scanning
        self.console_indicators = {
            'mac_prefixes': [
                'b4:0a:d8', 'b4:0a:d9', 'b4:0a:da', 'b4:0a:db',  # Sony PlayStation
                '0c:fe:45', 'f8:d0:ac',                              # Sony PlayStation
                '7c:ed:8d', '98:de:d0', '60:45:bd',                  # Microsoft Xbox
            ],
            'hostname_patterns': [
                r'ps5', r'ps4', r'playstation', r'sony', r'psn',
                r'xbox', r'xboxone', r'nintendo', r'switch'
            ],
            'vendor_patterns': [
                r'sony', r'playstation', r'microsoft.*xbox', r'nintendo'
            ]
        }
        self.scan_results = []
        self.scan_in_progress = False
        self.last_scan_time = 0
        
    def scan_network(self, network_range: str = "192.168.1.0/24", 
                    quick_scan: bool = True) -> List[Dict]:
        """Scan network for devices with enhanced discovery - OPTIMIZED FOR SPEED"""
        try:
            # Check if interpreter is shutting down
            import sys
            if sys.is_finalizing():
                log_error("Cannot scan network during interpreter shutdown")
                return []
                
            self.scan_in_progress = True
            start_time = time.time()
            
            log_info("Starting FAST enhanced network scan", network_range=network_range, quick_scan=quick_scan)
            
            # Method 1: ARP table — authoritative, instant, already deduped by MAC
            arp_devices = self._scan_arp_table()
            log_info(f"ARP table: {len(arp_devices)} unique devices")

            # Method 2: IP sweep — ONLY if ARP found zero devices
            # The ARP table is the source of truth for local-subnet devices.
            # Running a /24 ping sweep on hotspot subnets (192.168.137.x) causes
            # the adapter to respond for all IPs, flooding the list with ghosts.
            if len(arp_devices) == 0:
                log_info("ARP empty — falling back to IP sweep")
                ip_addresses = self._generate_ip_list(network_range)
                ip_devices = self._scan_ips_fast(ip_addresses)
                log_info(f"IP sweep found {len(ip_devices)} devices")
                all_devices = self._combine_device_lists([], ip_devices)
            else:
                all_devices = arp_devices

            # Final MAC dedup safety net
            all_devices = self._deduplicate_by_mac(all_devices)

            # Console/device type detection (fast)
            console_devices = self._detect_console_devices(all_devices)

            # Calculate scan statistics
            scan_duration = time.time() - start_time
            console_count = len([d for d in all_devices if d.get('is_console', False)])

            # Log scan results
            log_network_scan(
                devices_found=len(all_devices),
                scan_duration=scan_duration,
                network_range=network_range,
                quick_scan=quick_scan
            )

            log_device_detection(
                detected_count=console_count,
                total_devices=len(all_devices),
                scan_duration=scan_duration
            )
            
            self.scan_results = all_devices
            self.last_scan_time = time.time()
            self.scan_in_progress = False
            
            # Emit final scan complete signal
            try:
                if hasattr(self, 'scan_complete'):
                    self.scan_complete.emit(all_devices)
                    log_info(f"Scan complete signal emitted with {len(all_devices)} devices")
            except RuntimeError as e:
                log_error("Failed to emit scan complete signal", exception=e)
            
            return all_devices
            
        except Exception as e:
            self.scan_in_progress = False
            log_error("Network scan failed", exception=e, network_range=network_range)
            try:
                if hasattr(self, 'scan_error'):
                    self.scan_error.emit(str(e))
            except RuntimeError:
                pass
            return []
    
    def _get_local_ip(self) -> Optional[str]:
        """Get the local IP address dynamically"""
        try:
            import socket
            # Create a socket to get local IP
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
                return local_ip
        except Exception as e:
            log_error("Failed to get local IP", exception=e)
            return None
    
    def _generate_ip_list(self, network_range: str) -> List[str]:
        """Generate list of IP addresses to scan"""
        try:
            network = ipaddress.IPv4Network(network_range, strict=False)
            return [str(ip) for ip in network.hosts()]
        except Exception as e:
            log_error("Failed to generate IP list", exception=e, network_range=network_range)
            # Fallback to dynamic network detection
            try:
                local_ip = self._get_local_ip()
                if local_ip:
                    network_base = '.'.join(local_ip.split('.')[:-1])
                    return [f"{network_base}.{i}" for i in range(1, 255)]
                else:
                    return []
            except Exception as fallback_error:
                log_error("Failed to generate fallback IP list", exception=fallback_error)
                return []
    
    def _scan_ips(self, ip_addresses: List[str], quick_scan: bool) -> List[Dict]:
        """Scan IP addresses using thread pool"""
        devices = []
        
        try:
            # Check if interpreter is shutting down
            import sys
            if sys.is_finalizing():
                log_error("Cannot start thread pool during interpreter shutdown")
                return devices
                
            with ThreadPoolExecutor(max_workers=self.max_threads) as executor:
                # Submit scan tasks
                future_to_ip = {
                    executor.submit(self._scan_single_ip, ip, quick_scan): ip 
                    for ip in ip_addresses
                }
                
                # Collect results
                for future in as_completed(future_to_ip):
                    ip = future_to_ip[future]
                    try:
                        result = future.result()
                        if result:
                            devices.append(result)
                    except Exception as e:
                        log_error(f"Failed to scan IP {ip}", exception=e)
                        
        except RuntimeError as e:
            if "cannot schedule new futures after interpreter shutdown" in str(e):
                log_error("Thread pool failed due to interpreter shutdown")
            else:
                log_error("Thread pool execution failed", exception=e)
        except Exception as e:
            log_error("Thread pool execution failed", exception=e)
        
        return devices
    
    def _scan_single_ip(self, ip: str, quick_scan: bool) -> Optional[Dict]:
        """Scan a single IP address with enhanced detection using multiple methods"""
        try:
            # Try multiple detection methods
            device_detected = False
            
            # Method 1: Ping test
            if self._ping_host(ip):
                device_detected = True
            
            # Method 2: ARP table check (for devices that don't respond to ping)
            if not device_detected:
                if self._check_arp_table_for_ip(ip):
                    device_detected = True
            
            # Method 3: Port scan for common ports (even if ping fails)
            if not device_detected:
                if self._quick_port_scan(ip):
                    device_detected = True
            
            # Method 4: DNS resolution check
            if not device_detected:
                if self._check_dns_resolution(ip):
                    device_detected = True
            
            # If no device detected by any method, skip
            if not device_detected:
                return None
            
            device_info = {
                'ip': ip,
                'mac': 'Unknown',
                'hostname': 'Unknown',
                'vendor': 'Unknown',
                'device_type': 'Unknown',
                'is_console': False,
                'is_local': False,
                'response_time': 0.0,
                'ports': [],
                'services': [],
                'last_seen': time.time(),
                'traffic_level': 0,
                'connection_count': 0,
                'status': 'online',
                'detection_method': 'unknown'
            }
            
            # Get MAC address and hostname
            mac, hostname = self._get_device_info(ip)
            device_info['mac'] = mac
            device_info['hostname'] = hostname
            
            # Get vendor information
            vendor = self._get_vendor_info(mac)
            device_info['vendor'] = vendor
            
            # Console detection
            device_info['is_console'] = self._is_console_device(device_info)
            
            # Determine device type
            device_info['device_type'] = self._determine_device_type(device_info)
            
            # Check if local device
            device_info['is_local'] = self._is_local_device(ip)
            
            # Get additional info if not quick scan
            if not quick_scan:
                ports, services = self._scan_ports(ip)
                device_info['ports'] = ports
                device_info['services'] = services
                
                # Get traffic info
                traffic_level, connection_count = self._get_traffic_info(ip)
                device_info['traffic_level'] = traffic_level
                device_info['connection_count'] = connection_count
            
            return device_info
            
        except Exception as e:
            log_error(f"Failed to scan IP {ip}", exception=e)
            return None
    
    def _ping_host(self, ip: str) -> bool:
        """Ping a host to check if it's online"""
        try:
            if platform.system().lower() == "windows":
                result = subprocess.run(
                    ['ping', '-n', '1', '-w', str(self.timeout * 1000), ip],
                    capture_output=True, text=True, timeout=self.timeout + 1
                )
            else:
                result = subprocess.run(
                    ['ping', '-c', '1', '-W', str(self.timeout), ip],
                    capture_output=True, text=True, timeout=self.timeout + 1
                )
            
            return result.returncode == 0
            
        except Exception as e:
            log_error(f"Ping failed for {ip}", exception=e)
            return False
    
    def _get_device_info(self, ip: str) -> Tuple[str, str]:
        """Get MAC address and hostname for an IP"""
        mac = "Unknown"
        hostname = "Unknown"

        try:
            # Get MAC address using ARP
            if platform.system().lower() == "windows":
                result = subprocess.run(
                    ['arp', '-a', ip], capture_output=True, text=True, timeout=5
                )
            else:
                result = subprocess.run(
                    ['arp', '-n', ip], capture_output=True, text=True, timeout=5
                )

            if result.returncode == 0:
                mac_match = re.search(r'([0-9a-fA-F]{2}[:-]){5}([0-9a-fA-F]{2})', result.stdout)
                if mac_match:
                    mac = mac_match.group(0)

            # 1) Reverse DNS
            try:
                hostname = socket.gethostbyaddr(ip)[0]
            except Exception:
                pass

            # 2) NetBIOS fallback (Windows only)
            if hostname == "Unknown" and platform.system().lower() == "windows":
                try:
                    nbt = subprocess.run(
                        ['nbtstat', '-a', ip],
                        capture_output=True, text=True, timeout=3
                    )
                    if nbt.returncode == 0:
                        for line in nbt.stdout.splitlines():
                            line = line.strip()
                            if '<00>' in line and 'UNIQUE' in line:
                                name = line.split()[0].strip()
                                if name and name != ip:
                                    hostname = name
                                    break
                except Exception:
                    pass

        except Exception as e:
            log_error(f"Failed to get device info for {ip}", exception=e)

        return mac, hostname

    # Expanded OUI vendor table — covers most home/gaming network devices
    _VENDOR_OUIS = {
        # Sony / PlayStation
        'B40AD8': 'Sony (PlayStation)', 'B40AD9': 'Sony (PlayStation)',
        'B40ADA': 'Sony (PlayStation)', 'B40ADB': 'Sony (PlayStation)',
        '000E0E': 'Sony', '001315': 'Sony', 'A8E3EE': 'Sony',
        '0CFE45': 'Sony (PlayStation)', 'F8D0AC': 'Sony (PlayStation)',
        '00D9D1': 'Sony', '7CBD76': 'Sony', '008048': 'Sony',
        # Microsoft / Xbox
        '7C1E52': 'Microsoft (Xbox)', '001DD8': 'Microsoft (Xbox)',
        '0050F2': 'Microsoft', '60455E': 'Microsoft (Xbox)',
        '98DC24': 'Microsoft (Xbox)', 'C83F26': 'Microsoft (Xbox)',
        # Nintendo
        'E84ECE': 'Nintendo', '58BDA3': 'Nintendo', '002709': 'Nintendo',
        'CCFB65': 'Nintendo', '002444': 'Nintendo', '40D28A': 'Nintendo',
        '98415C': 'Nintendo', '7CBB8A': 'Nintendo', 'A45C27': 'Nintendo',
        # Apple
        '001B63': 'Apple', '3C15C2': 'Apple', 'A4D1D2': 'Apple',
        'F0B479': 'Apple', '38C986': 'Apple', '14109F': 'Apple',
        'AC87A3': 'Apple', 'D02B20': 'Apple', '6C709F': 'Apple',
        'F8FF0A': 'Apple', 'BCEC5D': 'Apple', '78CA39': 'Apple',
        # Samsung
        'A8F274': 'Samsung', 'B47443': 'Samsung', 'CC3A61': 'Samsung',
        'F025B7': 'Samsung', '340ABD': 'Samsung', 'AC5F3E': 'Samsung',
        '78D6F0': 'Samsung', '1C66AA': 'Samsung', '94350A': 'Samsung',
        # Google / Nest
        '001A11': 'Google', 'F4F5D8': 'Google', '54609A': 'Google',
        '3C5AB4': 'Google (Nest)', '18B430': 'Google (Nest)',
        'F4B7E2': 'Google (Pixel)', 'A47733': 'Google (Nest)',
        # TP-Link
        '50C7BF': 'TP-Link', '60A4B7': 'TP-Link', 'EC172F': 'TP-Link',
        'C006C3': 'TP-Link', 'B09575': 'TP-Link', '54AF97': 'TP-Link',
        # ASUS
        '000C6E': 'ASUS', '002354': 'ASUS', '1C872C': 'ASUS',
        '2CFDA1': 'ASUS', '50465D': 'ASUS', '049226': 'ASUS',
        # Netgear
        '00146C': 'Netgear', '001B2F': 'Netgear', '008EF2': 'Netgear',
        '204E7F': 'Netgear', '28C68E': 'Netgear', '6CB0CE': 'Netgear',
        # Linksys / Cisco
        '001517': 'Cisco', '000F66': 'Cisco', '001EBD': 'Linksys',
        '00259C': 'Cisco', 'C0C1C0': 'Cisco', '689CE2': 'Linksys',
        # Intel
        '001B21': 'Intel', '001E64': 'Intel', '001F3B': 'Intel',
        '3497F6': 'Intel', '48A472': 'Intel', '8C8D28': 'Intel',
        # Realtek
        '52540F': 'Realtek', '001665': 'Realtek', '000CE7': 'Realtek',
        # Amazon / Ring / Echo
        'F081AF': 'Amazon', 'FCA183': 'Amazon (Echo)',
        '747548': 'Amazon', '44D9E7': 'Amazon (Ring)',
        # VMware / Hyper-V
        '000C29': 'VMware', '005056': 'VMware', '000569': 'VMware',
        '00155D': 'Microsoft (Hyper-V)',
        # Dell / HP / Lenovo
        '001422': 'Dell', '0021701': 'Dell',
        '001A4B': 'HP', '0021B7': 'Lenovo',
        # Roku / Streaming
        'B083FE': 'Roku', 'DC3A5E': 'Roku', 'C83232': 'Roku',
    }

    def _get_vendor_info(self, mac: str) -> str:
        """Get vendor information from MAC address OUI table"""
        if mac == "Unknown":
            return "Unknown"

        try:
            oui = mac.replace(':', '').replace('-', '')[:6].upper()
            return self._VENDOR_OUIS.get(oui, "Unknown")
        except Exception as e:
            log_error(f"Failed to get vendor info for MAC {mac}", exception=e)
            return "Unknown"
    
    def _is_console_device(self, device_info: Dict) -> bool:
        """Detect gaming consoles using MAC OUI, hostname, and vendor indicators"""
        try:
            mac = device_info.get('mac', '').lower()
            for prefix in self.console_indicators['mac_prefixes']:
                if mac.startswith(prefix.lower()):
                    log_info(f"Console detected by MAC prefix: {device_info.get('ip', 'Unknown')}", mac=mac)
                    return True

            hostname = device_info.get('hostname', '').lower()
            for pattern in self.console_indicators['hostname_patterns']:
                if re.search(pattern, hostname):
                    log_info(f"Console detected by hostname: {device_info.get('ip', 'Unknown')}", hostname=hostname)
                    return True

            vendor = device_info.get('vendor', '').lower()
            for pattern in self.console_indicators['vendor_patterns']:
                if re.search(pattern, vendor):
                    log_info(f"Console detected by vendor: {device_info.get('ip', 'Unknown')}", vendor=vendor)
                    return True

            return False

        except Exception as e:
            log_error("Console detection failed", exception=e, device_info=device_info)
            return False
    
    def _determine_device_type(self, device_info: Dict) -> str:
        """Determine device type based on hostname, vendor, and MAC indicators"""
        try:
            hostname = device_info.get('hostname', '').lower()
            vendor = device_info.get('vendor', '').lower()

            # Gaming consoles (detected by _is_console_device)
            if device_info.get('is_console', False):
                # Narrow down the console type
                if any(kw in hostname or kw in vendor for kw in ['ps5', 'ps4', 'playstation', 'sony']):
                    return "PlayStation"
                elif any(kw in hostname or kw in vendor for kw in ['xbox']):
                    return "Xbox"
                elif any(kw in hostname or kw in vendor for kw in ['nintendo', 'switch']):
                    return "Nintendo"
                return "Gaming Console"

            # Common device type detection
            if any(word in hostname for word in ['router', 'gateway', 'modem']):
                return "Router/Gateway"
            elif any(word in hostname for word in ['phone', 'mobile', 'android', 'iphone']):
                return "Mobile Device"
            elif any(word in hostname for word in ['laptop', 'desktop', 'pc', 'computer']):
                return "Computer"
            elif any(word in hostname for word in ['tv', 'television', 'smarttv']):
                return "Smart TV"
            elif any(word in hostname for word in ['xbox', 'playstation', 'nintendo', 'switch']):
                return "Gaming Console"
            elif any(word in hostname for word in ['printer', 'scanner']):
                return "Printer/Scanner"
            elif any(word in hostname for word in ['camera', 'webcam']):
                return "Camera"
            else:
                return "Unknown Device"

        except Exception as e:
            log_error("Device type determination failed", exception=e, device_info=device_info)
            return "Unknown Device"
    
    def _is_local_device(self, ip: str) -> bool:
        """Check if device is local to the network"""
        try:
            # Check if IP is in common local ranges
            ip_obj = ipaddress.IPv4Address(ip)
            local_ranges = [
                ipaddress.IPv4Network('192.168.0.0/16'),
                ipaddress.IPv4Network('10.0.0.0/8'),
                ipaddress.IPv4Network('172.16.0.0/12')
            ]
            
            return any(ip_obj in network for network in local_ranges)
            
        except Exception as e:
            log_error(f"Failed to check if {ip} is local", exception=e)
            return False
    
    def _scan_ports(self, ip: str) -> Tuple[List[int], List[str]]:
        """Scan common ports on the device"""
        ports = []
        services = []
        
        try:
            common_ports = [21, 22, 23, 25, 53, 80, 110, 143, 443, 993, 995, 8080]
            
            for port in common_ports:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(1)
                    result = sock.connect_ex((ip, port))
                    if result == 0:
                        ports.append(port)
                        service = self._get_service_name(port)
                        if service:
                            services.append(service)
                    sock.close()
                except:
                    pass
                    
        except Exception as e:
            log_error(f"Port scan failed for {ip}", exception=e)
        
        return ports, services
    
    def _get_service_name(self, port: int) -> str:
        """Get service name for a port"""
        services = {
            21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP",
            53: "DNS", 80: "HTTP", 110: "POP3", 143: "IMAP",
            443: "HTTPS", 993: "IMAPS", 995: "POP3S", 8080: "HTTP-Alt"
        }
        return services.get(port, f"Unknown-{port}")
    
    def _get_traffic_info(self, ip: str) -> Tuple[int, int]:
        """Get traffic information for a device (simplified)"""
        # This would typically involve more complex network monitoring
        # For now, return placeholder values
        return 0, 0
    
    def _detect_console_devices(self, devices: List[Dict]) -> List[Dict]:
        """Detect gaming consoles from scanned devices"""
        console_devices = []

        for device in devices:
            if self._is_console_device(device):
                device['is_console'] = True
                device['device_type'] = self._determine_device_type(device)
                console_devices.append(device)
                log_info(f"Console detected: {device.get('ip')} | {device.get('mac')} | {device.get('hostname')}")

        return console_devices

    def get_console_devices(self) -> List[Dict]:
        """Get all gaming consoles from last scan"""
        return [device for device in self.scan_results if device.get('is_console', False)]

    # Backward compatibility
    get_ps5_devices = get_console_devices
    
    def get_device_by_ip(self, ip: str) -> Optional[Dict]:
        """Get device information by IP address"""
        for device in self.scan_results:
            if device.get('ip') == ip:
                return device
        return None
    
    def is_scanning(self) -> bool:
        """Check if scan is in progress"""
        return self.scan_in_progress
    
    def get_scan_stats(self) -> Dict:
        """Get scan statistics"""
        return {
            'total_devices': len(self.scan_results),
            'console_devices': len(self.get_console_devices()),
            'local_devices': len([d for d in self.scan_results if d.get('is_local', False)]),
            'last_scan_time': self.last_scan_time,
            'scan_in_progress': self.scan_in_progress
        }
    
    def start(self):
        """Start the network scan (GUI compatibility method)"""
        try:
            self.scan_in_progress = True
            self.status_update.emit("Starting network scan...")
            # Start the scan in a separate thread to avoid blocking GUI
            import threading
            scan_thread = threading.Thread(target=self._run_scan)
            scan_thread.daemon = True
            scan_thread.start()
            log_info("Network scan started")
        except Exception as e:
            log_error(f"Error starting scan: {e}")
            self.scan_error.emit(f"Error starting scan: {e}")
    
    def stop_scan(self):
        """Stop the network scan"""
        try:
            self.scan_in_progress = False
            self.status_update.emit("Scan stopped")
            log_info("Network scan stopped")
        except Exception as e:
            log_error(f"Error stopping scan: {e}")
    
    def _run_scan(self):
        """Run the actual scan in a separate thread"""
        try:
            log_info("_run_scan method called")
            devices = self.scan_network()
            log_info(f"scan_network returned {len(devices)} devices")
            if self.scan_in_progress:  # Only emit if not stopped
                log_info("Emitting scan_complete signal")
                self.scan_complete.emit(devices)
                self.status_update.emit(f"Scan completed: {len(devices)} devices found")
                log_info("Scan completion signals emitted")
            else:
                log_info("Scan was stopped, not emitting signals")
        except Exception as e:
            log_error(f"Error during scan: {e}")
            self.scan_error.emit(f"Scan error: {e}")
        finally:
            self.scan_in_progress = False

    def _scan_arp_table(self) -> List[Dict]:
        """Scan ARP table — dedup by MAC, no slow pings, keeps highest IP per MAC."""
        # mac_lower -> (ip, mac_raw, last_octet)
        mac_best = {}

        try:
            if platform.system().lower() == "windows":
                result = subprocess.run(
                    ['arp', '-a'], capture_output=True, text=True, timeout=5
                )
            else:
                result = subprocess.run(
                    ['arp', '-n'], capture_output=True, text=True, timeout=5
                )

            if result.returncode != 0:
                return []

            for line in result.stdout.splitlines():
                stripped = line.strip()
                # Skip non-data lines in Windows arp -a output
                if not stripped or stripped.startswith('Interface:') or '---' in stripped:
                    continue
                if 'Internet' in stripped or 'Physical' in stripped or 'Address' in stripped:
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

                mac_lower = mac_raw.replace('-', ':').lower()

                # Skip broadcast / multicast
                if mac_lower == 'ff:ff:ff:ff:ff:ff':
                    continue
                try:
                    if int(mac_lower.split(':')[0], 16) & 1:
                        continue
                except (ValueError, IndexError):
                    pass

                # Keep the highest last-octet per MAC (most recent DHCP lease)
                try:
                    last_octet = int(ip.rsplit('.', 1)[1])
                except (ValueError, IndexError):
                    last_octet = 0

                if mac_lower in mac_best:
                    if last_octet > mac_best[mac_lower][2]:
                        mac_best[mac_lower] = (ip, mac_raw, last_octet)
                else:
                    mac_best[mac_lower] = (ip, mac_raw, last_octet)

        except Exception as e:
            log_error("ARP table scan failed", exception=e)
            return []

        # Build device list from deduped entries
        devices = []
        for mac_lower, (ip, mac_raw, _) in mac_best.items():
            dev = self._create_device_info_from_arp_fast(ip, mac_raw)
            if dev:
                devices.append(dev)

        log_info(f"ARP scan: {len(devices)} unique devices (deduped by MAC)")
        return devices
    
    def _create_device_info_from_arp_fast(self, ip: str, mac: str) -> Optional[Dict]:
        """Create device info from ARP table entry - OPTIMIZED FOR SPEED"""
        try:
            device_info = {
                'ip': ip,
                'mac': mac,
                'hostname': 'Unknown',
                'vendor': 'Unknown',
                'device_type': 'Unknown',
                'is_console': False,
                'is_local': False,
                'response_time': 0.0,
                'ports': [],
                'services': [],
                'last_seen': time.time(),
                'traffic_level': 0,
                'connection_count': 0,
                'status': 'online',
                'detection_method': 'arp_table_fast'
            }
            
            # Get vendor information (fast)
            vendor = self._get_vendor_info(mac)
            device_info['vendor'] = vendor
            
            # Quick console detection
            device_info['is_console'] = self._is_console_device(device_info)
            
            # Determine device type
            device_info['device_type'] = self._determine_device_type(device_info)
            
            # Check if local device
            device_info['is_local'] = self._is_local_device(ip)
            
            return device_info
            
        except Exception as e:
            log_error(f"Failed to create device info for {ip}", exception=e)
            return None
    
    def _deduplicate_by_mac(self, devices: List[Dict]) -> List[Dict]:
        """Final safety-net dedup: one entry per physical MAC address.

        When multiple IPs share the same MAC (stale DHCP leases), keep only
        the first one encountered (ARP-sourced devices come first and are
        already ping-verified).
        """
        seen_macs = set()
        result = []
        for d in devices:
            mac_raw = d.get('mac', 'Unknown')
            if mac_raw == 'Unknown':
                result.append(d)
                continue
            mac_lower = mac_raw.replace('-', ':').lower()
            if mac_lower in seen_macs:
                log_info(f"Final dedup: dropping {d.get('ip')} (duplicate MAC {mac_lower})")
                continue
            seen_macs.add(mac_lower)
            result.append(d)
        return result

    def _is_valid_ip(self, ip: str) -> bool:
        """Check if string is a valid IP address"""
        try:
            socket.inet_aton(ip)
            return True
        except:
            return False
    
    def _is_valid_mac(self, mac: str) -> bool:
        """Check if string is a valid MAC address"""
        import re
        mac_pattern = re.compile(r'^([0-9a-fA-F]{2}[:-]){5}([0-9a-fA-F]{2})$')
        return bool(mac_pattern.match(mac))
    
    def _combine_device_lists(self, arp_devices: List[Dict], ip_devices: List[Dict]) -> List[Dict]:
        """Combine and deduplicate device lists by IP AND by MAC"""
        combined_by_ip = {}
        seen_macs = {}  # mac_lower -> ip (track which IP owns each MAC)

        def _add_device(device):
            ip = device.get('ip')
            if not ip:
                return
            mac_raw = device.get('mac', 'Unknown')
            mac_lower = mac_raw.replace('-', ':').lower() if mac_raw != 'Unknown' else None

            # MAC dedup: if we already have a device with this MAC, skip
            if mac_lower and mac_lower != 'unknown' and mac_lower in seen_macs:
                existing_ip = seen_macs[mac_lower]
                if existing_ip != ip:
                    log_info(f"Combine dedup: skipping {ip} (same MAC {mac_lower} as {existing_ip})")
                    return

            if ip not in combined_by_ip:
                combined_by_ip[ip] = device
                if mac_lower and mac_lower != 'unknown':
                    seen_macs[mac_lower] = ip
            else:
                # Merge information, preferring non-Unknown values
                existing = combined_by_ip[ip]
                for key, value in device.items():
                    if value != 'Unknown' and existing.get(key) == 'Unknown':
                        existing[key] = value

        # Add ARP devices first (they have MAC addresses)
        for device in arp_devices:
            _add_device(device)

        # Add IP-scan devices (fill in gaps)
        for device in ip_devices:
            _add_device(device)

        return list(combined_by_ip.values())

    def _check_arp_table_for_ip(self, ip: str) -> bool:
        """Check if specific IP exists in ARP table"""
        try:
            if platform.system().lower() == "windows":
                result = subprocess.run(
                    ['arp', '-a'], capture_output=True, text=True, timeout=5
                )
            else:
                result = subprocess.run(
                    ['arp', '-n'], capture_output=True, text=True, timeout=5
                )
            
            if result.returncode == 0:
                return ip in result.stdout
            return False
            
        except Exception as e:
            log_error(f"ARP table check failed for {ip}", exception=e)
            return False
    
    def _quick_port_scan(self, ip: str) -> bool:
        """Quick port scan for common ports"""
        try:
            common_ports = [80, 443, 22, 21, 23, 25, 53, 110, 143, 993, 995, 8080, 8443]
            
            for port in common_ports:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(1)
                    result = sock.connect_ex((ip, port))
                    sock.close()
                    if result == 0:
                        return True
                except:
                    continue
            
            return False
            
        except Exception as e:
            log_error(f"Quick port scan failed for {ip}", exception=e)
            return False
    
    def _check_dns_resolution(self, ip: str) -> bool:
        """Check if IP resolves to a hostname"""
        try:
            hostname = socket.gethostbyaddr(ip)
            return hostname[0] != ip
        except:
            return False

    def _scan_ips_fast(self, ip_addresses: List[str]) -> List[Dict]:
        """Fast IP scan using only ping detection"""
        devices = []
        
        try:
            # Use fewer threads for faster scanning
            with ThreadPoolExecutor(max_workers=10) as executor:
                # Submit scan tasks
                future_to_ip = {
                    executor.submit(self._scan_single_ip_fast, ip): ip 
                    for ip in ip_addresses
                }
                
                # Collect results
                for future in as_completed(future_to_ip):
                    ip = future_to_ip[future]
                    try:
                        result = future.result()
                        if result:
                            devices.append(result)
                    except Exception as e:
                        log_error(f"Failed to scan IP {ip}", exception=e)
                        
        except Exception as e:
            log_error("Fast IP scan failed", exception=e)
        
        return devices
    
    def _scan_single_ip_fast(self, ip: str) -> Optional[Dict]:
        """Fast single IP scan using only ping"""
        try:
            # Only use ping for speed
            if not self._ping_host(ip):
                return None
            
            device_info = {
                'ip': ip,
                'mac': 'Unknown',
                'hostname': 'Unknown',
                'vendor': 'Unknown',
                'device_type': 'Unknown',
                'is_console': False,
                'is_local': False,
                'response_time': 0.0,
                'ports': [],
                'services': [],
                'last_seen': time.time(),
                'traffic_level': 0,
                'connection_count': 0,
                'status': 'online',
                'detection_method': 'ping_fast'
            }
            
            # Get basic device info
            mac, hostname = self._get_device_info(ip)
            device_info['mac'] = mac
            device_info['hostname'] = hostname
            
            # Get vendor information
            vendor = self._get_vendor_info(mac)
            device_info['vendor'] = vendor
            
            # Quick console detection
            device_info['is_console'] = self._is_console_device(device_info)
            
            # Determine device type
            device_info['device_type'] = self._determine_device_type(device_info)
            
            # Check if local device
            device_info['is_local'] = self._is_local_device(ip)
            
            return device_info
            
        except Exception as e:
            log_error(f"Failed to scan IP {ip}", exception=e)
            return None

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
        _enhanced_scanner = None 
