#!/usr/bin/env python3
"""
UDP Port Interrupter - Laganator Integration
Advanced UDP packet manipulation for DayZ duping
Based on Laganator's UDP port interruption capabilities
"""

import json
import subprocess
import threading
import time
import socket
import struct
import os
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from app.logs.logger import log_info, log_error, log_warning

@dataclass
class DayZServer:
    """DayZ server configuration"""
    name: str
    ip: str
    port: int
    drop_rate: int  # 0-100, percentage of packets to drop
    local: bool = True  # Whether to affect local traffic
    
@dataclass
class UDPPacket:
    """UDP packet structure for manipulation"""
    source_ip: str
    dest_ip: str
    source_port: int
    dest_port: int
    payload: bytes
    timestamp: float

class UDPPortInterrupter:
    """Advanced UDP port interruption system for DayZ duping"""
    
    def __init__(self, config_file: str = "app/config/dayz_servers.json"):
        self.config_file = config_file
        self.servers: List[DayZServer] = []
        self.active_interruptions: Dict[str, threading.Thread] = {}
        self.is_running = False
        self.keybind = "F12"  # Default keybind
        self.timer_duration = 0  # 0 = no timer
        self.timer_active = False
        self.drop_rate = 90  # Default drop rate (90% for lagging without disconnection)
        self.local_traffic = True
        self.shared_traffic = True
        
        # UDP-specific settings
        self.dayz_ports = [2302, 2303, 2304, 2305, 27015, 27016, 27017, 27018]
        self.udp_flood_ports = [7777, 7778, 2302, 2303, 2304, 2305]
        
        # Load configuration
        self.load_config()
        
    def load_config(self):
        """Load server configuration from JSON file"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                    
                self.keybind = config.get('keybind', 'F12')
                self.drop_rate = config.get('drop_rate', 90)
                self.local_traffic = config.get('local', True)
                self.shared_traffic = config.get('shared', True)
                
                # Load servers
                servers_data = config.get('servers', [])
                self.servers = []
                for server_data in servers_data:
                    server = DayZServer(
                        name=server_data.get('name', 'Unknown'),
                        ip=server_data.get('ip', '0.0.0.0'),
                        port=server_data.get('port', 2302),
                        drop_rate=server_data.get('drop_rate', 90),
                        local=server_data.get('local', True)
                    )
                    self.servers.append(server)
                    
                log_info(f"✅ Loaded {len(self.servers)} DayZ servers from config")
            else:
                # Create default configuration
                self.create_default_config()
                
        except Exception as e:
            log_error(f"Failed to load UDP interrupter config: {e}")
            self.create_default_config()
    
    def create_default_config(self):
        """Create default DayZ server configuration"""
        try:
            default_config = {
                "keybind": "F12",
                "drop_rate": 90,
                "local": True,
                "shared": True,
                "servers": [
                    {
                        "name": "DayZ Official Server",
                        "ip": "0.0.0.0",
                        "port": 2302,
                        "drop_rate": 90,
                        "local": True
                    },
                    {
                        "name": "DayZ Community Server",
                        "ip": "0.0.0.0", 
                        "port": 2303,
                        "drop_rate": 90,
                        "local": True
                    }
                ]
            }
            
            # Ensure config directory exists
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
            
            with open(self.config_file, 'w') as f:
                json.dump(default_config, f, indent=2)
                
            log_info("✅ Created default DayZ server configuration")
            
        except Exception as e:
            log_error(f"Failed to create default config: {e}")
    
    def start_udp_interruption(self, target_ips: List[str] = None, 
                              drop_rate: int = None, 
                              duration: int = 0) -> bool:
        """Start UDP port interruption for DayZ duping"""
        try:
            if self.is_running:
                log_info("UDP interruption already active")
                return True
            
            # Use provided drop rate or default
            effective_drop_rate = drop_rate if drop_rate is not None else self.drop_rate
            
            # Use provided target IPs or all servers
            if target_ips:
                targets = target_ips
            else:
                targets = [server.ip for server in self.servers if server.ip != "0.0.0.0"]
                if not targets:
                    # Try to get local IP dynamically instead of hardcoded localhost
                    try:
                        import socket
                        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                            s.connect(("8.8.8.8", 80))
                            local_ip = s.getsockname()[0]
                            targets = [local_ip]
                    except Exception as e:
                        log_error(f"Failed to get local IP: {e}")
                        targets = []  # Empty list instead of hardcoded localhost
            
            log_info(f"🎮 Starting UDP interruption with {effective_drop_rate}% drop rate")
            log_info(f"🎮 Targets: {targets}")
            log_info(f"🎮 Duration: {duration}s" if duration > 0 else "🎮 Duration: Unlimited")
            
            self.is_running = True
            self.timer_duration = duration
            self.drop_rate = effective_drop_rate
            
            # Start interruption threads for each target
            for target_ip in targets:
                thread = threading.Thread(
                    target=self._udp_interruption_worker,
                    args=(target_ip, effective_drop_rate),
                    daemon=True
                )
                thread.start()
                self.active_interruptions[target_ip] = thread
            
            # Start timer if specified
            if duration > 0:
                self.timer_active = True
                timer_thread = threading.Thread(
                    target=self._timer_worker,
                    args=(duration,),
                    daemon=True
                )
                timer_thread.start()
            
            log_info(f"✅ UDP interruption started for {len(targets)} targets")
            return True
            
        except Exception as e:
            log_error(f"Failed to start UDP interruption: {e}")
            return False
    
    def stop_udp_interruption(self) -> bool:
        """Stop UDP port interruption"""
        try:
            if not self.is_running:
                log_info("UDP interruption not active")
                return True
            
            log_info("🛑 Stopping UDP interruption")
            
            self.is_running = False
            self.timer_active = False
            
            # Wait for threads to finish
            for thread in self.active_interruptions.values():
                if thread.is_alive():
                    thread.join(timeout=2)
            
            self.active_interruptions.clear()
            
            log_info("✅ UDP interruption stopped")
            return True
            
        except Exception as e:
            log_error(f"Failed to stop UDP interruption: {e}")
            return False
    
    def _udp_interruption_worker(self, target_ip: str, drop_rate: int):
        """Worker thread for UDP packet interruption"""
        try:
            log_info(f"🎯 Starting UDP interruption worker for {target_ip}")
            
            # Create UDP socket for packet manipulation
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
            while self.is_running and target_ip in self.active_interruptions:
                try:
                    # Send UDP flood packets to DayZ ports
                    self._send_udp_flood_packets(target_ip, sock)
                    
                    # Drop packets based on drop rate
                    if self._should_drop_packet(drop_rate):
                        self._drop_udp_packet(target_ip)
                    
                    # Send malformed UDP packets
                    self._send_malformed_udp_packets(target_ip, sock)
                    
                    # Manipulate packet timing
                    self._manipulate_packet_timing(target_ip)
                    
                    time.sleep(0.01)  # 10ms intervals for smooth interruption
                    
                except Exception as e:
                    log_error(f"UDP interruption worker error for {target_ip}: {e}")
                    break
            
            sock.close()
            log_info(f"🛑 UDP interruption worker stopped for {target_ip}")
            
        except Exception as e:
            log_error(f"Failed to start UDP interruption worker: {e}")
    
    def _send_udp_flood_packets(self, target_ip: str, sock: socket.socket):
        """Send UDP flood packets to disrupt connections"""
        try:
            # Send to DayZ-specific ports
            for port in self.dayz_ports:
                try:
                    # Create fake UDP packet
                    fake_data = b"DISRUPT_PACKET_" + str(time.time()).encode()
                    sock.sendto(fake_data, (target_ip, port))
                    
                    # Send multiple packets with different sizes
                    for size in [64, 128, 256, 512]:
                        fake_data = b"X" * size
                        sock.sendto(fake_data, (target_ip, port))
                        
                except Exception as e:
                    log_error(f"Failed to send UDP flood to {target_ip}:{port}: {e}")
                    
        except Exception as e:
            log_error(f"UDP flood error for {target_ip}: {e}")
    
    def _drop_udp_packet(self, target_ip: str):
        """Simulate dropping UDP packets"""
        try:
            # Use Windows Firewall to drop packets
            if self.local_traffic:
                self._add_firewall_rule(target_ip, "DROP")
                
        except Exception as e:
            log_error(f"Failed to drop UDP packet for {target_ip}: {e}")
    
    def _send_malformed_udp_packets(self, target_ip: str, sock: socket.socket):
        """Send malformed UDP packets to confuse the game"""
        try:
            for port in self.dayz_ports:
                # Send packets with invalid checksums
                malformed_data = self._create_malformed_udp_packet(target_ip, port)
                sock.sendto(malformed_data, (target_ip, port))
                
                # Send packets with wrong port numbers
                sock.sendto(b"MALFORMED", (target_ip, port + 1000))
                
        except Exception as e:
            log_error(f"Failed to send malformed UDP packets to {target_ip}: {e}")
    
    def _create_malformed_udp_packet(self, target_ip: str, port: int) -> bytes:
        """Create a malformed UDP packet"""
        try:
            # Create a UDP packet with invalid checksum
            source_port = 12345
            dest_port = port
            length = 8 + len(b"MALFORMED")
            checksum = 0xFFFF  # Invalid checksum
            
            # UDP header
            header = struct.pack('!HHHH', source_port, dest_port, length, checksum)
            return header + b"MALFORMED"
            
        except Exception as e:
            log_error(f"Failed to create malformed UDP packet: {e}")
            return b"MALFORMED"
    
    def _manipulate_packet_timing(self, target_ip: str):
        """Manipulate packet timing to create lag"""
        try:
            # Add random delays to simulate network congestion
            delay = (self.drop_rate / 100.0) * 0.1  # 0-100ms delay based on drop rate
            time.sleep(delay)
            
        except Exception as e:
            log_error(f"Failed to manipulate packet timing for {target_ip}: {e}")
    
    def _should_drop_packet(self, drop_rate: int) -> bool:
        """Determine if a packet should be dropped based on drop rate"""
        import random
        return random.randint(1, 100) <= drop_rate
    
    def _add_firewall_rule(self, target_ip: str, action: str):
        """Add Windows Firewall rule to drop packets"""
        try:
            rule_name = f"DupeZ_UDP_{target_ip.replace('.', '_')}"
            
            if action == "DROP":
                cmd = [
                    "netsh", "advfirewall", "firewall", "add", "rule",
                    f"name={rule_name}",
                    "dir=out",
                    "action=block",
                    f"remoteip={target_ip}",
                    "protocol=UDP"
                ]
            else:  # ALLOW
                cmd = [
                    "netsh", "advfirewall", "firewall", "add", "rule", 
                    f"name={rule_name}",
                    "dir=out",
                    "action=allow",
                    f"remoteip={target_ip}",
                    "protocol=UDP"
                ]
            
            subprocess.run(cmd, capture_output=True, timeout=5)
            
        except Exception as e:
            log_error(f"Failed to add firewall rule for {target_ip}: {e}")
    
    def _remove_firewall_rule(self, target_ip: str):
        """Remove Windows Firewall rule"""
        try:
            rule_name = f"DupeZ_UDP_{target_ip.replace('.', '_')}"
            cmd = [
                "netsh", "advfirewall", "firewall", "delete", "rule",
                f"name={rule_name}"
            ]
            subprocess.run(cmd, capture_output=True, timeout=5)
            
        except Exception as e:
            log_error(f"Failed to remove firewall rule for {target_ip}: {e}")
    
    def _timer_worker(self, duration: int):
        """Timer worker to automatically stop interruption"""
        try:
            log_info(f"⏰ Timer started: {duration} seconds")
            time.sleep(duration)
            
            if self.timer_active:
                log_info("⏰ Timer expired, stopping UDP interruption")
                self.stop_udp_interruption()
                
        except Exception as e:
            log_error(f"Timer worker error: {e}")
    
    def add_server(self, name: str, ip: str, port: int, drop_rate: int = 90) -> bool:
        """Add a new DayZ server to the configuration"""
        try:
            server = DayZServer(name=name, ip=ip, port=port, drop_rate=drop_rate)
            self.servers.append(server)
            self.save_config()
            log_info(f"✅ Added server: {name} ({ip}:{port})")
            return True
            
        except Exception as e:
            log_error(f"Failed to add server: {e}")
            return False
    
    def remove_server(self, name: str) -> bool:
        """Remove a DayZ server from the configuration"""
        try:
            self.servers = [s for s in self.servers if s.name != name]
            self.save_config()
            log_info(f"✅ Removed server: {name}")
            return True
            
        except Exception as e:
            log_error(f"Failed to remove server: {e}")
            return False
    
    def save_config(self):
        """Save current configuration to file"""
        try:
            config = {
                "keybind": self.keybind,
                "drop_rate": self.drop_rate,
                "local": self.local_traffic,
                "shared": self.shared_traffic,
                "servers": [
                    {
                        "name": server.name,
                        "ip": server.ip,
                        "port": server.port,
                        "drop_rate": server.drop_rate,
                        "local": server.local
                    }
                    for server in self.servers
                ]
            }
            
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=2)
                
            log_info("✅ UDP interrupter configuration saved")
            
        except Exception as e:
            log_error(f"Failed to save UDP interrupter config: {e}")
    
    def get_status(self) -> Dict[str, any]:
        """Get current status of UDP interrupter"""
        return {
            "is_running": self.is_running,
            "active_targets": list(self.active_interruptions.keys()),
            "drop_rate": self.drop_rate,
            "timer_active": self.timer_active,
            "timer_duration": self.timer_duration,
            "servers_count": len(self.servers),
            "keybind": self.keybind,
            "local_traffic": self.local_traffic,
            "shared_traffic": self.shared_traffic
        }
    
    def get_servers(self) -> List[DayZServer]:
        """Get list of configured servers"""
        return self.servers.copy()
    
    def set_drop_rate(self, drop_rate: int):
        """Set the drop rate (0-100)"""
        if 0 <= drop_rate <= 100:
            self.drop_rate = drop_rate
            log_info(f"✅ Drop rate set to {drop_rate}%")
        else:
            log_error("Drop rate must be between 0 and 100")
    
    def set_keybind(self, keybind: str):
        """Set the keybind for quick activation"""
        self.keybind = keybind
        log_info(f"✅ Keybind set to {keybind}")
    
    def set_timer_duration(self, duration: int):
        """Set timer duration in seconds (0 = no timer)"""
        self.timer_duration = max(0, duration)
        log_info(f"✅ Timer duration set to {duration} seconds") 
