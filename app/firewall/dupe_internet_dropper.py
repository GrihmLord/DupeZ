#!/usr/bin/env python3
"""
Dupe Internet Dropper Module
Provides internet dropping functionality for duping
"""

import threading
import time
from typing import List, Dict, Optional
from app.logs.logger import log_info, log_error

class DupeInternetDropper:
    """Internet dropping functionality for duping"""
    
    def __init__(self):
        self.is_active = False
        self.active_devices = set()
        self.active_methods = []
        self.stop_event = threading.Event()
        self.dropper_thread = None
    
    def start_dupe_with_devices(self, devices: List[Dict], methods: List[str]) -> bool:
        """Start dupe with specific devices and methods"""
        try:
            if self.is_active:
                log_info("Dupe already active")
                return True
            
            # Extract device IPs
            device_ips = [device.get('ip') for device in devices if device.get('ip')]
            
            if not device_ips:
                log_error("No valid device IPs provided")
                return False
            
            self.active_devices = set(device_ips)
            self.active_methods = methods
            self.stop_event.clear()
            self.is_active = True
            
            # Start dropper thread
            self.dropper_thread = threading.Thread(
                target=self._dupe_worker, daemon=True
            )
            self.dropper_thread.start()
            
            log_info(f"Dupe started on {len(device_ips)} devices with methods: {methods}")
            return True
            
        except Exception as e:
            log_error(f"Failed to start dupe: {e}", exception=e)
            return False
    
    def stop_dupe(self) -> bool:
        """Stop dupe functionality"""
        try:
            if not self.is_active:
                return True
            
            self.stop_event.set()
            self.is_active = False
            
            if self.dropper_thread:
                self.dropper_thread.join(timeout=5)
            
            self.active_devices.clear()
            self.active_methods.clear()
            
            log_info("Dupe stopped")
            return True
            
        except Exception as e:
            log_error(f"Failed to stop dupe: {e}", exception=e)
            return False
    
    def _dupe_worker(self):
        """Main dupe worker thread"""
        try:
            while not self.stop_event.is_set():
                # Apply dupe methods to active devices
                for device_ip in self.active_devices:
                    if self.stop_event.is_set():
                        break
                    
                    # Apply each method
                    for method in self.active_methods:
                        if self.stop_event.is_set():
                            break
                        
                        self._apply_method(device_ip, method)
                
                # Small delay between cycles
                time.sleep(0.1)
                
        except Exception as e:
            log_error(f"Dupe worker error: {e}", exception=e)
        finally:
            self.is_active = False
    
    def _apply_method(self, device_ip: str, method: str):
        """Apply a specific method to a device"""
        try:
            if method == "firewall":
                from app.firewall.blocker import block_device
                block_device(device_ip, block=True)
            elif method == "route":
                # Route blocking would go here
                pass
            elif method == "arp":
                # ARP spoofing would go here
                pass
            elif method == "udp_interrupt":
                # UDP interruption would go here
                pass
            
        except Exception as e:
            log_error(f"Error applying method {method} to {device_ip}: {e}", exception=e)
    
    def is_dupe_active(self) -> bool:
        """Check if dupe is currently active"""
        return self.is_active
    
    def get_active_devices(self) -> List[str]:
        """Get list of active devices"""
        return list(self.active_devices)
    
    def get_active_methods(self) -> List[str]:
        """Get list of active methods"""
        return self.active_methods.copy()

# Global instance
dupe_internet_dropper = DupeInternetDropper() 