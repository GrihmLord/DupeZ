#!/usr/bin/env python3
"""
Device Protection for DupeZ
Ensures devices aren't damaged during network interactions
"""

import sys
import os
import time
from typing import Dict, List, Optional, Tuple
from functools import wraps

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.health.device_health_monitor import health_monitor
from app.logs.logger import log_info, log_error, log_warning

def protect_device_health(func):
    """Decorator to protect device health during operations"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Extract IP address from arguments if present
        ip_address = None
        for arg in args:
            if isinstance(arg, str) and '.' in arg and arg.count('.') == 3:
                ip_address = arg
                break
        
        if not ip_address:
            # Try to find IP in kwargs
            for key, value in kwargs.items():
                if isinstance(value, str) and '.' in value and value.count('.') == 3:
                    ip_address = value
                    break
        
        if ip_address:
            # Check device health before operation
            if not health_monitor.is_device_healthy(ip_address):
                log_warning(f"Device {ip_address} health check failed - operation blocked")
                return False
            
            # Add device to monitoring if not already monitored
            if not health_monitor.get_device_health(ip_address):
                health_monitor.add_device(ip_address)
            
            # Perform health check
            device_health = health_monitor.check_device_health(ip_address)
            if device_health and device_health.health_score < 50:
                log_warning(f"Device {ip_address} has poor health score ({device_health.health_score}) - operation may be risky")
        
        # Execute the function
        try:
            result = func(*args, **kwargs)
            
            # Post-operation health check
            if ip_address:
                post_health = health_monitor.check_device_health(ip_address)
                if post_health and post_health.health_score < 30:
                    log_error(f"Device {ip_address} health deteriorated after operation")
                    # Consider automatic recovery measures
                    health_monitor._trigger_health_callbacks(post_health)
            
            return result
            
        except Exception as e:
            log_error(f"Operation failed for device {ip_address}: {e}")
            if ip_address:
                # Record error in device health
                device = health_monitor.get_device_health(ip_address)
                if device:
                    device.error_count += 1
                    health_monitor.check_device_health(ip_address)
            raise
    
    return wrapper

class DeviceProtectionManager:
    """Manages device protection during network operations"""
    
    def __init__(self):
        self.protection_enabled = True
        self.safe_operations = []
        self.blocked_operations = []
        self.health_thresholds = {
            'min_health_score': 70,
            'max_latency': 100,
            'max_packet_loss': 5.0,
            'max_error_count': 10
        }
    
    def enable_protection(self):
        """Enable device protection"""
        self.protection_enabled = True
        health_monitor.set_protection_mode(True)
        log_info("Device protection enabled")
    
    def disable_protection(self):
        """Disable device protection"""
        self.protection_enabled = False
        health_monitor.set_protection_mode(False)
        log_info("Device protection disabled")
    
    def safe_block_device(self, ip_address: str, **kwargs) -> bool:
        """Safely block device with health protection"""
        try:
            # Pre-operation health check
            if not self._pre_operation_check(ip_address, "block"):
                return False
            
            # Perform blocking operation
            from app.firewall.blocker import block_device
            result = block_device(ip_address, **kwargs)
            
            # Post-operation health check
            self._post_operation_check(ip_address, "block", result)
            
            return result
            
        except Exception as e:
            log_error(f"Safe block operation failed for {ip_address}: {e}")
            return False
    
    def safe_unblock_device(self, ip_address: str, **kwargs) -> bool:
        """Safely unblock device with health protection"""
        try:
            # Pre-operation health check
            if not self._pre_operation_check(ip_address, "unblock"):
                return False
            
            # Perform unblocking operation
            from app.firewall.blocker import unblock_device
            result = unblock_device(ip_address, **kwargs)
            
            # Post-operation health check
            self._post_operation_check(ip_address, "unblock", result)
            
            return result
            
        except Exception as e:
            log_error(f"Safe unblock operation failed for {ip_address}: {e}")
            return False
    
    def safe_scan_device(self, ip_address: str, **kwargs) -> Dict:
        """Safely scan device with health protection"""
        try:
            # Pre-operation health check
            if not self._pre_operation_check(ip_address, "scan"):
                return {}
            
            # Perform scan operation
            from app.network.device_scanner import scan_devices
            result = scan_devices([ip_address], **kwargs)
            
            # Post-operation health check
            self._post_operation_check(ip_address, "scan", len(result) > 0)
            
            return result
            
        except Exception as e:
            log_error(f"Safe scan operation failed for {ip_address}: {e}")
            return {}
    
    def _pre_operation_check(self, ip_address: str, operation: str) -> bool:
        """Pre-operation health and safety checks"""
        try:
            # Add device to monitoring if not already monitored
            if not health_monitor.get_device_health(ip_address):
                health_monitor.add_device(ip_address)
            
            # Perform health check
            device_health = health_monitor.check_device_health(ip_address)
            if not device_health:
                log_warning(f"Could not check health for device {ip_address}")
                return False
            
            # Check if device is healthy enough for operation
            if not health_monitor.is_device_healthy(ip_address):
                log_warning(f"Device {ip_address} not healthy enough for {operation} operation")
                return False
            
            # Check specific thresholds
            if device_health.health_score < self.health_thresholds['min_health_score']:
                log_warning(f"Device {ip_address} health score too low ({device_health.health_score}) for {operation}")
                return False
            
            if device_health.ping_latency > self.health_thresholds['max_latency']:
                log_warning(f"Device {ip_address} latency too high ({device_health.ping_latency}ms) for {operation}")
                return False
            
            if device_health.packet_loss > self.health_thresholds['max_packet_loss']:
                log_warning(f"Device {ip_address} packet loss too high ({device_health.packet_loss}%) for {operation}")
                return False
            
            if device_health.error_count > self.health_thresholds['max_error_count']:
                log_warning(f"Device {ip_address} error count too high ({device_health.error_count}) for {operation}")
                return False
            
            log_info(f"Device {ip_address} passed pre-operation health check for {operation}")
            return True
            
        except Exception as e:
            log_error(f"Pre-operation check failed for {ip_address}: {e}")
            return False
    
    def _post_operation_check(self, ip_address: str, operation: str, success: bool):
        """Post-operation health and safety checks"""
        try:
            # Wait a moment for network to stabilize
            time.sleep(1)
            
            # Perform post-operation health check
            device_health = health_monitor.check_device_health(ip_address)
            if not device_health:
                log_warning(f"Could not perform post-operation health check for {ip_address}")
                return
            
            # Check for health deterioration
            if device_health.health_score < 30:
                log_error(f"Device {ip_address} health severely deteriorated after {operation}")
                self._trigger_recovery_measures(ip_address, device_health)
            elif device_health.health_score < 50:
                log_warning(f"Device {ip_address} health deteriorated after {operation}")
            
            # Record operation
            if success:
                self.safe_operations.append({
                    'ip_address': ip_address,
                    'operation': operation,
                    'timestamp': time.time(),
                    'health_score': device_health.health_score
                })
            else:
                self.blocked_operations.append({
                    'ip_address': ip_address,
                    'operation': operation,
                    'timestamp': time.time(),
                    'reason': 'health_check_failed'
                })
            
            log_info(f"Post-operation health check completed for {ip_address} ({operation})")
            
        except Exception as e:
            log_error(f"Post-operation check failed for {ip_address}: {e}")
    
    def _trigger_recovery_measures(self, ip_address: str, device_health):
        """Trigger automatic recovery measures for unhealthy devices"""
        try:
            log_warning(f"Triggering recovery measures for device {ip_address}")
            
            # Attempt to unblock device if it was blocked
            from app.firewall.blocker import unblock_device
            unblock_result = unblock_device(ip_address)
            
            if unblock_result:
                log_info(f"Successfully unblocked device {ip_address} as recovery measure")
            
            # Wait for device to recover
            time.sleep(5)
            
            # Re-check health
            new_health = health_monitor.check_device_health(ip_address)
            if new_health and new_health.health_score > 50:
                log_info(f"Device {ip_address} recovered after measures")
            else:
                log_warning(f"Device {ip_address} did not recover after measures")
                
        except Exception as e:
            log_error(f"Recovery measures failed for {ip_address}: {e}")
    
    def get_protection_status(self) -> Dict:
        """Get device protection status"""
        health_report = health_monitor.get_health_report()
        
        return {
            'protection_enabled': self.protection_enabled,
            'health_monitoring_active': health_report['monitoring_active'],
            'total_monitored_devices': health_report['total_devices'],
            'healthy_devices': health_report['healthy_devices'],
            'degraded_devices': health_report['degraded_devices'],
            'poor_devices': health_report['poor_devices'],
            'disconnected_devices': health_report['disconnected_devices'],
            'average_health_score': health_report['average_health_score'],
            'safe_operations_count': len(self.safe_operations),
            'blocked_operations_count': len(self.blocked_operations),
            'health_thresholds': self.health_thresholds
        }
    
    def get_device_protection_info(self, ip_address: str) -> Dict:
        """Get protection information for specific device"""
        device_health = health_monitor.get_device_health(ip_address)
        if not device_health:
            return {'error': 'Device not monitored'}
        
        warnings = health_monitor.get_device_warnings(ip_address)
        recommendations = health_monitor.get_device_recommendations(ip_address)
        
        return {
            'ip_address': ip_address,
            'health_score': device_health.health_score,
            'connectivity_status': device_health.connectivity_status,
            'ping_latency': device_health.ping_latency,
            'packet_loss': device_health.packet_loss,
            'error_count': device_health.error_count,
            'last_seen': device_health.last_seen.isoformat(),
            'warnings': warnings,
            'recommendations': recommendations,
            'safe_for_operations': health_monitor.is_device_healthy(ip_address)
        }
    
    def start_health_monitoring(self):
        """Start health monitoring"""
        health_monitor.start_monitoring()
        log_info("Device health monitoring started")
    
    def stop_health_monitoring(self):
        """Stop health monitoring"""
        health_monitor.stop_monitoring()
        log_info("Device health monitoring stopped")

# Global device protection manager
device_protection = DeviceProtectionManager() 
