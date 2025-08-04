#!/usr/bin/env python3
"""
Device Health Monitor for DupeZ
Monitors and protects device health during network interactions
"""

import os
import sys
import time
import subprocess
import threading
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
import json

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.logs.logger import log_info, log_error, log_warning

@dataclass
class DeviceHealth:
    """Device health status"""
    ip_address: str
    mac_address: str
    device_name: str
    health_score: float  # 0.0 to 100.0
    connectivity_status: str  # "healthy", "degraded", "poor", "disconnected"
    last_seen: datetime
    ping_latency: float
    packet_loss: float
    response_time: float
    error_count: int
    warnings: List[str]
    recommendations: List[str]

@dataclass
class HealthThresholds:
    """Health monitoring thresholds"""
    max_ping_latency: float = 100.0  # ms
    max_packet_loss: float = 5.0  # %
    max_response_time: float = 200.0  # ms
    max_error_count: int = 10
    health_check_interval: float = 5.0  # seconds (reduced for faster testing)
    recovery_timeout: float = 60.0  # seconds (reduced for faster testing)

class DeviceHealthMonitor:
    """Comprehensive device health monitoring and protection"""
    
    def __init__(self):
        self.devices: Dict[str, DeviceHealth] = {}
        self.thresholds = HealthThresholds()
        self.monitoring_active = False
        self.monitor_thread = None
        self.health_history: Dict[str, List[Dict]] = {}
        self.protection_mode = True  # Enable protection by default
        
        # Health event callbacks
        self.health_callbacks: List[callable] = []
        
    def add_device(self, ip_address: str, mac_address: str = "", device_name: str = ""):
        """Add device to health monitoring"""
        try:
            device_health = DeviceHealth(
                ip_address=ip_address,
                mac_address=mac_address,
                device_name=device_name,
                health_score=100.0,
                connectivity_status="healthy",
                last_seen=datetime.now(),
                ping_latency=0.0,
                packet_loss=0.0,
                response_time=0.0,
                error_count=0,
                warnings=[],
                recommendations=[]
            )
            
            self.devices[ip_address] = device_health
            self.health_history[ip_address] = []
            
            log_info(f"Added device {ip_address} to health monitoring")
            return True
            
        except Exception as e:
            log_error(f"Failed to add device {ip_address} to health monitoring: {e}")
            return False
    
    def remove_device(self, ip_address: str):
        """Remove device from health monitoring"""
        try:
            if ip_address in self.devices:
                del self.devices[ip_address]
            if ip_address in self.health_history:
                del self.health_history[ip_address]
            
            log_info(f"Removed device {ip_address} from health monitoring")
            return True
            
        except Exception as e:
            log_error(f"Failed to remove device {ip_address} from health monitoring: {e}")
            return False
    
    def check_device_health(self, ip_address: str) -> Optional[DeviceHealth]:
        """Check health of specific device"""
        try:
            if ip_address not in self.devices:
                log_warning(f"Device {ip_address} not in health monitoring")
                return None
            
            device = self.devices[ip_address]
            
            # Perform health checks
            ping_result = self._ping_device(ip_address)
            latency = ping_result.get('latency', 0.0)
            packet_loss = ping_result.get('packet_loss', 0.0)
            
            # Update device health
            device.ping_latency = latency
            device.packet_loss = packet_loss
            device.last_seen = datetime.now()
            
            # Calculate health score
            health_score = self._calculate_health_score(device)
            device.health_score = health_score
            
            # Update connectivity status
            device.connectivity_status = self._determine_connectivity_status(device)
            
            # Generate warnings and recommendations
            device.warnings = self._generate_warnings(device)
            device.recommendations = self._generate_recommendations(device)
            
            # Record health history
            self._record_health_history(ip_address, device)
            
            # Trigger health callbacks
            self._trigger_health_callbacks(device)
            
            return device
            
        except Exception as e:
            log_error(f"Failed to check health for device {ip_address}: {e}")
            return None
    
    def _ping_device(self, ip_address: str) -> Dict:
        """Ping device to check connectivity"""
        try:
            # Use native ping with shorter timeout for faster testing
            result = subprocess.run(
                ["ping", "-n", "2", "-w", "500", ip_address],
                capture_output=True,
                text=True,
                timeout=3  # Reduced timeout
            )
            
            if result.returncode == 0:
                # Parse ping output for latency and packet loss
                output = result.stdout
                lines = output.split('\n')
                
                latency = 0.0
                packet_loss = 0.0
                
                for line in lines:
                    if "time=" in line:
                        # Extract latency
                        try:
                            time_part = line.split("time=")[1].split()[0]
                            latency = float(time_part.replace("ms", ""))
                        except:
                            pass
                    elif "packets" in line and "loss" in line:
                        # Extract packet loss
                        try:
                            loss_part = line.split("loss")[0].split()[-1]
                            packet_loss = float(loss_part.replace("%", ""))
                        except:
                            pass
                
                return {
                    'latency': latency,
                    'packet_loss': packet_loss,
                    'reachable': True
                }
            else:
                return {
                    'latency': float('inf'),
                    'packet_loss': 100.0,
                    'reachable': False
                }
                
        except Exception as e:
            log_error(f"Failed to ping device {ip_address}: {e}")
            return {
                'latency': float('inf'),
                'packet_loss': 100.0,
                'reachable': False
            }
    
    def _calculate_health_score(self, device: DeviceHealth) -> float:
        """Calculate device health score (0-100)"""
        score = 100.0
        
        # Deduct points for high latency
        if device.ping_latency > self.thresholds.max_ping_latency:
            latency_penalty = min(30, (device.ping_latency - self.thresholds.max_ping_latency) / 10)
            score -= latency_penalty
        
        # Deduct points for packet loss
        if device.packet_loss > self.thresholds.max_packet_loss:
            loss_penalty = min(40, device.packet_loss * 2)
            score -= loss_penalty
        
        # Deduct points for errors
        if device.error_count > self.thresholds.max_error_count:
            error_penalty = min(20, device.error_count - self.thresholds.max_error_count)
            score -= error_penalty
        
        # Deduct points for poor response time
        if device.response_time > self.thresholds.max_response_time:
            response_penalty = min(20, (device.response_time - self.thresholds.max_response_time) / 10)
            score -= response_penalty
        
        return max(0.0, score)
    
    def _determine_connectivity_status(self, device: DeviceHealth) -> str:
        """Determine device connectivity status"""
        if device.health_score >= 80:
            return "healthy"
        elif device.health_score >= 60:
            return "degraded"
        elif device.health_score >= 30:
            return "poor"
        else:
            return "disconnected"
    
    def _generate_warnings(self, device: DeviceHealth) -> List[str]:
        """Generate warnings for device health issues"""
        warnings = []
        
        if device.ping_latency > self.thresholds.max_ping_latency:
            warnings.append(f"High latency: {device.ping_latency:.1f}ms")
        
        if device.packet_loss > self.thresholds.max_packet_loss:
            warnings.append(f"High packet loss: {device.packet_loss:.1f}%")
        
        if device.error_count > self.thresholds.max_error_count:
            warnings.append(f"High error count: {device.error_count}")
        
        if device.response_time > self.thresholds.max_response_time:
            warnings.append(f"Slow response time: {device.response_time:.1f}ms")
        
        if device.health_score < 50:
            warnings.append("Critical health score")
        
        return warnings
    
    def _generate_recommendations(self, device: DeviceHealth) -> List[str]:
        """Generate recommendations for device health improvement"""
        recommendations = []
        
        if device.ping_latency > self.thresholds.max_ping_latency:
            recommendations.append("Check network congestion and router settings")
        
        if device.packet_loss > self.thresholds.max_packet_loss:
            recommendations.append("Check network cables and interference")
        
        if device.error_count > self.thresholds.max_error_count:
            recommendations.append("Restart device and check for software issues")
        
        if device.health_score < 30:
            recommendations.append("Consider device replacement or professional diagnosis")
        
        return recommendations
    
    def _record_health_history(self, ip_address: str, device: DeviceHealth):
        """Record device health history"""
        if ip_address not in self.health_history:
            self.health_history[ip_address] = []
        
        history_entry = {
            'timestamp': datetime.now().isoformat(),
            'health_score': device.health_score,
            'connectivity_status': device.connectivity_status,
            'ping_latency': device.ping_latency,
            'packet_loss': device.packet_loss,
            'error_count': device.error_count
        }
        
        self.health_history[ip_address].append(history_entry)
        
        # Keep only last 100 entries
        if len(self.health_history[ip_address]) > 100:
            self.health_history[ip_address] = self.health_history[ip_address][-100:]
    
    def _trigger_health_callbacks(self, device: DeviceHealth):
        """Trigger health event callbacks"""
        for callback in self.health_callbacks:
            try:
                callback(device)
            except Exception as e:
                log_error(f"Health callback error: {e}")
    
    def add_health_callback(self, callback: callable):
        """Add health event callback"""
        self.health_callbacks.append(callback)
    
    def start_monitoring(self):
        """Start continuous health monitoring"""
        if self.monitoring_active:
            return
        
        self.monitoring_active = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        
        log_info("Device health monitoring started")
    
    def stop_monitoring(self):
        """Stop continuous health monitoring"""
        self.monitoring_active = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        
        log_info("Device health monitoring stopped")
    
    def _monitor_loop(self):
        """Main monitoring loop"""
        while self.monitoring_active:
            try:
                # Check all devices
                for ip_address in list(self.devices.keys()):
                    self.check_device_health(ip_address)
                
                # Wait for next check
                time.sleep(self.thresholds.health_check_interval)
                
            except Exception as e:
                log_error(f"Health monitoring loop error: {e}")
                time.sleep(5)
    
    def get_device_health(self, ip_address: str) -> Optional[DeviceHealth]:
        """Get current device health"""
        return self.devices.get(ip_address)
    
    def get_all_devices_health(self) -> List[DeviceHealth]:
        """Get health of all monitored devices"""
        return list(self.devices.values())
    
    def get_health_report(self) -> Dict:
        """Generate comprehensive health report"""
        total_devices = len(self.devices)
        healthy_devices = sum(1 for d in self.devices.values() if d.connectivity_status == "healthy")
        degraded_devices = sum(1 for d in self.devices.values() if d.connectivity_status == "degraded")
        poor_devices = sum(1 for d in self.devices.values() if d.connectivity_status == "poor")
        disconnected_devices = sum(1 for d in self.devices.values() if d.connectivity_status == "disconnected")
        
        avg_health_score = sum(d.health_score for d in self.devices.values()) / max(1, total_devices)
        
        return {
            'total_devices': total_devices,
            'healthy_devices': healthy_devices,
            'degraded_devices': degraded_devices,
            'poor_devices': poor_devices,
            'disconnected_devices': disconnected_devices,
            'average_health_score': avg_health_score,
            'monitoring_active': self.monitoring_active,
            'protection_mode': self.protection_mode,
            'devices': [asdict(device) for device in self.devices.values()]
        }
    
    def set_protection_mode(self, enabled: bool):
        """Enable or disable device protection mode"""
        self.protection_mode = enabled
        log_info(f"Device protection mode: {'enabled' if enabled else 'disabled'}")
    
    def is_device_healthy(self, ip_address: str) -> bool:
        """Check if device is healthy for interaction"""
        device = self.get_device_health(ip_address)
        if not device:
            return False
        
        # In protection mode, only allow interactions with healthy devices
        if self.protection_mode:
            return device.health_score >= 70 and device.connectivity_status in ["healthy", "degraded"]
        
        return True
    
    def get_device_warnings(self, ip_address: str) -> List[str]:
        """Get warnings for specific device"""
        device = self.get_device_health(ip_address)
        return device.warnings if device else []
    
    def get_device_recommendations(self, ip_address: str) -> List[str]:
        """Get recommendations for specific device"""
        device = self.get_device_health(ip_address)
        return device.recommendations if device else []

# Global health monitor instance
health_monitor = DeviceHealthMonitor() 
