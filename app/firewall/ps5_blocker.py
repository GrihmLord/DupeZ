#!/usr/bin/env python3
"""
PS5 Network Blocker
Specialized blocking system for PlayStation 5 devices
"""

import subprocess
import socket
import time
import threading
from typing import List, Dict, Optional
from app.logs.logger import log_info, log_error

class PS5Blocker:
    """Specialized blocker for PS5 devices"""
    
    def __init__(self):
        self.blocked_ps5s = set()
        self.blocking_active = False
        self.lock = threading.Lock()
        
    def block_ps5(self, ip_address: str) -> bool:
        """Block a specific PS5 device"""
        try:
            with self.lock:
                # Add to Windows Firewall
                rule_name = f"DupeZ_PS5_Block_{ip_address}"
                
                # Create inbound rule
                cmd_inbound = [
                    "netsh", "advfirewall", "firewall", "add", "rule",
                    f"name={rule_name}_Inbound",
                    "dir=in",
                    "action=block",
                    f"remoteip={ip_address}",
                    "enable=yes"
                ]
                
                # Create outbound rule
                cmd_outbound = [
                    "netsh", "advfirewall", "firewall", "add", "rule",
                    f"name={rule_name}_Outbound",
                    "dir=out",
                    "action=block",
                    f"remoteip={ip_address}",
                    "enable=yes"
                ]
                
                # Execute commands
                subprocess.run(cmd_inbound, capture_output=True, check=True)
                subprocess.run(cmd_outbound, capture_output=True, check=True)
                
                # Add to hosts file
                self._add_to_hosts(ip_address)
                
                # Add to route table
                self._add_route_block(ip_address)
                
                self.blocked_ps5s.add(ip_address)
                log_info(f"PS5 blocked successfully: {ip_address}")
                return True
                
        except Exception as e:
            log_error(f"Failed to block PS5 {ip_address}: {e}")
            return False
    
    def unblock_ps5(self, ip_address: str) -> bool:
        """Unblock a specific PS5 device"""
        try:
            with self.lock:
                # Remove from Windows Firewall
                rule_name = f"DupeZ_PS5_Block_{ip_address}"
                
                # Remove inbound rule
                cmd_inbound = [
                    "netsh", "advfirewall", "firewall", "delete", "rule",
                    f"name={rule_name}_Inbound"
                ]
                
                # Remove outbound rule
                cmd_outbound = [
                    "netsh", "advfirewall", "firewall", "delete", "rule",
                    f"name={rule_name}_Outbound"
                ]
                
                # Execute commands
                subprocess.run(cmd_inbound, capture_output=True)
                subprocess.run(cmd_outbound, capture_output=True)
                
                # Remove from hosts file
                self._remove_from_hosts(ip_address)
                
                # Remove from route table
                self._remove_route_block(ip_address)
                
                self.blocked_ps5s.discard(ip_address)
                log_info(f"PS5 unblocked successfully: {ip_address}")
                return True
                
        except Exception as e:
            log_error(f"Failed to unblock PS5 {ip_address}: {e}")
            return False
    
    def block_all_ps5s(self, ps5_ips: List[str]) -> Dict[str, bool]:
        """Block all PS5 devices"""
        results = {}
        for ip in ps5_ips:
            results[ip] = self.block_ps5(ip)
        return results
    
    def unblock_all_ps5s(self, ps5_ips: List[str]) -> Dict[str, bool]:
        """Unblock all PS5 devices"""
        results = {}
        for ip in ps5_ips:
            results[ip] = self.unblock_ps5(ip)
        return results
    
    def clear_all_ps5_blocks(self) -> bool:
        """Clear all PS5 blocks"""
        try:
            with self.lock:
                # Remove all PulseDrop PS5 firewall rules
                cmd = [
                    "netsh", "advfirewall", "firewall", "delete", "rule",
                    "name=DupeZ_PS5_Block_*"
                ]
                subprocess.run(cmd, capture_output=True)
                
                # Clear hosts file blocks
                self._clear_hosts_blocks()
                
                # Clear route blocks
                self._clear_route_blocks()
                
                # Clear DNS cache
                subprocess.run(["ipconfig", "/flushdns"], capture_output=True)
                
                # Clear ARP cache
                subprocess.run(["arp", "-d", "*"], capture_output=True)
                
                self.blocked_ps5s.clear()
                log_info("All PS5 blocks cleared successfully")
                return True
                
        except Exception as e:
            log_error(f"Failed to clear PS5 blocks: {e}")
            return False
    
    def _add_to_hosts(self, ip_address: str):
        """Add IP to hosts file"""
        try:
            hosts_file = r"C:\Windows\System32\drivers\etc\hosts"
            with open(hosts_file, 'a') as f:
                f.write(f"\n{ip_address} localhost\n")
        except Exception as e:
            log_error(f"Failed to add {ip_address} to hosts file: {e}")
    
    def _remove_from_hosts(self, ip_address: str):
        """Remove IP from hosts file"""
        try:
            hosts_file = r"C:\Windows\System32\drivers\etc\hosts"
            with open(hosts_file, 'r') as f:
                lines = f.readlines()
            
            # Remove lines containing the IP
            filtered_lines = [line for line in lines if ip_address not in line]
            
            with open(hosts_file, 'w') as f:
                f.writelines(filtered_lines)
        except Exception as e:
            log_error(f"Failed to remove {ip_address} from hosts file: {e}")
    
    def _add_route_block(self, ip_address: str):
        """Add route block for IP"""
        try:
            cmd = ["route", "add", ip_address, "127.0.0.1"]
            subprocess.run(cmd, capture_output=True)
        except Exception as e:
            log_error(f"Failed to add route block for {ip_address}: {e}")
    
    def _remove_route_block(self, ip_address: str):
        """Remove route block for IP"""
        try:
            cmd = ["route", "delete", ip_address]
            subprocess.run(cmd, capture_output=True)
        except Exception as e:
            log_error(f"Failed to remove route block for {ip_address}: {e}")
    
    def _clear_hosts_blocks(self):
        """Clear all blocks from hosts file"""
        try:
            hosts_file = r"C:\Windows\System32\drivers\etc\hosts"
            with open(hosts_file, 'r') as f:
                lines = f.readlines()
            
            # Keep only original lines (no localhost redirects)
            original_lines = []
            for line in lines:
                if not line.strip().endswith("localhost") and not line.strip().endswith("127.0.0.1"):
                    original_lines.append(line)
            
            with open(hosts_file, 'w') as f:
                f.writelines(original_lines)
        except Exception as e:
            log_error(f"Failed to clear hosts blocks: {e}")
    
    def _clear_route_blocks(self):
        """Clear all route blocks"""
        try:
            # Get current routes
            result = subprocess.run(["route", "print"], capture_output=True, text=True)
            lines = result.stdout.split('\n')
            
            # Find and remove route blocks
            for line in lines:
                if "127.0.0.1" in line and "192.168." in line:
                    parts = line.split()
                    if len(parts) >= 4:
                        target_ip = parts[0]
                        if target_ip.startswith("192.168."):
                            subprocess.run(["route", "delete", target_ip], capture_output=True)
        except Exception as e:
            log_error(f"Failed to clear route blocks: {e}")
    
    def get_blocked_ps5s(self) -> List[str]:
        """Get list of currently blocked PS5s"""
        return list(self.blocked_ps5s)
    
    def is_ps5_blocked(self, ip_address: str) -> bool:
        """Check if a PS5 is blocked"""
        return ip_address in self.blocked_ps5s

# Global instance
ps5_blocker = PS5Blocker() 
