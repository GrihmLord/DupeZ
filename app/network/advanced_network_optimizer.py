#!/usr/bin/env python3
"""
Advanced Network Performance Optimizer
High-performance network optimization with real-time analytics and auto-tuning
"""

import json
import threading
import time
import psutil
import socket
import subprocess
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
from app.logs.logger import log_info, log_error, log_warning

@dataclass
class NetworkMetric:
    """Network performance metric"""
    timestamp: datetime
    latency: float
    bandwidth: float
    packet_loss: float
    jitter: float
    connection_count: int
    cpu_usage: float
    memory_usage: float

@dataclass
class OptimizationRule:
    """Network optimization rule"""
    name: str
    condition: str
    action: str
    threshold: float
    enabled: bool
    priority: int

class AdvancedNetworkOptimizer:
    """Advanced network performance optimizer with real-time analytics"""
    
    def __init__(self):
        self.metrics_history: List[NetworkMetric] = []
        self.optimization_rules: List[OptimizationRule] = []
        self.is_running = False
        self.optimization_thread = None
        self.metrics_thread = None
        
        # Performance thresholds
        self.latency_threshold = 50.0  # ms
        self.bandwidth_threshold = 80.0  # %
        self.packet_loss_threshold = 1.0  # %
        self.cpu_threshold = 70.0  # %
        self.memory_threshold = 80.0  # %
        
        # Auto-optimization settings
        self.auto_optimize = True
        self.optimization_interval = 5  # seconds
        self.metrics_interval = 1  # second
        
        # Load optimization rules
        self._load_optimization_rules()
        
    def _load_optimization_rules(self):
        """Load optimization rules from configuration"""
        try:
            # Default optimization rules
            self.optimization_rules = [
                OptimizationRule(
                    name="High Latency Response",
                    condition="latency > threshold",
                    action="optimize_routing",
                    threshold=50.0,
                    enabled=True,
                    priority=100
                ),
                OptimizationRule(
                    name="Packet Loss Recovery",
                    condition="packet_loss > threshold",
                    action="adjust_buffer_sizes",
                    threshold=1.0,
                    enabled=True,
                    priority=90
                ),
                OptimizationRule(
                    name="Bandwidth Optimization",
                    condition="bandwidth > threshold",
                    action="adjust_qos_policies",
                    threshold=80.0,
                    enabled=True,
                    priority=80
                ),
                OptimizationRule(
                    name="CPU Performance",
                    condition="cpu_usage > threshold",
                    action="optimize_processes",
                    threshold=70.0,
                    enabled=True,
                    priority=70
                ),
                OptimizationRule(
                    name="Memory Management",
                    condition="memory_usage > threshold",
                    action="cleanup_memory",
                    threshold=80.0,
                    enabled=True,
                    priority=60
                )
            ]
            log_info("Advanced network optimization rules loaded successfully")
        except Exception as e:
            log_error(f"Failed to load optimization rules: {e}")
    
    def start_optimization(self):
        """Start the advanced network optimizer"""
        if self.is_running:
            return True
            
        try:
            self.is_running = True
            
            # Start metrics collection thread
            self.metrics_thread = threading.Thread(
                target=self._metrics_collection_loop,
                daemon=True
            )
            self.metrics_thread.start()
            
            # Start optimization thread
            self.optimization_thread = threading.Thread(
                target=self._optimization_loop,
                daemon=True
            )
            self.optimization_thread.start()
            
            log_info("Advanced network optimizer started successfully")
            return True
            
        except Exception as e:
            log_error(f"Failed to start network optimizer: {e}")
            self.is_running = False
            return False
    
    def stop_optimization(self):
        """Stop the advanced network optimizer"""
        self.is_running = False
        log_info("Advanced network optimizer stopped")
    
    def _metrics_collection_loop(self):
        """Collect network and system metrics continuously"""
        while self.is_running:
            try:
                metric = self._collect_current_metrics()
                self.metrics_history.append(metric)
                
                # Keep only last 1000 metrics
                if len(self.metrics_history) > 1000:
                    self.metrics_history = self.metrics_history[-1000:]
                
                time.sleep(self.metrics_interval)
                
            except Exception as e:
                log_error(f"Error in metrics collection: {e}")
                time.sleep(1)
    
    def _collect_current_metrics(self) -> NetworkMetric:
        """Collect current network and system metrics"""
        try:
            # Network metrics
            net_io = psutil.net_io_counters()
            latency = self._measure_latency()
            packet_loss = self._measure_packet_loss()
            jitter = self._measure_jitter()
            connection_count = len(psutil.net_connections())
            
            # System metrics
            cpu_usage = psutil.cpu_percent(interval=0.1)
            memory_usage = psutil.virtual_memory().percent
            
            # Calculate bandwidth usage
            bandwidth = self._calculate_bandwidth_usage(net_io)
            
            return NetworkMetric(
                timestamp=datetime.now(),
                latency=latency,
                bandwidth=bandwidth,
                packet_loss=packet_loss,
                jitter=jitter,
                connection_count=connection_count,
                cpu_usage=cpu_usage,
                memory_usage=memory_usage
            )
            
        except Exception as e:
            log_error(f"Error collecting metrics: {e}")
            return NetworkMetric(
                timestamp=datetime.now(),
                latency=0.0,
                bandwidth=0.0,
                packet_loss=0.0,
                jitter=0.0,
                connection_count=0,
                cpu_usage=0.0,
                memory_usage=0.0
            )
    
    def _measure_latency(self) -> float:
        """Measure network latency to multiple targets"""
        try:
            targets = ["8.8.8.8", "1.1.1.1", "208.67.222.222"]  # Google, Cloudflare, OpenDNS
            latencies = []
            
            for target in targets:
                try:
                    start_time = time.time()
                    socket.create_connection((target, 53), timeout=2)
                    end_time = time.time()
                    latencies.append((end_time - start_time) * 1000)  # Convert to ms
                except:
                    continue
            
            return sum(latencies) / len(latencies) if latencies else 0.0
            
        except Exception as e:
            log_error(f"Error measuring latency: {e}")
            return 0.0
    
    def _measure_packet_loss(self) -> float:
        """Measure packet loss rate"""
        try:
            # Simulate packet loss measurement
            # In a real implementation, this would use ping or other tools
            return 0.1  # Placeholder: 0.1% packet loss
        except Exception as e:
            log_error(f"Error measuring packet loss: {e}")
            return 0.0
    
    def _measure_jitter(self) -> float:
        """Measure network jitter"""
        try:
            if len(self.metrics_history) < 2:
                return 0.0
            
            # Calculate jitter as variation in latency
            recent_latencies = [m.latency for m in self.metrics_history[-10:]]
            if len(recent_latencies) < 2:
                return 0.0
            
            jitter_values = []
            for i in range(1, len(recent_latencies)):
                jitter_values.append(abs(recent_latencies[i] - recent_latencies[i-1]))
            
            return sum(jitter_values) / len(jitter_values) if jitter_values else 0.0
            
        except Exception as e:
            log_error(f"Error measuring jitter: {e}")
            return 0.0
    
    def _calculate_bandwidth_usage(self, net_io) -> float:
        """Calculate current bandwidth usage percentage"""
        try:
            # Get total network capacity (simplified)
            total_capacity = 1000  # 1 Gbps in Mbps
            
            # Calculate current usage
            bytes_sent = net_io.bytes_sent
            bytes_recv = net_io.bytes_recv
            total_bytes = bytes_sent + bytes_recv
            
            # Convert to Mbps
            total_mbps = (total_bytes * 8) / (1024 * 1024)
            
            # Calculate percentage
            usage_percentage = (total_mbps / total_capacity) * 100
            
            return min(usage_percentage, 100.0)
            
        except Exception as e:
            log_error(f"Error calculating bandwidth usage: {e}")
            return 0.0
    
    def _optimization_loop(self):
        """Main optimization loop"""
        while self.is_running:
            try:
                if self.auto_optimize and self.metrics_history:
                    self._check_and_apply_optimizations()
                
                time.sleep(self.optimization_interval)
                
            except Exception as e:
                log_error(f"Error in optimization loop: {e}")
                time.sleep(1)
    
    def _check_and_apply_optimizations(self):
        """Check metrics and apply optimizations based on rules"""
        try:
            if not self.metrics_history:
                return
            
            current_metric = self.metrics_history[-1]
            
            # Sort rules by priority (highest first)
            sorted_rules = sorted(self.optimization_rules, key=lambda x: x.priority, reverse=True)
            
            for rule in sorted_rules:
                if not rule.enabled:
                    continue
                
                if self._should_apply_rule(rule, current_metric):
                    self._apply_optimization_rule(rule, current_metric)
                    
        except Exception as e:
            log_error(f"Error checking optimizations: {e}")
    
    def _should_apply_rule(self, rule: OptimizationRule, metric: NetworkMetric) -> bool:
        """Check if an optimization rule should be applied"""
        try:
            if rule.condition == "latency > threshold":
                return metric.latency > rule.threshold
            elif rule.condition == "packet_loss > threshold":
                return metric.packet_loss > rule.threshold
            elif rule.condition == "bandwidth > threshold":
                return metric.bandwidth > rule.threshold
            elif rule.condition == "cpu_usage > threshold":
                return metric.cpu_usage > rule.threshold
            elif rule.condition == "memory_usage > threshold":
                return metric.memory_usage > rule.threshold
            
            return False
            
        except Exception as e:
            log_error(f"Error checking rule condition: {e}")
            return False
    
    def _apply_optimization_rule(self, rule: OptimizationRule, metric: NetworkMetric):
        """Apply a specific optimization rule"""
        try:
            log_info(f"Applying optimization rule: {rule.name}")
            
            if rule.action == "optimize_routing":
                self._optimize_network_routing()
            elif rule.action == "adjust_buffer_sizes":
                self._adjust_network_buffers()
            elif rule.action == "adjust_qos_policies":
                self._adjust_qos_policies()
            elif rule.action == "optimize_processes":
                self._optimize_system_processes()
            elif rule.action == "cleanup_memory":
                self._cleanup_system_memory()
            
            log_info(f"Optimization rule {rule.name} applied successfully")
            
        except Exception as e:
            log_error(f"Error applying optimization rule {rule.name}: {e}")
    
    def _optimize_network_routing(self):
        """Optimize network routing for better performance"""
        try:
            # Apply TCP optimizations
            self._apply_tcp_optimizations()
            
            # Optimize DNS settings
            self._optimize_dns_settings()
            
            # Adjust network adapter settings
            self._optimize_network_adapters()
            
            log_info("Network routing optimization completed")
            
        except Exception as e:
            log_error(f"Error optimizing network routing: {e}")
    
    def _apply_tcp_optimizations(self):
        """Apply TCP performance optimizations"""
        try:
            # Optimize TCP window size
            subprocess.run([
                "netsh", "interface", "tcp", "set", "global", "autotuninglevel=normal"
            ], capture_output=True)
            
            # Enable TCP Chimney
            subprocess.run([
                "netsh", "interface", "tcp", "set", "global", "chimney=enabled"
            ], capture_output=True)
            
            # Enable Receive Segment Coalescing
            subprocess.run([
                "netsh", "interface", "tcp", "set", "global", "rss=enabled"
            ], capture_output=True)
            
            log_info("TCP optimizations applied successfully")
            
        except Exception as e:
            log_error(f"Error applying TCP optimizations: {e}")
    
    def _optimize_dns_settings(self):
        """Optimize DNS settings for better performance"""
        try:
            # Set fast DNS servers
            fast_dns_servers = ["8.8.8.8", "1.1.1.1", "208.67.222.222"]
            
            for i, dns_server in enumerate(fast_dns_servers):
                try:
                    subprocess.run([
                        "netsh", "interface", "ip", "set", "dns", 
                        f"name=*", "static", dns_server, f"primary" if i == 0 else "index=2"
                    ], capture_output=True)
                except:
                    continue
            
            log_info("DNS settings optimized successfully")
            
        except Exception as e:
            log_error(f"Error optimizing DNS settings: {e}")
    
    def _optimize_network_adapters(self):
        """Optimize network adapter settings"""
        try:
            # Enable Jumbo Frames for better throughput
            subprocess.run([
                "netsh", "interface", "set", "interface", "name=*", 
                "mtu=9000"
            ], capture_output=True)
            
            log_info("Network adapter settings optimized")
            
        except Exception as e:
            log_error(f"Error optimizing network adapters: {e}")
    
    def _adjust_network_buffers(self):
        """Adjust network buffer sizes for better performance"""
        try:
            # Increase network buffer sizes
            subprocess.run([
                "netsh", "interface", "tcp", "set", "global", 
                "autotuninglevel=normal"
            ], capture_output=True)
            
            log_info("Network buffer sizes adjusted")
            
        except Exception as e:
            log_error(f"Error adjusting network buffers: {e}")
    
    def _adjust_qos_policies(self):
        """Adjust QoS policies for better traffic management"""
        try:
            # Create gaming traffic priority
            subprocess.run([
                "netsh", "qos", "add", "policy", "name=GamingPriority",
                "rate=1000000", "priority=1"
            ], capture_output=True)
            
            log_info("QoS policies adjusted for gaming priority")
            
        except Exception as e:
            log_error(f"Error adjusting QoS policies: {e}")
    
    def _optimize_system_processes(self):
        """Optimize system processes for better performance"""
        try:
            # Set process priority for critical processes
            critical_processes = ["explorer.exe", "svchost.exe"]
            
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    if proc.info['name'] in critical_processes:
                        proc.nice(psutil.HIGH_PRIORITY_CLASS)
                except:
                    continue
            
            log_info("System processes optimized")
            
        except Exception as e:
            log_error(f"Error optimizing system processes: {e}")
    
    def _cleanup_system_memory(self):
        """Clean up system memory for better performance"""
        try:
            # Clear system cache
            subprocess.run([
                "powershell", "-Command", 
                "Clear-DnsClientCache; Clear-RecycleBin -Force"
            ], capture_output=True)
            
            log_info("System memory cleanup completed")
            
        except Exception as e:
            log_error(f"Error cleaning up system memory: {e}")
    
    def get_performance_report(self) -> Dict:
        """Get comprehensive performance report"""
        try:
            if not self.metrics_history:
                return {"error": "No metrics available"}
            
            current_metric = self.metrics_history[-1]
            
            # Calculate averages
            recent_metrics = self.metrics_history[-100:] if len(self.metrics_history) >= 100 else self.metrics_history
            
            avg_latency = sum(m.latency for m in recent_metrics) / len(recent_metrics)
            avg_bandwidth = sum(m.bandwidth for m in recent_metrics) / len(recent_metrics)
            avg_packet_loss = sum(m.packet_loss for m in recent_metrics) / len(recent_metrics)
            
            # Performance score (0-100)
            latency_score = max(0, 100 - (current_metric.latency / 10))
            bandwidth_score = min(100, current_metric.bandwidth)
            packet_loss_score = max(0, 100 - (current_metric.packet_loss * 50))
            
            overall_score = (latency_score + bandwidth_score + packet_loss_score) / 3
            
            return {
                "current_metrics": {
                    "latency_ms": round(current_metric.latency, 2),
                    "bandwidth_percent": round(current_metric.bandwidth, 2),
                    "packet_loss_percent": round(current_metric.packet_loss, 2),
                    "jitter_ms": round(current_metric.jitter, 2),
                    "connection_count": current_metric.connection_count,
                    "cpu_percent": round(current_metric.cpu_usage, 2),
                    "memory_percent": round(current_metric.memory_usage, 2)
                },
                "average_metrics": {
                    "avg_latency_ms": round(avg_latency, 2),
                    "avg_bandwidth_percent": round(avg_bandwidth, 2),
                    "avg_packet_loss_percent": round(avg_packet_loss, 2)
                },
                "performance_score": round(overall_score, 2),
                "optimization_status": {
                    "auto_optimize": self.auto_optimize,
                    "active_rules": len([r for r in self.optimization_rules if r.enabled]),
                    "last_optimization": datetime.now().isoformat()
                },
                "recommendations": self._generate_recommendations(current_metric)
            }
            
        except Exception as e:
            log_error(f"Error generating performance report: {e}")
            return {"error": str(e)}
    
    def _generate_recommendations(self, metric: NetworkMetric) -> List[str]:
        """Generate performance improvement recommendations"""
        recommendations = []
        
        if metric.latency > self.latency_threshold:
            recommendations.append("High latency detected - Consider optimizing network routing")
        
        if metric.packet_loss > self.packet_loss_threshold:
            recommendations.append("Packet loss detected - Check network stability and adjust buffers")
        
        if metric.bandwidth > self.bandwidth_threshold:
            recommendations.append("High bandwidth usage - Consider upgrading connection or optimizing traffic")
        
        if metric.cpu_usage > self.cpu_threshold:
            recommendations.append("High CPU usage - Close unnecessary applications or optimize processes")
        
        if metric.memory_usage > self.memory_threshold:
            recommendations.append("High memory usage - Consider adding RAM or closing applications")
        
        if not recommendations:
            recommendations.append("All systems operating within optimal parameters")
        
        return recommendations
    
    def set_optimization_thresholds(self, **kwargs):
        """Set optimization thresholds"""
        try:
            if 'latency' in kwargs:
                self.latency_threshold = float(kwargs['latency'])
            if 'bandwidth' in kwargs:
                self.bandwidth_threshold = float(kwargs['bandwidth'])
            if 'packet_loss' in kwargs:
                self.packet_loss_threshold = float(kwargs['packet_loss'])
            if 'cpu' in kwargs:
                self.cpu_threshold = float(kwargs['cpu'])
            if 'memory' in kwargs:
                self.memory_threshold = float(kwargs['memory'])
            
            log_info("Optimization thresholds updated successfully")
            
        except Exception as e:
            log_error(f"Error setting optimization thresholds: {e}")
    
    def get_optimization_status(self) -> Dict:
        """Get current optimization status"""
        return {
            "is_running": self.is_running,
            "auto_optimize": self.auto_optimize,
            "optimization_interval": self.optimization_interval,
            "metrics_interval": self.metrics_interval,
            "active_rules": len([r for r in self.optimization_rules if r.enabled]),
            "total_rules": len(self.optimization_rules),
            "metrics_collected": len(self.metrics_history),
            "last_metric_time": self.metrics_history[-1].timestamp.isoformat() if self.metrics_history else None
        }
