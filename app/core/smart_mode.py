# app/core/smart_mode.py

import time
import threading
from typing import List, Dict, Optional
from dataclasses import dataclass
from app.logs.logger import log_info, log_error

@dataclass
class TrafficStats:
    ip: str
    bytes_sent: int = 0
    bytes_received: int = 0
    packets_sent: int = 0
    packets_received: int = 0
    last_activity: float = 0
    connection_count: int = 0

class SmartModeEngine:
    def __init__(self):
        self.enabled = False
        self.traffic_stats: Dict[str, TrafficStats] = {}
        self.blocked_devices: List[str] = []
        self.thresholds = {
            "high_traffic": 1024 * 1024,  # 1MB
            "connection_limit": 50,
            "activity_timeout": 300,  # 5 minutes
            "block_duration": 600,  # 10 minutes
        }
        self.monitoring_thread = None
        self.stop_monitoring = False
    
    def start_monitoring(self):
        """Start the smart monitoring thread"""
        if self.monitoring_thread and self.monitoring_thread.is_alive():
            return
        
        self.stop_monitoring = False
        self.monitoring_thread = threading.Thread(target=self._monitor_traffic, daemon=True)
        self.monitoring_thread.start()
        log_info("Smart mode monitoring started")
    
    def stop_monitoring(self):
        """Stop the smart monitoring thread"""
        self.monitoring = False
        if hasattr(self, 'monitoring_thread') and self.monitoring_thread:
            self.monitoring_thread.join(timeout=5)
        log_info("Smart mode monitoring stopped")
    
    def _monitor_traffic(self):
        """Monitor traffic and apply smart blocking rules"""
        while self.monitoring:
            try:
                current_time = time.time()
                
                # Analyze traffic patterns
                for ip, stats in self.traffic_stats.items():
                    if self._should_block_device(ip, stats, current_time):
                        self._block_device(ip)
                
                # Check for devices that should be unblocked
                self._check_unblock_devices(current_time)
                
                time.sleep(5)  # Check every 5 seconds (reduced from 10)
                
            except Exception as e:
                log_error(f"Smart mode monitoring error: {e}")
                time.sleep(15)  # Reduced wait time on error (from 30)
    
    def _should_block_device(self, ip: str, stats: TrafficStats, current_time: float) -> bool:
        """Determine if a device should be blocked based on traffic patterns"""
        if ip in self.blocked_devices:
            return False
        
        # Check for high traffic
        total_bytes = stats.bytes_sent + stats.bytes_received
        if total_bytes > self.thresholds["high_traffic"]:
            log_info(f"High traffic detected for {ip}: {total_bytes} bytes")
            return True
        
        # Check for too many connections
        if stats.connection_count > self.thresholds["connection_limit"]:
            log_info(f"Too many connections for {ip}: {stats.connection_count}")
            return True
        
        # Check for suspicious activity patterns
        if self._detect_suspicious_activity(stats):
            log_info(f"Suspicious activity detected for {ip}")
            return True
        
        return False
    
    def _detect_suspicious_activity(self, stats: TrafficStats) -> bool:
        """Detect suspicious network activity patterns"""
        # High packet rate with low data
        if stats.packets_sent > 1000 and stats.bytes_sent < 1024:
            return True
        
        # Asymmetric traffic (suspicious for DDoS)
        if stats.bytes_sent > stats.bytes_received * 10:
            return True
        
        # Burst traffic patterns
        if stats.packets_sent > 500:  # High packet rate
            return True
        
        return False
    
    def _block_device(self, ip: str):
        """Block a device and record the action"""
        if ip not in self.blocked_devices:
            self.blocked_devices.append(ip)
            log_info(f"Smart mode blocked device: {ip}")
            # Notify the main controller
            self._notify_block_action(ip, True)
    
    def _check_unblock_devices(self, current_time: float):
        """Check if blocked devices should be unblocked"""
        # Simple timeout-based unblocking
        # In a real implementation, you'd track block times
        pass
    
    def _notify_block_action(self, ip: str, blocked: bool):
        """Notify the main application of blocking actions"""
        # This would be connected to the main controller
        pass
    
    def update_traffic_stats(self, ip: str, bytes_sent: int = 0, bytes_received: int = 0,
                           packets_sent: int = 0, packets_received: int = 0):
        """Update traffic statistics for a device"""
        if ip not in self.traffic_stats:
            self.traffic_stats[ip] = TrafficStats(ip=ip)
        
        stats = self.traffic_stats[ip]
        stats.bytes_sent += bytes_sent
        stats.bytes_received += bytes_received
        stats.packets_sent += packets_sent
        stats.packets_received += packets_received
        stats.last_activity = time.time()
    
    def get_top_talkers(self, limit: int = 5) -> List[Dict]:
        """Get the top traffic generators"""
        sorted_devices = sorted(
            self.traffic_stats.values(),
            key=lambda x: x.bytes_sent + x.bytes_received,
            reverse=True
        )
        
        return [
            {
                "ip": stats.ip,
                "total_bytes": stats.bytes_sent + stats.bytes_received,
                "bytes_sent": stats.bytes_sent,
                "bytes_received": stats.bytes_received,
                "packets": stats.packets_sent + stats.packets_received,
                "connections": stats.connection_count
            }
            for stats in sorted_devices[:limit]
        ]
    
    def get_device_stats(self, ip: str) -> Optional[TrafficStats]:
        """Get traffic statistics for a specific device"""
        return self.traffic_stats.get(ip)
    
    def clear_stats(self):
        """Clear all traffic statistics"""
        self.traffic_stats.clear()
        log_info("Traffic statistics cleared")
    
    def set_thresholds(self, thresholds: Dict):
        """Update smart mode thresholds"""
        self.thresholds.update(thresholds)
        log_info(f"Smart mode thresholds updated: {thresholds}")
    
    def is_enabled(self) -> bool:
        """Check if smart mode is enabled"""
        return self.enabled
    
    def enable(self):
        """Enable smart mode"""
        self.enabled = True
        self.start_monitoring()
        log_info("Smart mode enabled")
    
    def disable(self):
        """Disable smart mode"""
        self.enabled = False
        self.stop_monitoring()
        log_info("Smart mode disabled")

# Global smart mode instance
smart_mode = SmartModeEngine()

def detect_top_talkers(devices: List[Dict]) -> List[Dict]:
    """Legacy function for backward compatibility"""
    return smart_mode.get_top_talkers()

def enable_smart_mode():
    """Enable smart mode"""
    smart_mode.enable()

def disable_smart_mode():
    """Disable smart mode"""
    smart_mode.disable()

def get_smart_mode_status() -> Dict:
    """Get smart mode status and statistics"""
    return {
        "enabled": smart_mode.is_enabled(),
        "top_talkers": smart_mode.get_top_talkers(),
        "blocked_devices": smart_mode.blocked_devices,
        "thresholds": smart_mode.thresholds
    }
