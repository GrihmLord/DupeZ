# app/core/smart_mode.py

import threading
import time
import logging
from typing import Dict, List, Optional
from app.logs.logger import log_info, log_error

logger = logging.getLogger(__name__)

class SmartModeEngine:
    """Enterprise-level intelligent network management system"""
    
    def __init__(self):
        self.enabled = False
        self.monitoring = False
        self.monitored_devices = {}  # {ip: device_info}
        self.active_rules = {}  # {rule_id: rule_info}
        self.blocked_devices = set()
        self.monitor_thread = None
        self.should_stop = False  # Fixed: renamed from stop_monitoring to avoid conflict
        
        # Enterprise-level monitoring parameters
        self.bandwidth_threshold = 1024 * 1024  # 1MB/s
        self.connection_threshold = 100  # Max connections per device
        self.suspicious_ports = {22, 23, 3389, 5900, 8080, 8443}  # SSH, Telnet, RDP, VNC, HTTP/HTTPS
        self.block_duration = 300  # 5 minutes
        
        # Traffic patterns for anomaly detection
        self.traffic_patterns = {
            "ddos": {"packet_rate": 1000, "bandwidth": 10 * 1024 * 1024},  # 10MB/s
            "scanning": {"port_scan": 50, "time_window": 60},  # 50 ports in 60 seconds
            "malware": {"suspicious_domains": True, "encrypted_traffic": True}
        }
    
    def is_enabled(self) -> bool:
        """Check if smart mode is enabled"""
        return self.enabled
    
    def enable(self):
        """Enable smart mode"""
        self.enabled = True
        self.start_monitoring()
        log_info("🚀 Enterprise Smart Mode enabled")
    
    def disable(self):
        """Disable smart mode"""
        self.enabled = False
        self.stop_monitoring()
        log_info("🛑 Enterprise Smart Mode disabled")
    
    def start_monitoring(self):
        """Start enterprise-level network monitoring"""
        if self.monitoring:
            return
        
        self.monitoring = True
        self.should_stop = False  # Fixed: use should_stop instead of stop_monitoring
        
        # Start monitoring thread
        self.monitor_thread = threading.Thread(target=self._monitor_network, daemon=True)
        self.monitor_thread.start()
        
        log_info("📊 Enterprise network monitoring started")
    
    def stop_monitoring(self):
        """Stop enterprise-level network monitoring"""
        self.monitoring = False
        self.should_stop = True  # Fixed: use should_stop instead of stop_monitoring
        
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=5)
        
        log_info("📊 Enterprise network monitoring stopped")
    
    def _monitor_network(self):
        """Enterprise-level network monitoring loop"""
        while self.monitoring and not self.should_stop:  # Fixed: use should_stop
            try:
                # Monitor network traffic
                self._analyze_traffic_patterns()
                
                # Check for suspicious activities
                self._detect_suspicious_activities()
                
                # Apply automatic blocking rules
                self._apply_automatic_rules()
                
                # Update device status
                self._update_device_status()
                
                time.sleep(10)  # Check every 10 seconds
                
            except Exception as e:
                log_error(f"Enterprise monitoring error: {e}")
                time.sleep(30)  # Wait longer on error
    
    def _analyze_traffic_patterns(self):
        """Analyze network traffic patterns for anomalies"""
        try:
            import psutil
            
            # Get network connections
            connections = psutil.net_connections()
            
            # Group connections by remote IP
            ip_connections = {}
            for conn in connections:
                if conn.raddr:
                    remote_ip = conn.raddr.ip
                    if remote_ip not in ip_connections:
                        ip_connections[remote_ip] = []
                    ip_connections[remote_ip].append(conn)
            
            # Analyze each IP's traffic patterns
            for ip, conns in ip_connections.items():
                self._analyze_ip_traffic(ip, conns)
                
        except Exception as e:
            log_error(f"Traffic pattern analysis error: {e}")
    
    def _analyze_ip_traffic(self, ip: str, connections: List):
        """Analyze traffic patterns for a specific IP"""
        try:
            # Check connection count
            if len(connections) > self.connection_threshold:
                self._flag_suspicious_activity(ip, "high_connection_count", {
                    "connections": len(connections),
                    "threshold": self.connection_threshold
                })
            
            # Check for suspicious ports
            suspicious_ports_found = []
            for conn in connections:
                if conn.raddr and conn.raddr.port in self.suspicious_ports:
                    suspicious_ports_found.append(conn.raddr.port)
            
            if suspicious_ports_found:
                self._flag_suspicious_activity(ip, "suspicious_ports", {
                    "ports": suspicious_ports_found
                })
            
            # Check for port scanning patterns
            if len(set(conn.raddr.port for conn in connections if conn.raddr)) > self.traffic_patterns["scanning"]["port_scan"]:
                self._flag_suspicious_activity(ip, "port_scanning", {
                    "ports_scanned": len(set(conn.raddr.port for conn in connections if conn.raddr))
                })
                
        except Exception as e:
            log_error(f"IP traffic analysis error for {ip}: {e}")
    
    def _flag_suspicious_activity(self, ip: str, activity_type: str, details: Dict):
        """Flag suspicious activity for automatic response"""
        try:
            if ip not in self.monitored_devices:
                self.monitored_devices[ip] = {
                    "suspicious_activities": [],
                    "block_count": 0,
                    "last_blocked": None
                }
            
            activity = {
                "type": activity_type,
                "details": details,
                "timestamp": time.time()
            }
            
            self.monitored_devices[ip]["suspicious_activities"].append(activity)
            
            # Update device monitoring
            
            log_info(f"🚨 Suspicious activity detected: {ip} - {activity_type}")
            
        except Exception as e:
            log_error(f"Flag suspicious activity error: {e}")
    

    
    def _detect_suspicious_activities(self):
        """Detect enterprise-level suspicious activities"""
        try:
            import psutil
            
            # Get network I/O statistics
            net_io = psutil.net_io_counters()
            
            # Check for DDoS-like patterns
            if net_io.packets_recv > self.traffic_patterns["ddos"]["packet_rate"]:
                self._flag_network_anomaly("ddos_detected", {
                    "packets_received": net_io.packets_recv,
                    "threshold": self.traffic_patterns["ddos"]["packet_rate"]
                })
            
            # Check for bandwidth anomalies
            current_bandwidth = (net_io.bytes_sent + net_io.bytes_recv) / 1024 / 1024  # MB/s
            if current_bandwidth > self.traffic_patterns["ddos"]["bandwidth"] / 1024 / 1024:
                self._flag_network_anomaly("high_bandwidth", {
                    "bandwidth_mbps": current_bandwidth,
                    "threshold_mbps": self.traffic_patterns["ddos"]["bandwidth"] / 1024 / 1024
                })
                
        except Exception as e:
            log_error(f"Detect suspicious activities error: {e}")
    
    def _flag_network_anomaly(self, anomaly_type: str, details: Dict):
        """Flag network-wide anomalies"""
        try:
            log_info(f"🚨 Network anomaly detected: {anomaly_type}")
            
            # Apply network-wide protection measures
            if anomaly_type == "ddos_detected":
                self._apply_ddos_protection()
            elif anomaly_type == "high_bandwidth":
                self._apply_bandwidth_throttling()
                
        except Exception as e:
            log_error(f"Flag network anomaly error: {e}")
    
    def _apply_ddos_protection(self):
        """Apply DDoS protection measures"""
        try:
            log_info("🛡️ Applying DDoS protection measures")
            
            # This would implement DDoS protection
            # For now, just log the action
            
        except Exception as e:
            log_error(f"Apply DDoS protection error: {e}")
    
    def _apply_bandwidth_throttling(self):
        """Apply bandwidth throttling"""
        try:
            log_info("⏱️ Applying bandwidth throttling")
            
            # This would implement bandwidth throttling
            # For now, just log the action
            
        except Exception as e:
            log_error(f"Apply bandwidth throttling error: {e}")
    
    def _apply_automatic_rules(self):
        """Apply automatic blocking rules based on risk scores"""
        try:
            for ip, device in self.monitored_devices.items():
                risk_score = device.get("risk_score", 0)
                
                # Auto-block high-risk devices
                if risk_score >= 80 and ip not in self.blocked_devices:
                    self._auto_block_device(ip, "high_risk_score", {"risk_score": risk_score})
                
                # Auto-block devices with multiple suspicious activities
                suspicious_count = len(device.get("suspicious_activities", []))
                if suspicious_count >= 5 and ip not in self.blocked_devices:
                    self._auto_block_device(ip, "multiple_suspicious_activities", {"count": suspicious_count})
                    
        except Exception as e:
            log_error(f"Apply automatic rules error: {e}")
    
    def _auto_block_device(self, ip: str, reason: str, details: Dict):
        """Automatically block a device"""
        try:
            # Import here to avoid circular imports
            from app.firewall.network_disruptor import network_disruptor
            
            # Block the device
            if network_disruptor.disconnect_device(ip):
                self.blocked_devices.add(ip)
                
                # Update device info
                if ip in self.monitored_devices:
                    self.monitored_devices[ip]["block_count"] += 1
                    self.monitored_devices[ip]["last_blocked"] = time.time()
                
                log_info(f"🛡️ Auto-blocked device {ip} - {reason}")
                
                # Schedule unblock after duration
                threading.Timer(self.block_duration, self._auto_unblock_device, args=[ip]).start()
                
        except Exception as e:
            log_error(f"Auto block device error for {ip}: {e}")
    
    def _auto_unblock_device(self, ip: str):
        """Automatically unblock a device after duration"""
        try:
            # Import here to avoid circular imports
            from app.firewall.network_disruptor import network_disruptor
            
            # Unblock the device
            if network_disruptor.reconnect_device(ip):
                self.blocked_devices.discard(ip)
                log_info(f"🔓 Auto-unblocked device {ip}")
                
        except Exception as e:
            log_error(f"Auto unblock device error for {ip}: {e}")
    
    def _update_device_status(self):
        """Update device status and clean up old data"""
        try:
            current_time = time.time()
            
            # Clean up old suspicious activities (older than 1 hour)
            for ip, device in self.monitored_devices.items():
                if "suspicious_activities" in device:
                    device["suspicious_activities"] = [
                        activity for activity in device["suspicious_activities"]
                        if current_time - activity["timestamp"] < 3600
                    ]
                    
        except Exception as e:
            log_error(f"Update device status error: {e}")
    
    def get_smart_mode_status(self) -> Dict:
        """Get enterprise-level smart mode status"""
        try:
            return {
                "enabled": self.enabled,
                "monitoring": self.monitoring,
                "devices_monitored": len(self.monitored_devices),
                "blocked_devices": len(self.blocked_devices),
                "active_rules": len(self.active_rules),
                "block_duration": self.block_duration
            }
        except Exception as e:
            log_error(f"Get smart mode status error: {e}")
            return {"enabled": False, "error": str(e)}
    
    def add_device(self, ip: str, device_info: Dict):
        """Add a device to smart mode monitoring"""
        try:
            self.monitored_devices[ip] = {
                "info": device_info,
                "suspicious_activities": [],
                "block_count": 0,
                "last_blocked": None
            }
            log_info(f"📱 Added device {ip} to smart mode monitoring")
        except Exception as e:
            log_error(f"Add device error: {e}")
    
    def remove_device(self, ip: str):
        """Remove a device from smart mode monitoring"""
        try:
            if ip in self.monitored_devices:
                del self.monitored_devices[ip]
                log_info(f"📱 Removed device {ip} from smart mode monitoring")
        except Exception as e:
            log_error(f"Remove device error: {e}")
    

    

    
    def set_block_duration(self, duration: int):
        """Set the duration for automatic blocking"""
        try:
            self.block_duration = max(60, duration)  # Minimum 1 minute
            log_info(f"⏱️ Block duration set to {self.block_duration} seconds")
        except Exception as e:
            log_error(f"Set block duration error: {e}")

# Global enterprise instance
smart_mode = SmartModeEngine()

# Helper functions for external access
def enable_smart_mode():
    """Enable enterprise smart mode"""
    smart_mode.enable()

def disable_smart_mode():
    """Disable enterprise smart mode"""
    smart_mode.disable()

def get_smart_mode_status() -> Dict:
    """Get enterprise smart mode status"""
    return smart_mode.get_smart_mode_status()

def is_enabled() -> bool:
    """Check if enterprise smart mode is enabled"""
    return smart_mode.is_enabled()
