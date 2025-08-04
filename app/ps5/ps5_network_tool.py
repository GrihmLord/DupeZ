#!/usr/bin/env python3
"""
PS5 Network Management Tool
Specialized tool for PS5 network monitoring and control
"""

import socket
import subprocess
import threading
import time
import platform
import psutil
from typing import Dict, List, Optional, Set
from dataclasses import dataclass
from app.logs.logger import log_info, log_error

try:
    from scapy.all import ARP, Ether, send, srp, sr1, IP, ICMP, TCP, UDP
    SCAPY_AVAILABLE = True
except ImportError:
    SCAPY_AVAILABLE = False
    log_error("Scapy not available - some PS5 features will be disabled")

@dataclass
class PS5Device:
    """PS5 device information"""
    ip: str
    mac: str
    hostname: str
    device_type: str
    last_seen: float
    is_online: bool
    network_interface: str
    ps5_services: List[str]
    bandwidth_usage: Dict[str, float]
    connection_quality: str

class PS5NetworkTool:
    """PS5-specific network management tool"""
    
    def __init__(self):
        self.ps5_devices: Dict[str, PS5Device] = {}
        self.ps5_ips: Set[str] = set()
        self.ps5_services = {
            'psn': [80, 443, 3074, 3075, 3076, 3659, 14000, 14001, 14002, 14003, 14004, 14005],
            'game_servers': [3074, 3075, 3076, 3659, 14000, 14001, 14002, 14003, 14004, 14005],
            'media': [80, 443, 1935, 554],
            'updates': [80, 443, 8080],
            'remote_play': [9295, 9296, 9297],
            'party_chat': [3659, 14000, 14001, 14002, 14003, 14004, 14005],
            'cloud_gaming': [80, 443, 8080, 8443]
        }
        self.running = False
        self.scan_thread = None
        self.monitor_thread = None
        self.local_ip = None
        self.local_mac = None
        self._initialize_network_info()
    
    def _initialize_network_info(self):
        """Initialize local network information"""
        try:
            # Get local network info
            interfaces = psutil.net_if_addrs()
            for interface_name, interface_addresses in interfaces.items():
                for addr in interface_addresses:
                    if addr.family == socket.AF_INET and not addr.address.startswith('127.'):
                        self.local_ip = addr.address
                        for mac_addr in interface_addresses:
                            if mac_addr.family == psutil.AF_LINK:
                                self.local_mac = mac_addr.address.replace('-', ':')
                                break
                        break
                if self.local_ip:
                    break
            log_info(f"PS5 Tool initialized - Local IP: {self.local_ip}, MAC: {self.local_mac}")
        except Exception as e:
            log_error(f"Failed to initialize PS5 network info: {e}")
    
    def scan_for_ps5_devices(self) -> List[PS5Device]:
        """Scan network for PS5 devices specifically"""
        log_info("🔍 Scanning for PS5 devices...")
        ps5_devices = []
        
        try:
            # Common PS5 IP patterns and ranges
            ps5_ip_ranges = [
                "192.168.1.", "192.168.0.", "192.168.137.", "10.0.0.", "172.16.", "172.20."
            ]
            
            # PS5-specific ports to check
            ps5_ports = [3074, 3075, 3076, 3659, 14000, 14001, 14002, 14003, 14004, 14005]
            
            for base_ip in ps5_ip_ranges:
                for i in range(1, 255):
                    ip = f"{base_ip}{i}"
                    
                    # Skip local IP
                    if ip == self.local_ip:
                        continue
                    
                    # Check if device responds to PS5-specific ports
                    if self._is_ps5_device(ip, ps5_ports):
                        device = self._create_ps5_device(ip)
                        if device:
                            ps5_devices.append(device)
                            self.ps5_devices[ip] = device
                            self.ps5_ips.add(ip)
                            log_info(f"🎮 Found PS5 device: {ip} ({device.hostname})")
            
            log_info(f"🎮 PS5 scan complete - Found {len(ps5_devices)} PS5 devices")
            return ps5_devices
            
        except Exception as e:
            log_error(f"PS5 scan failed: {e}")
            return []
    
    def _is_ps5_device(self, ip: str, ps5_ports: List[int]) -> bool:
        """Check if IP is a PS5 device"""
        try:
            # Quick ping test
            result = subprocess.run(["ping", "-n", "1", "-w", "1000", ip], 
                                  capture_output=True, text=True, timeout=2)
            if result.returncode != 0:
                return False
            
            # Check PS5-specific ports
            ps5_port_count = 0
            for port in ps5_ports:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(1)
                    result = sock.connect_ex((ip, port))
                    sock.close()
                    if result == 0:
                        ps5_port_count += 1
                except:
                    continue
            
            # If device responds to multiple PS5 ports, it's likely a PS5
            return ps5_port_count >= 2
            
        except Exception as e:
            log_error(f"Error checking PS5 device {ip}: {e}")
            return False
    
    def _create_ps5_device(self, ip: str) -> Optional[PS5Device]:
        """Create PS5 device object"""
        try:
            # Get MAC address
            mac = self._get_mac_address(ip)
            
            # Get hostname
            hostname = self._get_hostname(ip)
            
            # Determine device type
            device_type = self._determine_ps5_type(ip)
            
            # Check PS5 services
            ps5_services = self._check_ps5_services(ip)
            
            # Get bandwidth usage
            bandwidth_usage = self._get_bandwidth_usage(ip)
            
            # Get connection quality
            connection_quality = self._get_connection_quality(ip)
            
            return PS5Device(
                ip=ip,
                mac=mac,
                hostname=hostname,
                device_type=device_type,
                last_seen=time.time(),
                is_online=True,
                network_interface=self._get_network_interface(ip),
                ps5_services=ps5_services,
                bandwidth_usage=bandwidth_usage,
                connection_quality=connection_quality
            )
            
        except Exception as e:
            log_error(f"Error creating PS5 device {ip}: {e}")
            return None
    
    def _get_mac_address(self, ip: str) -> str:
        """Get MAC address for IP"""
        try:
            if platform.system() == "Windows":
                result = subprocess.run(["arp", "-a", ip], 
                                      capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    lines = result.stdout.split('\n')
                    for line in lines:
                        if ip in line:
                            parts = line.split()
                            for part in parts:
                                if ':' in part or '-' in part:
                                    return part.replace('-', ':')
            return None
        except Exception as e:
            log_error(f"Error getting MAC for {ip}: {e}")
            return None
    
    def _get_hostname(self, ip: str) -> str:
        """Get hostname for IP"""
        try:
            result = subprocess.run(["nslookup", ip], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                lines = result.stdout.split('\n')
                for line in lines:
                    if 'Name:' in line:
                        return line.split('Name:')[1].strip()
            return None
        except Exception as e:
            log_error(f"Error getting hostname for {ip}: {e}")
            return None
    
    def _determine_ps5_type(self, ip: str) -> str:
        """Determine PS5 device type"""
        try:
            # Check for specific PS5 services
            ps5_services = self._check_ps5_services(ip)
            
            if 'psn' in ps5_services and 'game_servers' in ps5_services:
                return "PS5 (Gaming)"
            elif 'media' in ps5_services:
                return "PS5 (Media)"
            elif 'remote_play' in ps5_services:
                return "PS5 (Remote Play)"
            elif 'party_chat' in ps5_services:
                return "PS5 (Party Chat)"
            elif 'cloud_gaming' in ps5_services:
                return "PS5 (Cloud Gaming)"
            else:
                return "PS5 (Unknown)"
                
        except Exception as e:
            log_error(f"Error determining PS5 type for {ip}: {e}")
            return None
    
    def _check_ps5_services(self, ip: str) -> List[str]:
        """Check which PS5 services are active"""
        active_services = []
        
        try:
            for service_name, ports in self.ps5_services.items():
                for port in ports:
                    try:
                        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        sock.settimeout(1)
                        result = sock.connect_ex((ip, port))
                        sock.close()
                        if result == 0:
                            active_services.append(service_name)
                            break
                    except:
                        continue
        except Exception as e:
            log_error(f"Error checking PS5 services for {ip}: {e}")
        
        return active_services
    
    def _get_bandwidth_usage(self, ip: str) -> Dict[str, float]:
        """Get bandwidth usage for PS5 device"""
        try:
            # This would require more sophisticated network monitoring
            # For now, return placeholder data
            return {
                'download': 0.0,
                'upload': 0.0,
                'total': 0.0
            }
        except Exception as e:
            log_error(f"Error getting bandwidth for {ip}: {e}")
            return {'download': 0.0, 'upload': 0.0, 'total': 0.0}
    
    def _get_connection_quality(self, ip: str) -> str:
        """Get connection quality for PS5 device"""
        try:
            # Ping test for latency
            result = subprocess.run(["ping", "-n", "3", ip], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                # Parse ping results for latency
                lines = result.stdout.split('\n')
                for line in lines:
                    if 'Average' in line:
                        avg_time = line.split('Average =')[1].split('ms')[0].strip()
                        try:
                            latency = float(avg_time)
                            if latency < 10:
                                return "Excellent"
                            elif latency < 50:
                                return "Good"
                            elif latency < 100:
                                return "Fair"
                            else:
                                return "Poor"
                        except:
                            return "Unknown"
            return "Unknown"
        except Exception as e:
            log_error(f"Error getting connection quality for {ip}: {e}")
            return "Unknown"
    
    def _get_network_interface(self, ip: str) -> str:
        """Get network interface for IP"""
        try:
            # Determine which interface this IP belongs to
            interfaces = psutil.net_if_addrs()
            for interface_name, interface_addresses in interfaces.items():
                for addr in interface_addresses:
                    if addr.family == socket.AF_INET:
                        # Check if IP is in same subnet
                        if self._is_same_subnet(addr.address, ip):
                            return interface_name
            return "Unknown"
        except Exception as e:
            log_error(f"Error getting network interface for {ip}: {e}")
            return "Unknown"
    
    def _is_same_subnet(self, ip1: str, ip2: str) -> bool:
        """Check if two IPs are in the same subnet"""
        try:
            # Simple subnet check (assumes /24)
            parts1 = ip1.split('.')
            parts2 = ip2.split('.')
            return parts1[0] == parts2[0] and parts1[1] == parts2[1] and parts1[2] == parts2[2]
        except:
            return False
    
    def start_monitoring(self):
        """Start PS5 device monitoring"""
        if self.running:
            return
        
        self.running = True
        self.monitor_thread = threading.Thread(target=self._monitor_ps5_devices, daemon=True)
        self.monitor_thread.start()
        log_info("🎮 PS5 monitoring started")
    
    def stop_monitoring(self):
        """Stop PS5 device monitoring"""
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        log_info("🎮 PS5 monitoring stopped")
    
    def _monitor_ps5_devices(self):
        """Monitor PS5 devices continuously"""
        while self.running:
            try:
                # Update device status
                for ip, device in self.ps5_devices.items():
                    # Check if device is still online
                    is_online = self._check_device_online(ip)
                    device.is_online = is_online
                    device.last_seen = time.time()
                    
                    if is_online:
                        # Update bandwidth and connection quality
                        device.bandwidth_usage = self._get_bandwidth_usage(ip)
                        device.connection_quality = self._get_connection_quality(ip)
                        device.ps5_services = self._check_ps5_services(ip)
                
                # Scan for new PS5 devices every 30 seconds
                if time.time() % 30 < 1:
                    new_devices = self.scan_for_ps5_devices()
                    for device in new_devices:
                        if device.ip not in self.ps5_devices:
                            self.ps5_devices[device.ip] = device
                            self.ps5_ips.add(device.ip)
                            log_info(f"🎮 New PS5 device discovered: {device.ip}")
                
                time.sleep(5)  # Check every 5 seconds
                
            except Exception as e:
                log_error(f"PS5 monitoring error: {e}")
                time.sleep(10)
    
    def _check_device_online(self, ip: str) -> bool:
        """Check if PS5 device is online"""
        try:
            result = subprocess.run(["ping", "-n", "1", "-w", "1000", ip], 
                                  capture_output=True, text=True, timeout=2)
            return result.returncode == 0
        except Exception as e:
            log_error(f"Error checking device online {ip}: {e}")
            return False
    
    def get_ps5_devices(self) -> List[PS5Device]:
        """Get all PS5 devices"""
        return list(self.ps5_devices.values())
    
    def get_ps5_ips(self) -> List[str]:
        """Get all PS5 IP addresses"""
        return list(self.ps5_ips)
    
    def get_online_ps5_devices(self) -> List[PS5Device]:
        """Get online PS5 devices only"""
        return [device for device in self.ps5_devices.values() if device.is_online]
    
    def block_ps5_device(self, ip: str) -> bool:
        """Block a specific PS5 device"""
        try:
            log_info(f"🎮 Blocking PS5 device: {ip}")
            
            # Use NetCut-style blocking for PS5
            from app.firewall.netcut_blocker import netcut_blocker
            success = netcut_blocker.block_device(ip)
            
            if success:
                log_info(f"✅ PS5 device {ip} blocked successfully")
                return True
            else:
                log_error(f"❌ Failed to block PS5 device {ip}")
                return False
                
        except Exception as e:
            log_error(f"Error blocking PS5 device {ip}: {e}")
            return False
    
    def unblock_ps5_device(self, ip: str) -> bool:
        """Unblock a specific PS5 device"""
        try:
            log_info(f"🎮 Unblocking PS5 device: {ip}")
            
            # Use NetCut-style unblocking for PS5
            from app.firewall.netcut_blocker import netcut_blocker
            success = netcut_blocker.unblock_device(ip)
            
            if success:
                log_info(f"✅ PS5 device {ip} unblocked successfully")
                return True
            else:
                log_error(f"❌ Failed to unblock PS5 device {ip}")
                return False
                
        except Exception as e:
            log_error(f"Error unblocking PS5 device {ip}: {e}")
            return False
    
    def block_all_ps5_devices(self) -> Dict[str, bool]:
        """Block all PS5 devices"""
        results = {}
        for ip in self.ps5_ips:
            results[ip] = self.block_ps5_device(ip)
        return results
    
    def unblock_all_ps5_devices(self) -> Dict[str, bool]:
        """Unblock all PS5 devices"""
        results = {}
        for ip in self.ps5_ips:
            results[ip] = self.unblock_ps5_device(ip)
        return results
    
    def get_ps5_network_stats(self) -> Dict:
        """Get PS5 network statistics"""
        try:
            online_count = len(self.get_online_ps5_devices())
            total_count = len(self.ps5_devices)
            
            # Calculate total bandwidth usage
            total_bandwidth = {'download': 0.0, 'upload': 0.0, 'total': 0.0}
            for device in self.ps5_devices.values():
                if device.is_online:
                    total_bandwidth['download'] += device.bandwidth_usage.get('download', 0)
                    total_bandwidth['upload'] += device.bandwidth_usage.get('upload', 0)
                    total_bandwidth['total'] += device.bandwidth_usage.get('total', 0)
            
            return {
                'total_ps5_devices': total_count,
                'online_ps5_devices': online_count,
                'offline_ps5_devices': total_count - online_count,
                'total_bandwidth': total_bandwidth,
                'ps5_ips': list(self.ps5_ips),
                'local_ip': self.local_ip,
                'local_mac': self.local_mac
            }
        except Exception as e:
            log_error(f"Error getting PS5 network stats: {e}")
            return {}

    def block_gaming_services(self) -> bool:
        """Block PS5 gaming services"""
        try:
            from app.firewall.blocker import block_device
            from app.firewall.netcut_blocker import netcut_blocker
            
            # Block common gaming ports
            gaming_ports = [3074, 3075, 3076, 3659, 14000, 14001, 14002, 14003, 14004, 14005]
            
            for ps5_ip in self.ps5_ips:
                # Use firewall blocking
                success = block_device(ps5_ip)
                if success:
                    log_info(f"Blocked gaming services for PS5: {ps5_ip}")
                else:
                    log_error(f"Failed to block gaming services for PS5: {ps5_ip}")
            
            # Also block at network level
            netcut_blocker.start()
            
            return True
            
        except Exception as e:
            log_error(f"Error blocking gaming services: {e}")
            return False
    
    def block_media_services(self) -> bool:
        """Block PS5 media services"""
        try:
            from app.firewall.blocker import block_device
            
            # Block media streaming ports
            media_ports = [80, 443, 1935, 554]
            
            for ps5_ip in self.ps5_ips:
                success = block_device(ps5_ip)
                if success:
                    log_info(f"Blocked media services for PS5: {ps5_ip}")
                else:
                    log_error(f"Failed to block media services for PS5: {ps5_ip}")
            
            return True
            
        except Exception as e:
            log_error(f"Error blocking media services: {e}")
            return False
    
    def block_update_services(self) -> bool:
        """Block PS5 update services"""
        try:
            from app.firewall.blocker import block_device
            
            # Block update ports
            update_ports = [80, 443, 8080]
            
            for ps5_ip in self.ps5_ips:
                success = block_device(ps5_ip)
                if success:
                    log_info(f"Blocked update services for PS5: {ps5_ip}")
                else:
                    log_error(f"Failed to block update services for PS5: {ps5_ip}")
            
            return True
            
        except Exception as e:
            log_error(f"Error blocking update services: {e}")
            return False
    
    def block_remote_play(self) -> bool:
        """Block PS5 remote play"""
        try:
            from app.firewall.blocker import block_device
            
            # Block remote play ports
            remote_play_ports = [9295, 9296, 9297]
            
            for ps5_ip in self.ps5_ips:
                success = block_device(ps5_ip)
                if success:
                    log_info(f"Blocked remote play for PS5: {ps5_ip}")
                else:
                    log_error(f"Failed to block remote play for PS5: {ps5_ip}")
            
            return True
            
        except Exception as e:
            log_error(f"Error blocking remote play: {e}")
            return False
    
    def block_psn_services(self) -> bool:
        """Block PSN services"""
        try:
            from app.firewall.blocker import block_device
            
            # Block PSN ports
            psn_ports = [80, 443, 3074, 3075, 3076, 3659, 14000, 14001, 14002, 14003, 14004, 14005]
            
            for ps5_ip in self.ps5_ips:
                success = block_device(ps5_ip)
                if success:
                    log_info(f"Blocked PSN services for PS5: {ps5_ip}")
                else:
                    log_error(f"Failed to block PSN services for PS5: {ps5_ip}")
            
            return True
            
        except Exception as e:
            log_error(f"Error blocking PSN services: {e}")
            return False
    
    def unblock_gaming_services(self) -> bool:
        """Unblock PS5 gaming services"""
        try:
            from app.firewall.blocker import unblock_device
            from app.firewall.netcut_blocker import netcut_blocker
            
            for ps5_ip in self.ps5_ips:
                success = unblock_device(ps5_ip)
                if success:
                    log_info(f"Unblocked gaming services for PS5: {ps5_ip}")
                else:
                    log_error(f"Failed to unblock gaming services for PS5: {ps5_ip}")
            
            # Stop netcut blocking
            netcut_blocker.stop()
            
            return True
            
        except Exception as e:
            log_error(f"Error unblocking gaming services: {e}")
            return False
    
    def unblock_media_services(self) -> bool:
        """Unblock PS5 media services"""
        try:
            from app.firewall.blocker import unblock_device
            
            for ps5_ip in self.ps5_ips:
                success = unblock_device(ps5_ip)
                if success:
                    log_info(f"Unblocked media services for PS5: {ps5_ip}")
                else:
                    log_error(f"Failed to unblock media services for PS5: {ps5_ip}")
            
            return True
            
        except Exception as e:
            log_error(f"Error unblocking media services: {e}")
            return False
    
    def unblock_update_services(self) -> bool:
        """Unblock PS5 update services"""
        try:
            from app.firewall.blocker import unblock_device
            
            for ps5_ip in self.ps5_ips:
                success = unblock_device(ps5_ip)
                if success:
                    log_info(f"Unblocked update services for PS5: {ps5_ip}")
                else:
                    log_error(f"Failed to unblock update services for PS5: {ps5_ip}")
            
            return True
            
        except Exception as e:
            log_error(f"Error unblocking update services: {e}")
            return False
    
    def unblock_remote_play(self) -> bool:
        """Unblock PS5 remote play"""
        try:
            from app.firewall.blocker import unblock_device
            
            for ps5_ip in self.ps5_ips:
                success = unblock_device(ps5_ip)
                if success:
                    log_info(f"Unblocked remote play for PS5: {ps5_ip}")
                else:
                    log_error(f"Failed to unblock remote play for PS5: {ps5_ip}")
            
            return True
            
        except Exception as e:
            log_error(f"Error unblocking remote play: {e}")
            return False
    
    def unblock_psn_services(self) -> bool:
        """Unblock PSN services"""
        try:
            from app.firewall.blocker import unblock_device
            
            for ps5_ip in self.ps5_ips:
                success = unblock_device(ps5_ip)
                if success:
                    log_info(f"Unblocked PSN services for PS5: {ps5_ip}")
                else:
                    log_error(f"Failed to unblock PSN services for PS5: {ps5_ip}")
            
            return True
            
        except Exception as e:
            log_error(f"Error unblocking PSN services: {e}")
            return False

# Global PS5 network tool instance
ps5_network_tool = PS5NetworkTool() 