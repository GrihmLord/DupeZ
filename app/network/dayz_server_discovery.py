#!/usr/bin/env python3
"""
DayZ Server Discovery System
Real-time discovery and monitoring of DayZ servers on your network
"""

import socket
import threading
import time
import subprocess
import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
import json
import os

from app.logs.logger import log_info, log_error, log_warning

@dataclass
class DayZServer:
    """DayZ server information"""
    ip: str
    port: int
    name: str
    type: str
    status: str
    latency: int
    player_count: int
    max_players: int
    map_name: str
    version: str
    last_seen: datetime
    discovery_method: str
    is_local: bool = False
    is_favorite: bool = False

class DayZServerDiscovery:
    """Real DayZ server discovery system"""
    
    def __init__(self):
        self.discovered_servers: Dict[str, DayZServer] = {}
        self.favorite_servers: List[str] = []
        self.discovery_running = False
        self.discovery_thread = None
        self.local_network_range = self._get_local_network_range()
        
        # Load favorite servers
        self._load_favorite_servers()
        
        # Common DayZ server ports
        self.dayz_ports = [2302, 2303, 2304, 2305, 2306, 2307, 2308, 2309, 2310]
        
        # Known DayZ server IPs (you can add your favorites here)
        self.known_servers = [
            {"ip": "192.168.1.100", "port": 2302, "name": "Local DayZ Server", "type": "Private"},
            {"ip": "192.168.1.101", "port": 2303, "name": "Community Server", "type": "Community"},
            # Add more known servers here
        ]
    
    def _get_local_network_range(self) -> List[str]:
        """Get local network range for scanning"""
        try:
            # Get local IP address
            hostname = socket.gethostname()
            local_ip = socket.gethostbyname(hostname)
            
            # Extract network prefix (assuming /24 subnet)
            network_prefix = '.'.join(local_ip.split('.')[:-1])
            network_range = [f"{network_prefix}.{i}" for i in range(1, 255)]
            
            log_info(f"Local network range: {network_prefix}.0/24")
            return network_range
            
        except Exception as e:
            log_error(f"Error getting local network range: {e}")
            # Fallback to common local ranges
            return [
                "192.168.1.{}", "192.168.0.{}", "10.0.0.{}", 
                "172.16.0.{}", "172.17.0.{}", "172.18.0.{}"
            ]
    
    def _load_favorite_servers(self):
        """Load favorite servers from configuration"""
        try:
            config_file = "app/config/dayz_servers.json"
            if os.path.exists(config_file):
                with open(config_file, 'r') as f:
                    config = json.load(f)
                    self.favorite_servers = config.get('favorites', [])
                    log_info(f"Loaded {len(self.favorite_servers)} favorite servers")
        except Exception as e:
            log_error(f"Error loading favorite servers: {e}")
    
    def _save_favorite_servers(self):
        """Save favorite servers to configuration"""
        try:
            config_dir = "app/config"
            os.makedirs(config_dir, exist_ok=True)
            
            config_file = os.path.join(config_dir, "dayz_servers.json")
            config = {
                'favorites': self.favorite_servers,
                'last_updated': datetime.now().isoformat()
            }
            
            with open(config_file, 'w') as f:
                json.dump(config, f, indent=2)
                
            log_info("Favorite servers saved")
        except Exception as e:
            log_error(f"Error saving favorite servers: {e}")
    
    def start_discovery(self):
        """Start DayZ server discovery"""
        if self.discovery_running:
            log_warning("Discovery already running")
            return
        
        self.discovery_running = True
        self.discovery_thread = threading.Thread(target=self._discovery_loop, daemon=True)
        self.discovery_thread.start()
        log_info("DayZ server discovery started")
    
    def stop_discovery(self):
        """Stop DayZ server discovery"""
        self.discovery_running = False
        if self.discovery_thread:
            self.discovery_thread.join(timeout=5)
        log_info("DayZ server discovery stopped")
    
    def _discovery_loop(self):
        """Main discovery loop"""
        while self.discovery_running:
            try:
                # Scan for DayZ servers
                self._scan_known_servers()
                self._scan_local_network()
                self._scan_public_servers()
                
                # Update server statuses
                self._update_server_statuses()
                
                # Wait before next scan
                time.sleep(60)  # Scan every minute
                
            except Exception as e:
                log_error(f"Error in discovery loop: {e}")
                time.sleep(30)
    
    def _scan_known_servers(self):
        """Scan known DayZ servers"""
        for server_info in self.known_servers:
            try:
                ip = server_info['ip']
                port = server_info['port']
                
                # Check if server is reachable
                if self._is_server_reachable(ip, port):
                    server = DayZServer(
                        ip=ip,
                        port=port,
                        name=server_info['name'],
                        type=server_info['type'],
                        status='Online',
                        latency=self._ping_server(ip, port),
                        player_count=0,
                        max_players=0,
                        map_name='Unknown',
                        version='Unknown',
                        last_seen=datetime.now(),
                        discovery_method='Known',
                        is_local=self._is_local_ip(ip)
                    )
                    
                    self.discovered_servers[f"{ip}:{port}"] = server
                    log_info(f"Known server found: {ip}:{port}")
                
            except Exception as e:
                log_error(f"Error scanning known server {ip}:{port}: {e}")
    
    def _scan_local_network(self):
        """Scan local network for DayZ servers"""
        try:
            log_info("Scanning local network for DayZ servers...")
            
            # Use multiple scanning methods
            self._scan_with_nmap()
            self._scan_with_netstat()
            self._scan_with_arp()
            
        except Exception as e:
            log_error(f"Error scanning local network: {e}")
    
    def _scan_with_nmap(self):
        """Scan for DayZ servers using Nmap"""
        try:
            # Check if nmap is available
            if not self._is_nmap_available():
                return
            
            # Scan common DayZ ports on local network
            for port in self.dayz_ports:
                try:
                    # Use nmap to scan for open ports
                    cmd = f"nmap -p {port} --open --max-retries 1 --host-timeout 5s {self.local_network_range[0]}"
                    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
                    
                    if result.returncode == 0:
                        # Parse nmap output for open ports
                        open_hosts = self._parse_nmap_output(result.stdout, port)
                        for host in open_hosts:
                            self._check_dayz_server(host, port)
                            
                except Exception as e:
                    log_error(f"Error scanning port {port} with nmap: {e}")
                    
        except Exception as e:
            log_error(f"Error in nmap scan: {e}")
    
    def _scan_with_netstat(self):
        """Scan for DayZ servers using netstat"""
        try:
            # Use netstat to find active connections
            cmd = "netstat -an | findstr :230"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                connections = self._parse_netstat_output(result.stdout)
                for conn in connections:
                    if conn['port'] in self.dayz_ports:
                        self._check_dayz_server(conn['ip'], conn['port'])
                        
        except Exception as e:
            log_error(f"Error in netstat scan: {e}")
    
    def _scan_with_arp(self):
        """Scan for DayZ servers using ARP table"""
        try:
            # Get ARP table to find active hosts
            cmd = "arp -a"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                hosts = self._parse_arp_output(result.stdout)
                for host in hosts:
                    # Check if host has DayZ servers
                    for port in self.dayz_ports:
                        self._check_dayz_server(host, port)
                        
        except Exception as e:
            log_error(f"Error in ARP scan: {e}")
    
    def _scan_public_servers(self):
        """Scan for public DayZ servers"""
        try:
            # This would integrate with public DayZ server lists
            # For now, we'll scan some common public server IPs
            public_ranges = [
                "51.79.0.0/16",  # Example public range
                "185.199.0.0/16"  # Example public range
            ]
            
            log_info("Public server scanning not yet implemented")
            
        except Exception as e:
            log_error(f"Error scanning public servers: {e}")
    
    def _check_dayz_server(self, ip: str, port: int):
        """Check if a specific IP:port is a DayZ server"""
        try:
            # Check if server is reachable
            if not self._is_server_reachable(ip, port):
                return
            
            # Try to identify if it's a DayZ server
            if self._is_dayz_server(ip, port):
                server = DayZServer(
                    ip=ip,
                    port=port,
                    name=f"DayZ Server {ip}:{port}",
                    type='Unknown',
                    status='Online',
                    latency=self._ping_server(ip, port),
                    player_count=0,
                    max_players=0,
                    map_name='Unknown',
                    version='Unknown',
                    last_seen=datetime.now(),
                    discovery_method='Network Scan',
                    is_local=self._is_local_ip(ip)
                )
                
                server_key = f"{ip}:{port}"
                if server_key not in self.discovered_servers:
                    self.discovered_servers[server_key] = server
                    log_info(f"New DayZ server discovered: {ip}:{port}")
                
        except Exception as e:
            log_error(f"Error checking server {ip}:{port}: {e}")
    
    def _is_server_reachable(self, ip: str, port: int) -> bool:
        """Check if a server is reachable"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((ip, port))
            sock.close()
            return result == 0
        except Exception:
            return False
    
    def _is_dayz_server(self, ip: str, port: int) -> bool:
        """Check if a server is actually a DayZ server"""
        try:
            # Try to connect and check for DayZ-specific characteristics
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)
            sock.connect((ip, port))
            
            # Send a simple query to check if it's a DayZ server
            # This is a basic check - real implementation would be more sophisticated
            try:
                sock.send(b"\x00\x00\x00\x00")  # Simple query
                response = sock.recv(1024)
                sock.close()
                
                # Check if response looks like DayZ server response
                # This is a simplified check
                return len(response) > 0
                
            except Exception:
                sock.close()
                return False
                
        except Exception:
            return False
    
    def _ping_server(self, ip: str, port: int) -> int:
        """Ping a server and return latency in milliseconds"""
        try:
            start_time = time.time()
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((ip, port))
            sock.close()
            
            if result == 0:
                latency = int((time.time() - start_time) * 1000)
                return latency
            else:
                return -1
                
        except Exception:
            return -1
    
    def _is_local_ip(self, ip: str) -> bool:
        """Check if an IP is local"""
        local_prefixes = ['192.168.', '10.', '172.16.', '172.17.', '172.18.', '127.']
        return any(ip.startswith(prefix) for prefix in local_prefixes)
    
    def _is_nmap_available(self) -> bool:
        """Check if nmap is available"""
        try:
            result = subprocess.run("nmap --version", shell=True, capture_output=True, timeout=5)
            return result.returncode == 0
        except Exception:
            return False
    
    def _parse_nmap_output(self, output: str, port: int) -> List[str]:
        """Parse nmap output for open hosts"""
        hosts = []
        try:
            # Parse nmap output for open ports
            lines = output.split('\n')
            for line in lines:
                if f"{port}/tcp" in line and "open" in line:
                    # Extract IP address
                    parts = line.split()
                    if len(parts) > 0:
                        ip = parts[0]
                        if self._is_valid_ip(ip):
                            hosts.append(ip)
        except Exception as e:
            log_error(f"Error parsing nmap output: {e}")
        return hosts
    
    def _parse_netstat_output(self, output: str) -> List[Dict]:
        """Parse netstat output for connections"""
        connections = []
        try:
            lines = output.split('\n')
            for line in lines:
                if ':230' in line:
                    parts = line.split()
                    if len(parts) >= 2:
                        addr_part = parts[1]
                        if ':' in addr_part:
                            ip, port_str = addr_part.rsplit(':', 1)
                            try:
                                port = int(port_str)
                                if self._is_valid_ip(ip):
                                    connections.append({'ip': ip, 'port': port})
                            except ValueError:
                                continue
        except Exception as e:
            log_error(f"Error parsing netstat output: {e}")
        return connections
    
    def _parse_arp_output(self, output: str) -> List[str]:
        """Parse ARP output for hosts"""
        hosts = []
        try:
            lines = output.split('\n')
            for line in lines:
                # Look for IP addresses in ARP table
                parts = line.split()
                for part in parts:
                    if self._is_valid_ip(part):
                        hosts.append(part)
        except Exception as e:
            log_error(f"Error parsing ARP output: {e}")
        return hosts
    
    def _is_valid_ip(self, ip: str) -> bool:
        """Check if a string is a valid IP address"""
        try:
            socket.inet_aton(ip)
            return True
        except socket.error:
            return False
    
    def _update_server_statuses(self):
        """Update status of all discovered servers"""
        for server_key, server in self.discovered_servers.items():
            try:
                # Check if server is still reachable
                if self._is_server_reachable(server.ip, server.port):
                    server.status = 'Online'
                    server.latency = self._ping_server(server.ip, server.port)
                    server.last_seen = datetime.now()
                else:
                    server.status = 'Offline'
                    server.latency = -1
                    
            except Exception as e:
                log_error(f"Error updating server {server_key}: {e}")
    
    def add_favorite_server(self, ip: str, port: int, name: str = None):
        """Add a server to favorites"""
        try:
            server_key = f"{ip}:{port}"
            if server_key not in self.favorite_servers:
                self.favorite_servers.append(server_key)
                self._save_favorite_servers()
                
                # Update server info if it exists
                if server_key in self.discovered_servers:
                    self.discovered_servers[server_key].is_favorite = True
                    if name:
                        self.discovered_servers[server_key].name = name
                
                log_info(f"Added {ip}:{port} to favorites")
                
        except Exception as e:
            log_error(f"Error adding favorite server: {e}")
    
    def remove_favorite_server(self, ip: str, port: int):
        """Remove a server from favorites"""
        try:
            server_key = f"{ip}:{port}"
            if server_key in self.favorite_servers:
                self.favorite_servers.remove(server_key)
                self._save_favorite_servers()
                
                # Update server info if it exists
                if server_key in self.discovered_servers:
                    self.discovered_servers[server_key].is_favorite = False
                
                log_info(f"Removed {ip}:{port} from favorites")
                
        except Exception as e:
            log_error(f"Error removing favorite server: {e}")
    
    def get_discovered_servers(self) -> List[DayZServer]:
        """Get list of discovered servers"""
        return list(self.discovered_servers.values())
    
    def get_favorite_servers(self) -> List[DayZServer]:
        """Get list of favorite servers"""
        return [self.discovered_servers[key] for key in self.favorite_servers 
                if key in self.discovered_servers]
    
    def get_server_by_key(self, server_key: str) -> Optional[DayZServer]:
        """Get server by key (ip:port)"""
        return self.discovered_servers.get(server_key)
    
    def get_online_servers(self) -> List[DayZServer]:
        """Get list of online servers"""
        return [server for server in self.discovered_servers.values() 
                if server.status == 'Online']
    
    def get_local_servers(self) -> List[DayZServer]:
        """Get list of local servers"""
        return [server for server in self.discovered_servers.values() 
                if server.is_local]
    
    def search_servers(self, query: str) -> List[DayZServer]:
        """Search servers by name, IP, or type"""
        query = query.lower()
        results = []
        
        for server in self.discovered_servers.values():
            if (query in server.name.lower() or 
                query in server.ip.lower() or 
                query in server.type.lower()):
                results.append(server)
        
        return results
    
    def get_server_statistics(self) -> Dict:
        """Get server discovery statistics"""
        total_servers = len(self.discovered_servers)
        online_servers = len(self.get_online_servers())
        local_servers = len(self.get_local_servers())
        favorite_servers = len(self.get_favorite_servers())
        
        return {
            'total_servers': total_servers,
            'online_servers': online_servers,
            'offline_servers': total_servers - online_servers,
            'local_servers': local_servers,
            'remote_servers': total_servers - local_servers,
            'favorite_servers': favorite_servers,
            'discovery_running': self.discovery_running,
            'last_scan': datetime.now().isoformat()
        }
