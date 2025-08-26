#!/usr/bin/env python3
"""
PS5 Blocker Module
Provides PS5-specific blocking functionality
"""

import platform
import subprocess
import socket
from typing import List, Dict, Optional
from app.logs.logger import log_info, log_error

class PS5Blocker:
    """PS5-specific blocking functionality"""
    
    def __init__(self):
        self.blocked_ps5s = set()
        self.is_running = False
    
    def initialize(self) -> bool:
        """Initialize the PS5 blocker"""
        try:
            self.is_running = True
            log_info("PS5 blocker initialized")
            return True
        except Exception as e:
            log_error(f"Failed to initialize PS5 blocker: {e}", exception=e)
            return False
    
    def block_ps5(self, ip: str) -> bool:
        """Block a PS5 device"""
        try:
            if not self.is_running:
                self.initialize()
            
            # Add to blocked set
            self.blocked_ps5s.add(ip)
            
            # Use firewall blocking
            from app.firewall.blocker import block_device
            success = block_device(ip, block=True)
            
            if success:
                log_info(f"PS5 blocked: {ip}")
                return True
            else:
                log_error(f"Failed to block PS5: {ip}")
                return False
                
        except Exception as e:
            log_error(f"Error blocking PS5 {ip}: {e}", exception=e)
            return False
    
    def unblock_ps5(self, ip: str) -> bool:
        """Unblock a PS5 device"""
        try:
            # Remove from blocked set
            if ip in self.blocked_ps5s:
                self.blocked_ps5s.remove(ip)
            
            # Use firewall unblocking
            from app.firewall.blocker import block_device
            success = block_device(ip, block=False)
            
            if success:
                log_info(f"PS5 unblocked: {ip}")
                return True
            else:
                log_error(f"Failed to unblock PS5: {ip}")
                return False
                
        except Exception as e:
            log_error(f"Error unblocking PS5 {ip}: {e}", exception=e)
            return False
    
    def unblock_all_ps5s(self, ips: List[str]) -> bool:
        """Unblock multiple PS5 devices"""
        try:
            success_count = 0
            for ip in ips:
                if self.unblock_ps5(ip):
                    success_count += 1
            
            log_info(f"Unblocked {success_count}/{len(ips)} PS5s")
            return success_count > 0
            
        except Exception as e:
            log_error(f"Error unblocking PS5s: {e}", exception=e)
            return False
    
    def get_blocked_ps5s(self) -> List[str]:
        """Get list of blocked PS5 IPs"""
        return list(self.blocked_ps5s)
    
    def is_ps5_blocked(self, ip: str) -> bool:
        """Check if a PS5 is blocked"""
        return ip in self.blocked_ps5s
    
    def stop(self):
        """Stop the PS5 blocker"""
        self.is_running = False
        log_info("PS5 blocker stopped")

# Global instance
# Global instance - Singleton pattern to prevent duplicate initialization
_ps5_blocker = None

def get_ps5_blocker():
    """Get singleton PS5 blocker instance"""
    global _ps5_blocker
    if _ps5_blocker is None:
        _ps5_blocker = PS5Blocker()
    return _ps5_blocker

# Backward compatibility
ps5_blocker = get_ps5_blocker() 
