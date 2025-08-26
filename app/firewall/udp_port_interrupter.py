#!/usr/bin/env python3
"""
UDP Port Interrupter Module
Provides UDP port interruption functionality with actual traffic blocking
"""

import socket
import threading
import time
import random
import subprocess
import ctypes
from typing import List, Dict, Optional
from app.logs.logger import log_info, log_error
from datetime import datetime

class DayZServer:
    """DayZ server configuration"""
    def __init__(self, name: str, ip: str, port: int, drop_rate: int, local: bool = False):
        self.name = name
        self.ip = ip
        self.port = port
        self.drop_rate = drop_rate
        self.local = local

class UDPPortInterrupter:
    """UDP port interruption functionality with actual traffic blocking"""
    
    def __init__(self):
        self.is_running = False
        self.target_ips = []
        self.drop_rate = 50
        self.duration = 0  # 0 = manual stop
        self.stop_event = threading.Event()
        self.interruption_thread = None
        self.servers = []  # List of DayZServer objects
        self.local_traffic = True
        self.shared_traffic = True
        self.timer_active = False
        self.timer_duration = 0
        self.active_targets = []
        self.blocked_rules = []  # Track firewall rules we create
        self.requires_admin = True
    
    def is_admin(self) -> bool:
        """Check if running with administrator privileges"""
        try:
            return ctypes.windll.shell32.IsUserAnAdmin()
        except:
            return False
    
    def start_udp_interruption(self, target_ips: List[str] = None, 
                              drop_rate: int = 50, duration: int = 0) -> bool:
        """Start UDP port interruption with actual traffic blocking"""
        try:
            # Check admin privileges
            if self.requires_admin and not self.is_admin():
                log_error("UDP interruption requires administrator privileges")
                return False
            
            if self.is_running:
                log_info("UDP interruption already running")
                return True
            
            if target_ips:
                self.target_ips = target_ips
                self.active_targets = target_ips.copy()
            else:
                # Default to local network
                self.target_ips = ["192.168.1.1", "192.168.1.100"]
                self.active_targets = self.target_ips.copy()
            
            self.drop_rate = drop_rate
            self.duration = duration
            self.timer_duration = duration
            self.timer_active = duration > 0
            self.stop_event.clear()
            self.is_running = True
            
            # Create firewall rules to block traffic
            self._create_firewall_rules()
            
            # Start interruption thread
            self.interruption_thread = threading.Thread(
                target=self._udp_interruption_loop, daemon=True
            )
            self.interruption_thread.start()
            
            log_info(f"UDP interruption started on {len(self.target_ips)} targets with {drop_rate}% drop rate")
            return True
            
        except Exception as e:
            log_error(f"Failed to start UDP interruption: {e}", exception=e)
            return False
    
    def stop_udp_interruption(self) -> bool:
        """Stop UDP port interruption and remove firewall rules"""
        try:
            if not self.is_running:
                return True
            
            self.stop_event.set()
            self.is_running = False
            self.timer_active = False
            self.active_targets = []
            
            # Remove firewall rules
            self._remove_firewall_rules()
            
            if self.interruption_thread:
                self.interruption_thread.join(timeout=5)
            
            log_info("UDP interruption stopped and firewall rules removed")
            return True
            
        except Exception as e:
            log_error(f"Failed to stop UDP interruption: {e}", exception=e)
            return False
    
    def _create_firewall_rules(self):
        """Create Windows Firewall rules to block UDP traffic"""
        try:
            for target_ip in self.target_ips:
                # Block UDP traffic to target IPs
                rule_name = f"DupeZ_UDP_Block_{target_ip.replace('.', '_')}"
                
                # Create outbound rule
                cmd_out = [
                    'netsh', 'advfirewall', 'firewall', 'add', 'rule',
                    f'name="{rule_name}_Out"',
                    'dir=out',
                    'action=block',
                    'protocol=UDP',
                    f'remoteip={target_ip}',
                    'enable=yes'
                ]
                
                # Create inbound rule
                cmd_in = [
                    'netsh', 'advfirewall', 'firewall', 'add', 'rule',
                    f'name="{rule_name}_In"',
                    'dir=in',
                    'action=block',
                    'protocol=UDP',
                    f'remoteip={target_ip}',
                    'enable=yes'
                ]
                
                try:
                    subprocess.run(cmd_out, check=True, capture_output=True)
                    subprocess.run(cmd_in, check=True, capture_output=True)
                    self.blocked_rules.append(rule_name)
                    log_info(f"Created firewall rules for {target_ip}")
                except subprocess.CalledProcessError as e:
                    log_error(f"Failed to create firewall rules for {target_ip}: {e}")
                    
        except Exception as e:
            log_error(f"Error creating firewall rules: {e}")
    
    def _remove_firewall_rules(self):
        """Remove Windows Firewall rules created by this tool"""
        try:
            for rule_name in self.blocked_rules:
                # Remove outbound rule
                cmd_out = [
                    'netsh', 'advfirewall', 'firewall', 'delete', 'rule',
                    f'name="{rule_name}_Out"'
                ]
                
                # Remove inbound rule
                cmd_in = [
                    'netsh', 'advfirewall', 'firewall', 'delete', 'rule',
                    f'name="{rule_name}_In"'
                ]
                
                try:
                    subprocess.run(cmd_out, check=True, capture_output=True)
                    subprocess.run(cmd_in, check=True, capture_output=True)
                    log_info(f"Removed firewall rules for {rule_name}")
                except subprocess.CalledProcessError:
                    # Rule might not exist, ignore
                    pass
                    
            self.blocked_rules.clear()
            
        except Exception as e:
            log_error(f"Error removing firewall rules: {e}")
    
    def _udp_interruption_loop(self):
        """Main UDP interruption loop with packet manipulation"""
        try:
            start_time = time.time()
            
            while not self.stop_event.is_set():
                # Check duration
                if self.duration > 0 and (time.time() - start_time) > self.duration:
                    self.timer_active = False
                    break
                
                # Send malformed UDP packets to targets
                for target_ip in self.target_ips:
                    if self.stop_event.is_set():
                        break
                    
                    # Randomly drop packets based on drop rate
                    if random.randint(1, 100) <= self.drop_rate:
                        continue
                    
                    try:
                        # Send malformed UDP packets to disrupt traffic
                        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                        sock.settimeout(0.1)
                        
                        # Send to DayZ and gaming ports
                        for port in [2302, 2303, 2304, 2305, 27015, 27016, 27017, 27018]:
                            try:
                                # Send malformed packet
                                malformed_packet = b"\x00\x00\x00\x00\x00\x00" + b"UDP_DISRUPT"
                                sock.sendto(malformed_packet, (target_ip, port))
                            except:
                                pass
                        
                        sock.close()
                        
                    except Exception as e:
                        # Ignore individual packet errors
                        pass
                
                # Small delay between cycles
                time.sleep(0.01)
                
        except Exception as e:
            log_error(f"UDP interruption loop error: {e}", exception=e)
        finally:
            self.is_running = False
            self.timer_active = False
    
    def get_servers(self) -> List[DayZServer]:
        """Get list of configured DayZ servers"""
        return self.servers.copy()
    
    def add_server(self, name: str, ip: str, port: int, drop_rate: int) -> bool:
        """Add a new DayZ server"""
        try:
            server = DayZServer(name, ip, port, drop_rate)
            self.servers.append(server)
            log_info(f"Added DayZ server: {name} ({ip}:{port})")
            return True
        except Exception as e:
            log_error(f"Failed to add server: {e}")
            return False
    
    def remove_server(self, name: str) -> bool:
        """Remove a DayZ server by name"""
        try:
            for i, server in enumerate(self.servers):
                if server.name == name:
                    del self.servers[i]
                    log_info(f"Removed DayZ server: {name}")
                    return True
            return False
        except Exception as e:
            log_error(f"Failed to remove server: {e}")
            return False
    
    def set_drop_rate(self, drop_rate: int):
        """Set the drop rate percentage"""
        self.drop_rate = max(0, min(100, drop_rate))
    
    def set_timer_duration(self, duration: int):
        """Set the timer duration in seconds"""
        self.timer_duration = max(0, duration)
    
    def get_status(self) -> Dict:
        """Get UDP interruption status"""
        return {
            "is_running": self.is_running,
            "target_ips": self.target_ips.copy(),
            "active_targets": self.active_targets.copy(),
            "drop_rate": self.drop_rate,
            "duration": self.duration,
            "timer_active": self.timer_active,
            "timer_duration": self.timer_duration,
            "servers": [{"name": s.name, "ip": s.ip, "port": s.port, "drop_rate": s.drop_rate} for s in self.servers],
            "admin_required": self.requires_admin,
            "is_admin": self.is_admin(),
            "blocked_rules": len(self.blocked_rules)
        }

    def scan_for_dayz_servers(self) -> List['DayZServer']:
        """Scan for DayZ servers on the local network with enhanced detection"""
        try:
            log_info("Starting enhanced DayZ server scan...")
            
            # Get local IP and determine network range
            local_ip = self._get_local_ip()
            if not local_ip:
                log_error("Could not determine local IP address")
                return []
            
            # Determine network range based on local IP
            network_range = self._get_network_range(local_ip)
            log_info(f"Scanning network range: {network_range}")
            
            # Common DayZ server ports
            dayz_ports = [2302, 2303, 2304, 2305, 27015, 27016, 27017, 27018, 27019, 27020]
            
            # Additional ports that might be used
            additional_ports = [7777, 7778, 7779, 7780, 7781, 7782, 7783, 7784, 7785, 7786]
            dayz_ports.extend(additional_ports)
            
            discovered_servers = []
            
            # Scan the network range
            for i in range(1, 255):  # Skip .0 and .255
                target_ip = f"{network_range}.{i}"
                
                try:
                    # Quick ping check first
                    if not self._ping_host(target_ip):
                        continue
                    
                    log_info(f"Host {target_ip} is alive, checking DayZ ports...")
                    
                    # Check each DayZ port
                    for port in dayz_ports:
                        if self._test_dayz_port(target_ip, port):
                            # Create server object
                            server = DayZServer(
                                ip=target_ip,
                                port=port,
                                name=f"DayZ Server {target_ip}:{port}",
                                status="Online",
                                last_seen=datetime.now().isoformat()
                            )
                            
                            # Try to get more information about the server
                            server_info = self._get_server_info(target_ip, port)
                            if server_info:
                                server.name = server_info.get('name', server.name)
                                server.status = server_info.get('status', server.status)
                            
                            discovered_servers.append(server)
                            log_info(f"Found DayZ server: {target_ip}:{port}")
                            
                            # Only add one server per IP to avoid duplicates
                            break
                    
                except Exception as e:
                    log_error(f"Error scanning {target_ip}: {e}")
                    continue
            
            log_info(f"DayZ server scan completed. Found {len(discovered_servers)} servers.")
            return discovered_servers
            
        except Exception as e:
            log_error(f"Error in DayZ server scan: {e}")
            return []
    
    def _get_network_range(self, local_ip: str) -> str:
        """Get the network range from local IP"""
        try:
            # Extract network portion (e.g., 192.168.1 from 192.168.1.100)
            parts = local_ip.split('.')
            if len(parts) == 4:
                return '.'.join(parts[:3])
            return "192.168.1"  # Default fallback
        except Exception as e:
            log_error(f"Error getting network range: {e}")
            return "192.168.1"
    
    def _get_server_info(self, ip: str, port: int) -> Optional[Dict]:
        """Try to get additional server information"""
        try:
            # Try to connect and get basic info
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            
            result = sock.connect_ex((ip, port))
            if result == 0:
                # Connection successful, try to get some data
                try:
                    sock.send(b"\x00")  # Send null byte
                    data = sock.recv(1024)
                    if data:
                        # Try to extract readable text
                        text = data.decode('utf-8', errors='ignore')
                        if text.strip():
                            return {
                                'name': f"DayZ Server ({text[:50].strip()})",
                                'status': 'Online'
                            }
                except:
                    pass
                finally:
                    sock.close()
            
            return None
            
        except Exception as e:
            log_error(f"Error getting server info for {ip}:{port}: {e}")
            return None
    
    def auto_detect_and_add_servers(self) -> int:
        """Auto-detect and add DayZ servers to the list"""
        try:
            log_info("Starting auto-detection of DayZ servers...")
            
            # Scan for servers
            discovered_servers = self.scan_for_dayz_servers()
            
            if not discovered_servers:
                log_info("No DayZ servers discovered during auto-scan")
                return 0
            
            # Add discovered servers to the list
            added_count = 0
            for server in discovered_servers:
                # Check if server already exists
                if not any(s.ip == server.ip and s.port == server.port for s in self.servers):
                    self.servers.append(server)
                    added_count += 1
                    log_info(f"Added new server: {server.ip}:{server.port}")
                else:
                    log_info(f"Server already exists: {server.ip}:{server.port}")
            
            log_info(f"Auto-detection completed. Added {added_count} new servers.")
            return added_count
            
        except Exception as e:
            log_error(f"Error in auto-detection: {e}")
            return 0
    
    def _get_local_ip(self) -> Optional[str]:
        """Get local IP address"""
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            return local_ip
        except:
            return None
    
    def _ping_host(self, ip: str) -> bool:
        """Quick ping test for host availability"""
        try:
            import subprocess
            result = subprocess.run(["ping", "-n", "1", "-w", "1000", ip], 
                                  capture_output=True, timeout=2)
            return result.returncode == 0
        except:
            return False
    
    def _test_dayz_port(self, ip: str, port: int) -> bool:
        """Test if a port is open and responding like a DayZ server"""
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(1.0)
            
            # Try to connect to the port
            result = s.connect_ex((ip, port))
            s.close()
            
            return result == 0
        except:
            return False

# Global instance
# Global instance - Singleton pattern to prevent duplicate initialization
_udp_port_interrupter = None

def get_udp_port_interrupter():
    """Get singleton UDP port interrupter instance"""
    global _udp_port_interrupter
    if _udp_port_interrupter is None:
        _udp_port_interrupter = UDPPortInterrupter()
    return _udp_port_interrupter

# Backward compatibility
udp_port_interrupter = get_udp_port_interrupter() 
