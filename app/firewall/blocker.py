#!/usr/bin/env python3
"""
Simple Firewall Blocker Module
Provides basic firewall blocking functionality
"""

import platform
import subprocess
import socket
from typing import List, Dict, Optional
from app.logs.logger import log_info, log_error
import time

def is_admin() -> bool:
    """Check if running with administrator privileges"""
    try:
        if platform.system() == "Windows":
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        else:
            import os
            return os.geteuid() == 0
    except:
        return False

def block_device(ip: str, block: bool = True) -> bool:
    """Block or unblock a device using firewall rules - OPTIMIZED for TEMPORARY blocking"""
    try:
        if not is_admin():
            log_error("Firewall blocking requires administrator privileges")
            return False
        
        if platform.system() == "Windows":
            rule_name = f"DupeZBlock_{ip.replace('.', '_')}"
            
            if block:
                # Add firewall rule to block IP - TEMPORARY
                try:
                    # Performance optimization: Use single subprocess call with timeout
                    subprocess.run([
                        "netsh", "advfirewall", "firewall", "add", "rule",
                        f"name={rule_name}_In", "dir=in", "action=block",
                        f"remoteip={ip}", "enable=yes"
                    ], capture_output=True, timeout=3)  # Reduced timeout from 5 to 3
                    
                    subprocess.run([
                        "netsh", "advfirewall", "firewall", "add", "rule",
                        f"name={rule_name}_Out", "dir=out", "action=block",
                        f"remoteip={ip}", "enable=yes"
                    ], capture_output=True, timeout=3)  # Reduced timeout from 5 to 3
                    
                    # Performance optimization: Reduce logging
                    if hasattr(block_device, '_last_log_time') and time.time() - getattr(block_device, '_last_log_time', 0) > 2.0:
                        log_info(f"Blocked device: {ip} (TEMPORARY)")
                        block_device._last_log_time = time.time()
                    return True
                except subprocess.TimeoutExpired:
                    log_error(f"Timeout blocking device: {ip}")
                    return False
            else:
                # Remove firewall rules
                try:
                    subprocess.run([
                        "netsh", "advfirewall", "firewall", "delete", "rule",
                        f"name={rule_name}_In"
                    ], capture_output=True, timeout=3)  # Reduced timeout from 5 to 3
                    
                    subprocess.run([
                        "netsh", "advfirewall", "firewall", "delete", "rule",
                        f"name={rule_name}_Out"
                    ], capture_output=True, timeout=3)  # Reduced timeout from 5 to 3
                    
                    # Performance optimization: Reduce logging
                    if hasattr(block_device, '_last_log_time') and time.time() - getattr(block_device, '_last_log_time', 0) > 2.0:
                        log_info(f"Unblocked device: {ip}")
                        block_device._last_log_time = time.time()
                    return True
                except subprocess.TimeoutExpired:
                    log_error(f"Timeout unblocking device: {ip}")
                    return False
        else:
            log_error("Firewall blocking not implemented for this platform")
            return False
            
    except Exception as e:
        log_error(f"Error blocking device {ip}: {e}", exception=e)
        return False

def unblock_device(ip: str) -> bool:
    """Unblock a device"""
    return block_device(ip, block=False)

def block_ip(ip: str) -> bool:
    """Block an IP address (alias for block_device)"""
    return block_device(ip, block=True)

def unblock_ip(ip: str) -> bool:
    """Unblock an IP address (alias for unblock_device)"""
    return block_device(ip, block=False)

def is_blocking(ip: str) -> bool:
    """Check if an IP is currently being blocked"""
    return is_ip_blocked(ip)

def is_ip_blocked(ip: str) -> bool:
    """Check if an IP is currently blocked"""
    try:
        if platform.system() == "Windows":
            result = subprocess.run([
                "netsh", "advfirewall", "firewall", "show", "rule",
                f"name=DupeZBlock_{ip.replace('.', '_')}_In"
            ], capture_output=True, text=True, timeout=5)
            
            return "No rules match the specified criteria" not in result.stdout
        else:
            return False
    except:
        return False

def clear_all_dupez_blocks() -> bool:
    """Clear all DupeZ firewall blocks - OPTIMIZED"""
    try:
        if not is_admin():
            log_error("Clearing firewall blocks requires administrator privileges")
            return False
        
        if platform.system() == "Windows":
            # Performance optimization: Use single command to clear all rules
            try:
                # Clear all DupeZ blocks in one command
                result = subprocess.run([
                    "netsh", "advfirewall", "firewall", "delete", "rule",
                    "name=DupeZBlock_*"
                ], capture_output=True, timeout=5)
                
                if result.returncode == 0:
                    log_info("Cleared all DupeZ firewall blocks")
                    return True
                else:
                    log_warning("Some DupeZ firewall blocks may not have been cleared")
                    return True  # Return True even if some rules weren't found
                    
            except subprocess.TimeoutExpired:
                log_error("Timeout clearing firewall blocks")
                return False
        else:
            log_error("Firewall clearing not implemented for this platform")
            return False
            
    except Exception as e:
        log_error(f"Error clearing firewall blocks: {e}", exception=e)
        return False

def get_blocked_ips() -> List[str]:
    """Get list of currently blocked IPs"""
    try:
        blocked_ips = []
        if platform.system() == "Windows":
            result = subprocess.run([
                "netsh", "advfirewall", "firewall", "show", "rule", "name=DupeZBlock*"
            ], capture_output=True, text=True, timeout=5)
            
            for line in result.stdout.split('\n'):
                if 'Rule Name:' in line and 'DupeZBlock' in line:
                    # Extract IP from rule name
                    rule_name = line.split('Rule Name:')[1].strip()
                    if '_In' in rule_name:
                        ip = rule_name.replace('DupeZBlock_', '').replace('_In', '').replace('_', '.')
                        blocked_ips.append(ip)
        
        return blocked_ips
    except Exception as e:
        log_error(f"Error getting blocked IPs: {e}", exception=e)
        return []

# NetworkBlocker class for compatibility with tests
class NetworkBlocker:
    """Network blocker class for compatibility with existing tests"""
    
    def __init__(self):
        self.blocked_ips = set()
        self.is_active = False
    
    def block_ip(self, ip: str) -> bool:
        """Block an IP address"""
        try:
            success = block_device(ip, block=True)
            if success:
                self.blocked_ips.add(ip)
                self.is_active = True
                log_info(f"NetworkBlocker blocked IP: {ip}")
            return success
        except Exception as e:
            log_error(f"NetworkBlocker block error: {e}", exception=e)
            return False
    
    def unblock_ip(self, ip: str) -> bool:
        """Unblock an IP address"""
        try:
            success = block_device(ip, block=False)
            if success:
                self.blocked_ips.discard(ip)
                if not self.blocked_ips:
                    self.is_active = False
                log_info(f"NetworkBlocker unblocked IP: {ip}")
            return success
        except Exception as e:
            log_error(f"NetworkBlocker unblock error: {e}", exception=e)
            return False
    
    def is_ip_blocked(self, ip: str) -> bool:
        """Check if an IP is blocked"""
        try:
            return is_ip_blocked(ip)
        except Exception as e:
            log_error(f"NetworkBlocker check blocked error: {e}", exception=e)
            return False
    
    def get_blocked_ips(self) -> List[str]:
        """Get list of blocked IPs"""
        try:
            return list(self.blocked_ips)
        except Exception as e:
            log_error(f"NetworkBlocker get blocked IPs error: {e}", exception=e)
            return []
    
    def clear_all_blocks(self) -> bool:
        """Clear all blocks"""
        try:
            success = clear_all_dupez_blocks()
            if success:
                self.blocked_ips.clear()
                self.is_active = False
                log_info("NetworkBlocker cleared all blocks")
            return success
        except Exception as e:
            log_error(f"NetworkBlocker clear all error: {e}", exception=e)
            return False
    
    def is_active(self) -> bool:
        """Check if blocker is active"""
        return self.is_active
    
    def get_status(self) -> Dict:
        """Get blocker status"""
        return {
            "is_active": self.is_active,
            "blocked_ips": list(self.blocked_ips),
            "total_blocked": len(self.blocked_ips)
        }
