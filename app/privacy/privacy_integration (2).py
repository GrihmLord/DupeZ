#!/usr/bin/env python3
"""
Privacy Integration for DupeZ
"""

import sys
import os
from typing import Dict, List, Optional, Any
from functools import wraps

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.privacy.privacy_manager import privacy_manager
from app.logs.logger import log_info, log_error

def privacy_protect(func):
    """Decorator to add privacy protection to functions"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            # Log function call with privacy protection
            privacy_manager.log_privacy_event("function_call", {
                "function": func.__name__,
                "module": func.__module__
            })
            
            # Execute function
            result = func(*args, **kwargs)
            
            # Log successful execution
            privacy_manager.log_privacy_event("function_success", {
                "function": func.__name__,
                "module": func.__module__
            })
            
            return result
            
        except Exception as e:
            # Log error with privacy protection
            privacy_manager.log_privacy_event("function_error", {
                "function": func.__name__,
                "module": func.__module__,
                "error": str(e)
            }, sensitive=True)
            raise
            
    return wrapper

def anonymize_device_data(device_data: Dict) -> Dict:
    """Anonymize device data for privacy protection"""
    if not privacy_manager.settings.anonymize_device_names:
        return device_data
        
    anonymized = device_data.copy()
    
    # Anonymize device names
    if 'name' in anonymized:
        anonymized['name'] = privacy_manager.anonymize_device_name(anonymized['name'])
    
    # Anonymize IP addresses
    if 'ip' in anonymized:
        anonymized['ip'] = privacy_manager.anonymize_ip(anonymized['ip'])
    
    # Anonymize MAC addresses
    if 'mac' in anonymized:
        anonymized['mac'] = privacy_manager.anonymize_mac(anonymized['mac'])
    
    return anonymized

def anonymize_network_data(network_data: Dict) -> Dict:
    """Anonymize network data for privacy protection"""
    if not privacy_manager.settings.anonymize_ip_addresses:
        return network_data
        
    anonymized = network_data.copy()
    
    # Anonymize IP addresses
    for key, value in anonymized.items():
        if isinstance(value, str) and 'ip' in key.lower():
            anonymized[key] = privacy_manager.anonymize_ip(value)
        elif isinstance(value, dict):
            anonymized[key] = anonymize_network_data(value)
        elif isinstance(value, list):
            anonymized[key] = [anonymize_network_data(item) if isinstance(item, dict) else item for item in value]
    
    return anonymized

class PrivacyAwareDeviceScanner:
    """Privacy-aware device scanner wrapper"""
    
    def __init__(self, scanner):
        self.scanner = scanner
        
    def scan_devices(self, *args, **kwargs):
        """Scan devices with privacy protection"""
        try:
            # Log scan start
            privacy_manager.log_privacy_event("device_scan_start", {
                "timestamp": privacy_manager.start_time.isoformat()
            }, sensitive=True)
            
            # Perform scan
            devices = self.scanner.scan_devices(*args, **kwargs)
            
            # Anonymize device data
            anonymized_devices = []
            for device in devices:
                anonymized_device = anonymize_device_data(device)
                anonymized_devices.append(anonymized_device)
            
            # Log scan completion
            privacy_manager.log_privacy_event("device_scan_complete", {
                "devices_found": len(anonymized_devices),
                "timestamp": privacy_manager.start_time.isoformat()
            }, sensitive=True)
            
            return anonymized_devices
            
        except Exception as e:
            privacy_manager.log_privacy_event("device_scan_error", {
                "error": str(e),
                "timestamp": privacy_manager.start_time.isoformat()
            }, sensitive=True)
            raise

class PrivacyAwareNetworkBlocker:
    """Privacy-aware network blocker wrapper"""
    
    def __init__(self, blocker):
        self.blocker = blocker
        
    def block_device(self, device_ip: str, *args, **kwargs):
        """Block device with privacy protection"""
        try:
            # Anonymize IP for logging
            anonymized_ip = privacy_manager.anonymize_ip(device_ip)
            
            # Log blocking action
            privacy_manager.log_privacy_event("device_block", {
                "action": "block",
                "device_ip": anonymized_ip,
                "timestamp": privacy_manager.start_time.isoformat()
            }, sensitive=True)
            
            # Perform blocking
            result = self.blocker.block_device(device_ip, *args, **kwargs)
            
            # Log result
            privacy_manager.log_privacy_event("device_block_result", {
                "action": "block",
                "device_ip": anonymized_ip,
                "success": result,
                "timestamp": privacy_manager.start_time.isoformat()
            }, sensitive=True)
            
            return result
            
        except Exception as e:
            privacy_manager.log_privacy_event("device_block_error", {
                "action": "block",
                "device_ip": privacy_manager.anonymize_ip(device_ip),
                "error": str(e),
                "timestamp": privacy_manager.start_time.isoformat()
            }, sensitive=True)
            raise
    
    def unblock_device(self, device_ip: str, *args, **kwargs):
        """Unblock device with privacy protection"""
        try:
            # Anonymize IP for logging
            anonymized_ip = privacy_manager.anonymize_ip(device_ip)
            
            # Log unblocking action
            privacy_manager.log_privacy_event("device_unblock", {
                "action": "unblock",
                "device_ip": anonymized_ip,
                "timestamp": privacy_manager.start_time.isoformat()
            }, sensitive=True)
            
            # Perform unblocking
            result = self.blocker.unblock_device(device_ip, *args, **kwargs)
            
            # Log result
            privacy_manager.log_privacy_event("device_unblock_result", {
                "action": "unblock",
                "device_ip": anonymized_ip,
                "success": result,
                "timestamp": privacy_manager.start_time.isoformat()
            }, sensitive=True)
            
            return result
            
        except Exception as e:
            privacy_manager.log_privacy_event("device_unblock_error", {
                "action": "unblock",
                "device_ip": privacy_manager.anonymize_ip(device_ip),
                "error": str(e),
                "timestamp": privacy_manager.start_time.isoformat()
            }, sensitive=True)
            raise

def integrate_privacy_protection():
    """Integrate privacy protection into existing modules"""
    try:
        # Import existing modules
        from app.network.device_scanner import DeviceScanner
        from app.firewall.blocker import block_device, unblock_device
        
        # Create privacy-aware wrappers
        privacy_scanner = PrivacyAwareDeviceScanner(DeviceScanner())
        privacy_blocker = PrivacyAwareNetworkBlocker(None)  # Will be set dynamically
        
        # Replace original functions with privacy-aware versions
        import app.network.device_scanner
        app.network.device_scanner.scan_devices = privacy_scanner.scan_devices
        
        import app.firewall.blocker
        app.firewall.blocker.block_device = privacy_blocker.block_device
        app.firewall.blocker.unblock_device = privacy_blocker.unblock_device
        
        # Log integration
        privacy_manager.log_privacy_event("privacy_integration", {
            "status": "completed",
            "modules_integrated": ["device_scanner", "network_blocker"],
            "timestamp": privacy_manager.start_time.isoformat()
        })
        
        log_info("Privacy protection integrated successfully")
        
    except Exception as e:
        log_error(f"Failed to integrate privacy protection: {e}")
        privacy_manager.log_privacy_event("privacy_integration_error", {
            "error": str(e),
            "timestamp": privacy_manager.start_time.isoformat()
        }, sensitive=True)

def setup_privacy_protection():
    """Setup privacy protection for the application"""
    try:
        # Set default privacy level
        privacy_manager.set_privacy_level("high")
        
        # Integrate privacy protection
        integrate_privacy_protection()
        
        # Log privacy setup
        privacy_manager.log_privacy_event("privacy_setup", {
            "privacy_level": privacy_manager.settings.privacy_level,
            "timestamp": privacy_manager.start_time.isoformat()
        })
        
        log_info("Privacy protection setup completed")
        
    except Exception as e:
        log_error(f"Failed to setup privacy protection: {e}")

def cleanup_privacy_data():
    """Cleanup privacy data on application exit"""
    try:
        privacy_manager.clear_privacy_data()
        log_info("Privacy data cleaned up successfully")
        
    except Exception as e:
        log_error(f"Failed to cleanup privacy data: {e}")

# Auto-setup privacy protection when module is imported
if __name__ != "__main__":
    setup_privacy_protection() 