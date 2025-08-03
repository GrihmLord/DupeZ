# app/core/traffic_analyzer.py

import threading
import time
import psutil
import json
import os
from typing import Dict, List, Optional
from datetime import datetime
from app.logs.logger import log_info, log_error

class AdvancedTrafficAnalyzer:
    """Enterprise-level network traffic analyzer with real-time monitoring"""
    
    def __init__(self):
        self.is_running = False
        self.monitor_thread = None
        self.stop_monitoring = False
        
        # Traffic data storage
        self.traffic_history = []
        self.current_stats = {}
        self.peak_usage = {}
        self.anomalies = []
        
        # Analysis parameters
        self.history_size = 1000  # Keep last 1000 data points
        self.analysis_interval = 5  # Analyze every 5 seconds
        self.bandwidth_threshold = 1024 * 1024  # 1MB/s threshold
        
        # Performance metrics
        self.performance_metrics = {
            "total_bytes_sent": 0,
            "total_bytes_recv": 0,
            "peak_bandwidth": 0,
            "average_bandwidth": 0,
            "connection_count": 0,
            "start_time": time.time()
        }
    
    def start(self):
        """Start enterprise-level traffic analysis"""
        if self.is_running:
            return
        
        self.is_running = True
        self.stop_monitoring = False
        
        # Start monitoring thread
        self.monitor_thread = threading.Thread(target=self._monitor_traffic, daemon=True)
        self.monitor_thread.start()
        
        log_info("📊 Enterprise Traffic Analyzer started")
    
    def stop(self):
        """Stop enterprise-level traffic analysis"""
        self.is_running = False
        self.stop_monitoring = True
        
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=5)
        
        log_info("📊 Enterprise Traffic Analyzer stopped")
    
    def _monitor_traffic(self):
        """Enterprise-level traffic monitoring loop"""
        last_net_io = None
        last_time = time.time()
        
        while self.is_running and not self.stop_monitoring:
            try:
                current_time = time.time()
                
                # Get current network statistics
                net_io = psutil.net_io_counters()
                
                # Calculate bandwidth
                if last_net_io:
                    time_diff = current_time - last_time
                    bytes_sent_diff = net_io.bytes_sent - last_net_io.bytes_sent
                    bytes_recv_diff = net_io.bytes_recv - last_net_io.bytes_recv
                    
                    # Calculate bandwidth in KB/s
                    bandwidth_sent = (bytes_sent_diff / 1024) / time_diff if time_diff > 0 else 0
                    bandwidth_recv = (bytes_recv_diff / 1024) / time_diff if time_diff > 0 else 0
                    total_bandwidth = bandwidth_sent + bandwidth_recv
                    
                    # Store traffic data
                    traffic_data = {
                        "timestamp": current_time,
                        "bandwidth_sent": bandwidth_sent,
                        "bandwidth_recv": bandwidth_recv,
                        "total_bandwidth": total_bandwidth,
                        "bytes_sent": net_io.bytes_sent,
                        "bytes_recv": net_io.bytes_recv,
                        "packets_sent": net_io.packets_sent,
                        "packets_recv": net_io.packets_recv,
                        "connections": len(psutil.net_connections())
                    }
                    
                    self._store_traffic_data(traffic_data)
                    self._update_performance_metrics(traffic_data)
                    self._detect_anomalies(traffic_data)
                
                last_net_io = net_io
                last_time = current_time
                
                time.sleep(self.analysis_interval)
                
            except Exception as e:
                log_error(f"Traffic monitoring error: {e}")
                time.sleep(10)
    
    def _store_traffic_data(self, traffic_data: Dict):
        """Store traffic data with history management"""
        try:
            self.traffic_history.append(traffic_data)
            
            # Keep only recent history
            if len(self.traffic_history) > self.history_size:
                self.traffic_history = self.traffic_history[-self.history_size:]
            
            # Update current stats
            self.current_stats = traffic_data
                    
        except Exception as e:
            log_error(f"Store traffic data error: {e}")
    
    def _update_performance_metrics(self, traffic_data: Dict):
        """Update enterprise performance metrics"""
        try:
            # Update total bytes
            self.performance_metrics["total_bytes_sent"] = traffic_data["bytes_sent"]
            self.performance_metrics["total_bytes_recv"] = traffic_data["bytes_recv"]
            
            # Update peak bandwidth
            if traffic_data["total_bandwidth"] > self.performance_metrics["peak_bandwidth"]:
                self.performance_metrics["peak_bandwidth"] = traffic_data["total_bandwidth"]
            
            # Update average bandwidth
            if self.traffic_history:
                total_bandwidth = sum(data["total_bandwidth"] for data in self.traffic_history)
                self.performance_metrics["average_bandwidth"] = total_bandwidth / len(self.traffic_history)
            
            # Update connection count
            self.performance_metrics["connection_count"] = traffic_data["connections"]
            
        except Exception as e:
            log_error(f"Update performance metrics error: {e}")
    
    def _detect_anomalies(self, traffic_data: Dict):
        """Detect traffic anomalies"""
        try:
            # High packet rate detection (reduced frequency)
            if traffic_data["packets_recv"] > 10000:
                # Only log if we haven't logged recently for this anomaly
                current_time = time.time()
                if not hasattr(self, '_last_packet_rate_warning') or \
                   current_time - self._last_packet_rate_warning > 60:  # Only warn once per minute
                    
                    anomaly = {
                        "type": "high_packet_rate",
                        "timestamp": traffic_data["timestamp"],
                        "value": traffic_data["packets_recv"],
                        "threshold": 10000,
                        "severity": "medium"
                    }
                    self.anomalies.append(anomaly)
                    log_info(f"🚨 High packet rate detected: {traffic_data['packets_recv']} (will suppress for 60s)")
                    self._last_packet_rate_warning = current_time
            
            # Keep only recent anomalies
            if len(self.anomalies) > 100:
                self.anomalies = self.anomalies[-100:]
            
        except Exception as e:
            log_error(f"Detect anomalies error: {e}")
    
    def get_analysis(self) -> Dict:
        """Get enterprise-level traffic analysis"""
        try:
            analysis = {
                "current_bandwidth": self.current_stats.get("total_bandwidth", 0),
                "bandwidth_sent": self.current_stats.get("bandwidth_sent", 0),
                "bandwidth_recv": self.current_stats.get("bandwidth_recv", 0),
                "bytes_sent": self.current_stats.get("bytes_sent", 0),
                "bytes_recv": self.current_stats.get("bytes_recv", 0),
                "packets_sent": self.current_stats.get("packets_sent", 0),
                "packets_recv": self.current_stats.get("packets_recv", 0),
                "connections": self.current_stats.get("connections", 0),
                "performance_metrics": self.performance_metrics,
                "anomalies": self.anomalies[-10:],  # Last 10 anomalies
                "traffic_trend": self._calculate_traffic_trend(),
                "interface_stats": self._get_interface_stats(),
                "timestamp": time.time()
            }
            
            return analysis
                
        except Exception as e:
            log_error(f"Get analysis error: {e}")
            return {
                "current_bandwidth": 0,
                "bandwidth_sent": 0,
                "bandwidth_recv": 0,
                "bytes_sent": 0,
                "bytes_recv": 0,
                "packets_sent": 0,
                "packets_recv": 0,
                "connections": 0,
                "performance_metrics": {},
                "anomalies": [],
                "traffic_trend": "stable",
                "interface_stats": {},
                "timestamp": time.time()
            }
    
    def _calculate_traffic_trend(self) -> str:
        """Calculate traffic trend over time"""
        try:
            if len(self.traffic_history) < 10:
                return "insufficient_data"
            
            # Get recent bandwidth values
            recent_bandwidth = [data["total_bandwidth"] for data in self.traffic_history[-10:]]
            
            # Calculate trend
            if len(recent_bandwidth) >= 2:
                first_half = sum(recent_bandwidth[:5]) / 5
                second_half = sum(recent_bandwidth[5:]) / 5
                
                if second_half > first_half * 1.2:
                    return "increasing"
                elif second_half < first_half * 0.8:
                    return "decreasing"
            else:
                    return "stable"
            
            return "stable"
            
        except Exception as e:
            log_error(f"Calculate traffic trend error: {e}")
            return "unknown"
    
    def _get_interface_stats(self) -> Dict:
        """Get per-interface statistics"""
        try:
            interface_stats = {}
            
            # Get per-interface I/O counters
            net_io_per_nic = psutil.net_io_counters(pernic=True)
            
            for interface_name, io_stats in net_io_per_nic.items():
                interface_stats[interface_name] = {
                    "bytes_sent": io_stats.bytes_sent,
                    "bytes_recv": io_stats.bytes_recv,
                    "packets_sent": io_stats.packets_sent,
                    "packets_recv": io_stats.packets_recv,
                    "total_bytes": io_stats.bytes_sent + io_stats.bytes_recv
                }
            
            return interface_stats
                        
        except Exception as e:
            log_error(f"Get interface stats error: {e}")
            return {}
    
    def get_recommendations(self) -> List[str]:
        """Get enterprise-level traffic optimization recommendations"""
        try:
            recommendations = []
            
            # Analyze current traffic patterns
            if self.current_stats:
                # Bandwidth recommendations
                if self.current_stats["total_bandwidth"] > 1024:  # > 1MB/s
                    recommendations.append("🚀 High bandwidth usage detected - Consider bandwidth optimization")
                
                # Connection recommendations
                if self.current_stats["connections"] > 500:
                    recommendations.append("🔗 High connection count - Check for connection leaks or DDoS")
                
                # Packet rate recommendations
                if self.current_stats["packets_recv"] > 5000:
                    recommendations.append("📦 High packet rate - Monitor for network congestion")
                
                # Anomaly-based recommendations
                if len(self.anomalies) > 5:
                    recommendations.append("🚨 Multiple anomalies detected - Review network security")
                
                # Performance recommendations
                if self.performance_metrics["peak_bandwidth"] > 2048:  # > 2MB/s peak
                    recommendations.append("⚡ Peak bandwidth exceeded - Consider network upgrades")
            
            # General recommendations
            if not recommendations:
                recommendations.append("✅ Network traffic is within normal parameters")
            
            return recommendations
            
        except Exception as e:
            log_error(f"Get recommendations error: {e}")
            return ["❌ Unable to generate recommendations"]
    
    def export_report(self, filename: str = None) -> str:
        """Export enterprise traffic analysis report"""
        try:
            if not filename:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"traffic_report_{timestamp}.json"
            
            # Prepare report data
            report_data = {
                "report_info": {
                    "generated_at": datetime.now().isoformat(),
                    "analyzer_version": "Enterprise 1.0",
                    "analysis_duration": time.time() - self.performance_metrics["start_time"]
                },
                "current_stats": self.current_stats,
                "performance_metrics": self.performance_metrics,
                "traffic_history": self.traffic_history[-100:],  # Last 100 data points
                "anomalies": self.anomalies,
                "recommendations": self.get_recommendations(),
                "interface_stats": self._get_interface_stats()
            }
            
            # Save to file
            with open(filename, 'w') as f:
                json.dump(report_data, f, indent=2)
            
            log_info(f"📄 Traffic report exported to {filename}")
            return filename
            
        except Exception as e:
            log_error(f"Export report error: {e}")
            return ""
    
    def get_bandwidth_usage(self, interface: str = None) -> Dict:
        """Get bandwidth usage for specific interface or overall"""
        try:
            if interface:
                # Get specific interface stats
                net_io_per_nic = psutil.net_io_counters(pernic=True)
                if interface in net_io_per_nic:
                    io_stats = net_io_per_nic[interface]
                    return {
                        "interface": interface,
                        "bytes_sent": io_stats.bytes_sent,
                        "bytes_recv": io_stats.bytes_recv,
                        "total_bytes": io_stats.bytes_sent + io_stats.bytes_recv
                    }
                else:
                    return {"error": f"Interface {interface} not found"}
            else:
                # Get overall stats
                return {
                    "current_bandwidth": self.current_stats.get("total_bandwidth", 0),
                    "bytes_sent": self.current_stats.get("bytes_sent", 0),
                    "bytes_recv": self.current_stats.get("bytes_recv", 0)
                }
                
        except Exception as e:
            log_error(f"Get bandwidth usage error: {e}")
            return {"error": str(e)}
    
    def reset_metrics(self):
        """Reset all performance metrics"""
        try:
            self.performance_metrics = {
                "total_bytes_sent": 0,
                "total_bytes_recv": 0,
                "peak_bandwidth": 0,
                "average_bandwidth": 0,
                "connection_count": 0,
                "start_time": time.time()
            }
            self.traffic_history = []
            self.anomalies = []
            log_info("🔄 Traffic analyzer metrics reset")
            
        except Exception as e:
            log_error(f"Reset metrics error: {e}") 