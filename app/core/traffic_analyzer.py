# app/core/traffic_analyzer.py

import time
import threading
import statistics
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
import json
import psutil
import socket
from scapy.all import sniff, IP, TCP, UDP, ICMP
from app.logs.logger import log_info, log_error, log_warning, log_debug

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
    traffic_history: deque = field(default_factory=lambda: deque(maxlen=100))
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
    """Advanced traffic analysis and monitoring system"""
    
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
        self.analysis_interval = 5.0  # seconds
        self.history_window = 300  # 5 minutes
        self.thresholds = {
            'high_bandwidth': 1000,  # KB/s
            'high_packet_rate': 1000,  # packets/s
            'suspicious_connections': 50,
            'unusual_ports': 10,
            'data_exfiltration': 5000  # KB/s sustained
        }
        
        # Initialize packet capture
        self.packet_queue = deque(maxlen=10000)
        self.start_packet_capture()
    
    def start_packet_capture(self):
        """Start packet capture in background thread"""
        try:
            self.packet_capture_thread = threading.Thread(
                target=self._packet_capture_loop,
                daemon=True
            )
            self.packet_capture_thread.start()
            log_info("Advanced traffic analyzer started")
        except Exception as e:
            log_error(f"Failed to start packet capture: {e}")
    
    def _packet_capture_loop(self):
        """Main packet capture loop"""
        try:
            # Use scapy to capture packets
            sniff(
                prn=self._process_packet,
                store=0,
                stop_filter=lambda _: not self.is_running
            )
        except Exception as e:
            log_error(f"Packet capture error: {e}")
    
    def _process_packet(self, packet):
        """Process individual packets"""
        try:
            if IP in packet:
                src_ip = packet[IP].src
                dst_ip = packet[IP].dst
                
                # Update device statistics
                self._update_device_stats(src_ip, packet, 'sent')
                self._update_device_stats(dst_ip, packet, 'received')
                
                # Check for suspicious patterns
                self._check_suspicious_patterns(packet)
                
        except Exception as e:
            log_debug(f"Packet processing error: {e}")
    
    def _update_device_stats(self, ip: str, packet, direction: str):
        """Update statistics for a specific device"""
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
        
        stats.last_seen = datetime.now()
    
    def _check_suspicious_patterns(self, packet):
        """Check for suspicious network patterns"""
        try:
            if IP in packet:
                src_ip = packet[IP].src
                
                # Check for port scanning
                if TCP in packet and packet[TCP].flags & 2:  # SYN flag
                    self._check_port_scanning(src_ip, packet[TCP].dport)
                
                # Check for data exfiltration
                if len(packet) > 1400:  # Large packets
                    self._check_data_exfiltration(src_ip, len(packet))
                
                # Check for unusual protocols
                if packet.proto not in [6, 17, 1]:  # Not TCP, UDP, or ICMP
                    self._mark_suspicious_activity(src_ip, f"Unusual protocol: {packet.proto}")
                
        except Exception as e:
            log_debug(f"Pattern check error: {e}")
    
    def _check_port_scanning(self, ip: str, port: int):
        """Check for port scanning activity"""
        if ip not in self.device_stats:
            return
        
        stats = self.device_stats[ip]
        recent_ports = [p for p, count in stats.port_usage.items() 
                       if count > 0 and (datetime.now() - stats.last_seen).seconds < 60]
        
        if len(recent_ports) > self.thresholds['unusual_ports']:
            self._mark_suspicious_activity(ip, f"Port scanning detected: {len(recent_ports)} ports")
    
    def _check_data_exfiltration(self, ip: str, packet_size: int):
        """Check for potential data exfiltration"""
        if ip not in self.device_stats:
            return
        
        stats = self.device_stats[ip]
        recent_traffic = sum([size for size, _ in stats.traffic_history 
                            if (datetime.now() - stats.last_seen).seconds < 60])
        
        if recent_traffic > self.thresholds['data_exfiltration']:
            self._mark_suspicious_activity(ip, f"Potential data exfiltration: {recent_traffic} KB")
    
    def _mark_suspicious_activity(self, ip: str, activity: str):
        """Mark device as having suspicious activity"""
        if ip not in self.device_stats:
            return
        
        stats = self.device_stats[ip]
        stats.suspicious_activity.append(f"{datetime.now().strftime('%H:%M:%S')}: {activity}")
        stats.risk_score = min(100.0, stats.risk_score + 10.0)
        
        # Keep only recent suspicious activities
        if len(stats.suspicious_activity) > 10:
            stats.suspicious_activity = stats.suspicious_activity[-10:]
    
    def start_analysis(self):
        """Start the traffic analysis loop"""
        self.is_running = True
        self.analysis_thread = threading.Thread(
            target=self._analysis_loop,
            daemon=True
        )
        self.analysis_thread.start()
        log_info("Traffic analysis started")
    
    def stop_analysis(self):
        """Stop the traffic analysis"""
        self.is_running = False
        if self.analysis_thread:
            self.analysis_thread.join(timeout=5)
        log_info("Traffic analysis stopped")
    
    def _analysis_loop(self):
        """Main analysis loop"""
        while self.is_running:
            try:
                self._update_bandwidth_usage()
                self._detect_anomalies()
                self._analyze_traffic_patterns()
                self._update_network_stats()
                time.sleep(self.analysis_interval)
            except Exception as e:
                log_error(f"Analysis loop error: {e}")
                time.sleep(1)
    
    def _update_bandwidth_usage(self):
        """Update bandwidth usage for all devices"""
        current_time = datetime.now()
        
        for ip, stats in self.device_stats.items():
            # Calculate bandwidth usage
            total_bytes = stats.total_bytes_sent + stats.total_bytes_received
            stats.bandwidth_usage = total_bytes / 1024.0  # Convert to KB/s
            
            # Calculate packet rate
            total_packets = stats.packets_sent + stats.packets_received
            stats.packet_rate = total_packets / self.analysis_interval
            
            # Update traffic history
            stats.traffic_history.append((stats.bandwidth_usage, current_time))
            
            # Clean old history
            cutoff_time = current_time - timedelta(seconds=self.history_window)
            stats.traffic_history = deque(
                [(usage, time) for usage, time in stats.traffic_history 
                 if time > cutoff_time],
                maxlen=100
            )
    
    def _detect_anomalies(self):
        """Detect network anomalies"""
        current_time = datetime.now()
        
        for ip, stats in self.device_stats.items():
            # Check for high bandwidth usage
            if stats.bandwidth_usage > self.thresholds['high_bandwidth']:
                self._create_anomaly(ip, "HIGH_BANDWIDTH", "HIGH",
                                   f"High bandwidth usage: {stats.bandwidth_usage:.1f} KB/s",
                                   {"bandwidth": stats.bandwidth_usage}, 0.8)
            
            # Check for high packet rate
            if stats.packet_rate > self.thresholds['high_packet_rate']:
                self._create_anomaly(ip, "HIGH_PACKET_RATE", "MEDIUM",
                                   f"High packet rate: {stats.packet_rate:.1f} packets/s",
                                   {"packet_rate": stats.packet_rate}, 0.7)
            
            # Check for suspicious activity
            if len(stats.suspicious_activity) > 3:
                self._create_anomaly(ip, "SUSPICIOUS_ACTIVITY", "HIGH",
                                   f"Multiple suspicious activities detected",
                                   {"activities": stats.suspicious_activity}, 0.9)
            
            # Check for unusual traffic patterns
            if len(stats.traffic_history) > 10:
                pattern = self._analyze_device_pattern(stats)
                if pattern and pattern.pattern_type == "BURST":
                    self._create_anomaly(ip, "BURST_TRAFFIC", "MEDIUM",
                                       f"Burst traffic pattern detected",
                                       {"pattern": pattern.__dict__}, 0.6)
    
    def _create_anomaly(self, ip: str, anomaly_type: str, severity: str, 
                       description: str, evidence: Dict[str, Any], confidence: float):
        """Create a new network anomaly"""
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
        
        # Keep only recent anomalies
        if len(self.anomalies) > 100:
            self.anomalies = self.anomalies[-100:]
        
        log_warning(f"Anomaly detected: {description} for {ip}")
    
    def _analyze_device_pattern(self, stats: TrafficStats) -> Optional[TrafficPattern]:
        """Analyze traffic pattern for a device"""
        if len(stats.traffic_history) < 10:
            return None
        
        usage_values = [usage for usage, _ in stats.traffic_history]
        
        # Calculate pattern characteristics
        mean_usage = statistics.mean(usage_values)
        std_usage = statistics.stdev(usage_values) if len(usage_values) > 1 else 0
        
        # Determine pattern type
        if std_usage > mean_usage * 0.5:
            pattern_type = "BURST"
        elif std_usage < mean_usage * 0.1:
            pattern_type = "STEADY"
        else:
            pattern_type = "VARIABLE"
        
        return TrafficPattern(
            pattern_type=pattern_type,
            frequency=1.0 / self.analysis_interval,
            duration=len(usage_values) * self.analysis_interval,
            intensity=mean_usage,
            description=f"{pattern_type} traffic pattern with {mean_usage:.1f} KB/s average"
        )
    
    def _analyze_traffic_patterns(self):
        """Analyze traffic patterns across the network"""
        for ip, stats in self.device_stats.items():
            pattern = self._analyze_device_pattern(stats)
            if pattern:
                if ip not in self.traffic_patterns:
                    self.traffic_patterns[ip] = []
                self.traffic_patterns[ip].append(pattern)
                
                # Keep only recent patterns
                if len(self.traffic_patterns[ip]) > 10:
                    self.traffic_patterns[ip] = self.traffic_patterns[ip][-10:]
    
    def _update_network_stats(self):
        """Update overall network statistics"""
        self.network_stats['total_devices'] = len(self.device_stats)
        self.network_stats['total_bandwidth'] = sum(
            stats.bandwidth_usage for stats in self.device_stats.values()
        )
        self.network_stats['active_connections'] = sum(
            stats.connections_active for stats in self.device_stats.values()
        )
        self.network_stats['suspicious_devices'] = len([
            stats for stats in self.device_stats.values() 
            if stats.risk_score > 50
        ])
        self.network_stats['anomalies_detected'] = len(self.anomalies)
    
    def get_device_stats(self, ip: str) -> Optional[TrafficStats]:
        """Get traffic statistics for a specific device"""
        return self.device_stats.get(ip)
    
    def get_network_overview(self) -> Dict[str, Any]:
        """Get network overview statistics"""
        return {
            'network_stats': self.network_stats,
            'top_bandwidth_devices': self._get_top_devices('bandwidth_usage', 5),
            'top_risk_devices': self._get_top_devices('risk_score', 5),
            'recent_anomalies': self.anomalies[-10:] if self.anomalies else [],
            'total_anomalies': len(self.anomalies)
        }
    
    def _get_top_devices(self, metric: str, count: int) -> List[Dict[str, Any]]:
        """Get top devices by a specific metric"""
        sorted_devices = sorted(
            self.device_stats.values(),
            key=lambda x: getattr(x, metric, 0),
            reverse=True
        )
        
        return [
            {
                'ip': stats.device_ip,
                'hostname': stats.hostname,
                'metric_value': getattr(stats, metric, 0),
                'bandwidth': stats.bandwidth_usage,
                'risk_score': stats.risk_score
            }
            for stats in sorted_devices[:count]
        ]
    
    def export_traffic_report(self, filename: str = None) -> str:
        """Export comprehensive traffic analysis report"""
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"traffic_report_{timestamp}.json"
        
        report = {
            'timestamp': datetime.now().isoformat(),
            'network_overview': self.get_network_overview(),
            'device_details': {
                ip: {
                    'total_bytes_sent': stats.total_bytes_sent,
                    'total_bytes_received': stats.total_bytes_received,
                    'bandwidth_usage': stats.bandwidth_usage,
                    'packet_rate': stats.packet_rate,
                    'risk_score': stats.risk_score,
                    'suspicious_activity': stats.suspicious_activity,
                    'protocol_usage': stats.protocol_usage,
                    'port_usage': dict(list(stats.port_usage.items())[:10])  # Top 10 ports
                }
                for ip, stats in self.device_stats.items()
            },
            'anomalies': [
                {
                    'device_ip': anomaly.device_ip,
                    'type': anomaly.anomaly_type,
                    'severity': anomaly.severity,
                    'description': anomaly.description,
                    'timestamp': anomaly.timestamp.isoformat(),
                    'confidence': anomaly.confidence
                }
                for anomaly in self.anomalies
            ],
            'traffic_patterns': {
                ip: [pattern.__dict__ for pattern in patterns]
                for ip, patterns in self.traffic_patterns.items()
            }
        }
        
        try:
            with open(filename, 'w') as f:
                json.dump(report, f, indent=2, default=str)
            log_info(f"Traffic report exported to {filename}")
            return filename
        except Exception as e:
            log_error(f"Failed to export traffic report: {e}")
            return ""
    
    def get_recommendations(self) -> List[str]:
        """Get security recommendations based on analysis"""
        recommendations = []
        
        # Check for high-risk devices
        high_risk_devices = [
            stats for stats in self.device_stats.values() 
            if stats.risk_score > 70
        ]
        if high_risk_devices:
            recommendations.append(
                f"Consider blocking {len(high_risk_devices)} high-risk devices"
            )
        
        # Check for bandwidth abuse
        high_bandwidth_devices = [
            stats for stats in self.device_stats.values() 
            if stats.bandwidth_usage > self.thresholds['high_bandwidth']
        ]
        if high_bandwidth_devices:
            recommendations.append(
                f"Monitor {len(high_bandwidth_devices)} devices with high bandwidth usage"
            )
        
        # Check for recent anomalies
        recent_anomalies = [
            anomaly for anomaly in self.anomalies 
            if (datetime.now() - anomaly.timestamp).seconds < 300  # Last 5 minutes
        ]
        if recent_anomalies:
            recommendations.append(
                f"Investigate {len(recent_anomalies)} recent network anomalies"
            )
        
        return recommendations 