# app/core/advanced_traffic_analyzer.py

import time
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
import json
import sqlite3
from pathlib import Path

from app.logs.logger import log_info, log_error, log_warning

@dataclass
class TrafficFlow:
    """Represents a network traffic flow"""
    source_ip: str
    dest_ip: str
    source_port: int
    dest_port: int
    protocol: str
    bytes_sent: int = 0
    bytes_received: int = 0
    packets_sent: int = 0
    packets_received: int = 0
    start_time: datetime = field(default_factory=datetime.now)
    last_seen: datetime = field(default_factory=datetime.now)
    is_active: bool = True

@dataclass
class TrafficPattern:
    """Represents a traffic pattern for analysis"""
    pattern_id: str
    name: str
    description: str
    conditions: Dict[str, Any]
    severity: str  # low, medium, high, critical
    action: str  # block, alert, monitor, log
    created_at: datetime = field(default_factory=datetime.now)

@dataclass
class ThreatIndicator:
    """Represents a threat indicator"""
    indicator_id: str
    type: str  # ip, domain, url, hash, behavior
    value: str
    confidence: float  # 0.0 to 1.0
    source: str
    first_seen: datetime = field(default_factory=datetime.now)
    last_seen: datetime = field(default_factory=datetime.now)
    is_active: bool = True

class AdvancedTrafficAnalyzer:
    """Advanced traffic analysis system with deep packet inspection and pattern recognition"""
    
    def __init__(self):
        self.flows: Dict[str, TrafficFlow] = {}
        self.patterns: Dict[str, TrafficPattern] = {}
        self.threat_indicators: Dict[str, ThreatIndicator] = {}
        self.traffic_history: deque = deque(maxlen=10000)
        self.analysis_thread: Optional[threading.Thread] = None
        self.is_running = False
        self.db_path = Path("app/data/traffic_analysis.db")
        self.db_path.parent.mkdir(exist_ok=True)
        
        # Performance metrics
        self.total_bytes_analyzed = 0
        self.total_packets_analyzed = 0
        self.analysis_start_time = datetime.now()
        
        # Initialize database
        self._init_database()
        self._load_patterns()
        self._load_threat_indicators()
    
    def _init_database(self):
        """Initialize the traffic analysis database"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Create flows table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS flows (
                    flow_id TEXT PRIMARY KEY,
                    source_ip TEXT,
                    dest_ip TEXT,
                    source_port INTEGER,
                    dest_port INTEGER,
                    protocol TEXT,
                    bytes_sent INTEGER,
                    bytes_received INTEGER,
                    packets_sent INTEGER,
                    packets_received INTEGER,
                    start_time TIMESTAMP,
                    last_seen TIMESTAMP,
                    is_active BOOLEAN
                )
            ''')
            
            # Create patterns table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS patterns (
                    pattern_id TEXT PRIMARY KEY,
                    name TEXT,
                    description TEXT,
                    conditions TEXT,
                    severity TEXT,
                    action TEXT,
                    created_at TIMESTAMP
                )
            ''')
            
            # Create threat indicators table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS threat_indicators (
                    indicator_id TEXT PRIMARY KEY,
                    type TEXT,
                    value TEXT,
                    confidence REAL,
                    source TEXT,
                    first_seen TIMESTAMP,
                    last_seen TIMESTAMP,
                    is_active BOOLEAN
                )
            ''')
            
            # Create traffic events table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS traffic_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT,
                    flow_id TEXT,
                    description TEXT,
                    severity TEXT,
                    timestamp TIMESTAMP,
                    data TEXT
                )
            ''')
            
            conn.commit()
            conn.close()
            log_info("Traffic analysis database initialized")
            
        except Exception as e:
            log_error(f"Failed to initialize traffic analysis database: {e}")
    
    def start_analysis(self):
        """Start the traffic analysis thread"""
        if self.is_running:
            return
        
        self.is_running = True
        self.analysis_thread = threading.Thread(target=self._analysis_loop, daemon=True)
        self.analysis_thread.start()
        log_info("Advanced traffic analysis started")
    
    def stop_analysis(self):
        """Stop the traffic analysis thread"""
        self.is_running = False
        if self.analysis_thread:
            self.analysis_thread.join()
        log_info("Advanced traffic analysis stopped")
    
    def _analysis_loop(self):
        """Main analysis loop"""
        while self.is_running:
            try:
                self._analyze_traffic_patterns()
                self._detect_anomalies()
                self._update_threat_indicators()
                self._cleanup_old_flows()
                time.sleep(1)  # Analysis interval
            except Exception as e:
                log_error(f"Error in traffic analysis loop: {e}")
    
    def add_traffic_data(self, source_ip: str, dest_ip: str, source_port: int, 
                         dest_port: int, protocol: str, bytes_sent: int = 0, 
                         bytes_received: int = 0, packets_sent: int = 0, 
                         packets_received: int = 0):
        """Add traffic data for analysis"""
        try:
            flow_id = f"{source_ip}:{source_port}-{dest_ip}:{dest_port}-{protocol}"
            
            if flow_id in self.flows:
                # Update existing flow
                flow = self.flows[flow_id]
                flow.bytes_sent += bytes_sent
                flow.bytes_received += bytes_received
                flow.packets_sent += packets_sent
                flow.packets_received += packets_received
                flow.last_seen = datetime.now()
            else:
                # Create new flow
                flow = TrafficFlow(
                    source_ip=source_ip,
                    dest_ip=dest_ip,
                    source_port=source_port,
                    dest_port=dest_port,
                    protocol=protocol,
                    bytes_sent=bytes_sent,
                    bytes_received=bytes_received,
                    packets_sent=packets_sent,
                    packets_received=packets_received
                )
                self.flows[flow_id] = flow
            
            # Add to history
            self.traffic_history.append({
                'timestamp': datetime.now(),
                'flow_id': flow_id,
                'bytes_sent': bytes_sent,
                'bytes_received': bytes_received,
                'packets_sent': packets_sent,
                'packets_received': packets_received
            })
            
            # Update metrics
            self.total_bytes_analyzed += bytes_sent + bytes_received
            self.total_packets_analyzed += packets_sent + packets_received
            
        except Exception as e:
            log_error(f"Error adding traffic data: {e}")
    
    def _analyze_traffic_patterns(self):
        """Analyze traffic patterns and detect suspicious behavior"""
        try:
            for flow_id, flow in self.flows.items():
                if not flow.is_active:
                    continue
                
                # Check for high bandwidth usage
                total_bytes = flow.bytes_sent + flow.bytes_received
                if total_bytes > 1000000:  # 1MB threshold
                    self._create_traffic_event(
                        "high_bandwidth",
                        flow_id,
                        f"High bandwidth usage detected: {total_bytes} bytes",
                        "medium"
                    )
                
                # Check for unusual port activity
                if flow.dest_port in [22, 23, 3389, 5900]:  # SSH, Telnet, RDP, VNC
                    self._create_traffic_event(
                        "remote_access",
                        flow_id,
                        f"Remote access protocol detected on port {flow.dest_port}",
                        "high"
                    )
                
                # Check for data exfiltration patterns
                if flow.bytes_sent > flow.bytes_received * 10:  # 10:1 ratio
                    self._create_traffic_event(
                        "data_exfiltration",
                        flow_id,
                        f"Possible data exfiltration: {flow.bytes_sent} sent vs {flow.bytes_received} received",
                        "critical"
                    )
                
                # Check for DDoS patterns
                if flow.packets_sent > 1000:  # High packet count
                    self._create_traffic_event(
                        "ddos_attempt",
                        flow_id,
                        f"Possible DDoS attempt: {flow.packets_sent} packets sent",
                        "critical"
                    )
                
        except Exception as e:
            log_error(f"Error analyzing traffic patterns: {e}")
    
    def _detect_anomalies(self):
        """Detect anomalous traffic patterns"""
        try:
            # Calculate baseline metrics
            total_flows = len([f for f in self.flows.values() if f.is_active])
            if total_flows == 0:
                return
            
            avg_bytes_per_flow = sum(f.bytes_sent + f.bytes_received for f in self.flows.values() if f.is_active) / total_flows
            avg_packets_per_flow = sum(f.packets_sent + f.packets_received for f in self.flows.values() if f.is_active) / total_flows
            
            # Detect anomalies
            for flow_id, flow in self.flows.items():
                if not flow.is_active:
                    continue
                
                total_bytes = flow.bytes_sent + flow.bytes_received
                total_packets = flow.packets_sent + flow.packets_received
                
                # Check for statistical anomalies
                if total_bytes > avg_bytes_per_flow * 5:  # 5x average
                    self._create_traffic_event(
                        "anomaly_high_bandwidth",
                        flow_id,
                        f"Anomalous high bandwidth: {total_bytes} bytes (avg: {avg_bytes_per_flow:.0f})",
                        "high"
                    )
                
                if total_packets > avg_packets_per_flow * 10:  # 10x average
                    self._create_traffic_event(
                        "anomaly_high_packets",
                        flow_id,
                        f"Anomalous high packet count: {total_packets} packets (avg: {avg_packets_per_flow:.0f})",
                        "high"
                    )
                
        except Exception as e:
            log_error(f"Error detecting anomalies: {e}")
    
    def _update_threat_indicators(self):
        """Update threat indicators based on current traffic"""
        try:
            # Check for known malicious IPs
            malicious_ips = self._get_malicious_ips()
            for flow_id, flow in self.flows.items():
                if flow.source_ip in malicious_ips or flow.dest_ip in malicious_ips:
                    self._add_threat_indicator(
                        "ip",
                        flow.source_ip if flow.source_ip in malicious_ips else flow.dest_ip,
                        0.8,
                        "known_malicious_ip"
                    )
            
            # Check for suspicious behavior patterns
            for flow_id, flow in self.flows.items():
                if not flow.is_active:
                    continue
                
                # Check for port scanning
                if flow.dest_port in range(1, 1025):  # Common ports
                    self._check_port_scanning(flow)
                
                # Check for protocol anomalies
                if flow.protocol not in ['TCP', 'UDP', 'ICMP']:
                    self._add_threat_indicator(
                        "protocol",
                        flow.protocol,
                        0.6,
                        "unusual_protocol"
                    )
                
        except Exception as e:
            log_error(f"Error updating threat indicators: {e}")
    
    def _check_port_scanning(self, flow: TrafficFlow):
        """Check for port scanning behavior"""
        try:
            # Count connections to different ports from same source
            connections_from_source = [
                f for f in self.flows.values()
                if f.source_ip == flow.source_ip and f.is_active
            ]
            
            unique_ports = len(set(f.dest_port for f in connections_from_source))
            
            if unique_ports > 10:  # More than 10 different ports
                self._add_threat_indicator(
                    "behavior",
                    f"port_scanning_{flow.source_ip}",
                    0.7,
                    "port_scanning_detection"
                )
                
        except Exception as e:
            log_error(f"Error checking port scanning: {e}")
    
    def _get_malicious_ips(self) -> List[str]:
        """Get list of known malicious IPs using real threat intelligence"""
        try:
            # In a real implementation, this would query threat intelligence feeds
            # For now, we'll use a combination of local detection and external sources
            
            malicious_ips = []
            
            # Method 1: Check for known malicious patterns in current traffic
            for flow_id, flow in self.flows.items():
                if flow.packets_sent > 1000 or flow.packets_received > 1000:
                    # High packet count might indicate scanning
                    if flow.dest_ip not in malicious_ips:
                        malicious_ips.append(flow.dest_ip)
                
                # Check for suspicious port patterns
                if flow.dest_port in [22, 23, 3389, 445, 1433, 3306]:
                    # Common attack ports
                    if flow.packets_sent > 100:
                        if flow.dest_ip not in malicious_ips:
                            malicious_ips.append(flow.dest_ip)
            
            # Method 2: Check for rapid connection attempts
            connection_counts = {}
            for flow_id, flow in self.flows.items():
                if flow.source_ip not in connection_counts:
                    connection_counts[flow.source_ip] = 0
                connection_counts[flow.source_ip] += 1
            
            # Add IPs with suspicious connection patterns
            for ip, count in connection_counts.items():
                if count > 50:  # More than 50 connections in short time
                    if ip not in malicious_ips:
                        malicious_ips.append(ip)
            
            # Method 3: Check for known bad IPs from threat feeds
            # This would typically query external APIs
            known_bad_ips = [
                # These would come from real threat intelligence feeds
                # For demonstration, we'll use some example IPs
            ]
            
            malicious_ips.extend(known_bad_ips)
            
            return list(set(malicious_ips))  # Remove duplicates
            
        except Exception as e:
            log_error(f"Error getting malicious IPs: {e}")
            return []
    
    def _add_threat_indicator(self, indicator_type: str, value: str, 
                             confidence: float, source: str):
        """Add a new threat indicator"""
        try:
            indicator_id = f"{indicator_type}_{value}_{source}"
            
            if indicator_id in self.threat_indicators:
                # Update existing indicator
                indicator = self.threat_indicators[indicator_id]
                indicator.last_seen = datetime.now()
                indicator.confidence = max(indicator.confidence, confidence)
            else:
                # Create new indicator
                indicator = ThreatIndicator(
                    indicator_id=indicator_id,
                    type=indicator_type,
                    value=value,
                    confidence=confidence,
                    source=source
                )
                self.threat_indicators[indicator_id] = indicator
            
            # Save to database
            self._save_threat_indicator(indicator)
            
        except Exception as e:
            log_error(f"Error adding threat indicator: {e}")
    
    def _create_traffic_event(self, event_type: str, flow_id: str, 
                             description: str, severity: str, data: Dict = None):
        """Create a traffic event"""
        try:
            event = {
                'event_type': event_type,
                'flow_id': flow_id,
                'description': description,
                'severity': severity,
                'timestamp': datetime.now(),
                'data': json.dumps(data) if data else None
            }
            
            # Save to database
            self._save_traffic_event(event)
            
            # Log the event
            log_warning(f"Traffic Event [{severity.upper()}]: {description}")
            
        except Exception as e:
            log_error(f"Error creating traffic event: {e}")
    
    def _cleanup_old_flows(self):
        """Clean up old inactive flows"""
        try:
            cutoff_time = datetime.now() - timedelta(minutes=30)
            flows_to_remove = []
            
            for flow_id, flow in self.flows.items():
                if flow.last_seen < cutoff_time:
                    flows_to_remove.append(flow_id)
            
            for flow_id in flows_to_remove:
                del self.flows[flow_id]
            
            if flows_to_remove:
                log_info(f"Cleaned up {len(flows_to_remove)} old flows")
                
        except Exception as e:
            log_error(f"Error cleaning up old flows: {e}")
    
    def _save_threat_indicator(self, indicator: ThreatIndicator):
        """Save threat indicator to database"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO threat_indicators 
                (indicator_id, type, value, confidence, source, first_seen, last_seen, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                indicator.indicator_id,
                indicator.type,
                indicator.value,
                indicator.confidence,
                indicator.source,
                indicator.first_seen,
                indicator.last_seen,
                indicator.is_active
            ))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            log_error(f"Error saving threat indicator: {e}")
    
    def _save_traffic_event(self, event: Dict):
        """Save traffic event to database"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO traffic_events 
                (event_type, flow_id, description, severity, timestamp, data)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                event['event_type'],
                event['flow_id'],
                event['description'],
                event['severity'],
                event['timestamp'],
                event['data']
            ))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            log_error(f"Error saving traffic event: {e}")
    
    def _load_patterns(self):
        """Load traffic patterns from database"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM patterns')
            rows = cursor.fetchall()
            
            for row in rows:
                pattern = TrafficPattern(
                    pattern_id=row[0],
                    name=row[1],
                    description=row[2],
                    conditions=json.loads(row[3]),
                    severity=row[4],
                    action=row[5],
                    created_at=datetime.fromisoformat(row[6])
                )
                self.patterns[pattern.pattern_id] = pattern
            
            conn.close()
            log_info(f"Loaded {len(self.patterns)} traffic patterns")
            
        except Exception as e:
            log_error(f"Error loading patterns: {e}")
    
    def _load_threat_indicators(self):
        """Load threat indicators from database"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM threat_indicators WHERE is_active = 1')
            rows = cursor.fetchall()
            
            for row in rows:
                indicator = ThreatIndicator(
                    indicator_id=row[0],
                    type=row[1],
                    value=row[2],
                    confidence=row[3],
                    source=row[4],
                    first_seen=datetime.fromisoformat(row[5]),
                    last_seen=datetime.fromisoformat(row[6]),
                    is_active=bool(row[7])
                )
                self.threat_indicators[indicator.indicator_id] = indicator
            
            conn.close()
            log_info(f"Loaded {len(self.threat_indicators)} threat indicators")
            
        except Exception as e:
            log_error(f"Error loading threat indicators: {e}")
    
    def get_analysis_summary(self) -> Dict[str, Any]:
        """Get a summary of the traffic analysis"""
        try:
            active_flows = [f for f in self.flows.values() if f.is_active]
            total_bytes = sum(f.bytes_sent + f.bytes_received for f in active_flows)
            total_packets = sum(f.packets_sent + f.packets_received for f in active_flows)
            
            runtime = datetime.now() - self.analysis_start_time
            
            return {
                'active_flows': len(active_flows),
                'total_flows': len(self.flows),
                'total_bytes_analyzed': self.total_bytes_analyzed,
                'total_packets_analyzed': self.total_packets_analyzed,
                'current_bandwidth': total_bytes,
                'current_packets': total_packets,
                'runtime_seconds': runtime.total_seconds(),
                'threat_indicators': len(self.threat_indicators),
                'patterns': len(self.patterns),
                'is_running': self.is_running
            }
            
        except Exception as e:
            log_error(f"Error getting analysis summary: {e}")
            return {}
    
    def get_recent_events(self, limit: int = 50) -> List[Dict]:
        """Get recent traffic events"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT event_type, flow_id, description, severity, timestamp, data
                FROM traffic_events
                ORDER BY timestamp DESC
                LIMIT ?
            ''', (limit,))
            
            rows = cursor.fetchall()
            conn.close()
            
            events = []
            for row in rows:
                events.append({
                    'event_type': row[0],
                    'flow_id': row[1],
                    'description': row[2],
                    'severity': row[3],
                    'timestamp': datetime.fromisoformat(row[4]),
                    'data': json.loads(row[5]) if row[5] else None
                })
            
            return events
            
        except Exception as e:
            log_error(f"Error getting recent events: {e}")
            return []
    
    def add_custom_pattern(self, pattern: TrafficPattern):
        """Add a custom traffic pattern"""
        try:
            self.patterns[pattern.pattern_id] = pattern
            
            # Save to database
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO patterns 
                (pattern_id, name, description, conditions, severity, action, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                pattern.pattern_id,
                pattern.name,
                pattern.description,
                json.dumps(pattern.conditions),
                pattern.severity,
                pattern.action,
                pattern.created_at
            ))
            
            conn.commit()
            conn.close()
            
            log_info(f"Added custom pattern: {pattern.name}")
            
        except Exception as e:
            log_error(f"Error adding custom pattern: {e}")

# Global instance
advanced_traffic_analyzer = AdvancedTrafficAnalyzer() 