#!/usr/bin/env python3
"""
Simple Firewall Blocker Module
Provides basic firewall blocking functionality
"""

import platform
import subprocess
import sys

from typing import List, Dict
from app.logs.logger import log_info, log_error, log_warning
import time

# Suppress console window flash on Windows
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

def is_admin() -> bool:
    """Check if running with administrator privileges"""
    try:
        if platform.system() == "Windows":
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        else:
            import os
            return os.geteuid() == 0
    except Exception:
        return False

def _netsh(*args, timeout=3) -> bool:
    """Run a netsh advfirewall command. Returns True on success."""
    try:
        subprocess.run(["netsh", "advfirewall", "firewall", *args],
                       capture_output=True, timeout=timeout, creationflags=_NO_WINDOW)
        return True
    except subprocess.TimeoutExpired:
        return False

def _throttled_log(msg: str):
    """Log at most every 2 seconds to reduce spam."""
    now = time.time()
    if now - getattr(_throttled_log, '_last', 0) > 2.0:
        log_info(msg)
        _throttled_log._last = now

def block_device(ip: str, block: bool = True) -> bool:
    """Block or unblock a device using firewall rules."""
    try:
        if not is_admin():
            log_error("Firewall blocking requires administrator privileges")
            return False

        if platform.system() != "Windows":
            log_error("Firewall blocking not implemented for this platform")
            return False

        rule_name = f"DupeZBlock_{ip.replace('.', '_')}"
        if block:
            ok = (_netsh("add", "rule", f"name={rule_name}_In", "dir=in",
                         "action=block", f"remoteip={ip}", "enable=yes")
                  and _netsh("add", "rule", f"name={rule_name}_Out", "dir=out",
                             "action=block", f"remoteip={ip}", "enable=yes"))
            if ok:
                _throttled_log(f"Blocked device: {ip} (TEMPORARY)")
            else:
                log_error(f"Timeout blocking device: {ip}")
            return ok
        else:
            ok = (_netsh("delete", "rule", f"name={rule_name}_In")
                  and _netsh("delete", "rule", f"name={rule_name}_Out"))
            if ok:
                _throttled_log(f"Unblocked device: {ip}")
            else:
                log_error(f"Timeout unblocking device: {ip}")
            return ok

    except Exception as e:
        log_error(f"Error blocking device {ip}: {e}", exception=e)
        return False

def is_ip_blocked(ip: str) -> bool:
    """Check if an IP is currently blocked"""
    try:
        if platform.system() == "Windows":
            result = subprocess.run([
                "netsh", "advfirewall", "firewall", "show", "rule",
                f"name=DupeZBlock_{ip.replace('.', '_')}_In"
            ], capture_output=True, text=True, timeout=5, creationflags=_NO_WINDOW)

            return "No rules match the specified criteria" not in result.stdout
        else:
            return False
    except Exception:
        return False

# Aliases for backwards compatibility (must follow function definitions)
unblock_device = lambda ip: block_device(ip, block=False)
block_ip = block_device
unblock_ip = unblock_device
is_blocking = is_ip_blocked

def clear_all_dupez_blocks() -> bool:
    """Clear all DupeZ firewall blocks.

    netsh does NOT support wildcards in 'name=' — we enumerate DupeZ rules
    first then delete each by exact name.
    """
    try:
        if not is_admin():
            log_error("Clearing firewall blocks requires administrator privileges")
            return False

        if platform.system() != "Windows":
            log_error("Firewall clearing not implemented for this platform")
            return False

        try:
            # Enumerate all firewall rules and find DupeZ ones
            result = subprocess.run([
                "netsh", "advfirewall", "firewall", "show", "rule", "name=all"
            ], capture_output=True, text=True, timeout=10, creationflags=_NO_WINDOW)

            rule_names = []
            for line in result.stdout.split('\n'):
                if 'Rule Name:' in line and 'DupeZBlock' in line:
                    name = line.split('Rule Name:')[1].strip()
                    rule_names.append(name)

            if not rule_names:
                log_info("No DupeZ firewall blocks to clear")
                return True

            deleted = 0
            for name in rule_names:
                if _netsh("delete", "rule", f"name={name}"):
                    deleted += 1

            log_info(f"Cleared {deleted}/{len(rule_names)} DupeZ firewall blocks")
            return True

        except subprocess.TimeoutExpired:
            log_error("Timeout clearing firewall blocks")
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
            ], capture_output=True, text=True, timeout=5, creationflags=_NO_WINDOW)

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

    def get_active(self) -> bool:
        """Check if blocker is active"""
        return self.is_active

    def get_status(self) -> Dict:
        """Get blocker status"""
        return {
            "is_active": self.is_active,
            "blocked_ips": list(self.blocked_ips),
            "total_blocked": len(self.blocked_ips)
        }

