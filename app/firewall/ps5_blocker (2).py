#!/usr/bin/env python3
"""
PS5 Network Blocker
Specialized blocking system for PlayStation 5 devices
"""

import subprocess
import socket
import time
import threading
import os
import platform
from typing import List, Dict, Optional
from app.logs.logger import log_info, log_error

class PS5Blocker:
    """Specialized blocker for PS5 devices"""
    
    def __init__(self):
        self.blocked_ps5s = set()
        self.blocking_active = False
        self.lock = threading.Lock()
        self.is_admin = self._check_admin_privileges()
        
    def _check_admin_privileges(self) -> bool:
        """Check if running with admin privileges"""
        try:
            if platform.system() == "Windows":
                import ctypes
                return ctypes.windll.shell32.IsUserAnAdmin() != 0
            else:
                return os.geteuid() == 0
        except:
            return False
    
    def block_ps5(self, ip_address: str) -> bool:
        """Block a specific PS5 device"""
        try:
            with self.lock:
                success = False
                
                # Method 1: Windows Firewall (requires admin)
                if self.is_admin and platform.system() == "Windows":
                    success = self._block_with_windows_firewall(ip_address)
                
                # Method 2: Hosts file blocking
                if not success:
                    success = self._add_to_hosts(ip_address)
                
                # Method 3: Route table blocking
                if not success:
                    success = self._add_route_block(ip_address)
                
                # Method 4: ARP poisoning (for local network)
                if not success:
                    success = self._block_with_arp(ip_address)
                
                if success:
                    self.blocked_ps5s.add(ip_address)
                    log_info(f"PS5 blocked successfully: {ip_address}")
                    return True
                else:
                    log_error(f"All blocking methods failed for PS5: {ip_address}")
                    return False
                
        except Exception as e:
            log_error(f"Failed to block PS5 {ip_address}: {e}")
            return False
    
    def _block_with_windows_firewall(self, ip_address: str) -> bool:
        """Block using Windows Firewall"""
        try:
            rule_name = f"PulseDrop_PS5_Block_{ip_address.replace('.', '_')}"
            
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
            result1 = subprocess.run(cmd_inbound, capture_output=True, text=True)
            result2 = subprocess.run(cmd_outbound, capture_output=True, text=True)
            
            if result1.returncode == 0 and result2.returncode == 0:
                log_info(f"Windows Firewall blocking successful for {ip_address}")
                return True
            else:
                log_error(f"Windows Firewall blocking failed: {result1.stderr} {result2.stderr}")
                return False
                
        except Exception as e:
            log_error(f"Windows Firewall blocking error: {e}")
            return False
    
    def _block_with_arp(self, ip_address: str) -> bool:
        """Block using ARP poisoning"""
        try:
            if platform.system() == "Windows":
                cmd = ["arp", "-s", ip_address, "00-00-00-00-00-00"]
            else:
                cmd = ["arp", "-s", ip_address, "00:00:00:00:00:00"]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                log_info(f"ARP blocking successful for {ip_address}")
                return True
            else:
                log_error(f"ARP blocking failed: {result.stderr}")
                return False
                
        except Exception as e:
            log_error(f"ARP blocking error: {e}")
            return False
    
    def unblock_ps5(self, ip_address: str) -> bool:
        """Unblock a specific PS5 device"""
        try:
            with self.lock:
                success = False
                
                # Method 1: Remove Windows Firewall rules
                if self.is_admin and platform.system() == "Windows":
                    success = self._unblock_with_windows_firewall(ip_address)
                
                # Method 2: Remove from hosts file
                if not success:
                    success = self._remove_from_hosts(ip_address)
                
                # Method 3: Remove from route table
                if not success:
                    success = self._remove_route_block(ip_address)
                
                # Method 4: Remove ARP entry
                if not success:
                    success = self._unblock_with_arp(ip_address)
                
                if success:
                    self.blocked_ps5s.discard(ip_address)
                    log_info(f"PS5 unblocked successfully: {ip_address}")
                    return True
                else:
                    log_error(f"All unblocking methods failed for PS5: {ip_address}")
                    return False
                
        except Exception as e:
            log_error(f"Failed to unblock PS5 {ip_address}: {e}")
            return False
    
    def _unblock_with_windows_firewall(self, ip_address: str) -> bool:
        """Unblock using Windows Firewall"""
        try:
            rule_name = f"PulseDrop_PS5_Block_{ip_address.replace('.', '_')}"
            
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
            
            log_info(f"Windows Firewall unblocking successful for {ip_address}")
            return True
                
        except Exception as e:
            log_error(f"Windows Firewall unblocking error: {e}")
            return False
    
    def _unblock_with_arp(self, ip_address: str) -> bool:
        """Unblock using ARP removal"""
        try:
            if platform.system() == "Windows":
                cmd = ["arp", "-d", ip_address]
            else:
                cmd = ["arp", "-d", ip_address]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                log_info(f"ARP unblocking successful for {ip_address}")
                return True
            else:
                log_error(f"ARP unblocking failed: {result.stderr}")
                return False
                
        except Exception as e:
            log_error(f"ARP unblocking error: {e}")
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
                success = True
                
                # Clear hosts file blocks
                if not self._clear_hosts_blocks():
                    success = False
                
                # Clear route blocks
                if not self._clear_route_blocks():
                    success = False
                
                # Clear Windows Firewall rules
                if self.is_admin and platform.system() == "Windows":
                    if not self._clear_windows_firewall_rules():
                        success = False
                
                # Clear ARP entries
                if not self._clear_arp_entries():
                    success = False
                
                self.blocked_ps5s.clear()
                
                if success:
                    log_info("All PS5 blocks cleared successfully")
                else:
                    log_error("Some PS5 blocks failed to clear")
                
                return success
                
        except Exception as e:
            log_error(f"Failed to clear all PS5 blocks: {e}")
            return False
    
    def _clear_windows_firewall_rules(self) -> bool:
        """Clear Windows Firewall rules"""
        try:
            # List all PulseDrop rules
            cmd_list = ["netsh", "advfirewall", "firewall", "show", "rule", "name=all"]
            result = subprocess.run(cmd_list, capture_output=True, text=True)
            
            if result.returncode == 0:
                lines = result.stdout.split('\n')
                for line in lines:
                    if 'PulseDrop_PS5_Block' in line:
                        # Extract rule name and delete it
                        parts = line.split()
                        if len(parts) > 1:
                            rule_name = parts[1]
                            cmd_delete = ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={rule_name}"]
                            subprocess.run(cmd_delete, capture_output=True)
            
            log_info("Windows Firewall rules cleared")
            return True
            
        except Exception as e:
            log_error(f"Failed to clear Windows Firewall rules: {e}")
            return False
    
    def _clear_arp_entries(self) -> bool:
        """Clear ARP entries"""
        try:
            if platform.system() == "Windows":
                cmd = ["arp", "-d", "*"]
            else:
                cmd = ["arp", "-d", "*"]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                log_info("ARP entries cleared")
                return True
            else:
                log_error(f"Failed to clear ARP entries: {result.stderr}")
                return False
                
        except Exception as e:
            log_error(f"Failed to clear ARP entries: {e}")
            return False
    
    def _add_to_hosts(self, ip_address: str) -> bool:
        """Add IP to hosts file"""
        try:
            hosts_file = r"C:\Windows\System32\drivers\etc\hosts" if platform.system() == "Windows" else "/etc/hosts"
            
            # Check if already in hosts file
            with open(hosts_file, 'r') as f:
                content = f.read()
                if ip_address in content:
                    log_info(f"IP {ip_address} already in hosts file")
                    return True
            
            # Add to hosts file
            with open(hosts_file, 'a') as f:
                f.write(f"\n{ip_address} localhost\n")
            
            log_info(f"Added {ip_address} to hosts file")
            return True
            
        except Exception as e:
            log_error(f"Failed to add to hosts file: {e}")
            return False
    
    def _remove_from_hosts(self, ip_address: str) -> bool:
        """Remove IP from hosts file"""
        try:
            hosts_file = r"C:\Windows\System32\drivers\etc\hosts" if platform.system() == "Windows" else "/etc/hosts"
            
            # Read current content
            with open(hosts_file, 'r') as f:
                lines = f.readlines()
            
            # Remove lines containing the IP
            new_lines = [line for line in lines if ip_address not in line]
            
            # Write back
            with open(hosts_file, 'w') as f:
                f.writelines(new_lines)
            
            log_info(f"Removed {ip_address} from hosts file")
            return True
            
        except Exception as e:
            log_error(f"Failed to remove from hosts file: {e}")
            return False
    
    def _add_route_block(self, ip_address: str) -> bool:
        """Add route block"""
        try:
            if platform.system() == "Windows":
                cmd = ["route", "add", ip_address, "mask", "255.255.255.255", "0.0.0.0", "metric", "1"]
            else:
                cmd = ["ip", "route", "add", "blackhole", ip_address]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0 or "already exists" in result.stderr:
                log_info(f"Route block added for {ip_address}")
                return True
            else:
                log_error(f"Failed to add route block: {result.stderr}")
                return False
                
        except Exception as e:
            log_error(f"Failed to add route block: {e}")
            return False
    
    def _remove_route_block(self, ip_address: str) -> bool:
        """Remove route block"""
        try:
            if platform.system() == "Windows":
                cmd = ["route", "delete", ip_address]
            else:
                cmd = ["ip", "route", "del", "blackhole", ip_address]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                log_info(f"Route block removed for {ip_address}")
                return True
            else:
                log_error(f"Failed to remove route block: {result.stderr}")
                return False
                
        except Exception as e:
            log_error(f"Failed to remove route block: {e}")
            return False
    
    def _clear_hosts_blocks(self) -> bool:
        """Clear all hosts file blocks"""
        try:
            hosts_file = r"C:\Windows\System32\drivers\etc\hosts" if platform.system() == "Windows" else "/etc/hosts"
            
            # Read current content
            with open(hosts_file, 'r') as f:
                lines = f.readlines()
            
            # Remove lines containing localhost (our blocks)
            new_lines = [line for line in lines if "localhost" not in line]
            
            # Write back
            with open(hosts_file, 'w') as f:
                f.writelines(new_lines)
            
            log_info("Hosts file blocks cleared")
            return True
            
        except Exception as e:
            log_error(f"Failed to clear hosts blocks: {e}")
            return False
    
    def _clear_route_blocks(self) -> bool:
        """Clear all route blocks"""
        try:
            if platform.system() == "Windows":
                # Get current routes and remove blackhole routes
                cmd_list = ["route", "print"]
                result = subprocess.run(cmd_list, capture_output=True, text=True)
                
                if result.returncode == 0:
                    lines = result.stdout.split('\n')
                    for line in lines:
                        if '0.0.0.0' in line and 'metric 1' in line:
                            parts = line.split()
                            if len(parts) > 0:
                                ip = parts[0]
                                cmd_delete = ["route", "delete", ip]
                                subprocess.run(cmd_delete, capture_output=True)
            else:
                # Linux route clearing
                cmd = ["ip", "route", "flush", "blackhole"]
                subprocess.run(cmd, capture_output=True)
            
            log_info("Route blocks cleared")
            return True
            
        except Exception as e:
            log_error(f"Failed to clear route blocks: {e}")
            return False
    
    def get_blocked_ps5s(self) -> List[str]:
        """Get list of blocked PS5 IPs"""
        return list(self.blocked_ps5s)
    
    def is_ps5_blocked(self, ip_address: str) -> bool:
        """Check if PS5 is blocked"""
        return ip_address in self.blocked_ps5s 