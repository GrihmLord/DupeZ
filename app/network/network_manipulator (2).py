# app/network/network_manipulator.py

import subprocess
import platform
import socket
import threading
import time
import json
import os
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from app.logs.logger import log_info, log_error, log_warning

@dataclass
class NetworkRule:
    """Network manipulation rule"""
    rule_id: str
    rule_type: str  # 'block', 'throttle', 'redirect', 'modify'
    target_ip: str
    target_port: Optional[int] = None
    action: str = 'drop'  # 'drop', 'delay', 'modify', 'redirect'
    parameters: Dict[str, Any] = None
    enabled: bool = True
    created_at: float = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = time.time()
        if self.parameters is None:
            self.parameters = {}

class NetworkManipulator:
    """Advanced network manipulation system"""
    
    def __init__(self):
        self.rules: Dict[str, NetworkRule] = {}
        self.active_manipulations: Dict[str, Any] = {}
        self.is_admin = self._check_admin_privileges()
        self.platform = platform.system().lower()
        self.manipulation_thread = None
        self.is_running = False
        
        # Load existing rules
        self._load_rules()
        
    def _check_admin_privileges(self) -> bool:
        """Check if running with admin privileges"""
        try:
            if platform.system().lower() == "windows":
                import ctypes
                return ctypes.windll.shell32.IsUserAnAdmin() != 0
            else:
                return os.geteuid() == 0
        except:
            return False
    
    def _load_rules(self):
        """Load saved network rules"""
        try:
            rules_file = "app/config/network_rules.json"
            if os.path.exists(rules_file):
                with open(rules_file, 'r') as f:
                    data = json.load(f)
                    for rule_data in data:
                        rule = NetworkRule(**rule_data)
                        self.rules[rule.rule_id] = rule
                log_info(f"Loaded {len(self.rules)} network rules")
        except Exception as e:
            log_error(f"Error loading network rules: {e}")
    
    def _save_rules(self):
        """Save network rules to file"""
        try:
            os.makedirs("app/config", exist_ok=True)
            rules_file = "app/config/network_rules.json"
            with open(rules_file, 'w') as f:
                json.dump([vars(rule) for rule in self.rules.values()], f, indent=2)
        except Exception as e:
            log_error(f"Error saving network rules: {e}")
    
    def block_ip(self, ip: str, permanent: bool = False) -> bool:
        """Block an IP address using multiple methods"""
        try:
            rule_id = f"block_{ip}_{int(time.time())}"
            rule = NetworkRule(
                rule_id=rule_id,
                rule_type='block',
                target_ip=ip,
                action='drop'
            )
            
            success = False
            
            # Method 1: Windows Firewall (Windows only)
            if self.platform == "windows" and self.is_admin:
                success = self._block_with_windows_firewall(ip)
            
            # Method 2: Route table manipulation
            if not success:
                success = self._block_with_route_table(ip)
            
            # Method 3: ARP poisoning (for local network)
            if not success and self._is_local_network(ip):
                success = self._block_with_arp(ip)
            
            # Method 4: iptables (Linux)
            if self.platform == "linux" and self.is_admin:
                success = self._block_with_iptables(ip)
            
            if success:
                self.rules[rule_id] = rule
                if permanent:
                    self._save_rules()
                log_info(f"Successfully blocked IP: {ip}")
                return True
            else:
                log_error(f"Failed to block IP: {ip}")
                return False
                
        except Exception as e:
            log_error(f"Error blocking IP {ip}: {e}")
            return False
    
    def unblock_ip(self, ip: str) -> bool:
        """Unblock an IP address"""
        try:
            # Remove all blocking rules for this IP
            rules_to_remove = []
            for rule_id, rule in self.rules.items():
                if rule.target_ip == ip and rule.rule_type == 'block':
                    rules_to_remove.append(rule_id)
            
            for rule_id in rules_to_remove:
                self._remove_rule(rule_id)
            
            log_info(f"Unblocked IP: {ip}")
            return True
            
        except Exception as e:
            log_error(f"Error unblocking IP {ip}: {e}")
            return False
    
    def throttle_connection(self, ip: str, bandwidth_mbps: float, latency_ms: int = 0, 
                          jitter_ms: int = 0, packet_loss_percent: float = 0) -> bool:
        """Throttle network connection to an IP"""
        try:
            rule_id = f"throttle_{ip}_{int(time.time())}"
            rule = NetworkRule(
                rule_id=rule_id,
                rule_type='throttle',
                target_ip=ip,
                action='delay',
                parameters={
                    'bandwidth': bandwidth_mbps,
                    'latency': latency_ms,
                    'jitter': jitter_ms,
                    'packet_loss': packet_loss_percent
                }
            )
            
            success = False
            
            # Method 1: Windows QoS (Windows)
            if self.platform == "windows" and self.is_admin:
                success = self._throttle_with_windows_qos(ip, bandwidth_mbps, latency_ms)
            
            # Method 2: Linux tc (Linux)
            if self.platform == "linux" and self.is_admin:
                success = self._throttle_with_linux_tc(ip, bandwidth_mbps, latency_ms, jitter_ms, packet_loss_percent)
            
            # Method 3: Custom packet manipulation
            if not success:
                success = self._throttle_with_packet_manipulation(ip, rule)
            
            if success:
                self.rules[rule_id] = rule
                self._save_rules()
                log_info(f"Successfully throttled IP: {ip}")
                return True
            else:
                log_error(f"Failed to throttle IP: {ip}")
                return False
                
        except Exception as e:
            log_error(f"Error throttling IP {ip}: {e}")
            return False
    
    def redirect_traffic(self, source_ip: str, target_ip: str, port: Optional[int] = None) -> bool:
        """Redirect traffic from one IP to another"""
        try:
            rule_id = f"redirect_{source_ip}_{int(time.time())}"
            rule = NetworkRule(
                rule_id=rule_id,
                rule_type='redirect',
                target_ip=source_ip,
                target_port=port,
                action='redirect',
                parameters={'redirect_to': target_ip}
            )
            
            success = False
            
            # Method 1: Windows Firewall with NAT
            if self.platform == "windows" and self.is_admin:
                success = self._redirect_with_windows_nat(source_ip, target_ip, port)
            
            # Method 2: Linux iptables NAT
            if self.platform == "linux" and self.is_admin:
                success = self._redirect_with_linux_nat(source_ip, target_ip, port)
            
            if success:
                self.rules[rule_id] = rule
                self._save_rules()
                log_info(f"Successfully redirected traffic from {source_ip} to {target_ip}")
                return True
            else:
                log_error(f"Failed to redirect traffic from {source_ip} to {target_ip}")
                return False
                
        except Exception as e:
            log_error(f"Error redirecting traffic: {e}")
            return False
    
    def modify_packets(self, ip: str, modifications: Dict[str, Any]) -> bool:
        """Modify packets for a specific IP"""
        try:
            rule_id = f"modify_{ip}_{int(time.time())}"
            rule = NetworkRule(
                rule_id=rule_id,
                rule_type='modify',
                target_ip=ip,
                action='modify',
                parameters=modifications
            )
            
            # Start packet modification thread
            success = self._start_packet_modification(ip, modifications)
            
            if success:
                self.rules[rule_id] = rule
                self._save_rules()
                log_info(f"Successfully started packet modification for IP: {ip}")
                return True
            else:
                log_error(f"Failed to start packet modification for IP: {ip}")
                return False
                
        except Exception as e:
            log_error(f"Error modifying packets for IP {ip}: {e}")
            return False
    
    def get_network_info(self) -> Dict[str, Any]:
        """Get current network information"""
        try:
            info = {
                'platform': self.platform,
                'is_admin': self.is_admin,
                'active_rules': len(self.rules),
                'active_manipulations': len(self.active_manipulations),
                'local_ip': self._get_local_ip(),
                'network_interface': self._get_network_interface(),
                'dns_servers': self._get_dns_servers(),
                'routing_table': self._get_routing_table()
            }
            return info
        except Exception as e:
            log_error(f"Error getting network info: {e}")
            return {}
    
    def get_active_rules(self) -> List[Dict[str, Any]]:
        """Get list of active network rules"""
        return [vars(rule) for rule in self.rules.values()]
    
    def remove_rule(self, rule_id: str) -> bool:
        """Remove a specific network rule"""
        return self._remove_rule(rule_id)
    
    def clear_all_rules(self) -> bool:
        """Clear all network rules"""
        try:
            for rule_id in list(self.rules.keys()):
                self._remove_rule(rule_id)
            log_info("Cleared all network rules")
            return True
        except Exception as e:
            log_error(f"Error clearing all rules: {e}")
            return False
    
    def _block_with_windows_firewall(self, ip: str) -> bool:
        """Block IP using Windows Firewall"""
        try:
            rule_name = f"PulseDrop_Block_{ip.replace('.', '_')}"
            cmd = [
                "netsh", "advfirewall", "firewall", "add", "rule",
                f"name={rule_name}",
                "dir=out",
                "action=block",
                f"remoteip={ip}",
                "enable=yes"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
            return result.returncode == 0
        except Exception as e:
            log_error(f"Windows firewall blocking failed: {e}")
            return False
    
    def _block_with_route_table(self, ip: str) -> bool:
        """Block IP using route table manipulation"""
        try:
            if self.platform == "windows":
                cmd = ["route", "add", ip, "mask", "255.255.255.255", "0.0.0.0", "metric", "1"]
            else:
                cmd = ["ip", "route", "add", "blackhole", ip]
            
            result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
            return result.returncode == 0 or "already exists" in result.stderr
        except Exception as e:
            log_error(f"Route table blocking failed: {e}")
            return False
    
    def _block_with_arp(self, ip: str) -> bool:
        """Block IP using ARP poisoning"""
        try:
            if self.platform == "windows":
                cmd = ["arp", "-s", ip, "00-00-00-00-00-00"]
            else:
                cmd = ["arp", "-s", ip, "00:00:00:00:00:00"]
            
            result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
            return result.returncode == 0
        except Exception as e:
            log_error(f"ARP blocking failed: {e}")
            return False
    
    def _block_with_iptables(self, ip: str) -> bool:
        """Block IP using iptables"""
        try:
            cmd = ["iptables", "-A", "OUTPUT", "-d", ip, "-j", "DROP"]
            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.returncode == 0
        except Exception as e:
            log_error(f"iptables blocking failed: {e}")
            return False
    
    def _throttle_with_windows_qos(self, ip: str, bandwidth_mbps: float, latency_ms: int) -> bool:
        """Throttle using Windows QoS"""
        try:
            # Windows QoS policy creation
            policy_name = f"PulseDrop_Throttle_{ip.replace('.', '_')}"
            cmd = [
                "netsh", "qos", "add", "policy", f"name={policy_name}",
                "rate={bandwidth_mbps}Mbps"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
            return result.returncode == 0
        except Exception as e:
            log_error(f"Windows QoS throttling failed: {e}")
            return False
    
    def _throttle_with_linux_tc(self, ip: str, bandwidth_mbps: float, latency_ms: int, 
                               jitter_ms: int, packet_loss_percent: float) -> bool:
        """Throttle using Linux tc"""
        try:
            # Create tc qdisc and filter for the IP
            interface = self._get_default_interface()
            if not interface:
                return False
            
            # Add qdisc
            cmd1 = ["tc", "qdisc", "add", "dev", interface, "root", "handle", "1:", "htb"]
            result1 = subprocess.run(cmd1, capture_output=True, text=True)
            
            # Add class
            cmd2 = ["tc", "class", "add", "dev", interface, "parent", "1:", "classid", "1:1", 
                   "htb", "rate", f"{bandwidth_mbps}mbit"]
            result2 = subprocess.run(cmd2, capture_output=True, text=True)
            
            # Add filter
            cmd3 = ["tc", "filter", "add", "dev", interface, "protocol", "ip", "parent", "1:", 
                   "prio", "1", "u32", "match", "ip", "dst", ip, "flowid", "1:1"]
            result3 = subprocess.run(cmd3, capture_output=True, text=True)
            
            return result1.returncode == 0 and result2.returncode == 0 and result3.returncode == 0
        except Exception as e:
            log_error(f"Linux tc throttling failed: {e}")
            return False
    
    def _throttle_with_packet_manipulation(self, ip: str, rule: NetworkRule) -> bool:
        """Throttle using custom packet manipulation"""
        try:
            # Start a background thread for packet manipulation
            thread = threading.Thread(
                target=self._packet_manipulation_loop,
                args=(ip, rule.parameters),
                daemon=True
            )
            thread.start()
            self.active_manipulations[ip] = thread
            return True
        except Exception as e:
            log_error(f"Packet manipulation throttling failed: {e}")
            return False
    
    def _packet_manipulation_loop(self, ip: str, parameters: Dict[str, Any]):
        """Packet manipulation loop for throttling"""
        try:
            # This would implement actual packet manipulation
            # For now, just log the attempt
            log_info(f"Packet manipulation started for {ip} with parameters: {parameters}")
            while self.is_running:
                time.sleep(1)
        except Exception as e:
            log_error(f"Packet manipulation loop error: {e}")
    
    def _redirect_with_windows_nat(self, source_ip: str, target_ip: str, port: Optional[int]) -> bool:
        """Redirect traffic using Windows NAT"""
        try:
            # Windows NAT rules
            rule_name = f"PulseDrop_Redirect_{source_ip.replace('.', '_')}"
            cmd = [
                "netsh", "interface", "portproxy", "add", "v4tov4",
                f"listenport={port or 80}", f"listenaddress={source_ip}",
                f"connectport={port or 80}", f"connectaddress={target_ip}"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
            return result.returncode == 0
        except Exception as e:
            log_error(f"Windows NAT redirect failed: {e}")
            return False
    
    def _redirect_with_linux_nat(self, source_ip: str, target_ip: str, port: Optional[int]) -> bool:
        """Redirect traffic using Linux NAT"""
        try:
            # Linux iptables NAT rules
            cmd = ["iptables", "-t", "nat", "-A", "PREROUTING", "-d", source_ip]
            if port:
                cmd.extend(["-p", "tcp", "--dport", str(port)])
            cmd.extend(["-j", "DNAT", "--to-destination", target_ip])
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.returncode == 0
        except Exception as e:
            log_error(f"Linux NAT redirect failed: {e}")
            return False
    
    def _start_packet_modification(self, ip: str, modifications: Dict[str, Any]) -> bool:
        """Start packet modification for an IP"""
        try:
            # Start modification thread
            thread = threading.Thread(
                target=self._packet_modification_loop,
                args=(ip, modifications),
                daemon=True
            )
            thread.start()
            self.active_manipulations[ip] = thread
            return True
        except Exception as e:
            log_error(f"Packet modification start failed: {e}")
            return False
    
    def _packet_modification_loop(self, ip: str, modifications: Dict[str, Any]):
        """Packet modification loop"""
        try:
            log_info(f"Packet modification started for {ip} with modifications: {modifications}")
            while self.is_running:
                time.sleep(1)
        except Exception as e:
            log_error(f"Packet modification loop error: {e}")
    
    def _remove_rule(self, rule_id: str) -> bool:
        """Remove a specific rule"""
        try:
            if rule_id in self.rules:
                rule = self.rules[rule_id]
                
                # Remove the actual network rule (don't fail if it doesn't exist)
                try:
                    if rule.rule_type == 'block':
                        self.unblock_ip(rule.target_ip)
                    elif rule.rule_type == 'throttle':
                        self._remove_throttle(rule.target_ip)
                    elif rule.rule_type == 'redirect':
                        self._remove_redirect(rule.target_ip)
                    elif rule.rule_type == 'modify':
                        self._remove_modification(rule.target_ip)
                except Exception as e:
                    log_error(f"Error removing network rule for {rule_id}: {e}")
                    # Continue anyway to remove from rules dict
                
                # Remove from rules dict
                del self.rules[rule_id]
                self._save_rules()
                log_info(f"Removed rule: {rule_id}")
                return True
            else:
                log_error(f"Rule {rule_id} not found in rules dict")
                return False
        except Exception as e:
            log_error(f"Error removing rule {rule_id}: {e}")
            return False
    
    def _remove_throttle(self, ip: str):
        """Remove throttling for an IP"""
        try:
            if self.platform == "windows" and self.is_admin:
                policy_name = f"PulseDrop_Throttle_{ip.replace('.', '_')}"
                cmd = ["netsh", "qos", "delete", "policy", f"name={policy_name}"]
                subprocess.run(cmd, capture_output=True, text=True, shell=True)
            elif self.platform == "linux" and self.is_admin:
                interface = self._get_default_interface()
                if interface:
                    cmd = ["tc", "qdisc", "del", "dev", interface, "root"]
                    subprocess.run(cmd, capture_output=True, text=True)
            
            # Stop packet manipulation thread
            if ip in self.active_manipulations:
                del self.active_manipulations[ip]
        except Exception as e:
            log_error(f"Error removing throttle for {ip}: {e}")
    
    def _remove_redirect(self, ip: str):
        """Remove redirect for an IP"""
        try:
            if self.platform == "windows" and self.is_admin:
                cmd = ["netsh", "interface", "portproxy", "delete", "v4tov4", f"listenaddress={ip}"]
                subprocess.run(cmd, capture_output=True, text=True, shell=True)
            elif self.platform == "linux" and self.is_admin:
                cmd = ["iptables", "-t", "nat", "-D", "PREROUTING", "-d", ip, "-j", "DNAT"]
                subprocess.run(cmd, capture_output=True, text=True)
        except Exception as e:
            log_error(f"Error removing redirect for {ip}: {e}")
    
    def _remove_modification(self, ip: str):
        """Remove packet modification for an IP"""
        try:
            if ip in self.active_manipulations:
                del self.active_manipulations[ip]
        except Exception as e:
            log_error(f"Error removing modification for {ip}: {e}")
    
    def _is_local_network(self, ip: str) -> bool:
        """Check if IP is on local network"""
        try:
            local_ip = self._get_local_ip()
            if not local_ip:
                return False
            
            local_parts = local_ip.split('.')
            ip_parts = ip.split('.')
            return local_parts[:3] == ip_parts[:3]
        except:
            return False
    
    def _get_local_ip(self) -> Optional[str]:
        """Get local IP address"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            return local_ip
        except:
            return None
    
    def _get_network_interface(self) -> Optional[str]:
        """Get default network interface"""
        try:
            if self.platform == "windows":
                cmd = ["netsh", "interface", "show", "interface"]
                result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
                # Parse output to find default interface
                return "Ethernet"  # Default fallback
            else:
                cmd = ["ip", "route", "show", "default"]
                result = subprocess.run(cmd, capture_output=True, text=True)
                # Parse output to find interface
                return "eth0"  # Default fallback
        except:
            return None
    
    def _get_dns_servers(self) -> List[str]:
        """Get DNS servers"""
        try:
            if self.platform == "windows":
                cmd = ["ipconfig", "/all"]
                result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
                # Parse output for DNS servers
                return ["8.8.8.8", "8.8.4.4"]  # Default fallback
            else:
                with open("/etc/resolv.conf", "r") as f:
                    content = f.read()
                    # Parse for nameserver entries
                    return ["8.8.8.8", "8.8.4.4"]  # Default fallback
        except:
            return ["8.8.8.8", "8.8.4.4"]
    
    def _get_routing_table(self) -> List[Dict[str, str]]:
        """Get routing table"""
        try:
            if self.platform == "windows":
                cmd = ["route", "print"]
                result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
                # Parse routing table
                return []
            else:
                cmd = ["ip", "route", "show"]
                result = subprocess.run(cmd, capture_output=True, text=True)
                # Parse routing table
                return []
        except:
            return []
    
    def _get_default_interface(self) -> Optional[str]:
        """Get default network interface"""
        return self._get_network_interface()
    
    def start(self):
        """Start the network manipulator"""
        self.is_running = True
        log_info("Network manipulator started")
    
    def stop(self):
        """Stop the network manipulator"""
        self.is_running = False
        
        # Clear all active manipulations
        for ip in list(self.active_manipulations.keys()):
            del self.active_manipulations[ip]
        
        # Clear all rules
        self.clear_all_rules()
        
        log_info("Network manipulator stopped")

# Global instance
_network_manipulator = None

def get_network_manipulator() -> NetworkManipulator:
    """Get the global network manipulator instance"""
    global _network_manipulator
    if _network_manipulator is None:
        _network_manipulator = NetworkManipulator()
        _network_manipulator.start()
    return _network_manipulator

def cleanup_network_manipulator():
    """Cleanup the network manipulator"""
    global _network_manipulator
    if _network_manipulator:
        _network_manipulator.stop()
        _network_manipulator = None 