#!/usr/bin/env python3
"""
Enhanced Network Scanner for DupeZ
Provides advanced network scanning with improved PS5 detection and error handling
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

from app.logs.logger import log_info, log_error, log_performance, log_network_scan, log_ps5_detection
from PyQt6.QtCore import QObject, pyqtSignal

@dataclass
class NetworkDevice:
    """Enhanced network device information"""
    ip: str
    mac: str
    hostname: str
    vendor: str
    device_type: str
    is_ps5: bool
    is_local: bool
    response_time: float
    ports: List[int]
    services: List[str]
    last_seen: float
    traffic_level: int
    connection_count: int
    status: str  # online, offline, blocked, suspicious

class EnhancedNetworkScanner(QObject):
    """Enhanced network scanner with advanced PS5 detection and error handling"""
    
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
        self.ps5_indicators = {
            'mac_prefixes': ['b4:0a:d8', 'b4:0a:d9', 'b4:0a:da', 'b4:0a:db'],
            'hostname_patterns': [
                r'ps5', r'playstation', r'sony', r'psn', r'playstation5',
                r'ps-5', r'ps_5', r'playstation-5', r'playstation_5'
            ],
            'vendor_patterns': [
                r'sony', r'playstation', r'ps5', r'playstation5'
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
            
            # Method 1: Scan ARP table first (FASTEST - most devices found here)
            arp_devices = self._scan_arp_table()
            log_info(f"Found {len(arp_devices)} devices via ARP table")
            
            # Emit devices immediately as they're found
            for device in arp_devices:
                try:
                    if hasattr(self, 'device_found'):
                        self.device_found.emit(device)
                except RuntimeError:
                    pass
            
            # Method 2: Quick IP scan (only if ARP didn't find enough devices)
            if len(arp_devices) < 10:  # Only do IP scan if ARP found few devices
                ip_addresses = self._generate_ip_list(network_range)
                ip_devices = self._scan_ips_fast(ip_addresses)  # Use fast scan
                log_info(f"Found {len(ip_devices)} additional devices via IP scan")
                
                # Emit additional devices immediately
                for device in ip_devices:
                    try:
                        if hasattr(self, 'device_found'):
                            self.device_found.emit(device)
                    except RuntimeError:
                        pass
                
                # Combine results
                all_devices = self._combine_device_lists(arp_devices, ip_devices)
            else:
                all_devices = arp_devices
            
            # Enhanced PS5 detection (fast)
            ps5_devices = self._detect_ps5_devices(all_devices)
            
            # Calculate scan statistics
            scan_duration = time.time() - start_time
            ps5_count = len([d for d in all_devices if d.get('is_ps5', False)])
            
            # Log scan results
            log_network_scan(
                devices_found=len(all_devices),
                scan_duration=scan_duration,
                network_range=network_range,
                quick_scan=quick_scan
            )
            
            log_ps5_detection(
                ps5_count=ps5_count,
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
                'is_ps5': False,
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
            
            # Enhanced PS5 detection
            device_info['is_ps5'] = self._is_ps5_device(device_info)
            
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
                # Parse MAC address from ARP output
                mac_match = re.search(r'([0-9a-fA-F]{2}[:-]){5}([0-9a-fA-F]{2})', result.stdout)
                if mac_match:
                    mac = mac_match.group(0)
            
            # Get hostname
            try:
                hostname = socket.gethostbyaddr(ip)[0]
            except:
                pass
                
        except Exception as e:
            log_error(f"Failed to get device info for {ip}", exception=e)
        
        return mac, hostname
    
    def _get_vendor_info(self, mac: str) -> str:
        """Get vendor information from MAC address"""
        if mac == "Unknown":
            return "Unknown"
        
        try:
            # Extract OUI (first 6 characters)
            oui = mac.replace(':', '').replace('-', '')[:6].upper()
            
            # Common vendor OUIs (simplified)
            vendor_ouis = {
                'B40AD8': 'Sony Interactive Entertainment',
                'B40AD9': 'Sony Interactive Entertainment',
                'B40ADA': 'Sony Interactive Entertainment',
                'B40ADB': 'Sony Interactive Entertainment',
                '001A11': 'Google Inc.',
                '001B63': 'Apple Inc.',
                '000C29': 'VMware Inc.',
                '00037F': 'Toshiba',
                '001517': 'Cisco Systems',
                '000E0E': 'Sony Corporation'
            }
            
            return vendor_ouis.get(oui, "Unknown")
            
        except Exception as e:
            log_error(f"Failed to get vendor info for MAC {mac}", exception=e)
            return "Unknown"
    
    def _is_ps5_device(self, device_info: Dict) -> bool:
        """Enhanced PS5 detection using multiple indicators"""
        try:
            # Check MAC address prefixes
            mac = device_info.get('mac', '').lower()
            for prefix in self.ps5_indicators['mac_prefixes']:
                if mac.startswith(prefix.lower()):
                    log_info(f"PS5 detected by MAC prefix: {device_info.get('ip', 'Unknown')}", mac=mac)
                    return True
            
            # Check hostname patterns
            hostname = device_info.get('hostname', '').lower()
            for pattern in self.ps5_indicators['hostname_patterns']:
                if re.search(pattern, hostname):
                    log_info(f"PS5 detected by hostname: {device_info.get('ip', 'Unknown')}", hostname=hostname)
                    return True
            
            # Check vendor patterns
            vendor = device_info.get('vendor', '').lower()
            for pattern in self.ps5_indicators['vendor_patterns']:
                if re.search(pattern, vendor):
                    log_info(f"PS5 detected by vendor: {device_info.get('ip', 'Unknown')}", vendor=vendor)
                    return True
            
            return False
            
        except Exception as e:
            log_error("PS5 detection failed", exception=e, device_info=device_info)
            return False
    
    def _determine_device_type(self, device_info: Dict) -> str:
        """Determine device type based on various indicators"""
        try:
            if device_info.get('is_ps5', False):
                return "PlayStation 5"
            
            hostname = device_info.get('hostname', '').lower()
            vendor = device_info.get('vendor', '').lower()
            mac = device_info.get('mac', '').lower()
            
            # Check for PS5 indicators in all fields
            ps5_indicators = ['ps5', 'playstation', 'sony', 'psn']
            for indicator in ps5_indicators:
                if (indicator in hostname or 
                    indicator in vendor or 
                    any(prefix in mac for prefix in ['b4:0a:d8', 'b4:0a:d9', 'b4:0a:da', 'b4:0a:db'])):
                    return "PlayStation 5"
            
            # Common device type detection
            if any(word in hostname for word in ['router', 'gateway', 'modem']):
                return "Router/Gateway"
            elif any(word in hostname for word in ['phone', 'mobile', 'android', 'iphone']):
                return "Mobile Device"
            elif any(word in hostname for word in ['laptop', 'desktop', 'pc', 'computer']):
                return "Computer"
            elif any(word in hostname for word in ['tv', 'television', 'smarttv']):
                return "Smart TV"
            elif any(word in hostname for word in ['xbox', 'playstation', 'nintendo']):
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
    
    def _detect_ps5_devices(self, devices: List[Dict]) -> List[Dict]:
        """Detect PS5 devices from scanned devices"""
        ps5_devices = []
        
        for device in devices:
            if self._is_ps5_device(device):
                device['is_ps5'] = True
                device['device_type'] = 'PlayStation 5'
                ps5_devices.append(device)
                log_info(f"PS5 detected: {device.get('ip')} | {device.get('mac')} | {device.get('hostname')}")
        
        return ps5_devices
    
    def get_ps5_devices(self) -> List[Dict]:
        """Get all PS5 devices from last scan"""
        return [device for device in self.scan_results if device.get('is_ps5', False)]
    
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
            'ps5_devices': len(self.get_ps5_devices()),
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
        """Scan ARP table for all known devices - OPTIMIZED FOR SPEED"""
        devices = []
        
        try:
            if platform.system().lower() == "windows":
                result = subprocess.run(
                    ['arp', '-a'], capture_output=True, text=True, timeout=5  # Reduced timeout
                )
            else:
                result = subprocess.run(
                    ['arp', '-n'], capture_output=True, text=True, timeout=5  # Reduced timeout
                )
            
            if result.returncode == 0:
                # Parse ARP table output
                lines = result.stdout.strip().split('\n')
                
                for line in lines:
                    try:
                        # Parse IP and MAC from ARP output
                        # Windows format: "192.168.1.1    00-11-22-33-44-55     dynamic"
                        # Linux format: "192.168.1.1 ether 00:11:22:33:44:55 C eth0"
                        
                        if platform.system().lower() == "windows":
                            # Windows ARP format
                            parts = line.split()
                            if len(parts) >= 2:
                                ip = parts[0]
                                mac = parts[1]
                                
                                # Validate IP and MAC
                                if self._is_valid_ip(ip) and self._is_valid_mac(mac):
                                    device_info = self._create_device_info_from_arp_fast(ip, mac)
                                    if device_info:
                                        devices.append(device_info)
                        else:
                            # Linux ARP format
                            parts = line.split()
                            if len(parts) >= 2:
                                ip = parts[0]
                                mac = parts[2] if len(parts) > 2 else "Unknown"
                                
                                # Validate IP and MAC
                                if self._is_valid_ip(ip) and self._is_valid_mac(mac):
                                    device_info = self._create_device_info_from_arp_fast(ip, mac)
                                    if device_info:
                                        devices.append(device_info)
                                        
                    except Exception as e:
                        # Skip invalid lines silently for speed
                        continue
                        
        except Exception as e:
            log_error("ARP table scan failed", exception=e)
        
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
                'is_ps5': False,
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
            
            # Quick PS5 detection
            device_info['is_ps5'] = self._is_ps5_device(device_info)
            
            # Determine device type
            device_info['device_type'] = self._determine_device_type(device_info)
            
            # Check if local device
            device_info['is_local'] = self._is_local_device(ip)
            
            return device_info
            
        except Exception as e:
            log_error(f"Failed to create device info for {ip}", exception=e)
            return None
    
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
        """Combine and deduplicate device lists"""
        combined = {}
        
        # Add ARP devices first
        for device in arp_devices:
            ip = device.get('ip')
            if ip:
                combined[ip] = device
        
        # Add IP devices (overwrite if better info)
        for device in ip_devices:
            ip = device.get('ip')
            if ip:
                if ip not in combined:
                    combined[ip] = device
                else:
                    # Merge information, preferring non-Unknown values
                    existing = combined[ip]
                    for key, value in device.items():
                        if value != 'Unknown' and existing.get(key) == 'Unknown':
                            existing[key] = value
        
        return list(combined.values())

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
                'is_ps5': False,
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
            
            # Quick PS5 detection
            device_info['is_ps5'] = self._is_ps5_device(device_info)
            
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
