#!/usr/bin/env python3
"""
Ultra-Fast Network Scanner
High-performance network device discovery with parallel scanning and intelligent caching
"""

import asyncio
import socket
import threading
import time
import subprocess
import json
import os
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from app.logs.logger import log_info, log_error, log_warning

@dataclass
class DeviceInfo:
    """Network device information"""
    ip: str
    hostname: str
    mac: str
    status: str
    discovery_method: str
    response_time: float
    last_seen: datetime
    device_type: str
    ports: List[int]
    services: List[str]

class UltraFastScanner:
    """Ultra-fast network scanner with parallel processing and intelligent caching"""
    
    def __init__(self):
        self.discovered_devices: Dict[str, DeviceInfo] = {}
        self.device_cache: Dict[str, DeviceInfo] = {}
        self.scan_history: List[Dict] = []
        self.is_scanning = False
        self.scan_thread = None
        
        # Performance settings
        self.max_concurrent_scans = 100
        self.scan_timeout = 2.0
        self.cache_duration = 300  # 5 minutes
        self.auto_refresh = True
        self.refresh_interval = 60  # 1 minute
        
        # Network ranges to scan
        self.network_ranges = [
            "192.168.1.0/24",
            "10.0.0.0/8",
            "172.16.0.0/12"
        ]
        
        # Common ports to scan
        self.common_ports = [22, 23, 25, 53, 80, 110, 143, 443, 993, 995, 1433, 1521, 3306, 3389, 5432, 5900, 6379, 8080, 8443, 27017]
        
        # Load cached devices
        self._load_device_cache()
        
    def _load_device_cache(self):
        """Load cached device information"""
        try:
            cache_file = "app/data/device_cache.json"
            if os.path.exists(cache_file):
                with open(cache_file, 'r') as f:
                    cache_data = json.load(f)
                    
                for device_data in cache_data:
                    device = DeviceInfo(
                        ip=device_data['ip'],
                        hostname=device_data.get('hostname', ''),
                        mac=device_data.get('mac', ''),
                        status=device_data.get('status', 'unknown'),
                        discovery_method=device_data.get('discovery_method', 'cache'),
                        response_time=device_data.get('response_time', 0.0),
                        last_seen=datetime.fromisoformat(device_data['last_seen']),
                        device_type=device_data.get('device_type', 'unknown'),
                        ports=device_data.get('ports', []),
                        services=device_data.get('services', [])
                    )
                    self.device_cache[device.ip] = device
                    
                log_info(f"Loaded {len(self.device_cache)} cached devices")
                
        except Exception as e:
            log_error(f"Failed to load device cache: {e}")
    
    def _save_device_cache(self):
        """Save device information to cache"""
        try:
            cache_file = "app/data/device_cache.json"
            os.makedirs(os.path.dirname(cache_file), exist_ok=True)
            
            cache_data = []
            for device in self.device_cache.values():
                cache_data.append({
                    'ip': device.ip,
                    'hostname': device.hostname,
                    'mac': device.mac,
                    'status': device.status,
                    'discovery_method': device.discovery_method,
                    'response_time': device.response_time,
                    'last_seen': device.last_seen.isoformat(),
                    'device_type': device.device_type,
                    'ports': device.ports,
                    'services': device.services
                })
            
            with open(cache_file, 'w') as f:
                json.dump(cache_data, f, indent=2)
                
            log_info(f"Saved {len(cache_data)} devices to cache")
            
        except Exception as e:
            log_error(f"Failed to save device cache: {e}")
    
    def start_scan(self, network_ranges: Optional[List[str]] = None) -> bool:
        """Start ultra-fast network scanning"""
        if self.is_scanning:
            return False
            
        try:
            self.is_scanning = True
            
            # Use provided ranges or default
            ranges_to_scan = network_ranges if network_ranges else self.network_ranges
            
            # Start scan in background thread
            self.scan_thread = threading.Thread(
                target=self._perform_ultra_fast_scan,
                args=(ranges_to_scan,),
                daemon=True
            )
            self.scan_thread.start()
            
            log_info("Ultra-fast network scan started")
            return True
            
        except Exception as e:
            log_error(f"Failed to start network scan: {e}")
            self.is_scanning = False
            return False
    
    def stop_scan(self):
        """Stop network scanning"""
        self.is_scanning = False
        log_info("Network scan stopped")
    
    def _perform_ultra_fast_scan(self, network_ranges: List[str]):
        """Perform ultra-fast network scanning with parallel processing"""
        try:
            start_time = time.time()
            scan_results = {
                'start_time': start_time,
                'network_ranges': network_ranges,
                'devices_found': 0,
                'scan_methods': []
            }
            
            # Generate IP addresses to scan
            all_ips = self._generate_ip_list(network_ranges)
            log_info(f"Scanning {len(all_ips)} IP addresses with ultra-fast scanner")
            
            # Use ThreadPoolExecutor for parallel scanning
            with ThreadPoolExecutor(max_workers=self.max_concurrent_scans) as executor:
                # Submit all scan tasks
                future_to_ip = {
                    executor.submit(self._scan_single_ip, ip): ip 
                    for ip in all_ips
                }
                
                # Process completed scans
                for future in as_completed(future_to_ip, timeout=self.scan_timeout * len(all_ips)):
                    try:
                        device_info = future.result()
                        if device_info:
                            self.discovered_devices[device_info.ip] = device_info
                            self.device_cache[device_info.ip] = device_info
                            scan_results['devices_found'] += 1
                    except Exception as e:
                        continue
            
            # Update scan history
            scan_results['end_time'] = time.time()
            scan_results['duration'] = scan_results['end_time'] - scan_results['start_time']
            scan_results['total_devices'] = len(self.discovered_devices)
            self.scan_history.append(scan_results)
            
            # Save updated cache
            self._save_device_cache()
            
            log_info(f"Ultra-fast scan completed: {scan_results['devices_found']} devices found in {scan_results['duration']:.2f}s")
            
        except Exception as e:
            log_error(f"Error in ultra-fast scan: {e}")
        finally:
            self.is_scanning = False
    
    def _generate_ip_list(self, network_ranges: List[str]) -> List[str]:
        """Generate list of IP addresses to scan from network ranges"""
        ips = []
        
        for network_range in network_ranges:
            try:
                if '/' in network_range:
                    # CIDR notation
                    base_ip, prefix = network_range.split('/')
                    prefix = int(prefix)
                    
                    if prefix == 24:  # /24 network
                        base_parts = base_ip.split('.')
                        base_network = f"{base_parts[0]}.{base_parts[1]}.{base_parts[2]}"
                        
                        for i in range(1, 255):  # Skip .0 and .255
                            ips.append(f"{base_network}.{i}")
                    
                    elif prefix == 16:  # /16 network
                        base_parts = base_ip.split('.')
                        base_network = f"{base_parts[0]}.{base_parts[1]}"
                        
                        # Sample from /16 (too many IPs to scan all)
                        for i in range(0, 256, 4):  # Sample every 4th IP
                            for j in range(1, 255, 4):
                                ips.append(f"{base_network}.{i}.{j}")
                    
                    elif prefix == 8:  # /8 network
                        base_parts = base_ip.split('.')
                        base_network = base_parts[0]
                        
                        # Sample from /8 (way too many IPs)
                        for i in range(0, 256, 16):  # Sample every 16th IP
                            for j in range(0, 256, 16):
                                for k in range(1, 255, 16):
                                    ips.append(f"{base_network}.{i}.{j}.{k}")
                else:
                    # Single IP
                    ips.append(network_range)
                    
            except Exception as e:
                log_error(f"Error parsing network range {network_range}: {e}")
                continue
        
        return ips
    
    def _scan_single_ip(self, ip: str) -> Optional[DeviceInfo]:
        """Scan a single IP address using multiple methods"""
        try:
            # Check cache first
            if ip in self.device_cache:
                cached_device = self.device_cache[ip]
                # Update last seen
                cached_device.last_seen = datetime.now()
                return cached_device
            
            # Try multiple discovery methods
            device_info = None
            
            # Method 1: Fast ping
            if self._ping_host(ip):
                device_info = self._create_device_info(ip, "ping")
            
            # Method 2: ARP lookup (if ping succeeded)
            if device_info:
                mac = self._get_mac_address(ip)
                if mac:
                    device_info.mac = mac
                    device_info.discovery_method = "ping+arp"
            
            # Method 3: Port scan (if device is responsive)
            if device_info:
                open_ports = self._quick_port_scan(ip)
                if open_ports:
                    device_info.ports = open_ports
                    device_info.services = self._identify_services(open_ports)
            
            # Method 4: Hostname resolution
            if device_info:
                hostname = self._resolve_hostname(ip)
                if hostname:
                    device_info.hostname = hostname
                    device_info.device_type = self._identify_device_type(hostname, open_ports)
            
            return device_info
            
        except Exception as e:
            return None
    
    def _ping_host(self, ip: str) -> bool:
        """Fast ping to check if host is alive"""
        try:
            # Use subprocess ping with timeout
            result = subprocess.run(
                ["ping", "-n", "1", "-w", "1000", ip],
                capture_output=True,
                timeout=2
            )
            return result.returncode == 0
        except:
            return False
    
    def _get_mac_address(self, ip: str) -> Optional[str]:
        """Get MAC address using ARP"""
        try:
            result = subprocess.run(
                ["arp", "-a", ip],
                capture_output=True,
                text=True,
                timeout=2
            )
            
            if result.returncode == 0:
                # Parse ARP output for MAC address
                lines = result.stdout.split('\n')
                for line in lines:
                    if ip in line and '-' in line:
                        parts = line.split()
                        for part in parts:
                            if len(part) == 17 and ':' in part:
                                return part
            return None
            
        except:
            return None
    
    def _quick_port_scan(self, ip: str) -> List[int]:
        """Quick port scan for common ports"""
        open_ports = []
        
        try:
            # Use threading for faster port scanning
            with ThreadPoolExecutor(max_workers=20) as executor:
                future_to_port = {
                    executor.submit(self._check_port, ip, port): port 
                    for port in self.common_ports
                }
                
                for future in as_completed(future_to_port, timeout=5):
                    try:
                        port, is_open = future.result()
                        if is_open:
                            open_ports.append(port)
                    except:
                        continue
                        
        except Exception as e:
            log_error(f"Error in quick port scan for {ip}: {e}")
        
        return open_ports
    
    def _check_port(self, ip: str, port: int) -> Tuple[int, bool]:
        """Check if a specific port is open"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex((ip, port))
            sock.close()
            return port, result == 0
        except:
            return port, False
    
    def _identify_services(self, ports: List[int]) -> List[str]:
        """Identify services based on open ports"""
        service_map = {
            22: "SSH",
            23: "Telnet",
            25: "SMTP",
            53: "DNS",
            80: "HTTP",
            110: "POP3",
            143: "IMAP",
            443: "HTTPS",
            993: "IMAPS",
            995: "POP3S",
            1433: "MSSQL",
            1521: "Oracle",
            3306: "MySQL",
            3389: "RDP",
            5432: "PostgreSQL",
            5900: "VNC",
            6379: "Redis",
            8080: "HTTP-Alt",
            8443: "HTTPS-Alt",
            27017: "MongoDB"
        }
        
        return [service_map.get(port, f"Port-{port}") for port in ports]
    
    def _resolve_hostname(self, ip: str) -> Optional[str]:
        """Resolve hostname from IP address"""
        try:
            hostname = socket.gethostbyaddr(ip)[0]
            return hostname
        except:
            return None
    
    def _identify_device_type(self, hostname: str, ports: List[int]) -> str:
        """Identify device type based on hostname and ports"""
        hostname_lower = hostname.lower()
        
        # Router/Network devices
        if any(keyword in hostname_lower for keyword in ['router', 'gateway', 'modem', 'switch']):
            return "Network Device"
        
        # Servers
        if any(keyword in hostname_lower for keyword in ['server', 'srv', 'db', 'web']):
            return "Server"
        
        # Gaming devices
        if any(keyword in hostname_lower for keyword in ['gaming', 'game', 'ps5', 'xbox']):
            return "Gaming Device"
        
        # IoT devices
        if any(keyword in hostname_lower for keyword in ['iot', 'smart', 'camera', 'sensor']):
            return "IoT Device"
        
        # Check ports for device type
        if 3389 in ports:  # RDP
            return "Windows PC"
        elif 22 in ports:  # SSH
            return "Linux/Unix Device"
        elif 80 in ports or 443 in ports:  # Web
            return "Web Device"
        
        return "Unknown Device"
    
    def _create_device_info(self, ip: str, discovery_method: str) -> DeviceInfo:
        """Create device info object"""
        return DeviceInfo(
            ip=ip,
            hostname="",
            mac="",
            status="online",
            discovery_method=discovery_method,
            response_time=0.0,
            last_seen=datetime.now(),
            device_type="unknown",
            ports=[],
            services=[]
        )
    
    def get_discovered_devices(self) -> List[DeviceInfo]:
        """Get list of discovered devices"""
        return list(self.discovered_devices.values())
    
    def get_device_by_ip(self, ip: str) -> Optional[DeviceInfo]:
        """Get device information by IP address"""
        return self.discovered_devices.get(ip) or self.device_cache.get(ip)
    
    def get_scan_status(self) -> Dict:
        """Get current scan status"""
        return {
            "is_scanning": self.is_scanning,
            "total_devices": len(self.discovered_devices),
            "cached_devices": len(self.device_cache),
            "scan_history_count": len(self.scan_history),
            "last_scan": self.scan_history[-1] if self.scan_history else None,
            "auto_refresh": self.auto_refresh,
            "refresh_interval": self.refresh_interval
        }
    
    def get_device_statistics(self) -> Dict:
        """Get device discovery statistics"""
        try:
            device_types = {}
            discovery_methods = {}
            services = {}
            
            all_devices = list(self.discovered_devices.values()) + list(self.device_cache.values())
            
            for device in all_devices:
                # Count device types
                device_types[device.device_type] = device_types.get(device.device_type, 0) + 1
                
                # Count discovery methods
                discovery_methods[device.discovery_method] = discovery_methods.get(device.discovery_method, 0) + 1
                
                # Count services
                for service in device.services:
                    services[service] = services.get(service, 0) + 1
            
            return {
                "total_devices": len(all_devices),
                "device_types": device_types,
                "discovery_methods": discovery_methods,
                "services": services,
                "scan_performance": {
                    "avg_devices_per_scan": sum(s['devices_found'] for s in self.scan_history) / len(self.scan_history) if self.scan_history else 0,
                    "avg_scan_duration": sum(s['duration'] for s in self.scan_history) / len(self.scan_history) if self.scan_history else 0
                }
            }
            
        except Exception as e:
            log_error(f"Error generating device statistics: {e}")
            return {"error": str(e)}
    
    def clear_cache(self):
        """Clear device cache"""
        self.device_cache.clear()
        self._save_device_cache()
        log_info("Device cache cleared")
    
    def export_devices(self, format_type: str = "json") -> str:
        """Export discovered devices in various formats"""
        try:
            all_devices = list(self.discovered_devices.values()) + list(self.device_cache.values())
            
            if format_type.lower() == "json":
                return json.dumps([{
                    'ip': d.ip,
                    'hostname': d.hostname,
                    'mac': d.mac,
                    'status': d.status,
                    'device_type': d.device_type,
                    'ports': d.ports,
                    'services': d.services,
                    'last_seen': d.last_seen.isoformat()
                } for d in all_devices], indent=2)
            
            elif format_type.lower() == "csv":
                csv_lines = ["IP,Hostname,MAC,Status,Device Type,Ports,Services,Last Seen"]
                for device in all_devices:
                    csv_lines.append(f"{device.ip},{device.hostname},{device.mac},{device.status},{device.device_type},{','.join(map(str, device.ports))},{','.join(device.services)},{device.last_seen.isoformat()}")
                return "\n".join(csv_lines)
            
            else:
                return f"Unsupported format: {format_type}"
                
        except Exception as e:
            log_error(f"Error exporting devices: {e}")
            return f"Export error: {str(e)}"
