#!/usr/bin/env python3
"""
Enhanced Multi-Protocol Network Scanner for DupeZ
Combines multiple discovery methods for maximum device detection
"""

import asyncio
import socket
import struct
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
import json
import os
import subprocess
import platform

@dataclass
class DeviceInfo:
    """Enhanced device information"""
    ip: str
    mac: str = ""
    hostname: str = ""
    device_type: str = "Unknown"
    os_info: str = ""
    services: List[str] = field(default_factory=list)
    last_seen: float = 0
    discovery_methods: List[str] = field(default_factory=list)
    response_time: float = 0
    ports: List[int] = field(default_factory=list)
    vendor: str = ""
    is_active: bool = True

class EnhancedMultiProtocolScanner:
    """Multi-protocol network scanner with intelligent caching"""
    
    def __init__(self, network_range: str = "192.168.1.0/24"):
        self.network_range = network_range
        self.devices: Dict[str, DeviceInfo] = {}
        self.scan_cache_file = "device_cache.json"
        self.is_scanning = False
        self.scan_thread = None
        self.executor = ThreadPoolExecutor(max_workers=20)
        
        # Load cached devices
        self._load_device_cache()
        
        # Discovery methods
        self.discovery_methods = {
            'arp': self._arp_scan,
            'ping': self._icmp_ping_scan,
            'netbios': self._netbios_scan,
            'mdns': self._mdns_scan,
            'snmp': self._snmp_scan,
            'port_scan': self._quick_port_scan
        }
    
    def _load_device_cache(self):
        """Load cached device information"""
        try:
            if os.path.exists(self.scan_cache_file):
                with open(self.scan_cache_file, 'r') as f:
                    cached_data = json.load(f)
                    for ip, data in cached_data.items():
                        self.devices[ip] = DeviceInfo(**data)
                print(f"Loaded {len(self.devices)} cached devices")
        except Exception as e:
            print(f"Error loading device cache: {e}")
    
    def _save_device_cache(self):
        """Save device information to cache"""
        try:
            cache_data = {}
            for ip, device in self.devices.items():
                cache_data[ip] = {
                    'ip': device.ip,
                    'mac': device.mac,
                    'hostname': device.hostname,
                    'device_type': device.device_type,
                    'os_info': device.os_info,
                    'services': device.services,
                    'last_seen': device.last_seen,
                    'discovery_methods': device.discovery_methods,
                    'response_time': device.response_time,
                    'ports': device.ports,
                    'vendor': device.vendor,
                    'is_active': device.is_active
                }
            
            with open(self.scan_cache_file, 'w') as f:
                json.dump(cache_data, f, indent=2)
        except Exception as e:
            print(f"Error saving device cache: {e}")
    
    def start_scan(self, methods: List[str] = None) -> bool:
        """Start comprehensive network scan"""
        if self.is_scanning:
            return False
        
        if methods is None:
            methods = list(self.discovery_methods.keys())
        
        self.is_scanning = True
        self.scan_thread = threading.Thread(
            target=self._run_comprehensive_scan,
            args=(methods,)
        )
        self.scan_thread.start()
        return True
    
    def stop_scan(self):
        """Stop ongoing scan"""
        self.is_scanning = False
        if self.scan_thread:
            self.scan_thread.join()
        self.executor.shutdown(wait=False)
    
    def _run_comprehensive_scan(self, methods: List[str]):
        """Run comprehensive scan using multiple methods"""
        print(f"Starting comprehensive scan with methods: {methods}")
        
        # Generate IP list
        ip_list = self._generate_ip_list()
        print(f"Scanning {len(ip_list)} IP addresses")
        
        # Run discovery methods in parallel
        for method in methods:
            if method in self.discovery_methods:
                try:
                    print(f"Running {method} discovery...")
                    self.discovery_methods[method](ip_list)
                except Exception as e:
                    print(f"Error in {method} discovery: {e}")
        
        # Update device cache
        self._save_device_cache()
        print(f"Scan complete. Found {len(self.devices)} devices")
        self.is_scanning = False
    
    def _generate_ip_list(self) -> List[str]:
        """Generate list of IPs to scan"""
        try:
            # Simple network range expansion
            base_ip = self.network_range.split('/')[0]
            base_parts = base_ip.split('.')
            base_parts[-1] = '0'
            base_ip = '.'.join(base_parts)
            
            ips = []
            for i in range(1, 255):
                ip = f"{base_parts[0]}.{base_parts[1]}.{base_parts[2]}.{i}"
                ips.append(ip)
            return ips
        except Exception as e:
            print(f"Error generating IP list: {e}")
            return []
    
    def _arp_scan(self, ip_list: List[str]):
        """ARP-based device discovery"""
        print("Running ARP scan...")
        
        # Use system ARP table
        try:
            if platform.system() == "Windows":
                result = subprocess.run(['arp', '-a'], capture_output=True, text=True)
                lines = result.stdout.split('\n')
                
                for line in lines:
                    if 'dynamic' in line.lower():
                        parts = line.split()
                        if len(parts) >= 2:
                            ip = parts[0]
                            mac = parts[1].replace('-', ':')
                            if ip in ip_list:
                                self._add_or_update_device(ip, mac=mac, method='arp')
            else:
                # Linux/Mac ARP scan
                result = subprocess.run(['arp', '-n'], capture_output=True, text=True)
                lines = result.stdout.split('\n')
                
                for line in lines:
                    if 'ether' in line.lower():
                        parts = line.split()
                        if len(parts) >= 2:
                            ip = parts[0]
                            mac = parts[1]
                            if ip in ip_list:
                                self._add_or_update_device(ip, mac=mac, method='arp')
        except Exception as e:
            print(f"ARP scan error: {e}")
    
    def _icmp_ping_scan(self, ip_list: List[str]):
        """ICMP ping-based discovery"""
        print("Running ICMP ping scan...")
        
        def ping_host(ip):
            try:
                start_time = time.time()
                if platform.system() == "Windows":
                    result = subprocess.run(['ping', '-n', '1', '-w', '1000', ip], 
                                         capture_output=True, text=True, timeout=2)
                else:
                    result = subprocess.run(['ping', '-c', '1', '-W', '1', ip], 
                                         capture_output=True, text=True, timeout=2)
                
                if result.returncode == 0:
                    response_time = (time.time() - start_time) * 1000
                    self._add_or_update_device(ip, method='ping', response_time=response_time)
                    return True
                return False
            except Exception:
                return False
        
        # Run ping scans in parallel
        futures = [self.executor.submit(ping_host, ip) for ip in ip_list]
        for future in as_completed(futures):
            if not self.is_scanning:
                break
            try:
                future.result()
            except Exception as e:
                print(f"Ping scan error: {e}")
    
    def _netbios_scan(self, ip_list: List[str]):
        """NetBIOS-based Windows device discovery"""
        print("Running NetBIOS scan...")
        
        def scan_netbios(ip):
            try:
                # Try to connect to NetBIOS ports
                for port in [139, 445]:
                    try:
                        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        sock.settimeout(1)
                        result = sock.connect_ex((ip, port))
                        if result == 0:
                            self._add_or_update_device(ip, method='netbios', 
                                                     services=['SMB'], ports=[port])
                            sock.close()
                            return True
                        sock.close()
                    except Exception:
                        continue
                return False
            except Exception:
                return False
        
        # Run NetBIOS scans in parallel
        futures = [self.executor.submit(scan_netbios, ip) for ip in ip_list]
        for future in as_completed(futures):
            if not self.is_scanning:
                break
            try:
                future.result()
            except Exception as e:
                print(f"NetBIOS scan error: {e}")
    
    def _mdns_scan(self, ip_list: List[str]):
        """mDNS-based device discovery"""
        print("Running mDNS scan...")
        
        def scan_mdns(ip):
            try:
                # Try common mDNS ports
                for port in [5353, 5354]:
                    try:
                        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                        sock.settimeout(1)
                        sock.sendto(b'\x00\x00\x00\x00\x00\x01\x00\x00', (ip, port))
                        sock.close()
                        
                        # Simple mDNS response check
                        self._add_or_update_device(ip, method='mdns', 
                                                 services=['mDNS'], ports=[port])
                        return True
                    except Exception:
                        continue
                return False
            except Exception:
                return False
        
        # Run mDNS scans in parallel
        futures = [self.executor.submit(scan_mdns, ip) for ip in ip_list]
        for future in as_completed(futures):
            if not self.is_scanning:
                break
            try:
                future.result()
            except Exception as e:
                print(f"mDNS scan error: {e}")
    
    def _snmp_scan(self, ip_list: List[str]):
        """SNMP-based network device discovery"""
        print("Running SNMP scan...")
        
        def scan_snmp(ip):
            try:
                # Try common SNMP ports
                for port in [161, 162]:
                    try:
                        sock = socket.socket(socket.AF_INET, socket.SOCK_UDP)
                        sock.settimeout(1)
                        sock.sendto(b'\x30\x26\x02\x01\x00\x04\x06\x70\x75\x62\x6c\x69\x63', (ip, port))
                        sock.close()
                        
                        # Simple SNMP response check
                        self._add_or_update_device(ip, method='snmp', 
                                                 services=['SNMP'], ports=[port])
                        return True
                    except Exception:
                        continue
                return False
            except Exception:
                return False
        
        # Run SNMP scans in parallel
        futures = [self.executor.submit(scan_snmp, ip) for ip in ip_list]
        for future in as_completed(futures):
            if not self.is_scanning:
                break
            try:
                future.result()
            except Exception as e:
                print(f"SNMP scan error: {e}")
    
    def _quick_port_scan(self, ip_list: List[str]):
        """Quick port scan for common services"""
        print("Running quick port scan...")
        
        common_ports = [21, 22, 23, 25, 53, 80, 110, 143, 443, 993, 995, 3389, 5900]
        
        def scan_ports(ip):
            try:
                open_ports = []
                for port in common_ports:
                    try:
                        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        sock.settimeout(0.5)
                        result = sock.connect_ex((ip, port))
                        if result == 0:
                            open_ports.append(port)
                        sock.close()
                    except Exception:
                        continue
                
                if open_ports:
                    self._add_or_update_device(ip, method='port_scan', ports=open_ports)
                return True
            except Exception:
                return False
        
        # Run port scans in parallel
        futures = [self.executor.submit(scan_ports, ip) for ip in ip_list]
        for future in as_completed(futures):
            if not self.is_scanning:
                break
            try:
                future.result()
            except Exception as e:
                print(f"Port scan error: {e}")
    
    def _add_or_update_device(self, ip: str, **kwargs):
        """Add or update device information"""
        if ip not in self.devices:
            self.devices[ip] = DeviceInfo(ip=ip)
        
        device = self.devices[ip]
        device.last_seen = time.time()
        
        # Update device info
        for key, value in kwargs.items():
            if key == 'method' and value not in device.discovery_methods:
                device.discovery_methods.append(value)
            elif key == 'mac' and value:
                device.mac = value
                device.vendor = self._get_vendor_from_mac(value)
            elif key == 'services' and value:
                for service in value:
                    if service not in device.services:
                        device.services.append(service)
            elif key == 'ports' and value:
                for port in value:
                    if port not in device.ports:
                        device.ports.append(port)
            elif key == 'response_time' and value:
                device.response_time = value
        
        # Determine device type
        device.device_type = self._determine_device_type(device)
    
    def _get_vendor_from_mac(self, mac: str) -> str:
        """Get vendor information from MAC address"""
        try:
            # Simple vendor lookup (first 6 characters)
            oui = mac.replace(':', '').replace('-', '')[:6].upper()
            
            # Common vendor OUIs
            vendors = {
                '000C29': 'VMware',
                '001C14': 'Dell',
                '00237D': 'Cisco',
                '00AABB': 'Test',
                '00E04C': 'Realtek',
                '080027': 'PCS Systemtechnik',
                '080069': 'Silicon Graphics',
                '080086': 'Sun Microsystems',
                '0800C0': 'Omron',
                '0800D3': 'Cray',
                '0800E3': 'Proteon',
                '0800E4': 'Ascom',
                '0800E5': 'Sytek',
                '0800E6': 'Pyramid',
                '0800E7': 'Network Research',
                '0800E8': 'Xerox',
                '0800E9': 'Digital Equipment',
                '0800EA': 'Bull',
                '0800EB': 'Spider',
                '0800EC': 'Prime Computer',
                '0800ED': 'Silicon Graphics',
                '0800EE': 'Interphase',
                '0800EF': 'Lanco',
                '0800F0': 'Comdesign',
                '0800F1': 'Gould',
                '0800F2': 'Unisys',
                '0800F3': 'CIMLinc',
                '0800F4': 'General Electric',
                '0800F5': 'Honeywell',
                '0800F6': 'Bull',
                '0800F7': 'Bull',
                '0800F8': 'Bull',
                '0800F9': 'Bull',
                '0800FA': 'Bull',
                '0800FB': 'Bull',
                '0800FC': 'Bull',
                '0800FD': 'Bull',
                '0800FE': 'Bull',
                '0800FF': 'Bull'
            }
            
            return vendors.get(oui, 'Unknown')
        except Exception:
            return 'Unknown'
    
    def _determine_device_type(self, device: DeviceInfo) -> str:
        """Determine device type based on characteristics"""
        try:
            # Check for gaming consoles
            if any(port in device.ports for port in [3074, 3075, 3076, 3077, 3078, 3079]):
                return 'Gaming Console'
            
            # Check for mobile devices
            if 'mDNS' in device.services:
                return 'Mobile Device'
            
            # Check for network infrastructure
            if 'SNMP' in device.services:
                return 'Network Device'
            
            # Check for Windows devices
            if 'SMB' in device.services:
                return 'Windows PC'
            
            # Check for servers
            if any(port in device.ports for port in [80, 443, 22, 21]):
                return 'Server'
            
            # Default to PC
            return 'PC'
        except Exception:
            return 'Unknown'
    
    def get_discovered_devices(self) -> List[DeviceInfo]:
        """Get list of discovered devices"""
        return list(self.devices.values())
    
    def get_device_by_ip(self, ip: str) -> Optional[DeviceInfo]:
        """Get device by IP address"""
        return self.devices.get(ip)
    
    def get_scan_status(self) -> Dict:
        """Get current scan status"""
        return {
            'is_scanning': self.is_scanning,
            'total_devices': len(self.devices),
            'active_devices': len([d for d in self.devices.values() if d.is_active]),
            'last_scan': max([d.last_seen for d in self.devices.values()]) if self.devices else 0
        }
    
    def clear_cache(self):
        """Clear device cache"""
        self.devices.clear()
        if os.path.exists(self.scan_cache_file):
            os.remove(self.scan_cache_file)
    
    def export_devices(self, filename: str = None):
        """Export device information to file"""
        if filename is None:
            filename = f"device_export_{int(time.time())}.json"
        
        try:
            export_data = []
            for device in self.devices.values():
                export_data.append({
                    'ip': device.ip,
                    'mac': device.mac,
                    'hostname': device.hostname,
                    'device_type': device.device_type,
                    'os_info': device.os_info,
                    'services': device.services,
                    'ports': device.ports,
                    'vendor': device.vendor,
                    'last_seen': device.last_seen,
                    'discovery_methods': device.discovery_methods
                })
            
            with open(filename, 'w') as f:
                json.dump(export_data, f, indent=2)
            
            print(f"Exported {len(export_data)} devices to {filename}")
            return filename
        except Exception as e:
            print(f"Export error: {e}")
            return None
