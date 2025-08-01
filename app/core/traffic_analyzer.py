# app/core/traffic_analyzer.py

import time
import threading
import statistics
import traceback
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
import json
import psutil
import socket
from scapy.all import sniff, IP, TCP, UDP, ICMP
from app.logs.logger import log_info, log_error, log_warning, log_debug

# Global error handler for traffic analysis
def handle_traffic_error(func):
    """Decorator to handle errors in traffic analysis functions"""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            error_msg = f"Traffic analysis error in {func.__name__}: {e}"
            log_error(error_msg)
            
            # Write to traffic error log
            try:
                with open('logs/traffic_errors.log', 'a', encoding='utf-8') as f:
                    f.write(f"\n{'='*60}\n")
                    f.write(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write(f"Function: {func.__name__}\n")
                    f.write(f"Error: {e}\n")
                    f.write(f"Traceback:\n{traceback.format_exc()}\n")
                    f.write(f"{'='*60}\n")
            except Exception as log_error:
                pass  # Don't let logging errors cause more issues
            
            # Return safe defaults
            if func.__name__ in ['get_device_stats', 'get_network_overview']:
                return {}
            elif func.__name__ in ['get_recommendations']:
                return []
            elif func.__name__ in ['export_traffic_report']:
                return "Error generating report"
            else:
                return None
    return wrapper

@dataclass
class TrafficStats:
    """Traffic statistics for a device"""
    device_ip: str
    device_mac: str = ""
    hostname: str = ""
    total_bytes_sent: int = 0
    total_bytes_received: int = 0
    packets_sent: int = 0
    packets_received: int = 0
    connections_active: int = 0
    connections_total: int = 0
    bandwidth_usage: float = 0.0  # KB/s
    packet_rate: float = 0.0  # packets/s
    last_seen: datetime = field(default_factory=datetime.now)
    traffic_history: deque = field(default_factory=lambda: deque(maxlen=50))  # Reduced from 100
    port_usage: Dict[int, int] = field(default_factory=dict)
    protocol_usage: Dict[str, int] = field(default_factory=dict)
    suspicious_activity: List[str] = field(default_factory=list)
    risk_score: float = 0.0
    is_blocked: bool = False
    is_gaming_device: bool = False
    is_router: bool = False
    is_mobile: bool = False

@dataclass
class NetworkAnomaly:
    """Network anomaly detection result"""
    device_ip: str
    anomaly_type: str
    severity: str  # LOW, MEDIUM, HIGH, CRITICAL
    description: str
    timestamp: datetime
    evidence: Dict[str, Any]
    confidence: float

@dataclass
class TrafficPattern:
    """Traffic pattern analysis"""
    pattern_type: str  # BURST, STEADY, PERIODIC, RANDOM
    frequency: float
    duration: float
    intensity: float
    description: str

class AdvancedTrafficAnalyzer:
    """Advanced traffic analysis and monitoring system with resource management"""
    
    def __init__(self):
        self.device_stats: Dict[str, TrafficStats] = {}
        self.network_stats = {
            'total_bandwidth': 0.0,
            'active_connections': 0,
            'total_devices': 0,
            'suspicious_devices': 0,
            'anomalies_detected': 0
        }
        self.anomalies: List[NetworkAnomaly] = []
        self.traffic_patterns: Dict[str, List[TrafficPattern]] = {}
        self.packet_capture_thread: Optional[threading.Thread] = None
        self.analysis_thread: Optional[threading.Thread] = None
        self.is_running = False
        self.analysis_interval = 30.0  # Increased from 5.0 to 30.0 seconds for stability
        self.history_window = 180  # Reduced from 300 to 180 seconds (3 minutes)
        self.thresholds = {
            'high_bandwidth': 1000,  # KB/s
            'high_packet_rate': 1000,  # packets/s
            'suspicious_connections': 50,
            'unusual_ports': 10,
            'data_exfiltration': 5000  # KB/s sustained
        }
        
        # Resource management
        self.packet_queue = deque(maxlen=1000)  # Reduced from 10000
        self.processed_ips = set()  # Track processed IPs to prevent duplicates
        self.last_cleanup = time.time()
        self.cleanup_interval = 300  # Clean up every 5 minutes
        
        # Initialize with reduced monitoring
        self.packet_capture_enabled = False  # Disabled by default for stability
        self.psutil_monitoring_enabled = True  # Keep basic monitoring
        
        # Start basic monitoring only
        self._start_psutil_monitoring()
    
    def _check_admin_privileges(self) -> bool:
        """Check if running with admin privileges"""
        try:
            # Try to create a raw socket (requires admin privileges)
            test_socket = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
            test_socket.close()
            return True
        except (OSError, PermissionError):
            return False
    
    def _packet_capture_loop(self):
        """Packet capture loop with resource management"""
        try:
            log_info("Starting packet capture...")
            sniff(prn=self._process_packet, store=0, timeout=1)
        except Exception as e:
            log_error(f"Packet capture error: {e}")
        finally:
            log_info("Packet capture stopped")
    
    def _start_psutil_monitoring(self):
        """Start psutil-based monitoring with reduced frequency"""
        if self.psutil_monitoring_enabled:
            self.psutil_thread = threading.Thread(target=self._psutil_monitoring_loop, daemon=True)
            self.psutil_thread.start()
            log_info("Psutil monitoring started")
    
    def _psutil_monitoring_loop(self):
        """Psutil monitoring loop with resource management"""
        last_check = time.time()
        check_interval = 60.0  # Check every 60 seconds instead of continuous
        
        while self.is_running:
            try:
                current_time = time.time()
                if current_time - last_check >= check_interval:
                    self._update_network_connections()
                    last_check = current_time
                    
                    # Periodic cleanup
                    if current_time - self.last_cleanup >= self.cleanup_interval:
                        self._cleanup_resources()
                        self.last_cleanup = current_time
                
                time.sleep(10)  # Sleep for 10 seconds between checks
                
            except Exception as e:
                log_error(f"Psutil monitoring error: {e}")
                time.sleep(30)  # Wait longer on error
    
    def _update_network_connections(self):
        """Update network connections with error handling"""
        try:
            connections = psutil.net_connections()
            
            # Process only a subset of connections to prevent resource exhaustion
            max_connections = 100
            connections = connections[:max_connections]
            
            for conn in connections:
                try:
                    if conn.status == 'ESTABLISHED' and conn.raddr:
                        ip = conn.raddr.ip
                        if ip not in self.processed_ips:
                            self._update_device_stats_simulated(ip, 1024, 'received')
                            self.processed_ips.add(ip)
                except Exception as e:
                    continue
                    
        except Exception as e:
            log_error(f"Network connections update error: {e}")
    
    def _cleanup_resources(self):
        """Clean up resources to prevent memory leaks"""
        try:
            # Clear old processed IPs
            if len(self.processed_ips) > 1000:
                self.processed_ips.clear()
            
            # Clear old anomalies
            current_time = datetime.now()
            self.anomalies = [
                anomaly for anomaly in self.anomalies 
                if (current_time - anomaly.timestamp).seconds < 3600  # Keep only last hour
            ]
            
            # Clear old traffic patterns
            for device_ip in list(self.traffic_patterns.keys()):
                if len(self.traffic_patterns[device_ip]) > 10:
                    self.traffic_patterns[device_ip] = self.traffic_patterns[device_ip][-10:]
            
            log_info("Traffic analyzer resources cleaned up")
            
        except Exception as e:
            log_error(f"Resource cleanup error: {e}")
    
    def _update_device_stats_simulated(self, ip: str, size: int, direction: str):
        """Update device stats with simulated data"""
        try:
            if ip not in self.device_stats:
                self.device_stats[ip] = TrafficStats(device_ip=ip)
            
            stats = self.device_stats[ip]
            
            if direction == 'sent':
                stats.total_bytes_sent += size
                stats.packets_sent += 1
            else:
                stats.total_bytes_received += size
                stats.packets_received += 1
            
            stats.last_seen = datetime.now()
            
            # Update traffic history
            current_time = datetime.now()
            stats.traffic_history.append({
                'timestamp': current_time,
                'bytes': size,
                'direction': direction
            })
            
        except Exception as e:
            log_error(f"Device stats update error: {e}")
    
    def _process_packet(self, packet):
        """Process packet with error handling"""
        try:
            if IP in packet:
                src_ip = packet[IP].src
                dst_ip = packet[IP].dst
                
                # Process source IP
                self._update_device_stats(src_ip, packet, 'sent')
                
                # Process destination IP
                self._update_device_stats(dst_ip, packet, 'received')
                
                # Check for suspicious patterns
                self._check_suspicious_patterns(packet)
                
        except Exception as e:
            log_error(f"Packet processing error: {e}")
    
    def _update_device_stats(self, ip: str, packet, direction: str):
        """Update device statistics with error handling"""
        try:
            if ip not in self.device_stats:
                self.device_stats[ip] = TrafficStats(device_ip=ip)
            
            stats = self.device_stats[ip]
            packet_size = len(packet)
            
            if direction == 'sent':
                stats.total_bytes_sent += packet_size
                stats.packets_sent += 1
            else:
                stats.total_bytes_received += packet_size
                stats.packets_received += 1
            
            stats.last_seen = datetime.now()
            
            # Update protocol usage
            if TCP in packet:
                protocol = 'TCP'
                port = packet[TCP].dport if direction == 'sent' else packet[TCP].sport
            elif UDP in packet:
                protocol = 'UDP'
                port = packet[UDP].dport if direction == 'sent' else packet[UDP].sport
            elif ICMP in packet:
                protocol = 'ICMP'
                port = 0
            else:
                protocol = 'OTHER'
                port = 0
            
            stats.protocol_usage[protocol] = stats.protocol_usage.get(protocol, 0) + 1
            if port > 0:
                stats.port_usage[port] = stats.port_usage.get(port, 0) + 1
            
            # Update traffic history
            current_time = datetime.now()
            stats.traffic_history.append({
                'timestamp': current_time,
                'bytes': packet_size,
                'direction': direction
            })
            
        except Exception as e:
            log_error(f"Device stats update error for {ip}: {e}")
    
    def _check_suspicious_patterns(self, packet):
        """Check for suspicious patterns with error handling"""
        try:
            if IP in packet and TCP in packet:
                src_ip = packet[IP].src
                dst_port = packet[TCP].dport
                
                # Check for port scanning
                self._check_port_scanning(src_ip, dst_port)
                
                # Check for data exfiltration
                packet_size = len(packet)
                self._check_data_exfiltration(src_ip, packet_size)
                
        except Exception as e:
            log_error(f"Suspicious pattern check error: {e}")
    
    def _check_port_scanning(self, ip: str, port: int):
        """Check for port scanning activity"""
        try:
            if ip not in self.device_stats:
                return
            
            stats = self.device_stats[ip]
            unusual_ports = len([p for p in stats.port_usage.keys() if p > 1024])
            
            if unusual_ports > self.thresholds['unusual_ports']:
                self._mark_suspicious_activity(ip, f"Port scanning detected: {unusual_ports} unusual ports")
                
        except Exception as e:
            log_error(f"Port scanning check error: {e}")
    
    def _check_data_exfiltration(self, ip: str, packet_size: int):
        """Check for data exfiltration patterns"""
        try:
            if ip not in self.device_stats:
                return
            
            stats = self.device_stats[ip]
            
            # Calculate bandwidth usage
            if len(stats.traffic_history) >= 2:
                recent_traffic = [entry for entry in stats.traffic_history 
                                if (datetime.now() - entry['timestamp']).seconds < 60]
                
                if recent_traffic:
                    total_bytes = sum(entry['bytes'] for entry in recent_traffic)
                    bandwidth_kb = total_bytes / 1024
                    
                    if bandwidth_kb > self.thresholds['data_exfiltration']:
                        self._mark_suspicious_activity(ip, f"High bandwidth usage: {bandwidth_kb:.1f} KB/s")
                        
        except Exception as e:
            log_error(f"Data exfiltration check error: {e}")
    
    def _mark_suspicious_activity(self, ip: str, activity: str):
        """Mark suspicious activity for a device"""
        try:
            if ip not in self.device_stats:
                return
            
            stats = self.device_stats[ip]
            if activity not in stats.suspicious_activity:
                stats.suspicious_activity.append(activity)
                stats.risk_score = min(100.0, stats.risk_score + 10.0)
                
                log_warning(f"Suspicious activity detected for {ip}: {activity}")
                
        except Exception as e:
            log_error(f"Mark suspicious activity error: {e}")
    
    def start_analysis(self):
        """Start traffic analysis with reduced frequency"""
        if not self.is_running:
            self.is_running = True
            self.analysis_thread = threading.Thread(target=self._analysis_loop, daemon=True)
            self.analysis_thread.start()
            log_info("Traffic analysis started")
    
    def stop_analysis(self):
        """Stop traffic analysis"""
        self.is_running = False
        if self.analysis_thread:
            self.analysis_thread.join(timeout=5)
        log_info("Traffic analysis stopped")
    
    def _analysis_loop(self):
        """Analysis loop with reduced frequency"""
        while self.is_running:
            try:
                self._update_bandwidth_usage()
                self._detect_anomalies()
                self._analyze_traffic_patterns()
                self._update_network_stats()
                
                # Sleep for longer intervals to reduce resource usage
                time.sleep(self.analysis_interval)
                
            except Exception as e:
                log_error(f"Analysis loop error: {e}")
                time.sleep(60)  # Wait longer on error
    
    def _update_bandwidth_usage(self):
        """Update bandwidth usage with error handling"""
        try:
            current_time = datetime.now()
            
            for ip, stats in self.device_stats.items():
                try:
                    # Calculate bandwidth from recent traffic history
                    recent_traffic = [entry for entry in stats.traffic_history 
                                    if (current_time - entry['timestamp']).seconds < 60]
                    
                    if recent_traffic:
                        total_bytes = sum(entry['bytes'] for entry in recent_traffic)
                        stats.bandwidth_usage = total_bytes / 1024  # Convert to KB/s
                        
                        # Calculate packet rate
                        stats.packet_rate = len(recent_traffic)
                        
                        # Check for high bandwidth usage
                        if stats.bandwidth_usage > self.thresholds['high_bandwidth']:
                            self._mark_suspicious_activity(ip, f"High bandwidth: {stats.bandwidth_usage:.1f} KB/s")
                            
                except Exception as e:
                    log_error(f"Bandwidth update error for {ip}: {e}")
                    continue
                    
        except Exception as e:
            log_error(f"Bandwidth usage update error: {e}")
    
    def _detect_anomalies(self):
        """Detect network anomalies with error handling"""
        try:
            current_time = datetime.now()
            
            for ip, stats in self.device_stats.items():
                try:
                    # Check for high risk score
                    if stats.risk_score > 50:
                        self._create_anomaly(
                            ip, "HIGH_RISK_SCORE", "HIGH",
                            f"Device has high risk score: {stats.risk_score}",
                            {"risk_score": stats.risk_score, "suspicious_activities": stats.suspicious_activity},
                            0.8
                        )
                    
                    # Check for unusual traffic patterns
                    if stats.bandwidth_usage > self.thresholds['high_bandwidth'] * 2:
                        self._create_anomaly(
                            ip, "EXCESSIVE_BANDWIDTH", "CRITICAL",
                            f"Excessive bandwidth usage: {stats.bandwidth_usage:.1f} KB/s",
                            {"bandwidth_usage": stats.bandwidth_usage},
                            0.9
                        )
                        
                except Exception as e:
                    log_error(f"Anomaly detection error for {ip}: {e}")
                    continue
                    
        except Exception as e:
            log_error(f"Anomaly detection error: {e}")
    
    def _create_anomaly(self, ip: str, anomaly_type: str, severity: str, 
                       description: str, evidence: Dict[str, Any], confidence: float):
        """Create a network anomaly record"""
        try:
            anomaly = NetworkAnomaly(
                device_ip=ip,
                anomaly_type=anomaly_type,
                severity=severity,
                description=description,
                timestamp=datetime.now(),
                evidence=evidence,
                confidence=confidence
            )
            
            self.anomalies.append(anomaly)
            log_warning(f"Anomaly detected: {description}")
            
        except Exception as e:
            log_error(f"Create anomaly error: {e}")
    
    def _analyze_device_pattern(self, stats: TrafficStats) -> Optional[TrafficPattern]:
        """Analyze traffic pattern for a device"""
        try:
            if len(stats.traffic_history) < 5:
                return None
            
            # Simple pattern analysis
            recent_traffic = list(stats.traffic_history)[-10:]
            bytes_list = [entry['bytes'] for entry in recent_traffic]
            
            if not bytes_list:
                return None
            
            avg_bytes = statistics.mean(bytes_list)
            std_bytes = statistics.stdev(bytes_list) if len(bytes_list) > 1 else 0
            
            if std_bytes > avg_bytes * 0.5:
                pattern_type = "BURST"
            elif avg_bytes > 1000:
                pattern_type = "STEADY"
            else:
                pattern_type = "LOW"
            
            return TrafficPattern(
                pattern_type=pattern_type,
                frequency=1.0,
                duration=60.0,
                intensity=avg_bytes,
                description=f"{pattern_type} traffic pattern"
            )
            
        except Exception as e:
            log_error(f"Device pattern analysis error: {e}")
            return None
    
    def _analyze_traffic_patterns(self):
        """Analyze traffic patterns for all devices"""
        try:
            for ip, stats in self.device_stats.items():
                try:
                    pattern = self._analyze_device_pattern(stats)
                    if pattern:
                        if ip not in self.traffic_patterns:
                            self.traffic_patterns[ip] = []
                        self.traffic_patterns[ip].append(pattern)
                        
                        # Keep only recent patterns
                        if len(self.traffic_patterns[ip]) > 5:
                            self.traffic_patterns[ip] = self.traffic_patterns[ip][-5:]
                            
                except Exception as e:
                    log_error(f"Traffic pattern analysis error for {ip}: {e}")
                    continue
                    
        except Exception as e:
            log_error(f"Traffic pattern analysis error: {e}")
    
    def _update_network_stats(self):
        """Update overall network statistics"""
        try:
            total_bandwidth = sum(stats.bandwidth_usage for stats in self.device_stats.values())
            active_connections = sum(stats.connections_active for stats in self.device_stats.values())
            suspicious_devices = len([stats for stats in self.device_stats.values() if stats.risk_score > 30])
            
            self.network_stats.update({
                'total_bandwidth': total_bandwidth,
                'active_connections': active_connections,
                'total_devices': len(self.device_stats),
                'suspicious_devices': suspicious_devices,
                'anomalies_detected': len(self.anomalies)
            })
            
        except Exception as e:
            log_error(f"Network stats update error: {e}")
    
    @handle_traffic_error
    def get_device_stats(self, ip: str) -> Optional[TrafficStats]:
        """Get traffic statistics for a specific device"""
        return self.device_stats.get(ip)
    
    @handle_traffic_error
    def get_network_overview(self) -> Dict[str, Any]:
        """Get network overview with error handling"""
        try:
            return {
                'network_stats': self.network_stats,
                'top_bandwidth_devices': self._get_top_devices('bandwidth_usage', 5),
                'top_risk_devices': self._get_top_devices('risk_score', 5),
                'recent_anomalies': self.anomalies[-10:] if self.anomalies else [],
                'total_devices': len(self.device_stats)
            }
        except Exception as e:
            log_error(f"Network overview error: {e}")
            return {}
    
    def _get_top_devices(self, metric: str, count: int) -> List[Dict[str, Any]]:
        """Get top devices by metric"""
        try:
            devices = []
            for ip, stats in self.device_stats.items():
                try:
                    value = getattr(stats, metric, 0)
                    devices.append({
                        'ip': ip,
                        'hostname': stats.hostname,
                        'value': value,
                        'risk_score': stats.risk_score
                    })
                except Exception as e:
                    log_error(f"Device metric error for {ip}: {e}")
                    continue
            
            # Sort by metric value and return top devices
            devices.sort(key=lambda x: x['value'], reverse=True)
            return devices[:count]
            
        except Exception as e:
            log_error(f"Top devices error: {e}")
            return []
    
    def export_traffic_report(self, filename: str = None) -> str:
        """Export traffic report with error handling"""
        try:
            if not filename:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"traffic_report_{timestamp}.json"
            
            report_data = {
                'timestamp': datetime.now().isoformat(),
                'network_stats': self.network_stats,
                'devices': {},
                'anomalies': [],
                'recommendations': self.get_recommendations()
            }
            
            # Add device data
            for ip, stats in self.device_stats.items():
                try:
                    report_data['devices'][ip] = {
                        'hostname': stats.hostname,
                        'total_bytes_sent': stats.total_bytes_sent,
                        'total_bytes_received': stats.total_bytes_received,
                        'bandwidth_usage': stats.bandwidth_usage,
                        'risk_score': stats.risk_score,
                        'suspicious_activity': stats.suspicious_activity
                    }
                except Exception as e:
                    log_error(f"Device export error for {ip}: {e}")
                    continue
            
            # Add anomalies
            for anomaly in self.anomalies[-20:]:  # Last 20 anomalies
                try:
                    report_data['anomalies'].append({
                        'device_ip': anomaly.device_ip,
                        'type': anomaly.anomaly_type,
                        'severity': anomaly.severity,
                        'description': anomaly.description,
                        'timestamp': anomaly.timestamp.isoformat()
                    })
                except Exception as e:
                    log_error(f"Anomaly export error: {e}")
                    continue
            
            # Write to file
            with open(filename, 'w') as f:
                json.dump(report_data, f, indent=2)
            
            log_info(f"Traffic report exported to {filename}")
            return filename
            
        except Exception as e:
            log_error(f"Traffic report export error: {e}")
            return ""
    
    def get_recommendations(self) -> List[str]:
        """Get security recommendations based on analysis"""
        try:
            recommendations = []
            
            # Check for high-risk devices
            high_risk_devices = [stats for stats in self.device_stats.values() if stats.risk_score > 50]
            if high_risk_devices:
                recommendations.append(f"Investigate {len(high_risk_devices)} high-risk devices")
            
            # Check for excessive bandwidth usage
            high_bandwidth_devices = [stats for stats in self.device_stats.values() 
                                    if stats.bandwidth_usage > self.thresholds['high_bandwidth']]
            if high_bandwidth_devices:
                recommendations.append(f"Monitor {len(high_bandwidth_devices)} devices with high bandwidth usage")
            
            # Check for recent anomalies
            recent_anomalies = [anomaly for anomaly in self.anomalies 
                              if (datetime.now() - anomaly.timestamp).seconds < 3600]
            if recent_anomalies:
                recommendations.append(f"Review {len(recent_anomalies)} recent anomalies")
            
            if not recommendations:
                recommendations.append("Network appears to be operating normally")
            
            return recommendations
            
        except Exception as e:
            log_error(f"Recommendations error: {e}")
            return ["Error generating recommendations"] 