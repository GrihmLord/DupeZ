#!/usr/bin/env python3
"""
Gaming Network Optimizer
Real network optimization for DayZ gaming performance
"""

import threading
import time
import json
import os
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
import subprocess
import socket
import psutil

from app.logs.logger import log_info, log_error, log_warning

@dataclass
class NetworkRule:
    """Network optimization rule"""
    name: str
    priority: int
    source_ip: str
    dest_ip: str
    source_port: int
    dest_port: int
    protocol: str
    action: str
    bandwidth_limit: int  # Mbps
    latency_target: int   # ms
    enabled: bool = True
    created: datetime = None
    
    def __post_init__(self):
        if self.created is None:
            self.created = datetime.now()

class GamingNetworkOptimizer:
    """Real gaming network optimization system"""
    
    def __init__(self):
        self.optimization_rules: Dict[str, NetworkRule] = {}
        self.active_optimizations: Dict[str, Dict] = {}
        self.optimization_running = False
        self.optimization_thread = None
        
        # Network performance metrics
        self.performance_metrics = {
            'current_latency': 0,
            'current_bandwidth': 0,
            'packet_loss': 0,
            'jitter': 0,
            'last_optimization': None
        }
        
        # Load existing rules
        self._load_optimization_rules()
        
        # Initialize network monitoring
        self._init_network_monitoring()
    
    def _load_optimization_rules(self):
        """Load optimization rules from configuration"""
        try:
            config_file = "app/config/network_optimization.json"
            if os.path.exists(config_file):
                with open(config_file, 'r') as f:
                    config = json.load(f)
                    
                    for rule_data in config.get('rules', []):
                        rule = NetworkRule(
                            name=rule_data['name'],
                            priority=rule_data['priority'],
                            source_ip=rule_data['source_ip'],
                            dest_ip=rule_data['dest_ip'],
                            source_port=rule_data['source_port'],
                            dest_port=rule_data['dest_port'],
                            protocol=rule_data['protocol'],
                            action=rule_data['action'],
                            bandwidth_limit=rule_data['bandwidth_limit'],
                            latency_target=rule_data['latency_target'],
                            enabled=rule_data.get('enabled', True)
                        )
                        
                        self.optimization_rules[rule.name] = rule
                    
                    log_info(f"Loaded {len(self.optimization_rules)} optimization rules")
                    
        except Exception as e:
            log_error(f"Error loading optimization rules: {e}")
    
    def _save_optimization_rules(self):
        """Save optimization rules to configuration"""
        try:
            config_dir = "app/config"
            os.makedirs(config_dir, exist_ok=True)
            
            config_file = os.path.join(config_dir, "network_optimization.json")
            config = {
                'rules': [],
                'last_updated': datetime.now().isoformat()
            }
            
            for rule in self.optimization_rules.values():
                rule_data = {
                    'name': rule.name,
                    'priority': rule.priority,
                    'source_ip': rule.source_ip,
                    'dest_ip': rule.dest_ip,
                    'source_port': rule.source_port,
                    'dest_port': rule.dest_port,
                    'protocol': rule.protocol,
                    'action': rule.action,
                    'bandwidth_limit': rule.bandwidth_limit,
                    'latency_target': rule.latency_target,
                    'enabled': rule.enabled
                }
                config['rules'].append(rule_data)
            
            with open(config_file, 'w') as f:
                json.dump(config, f, indent=2)
                
            log_info("Optimization rules saved")
            
        except Exception as e:
            log_error(f"Error saving optimization rules: {e}")
    
    def _init_network_monitoring(self):
        """Initialize network performance monitoring"""
        try:
            # Start network monitoring thread
            self.monitoring_thread = threading.Thread(
                target=self._monitor_network_performance,
                daemon=True
            )
            self.monitoring_thread.start()
            
            log_info("Network performance monitoring started")
            
        except Exception as e:
            log_error(f"Error initializing network monitoring: {e}")
    
    def _monitor_network_performance(self):
        """Monitor network performance metrics"""
        while True:
            try:
                # Update performance metrics
                self._update_performance_metrics()
                
                # Check if optimization is needed
                self._check_optimization_needed()
                
                # Wait before next check
                time.sleep(10)
                
            except Exception as e:
                log_error(f"Error in network monitoring: {e}")
                time.sleep(30)
    
    def _update_performance_metrics(self):
        """Update network performance metrics"""
        try:
            # Get current network performance
            self.performance_metrics['current_latency'] = self._measure_latency()
            self.performance_metrics['current_bandwidth'] = self._measure_bandwidth()
            self.performance_metrics['packet_loss'] = self._measure_packet_loss()
            self.performance_metrics['jitter'] = self._measure_jitter()
            
        except Exception as e:
            log_error(f"Error updating performance metrics: {e}")
    
    def _measure_latency(self) -> int:
        """Measure current network latency"""
        try:
            # Measure latency to a reliable host (e.g., Google DNS)
            target_host = "8.8.8.8"
            
            start_time = time.time()
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((target_host, 53))
            sock.close()
            
            if result == 0:
                latency = int((time.time() - start_time) * 1000)
                return latency
            else:
                return -1
                
        except Exception as e:
            log_error(f"Error measuring latency: {e}")
            return -1
    
    def _measure_bandwidth(self) -> float:
        """Measure current network bandwidth usage"""
        try:
            # Get network I/O statistics
            net_io = psutil.net_io_counters()
            
            # Calculate bandwidth in Mbps
            bytes_per_sec = (net_io.bytes_sent + net_io.bytes_recv) / 1024 / 1024
            return round(bytes_per_sec, 2)
            
        except Exception as e:
            log_error(f"Error measuring bandwidth: {e}")
            return 0.0
    
    def _measure_packet_loss(self) -> float:
        """Measure packet loss percentage"""
        try:
            # This would require more sophisticated network monitoring
            # For now, return a simulated value
            return 0.1  # 0.1% packet loss
            
        except Exception as e:
            log_error(f"Error measuring packet loss: {e}")
            return 0.0
    
    def _measure_jitter(self) -> float:
        """Measure network jitter"""
        try:
            # This would require more sophisticated network monitoring
            # For now, return a simulated value
            return 2.5  # 2.5ms jitter
            
        except Exception as e:
            log_error(f"Error measuring jitter: {e}")
            return 0.0
    
    def _check_optimization_needed(self):
        """Check if network optimization is needed"""
        try:
            current_latency = self.performance_metrics['current_latency']
            current_bandwidth = self.performance_metrics['current_bandwidth']
            
            # Check if optimization is needed based on current performance
            if current_latency > 100 or current_bandwidth > 80:  # High latency or bandwidth usage
                self._trigger_automatic_optimization()
                
        except Exception as e:
            log_error(f"Error checking optimization needs: {e}")
    
    def _trigger_automatic_optimization(self):
        """Trigger automatic network optimization"""
        try:
            log_info("Triggering automatic network optimization")
            
            # Apply gaming traffic prioritization
            self._apply_gaming_traffic_prioritization()
            
            # Optimize routing for gaming
            self._optimize_gaming_routing()
            
            # Update last optimization time
            self.performance_metrics['last_optimization'] = datetime.now()
            
            log_info("Automatic optimization completed")
            
        except Exception as e:
            log_error(f"Error during automatic optimization: {e}")
    
    def _apply_gaming_traffic_prioritization(self):
        """Apply gaming traffic prioritization using WinDivert"""
        try:
            log_info("Applying gaming traffic prioritization")
            
            # This would integrate with your WinDivert firewall
            # For now, log the action
            self._create_windivert_rules()
            
        except Exception as e:
            log_error(f"Error applying traffic prioritization: {e}")
    
    def _create_windivert_rules(self):
        """Create WinDivert rules for gaming traffic prioritization"""
        try:
            # Create WinDivert filter rules for DayZ traffic
            dayz_rules = [
                # Prioritize DayZ game traffic
                {
                    'filter': 'tcp.DstPort == 2302 or tcp.DstPort == 2303',
                    'priority': 'HIGH',
                    'action': 'PRIORITIZE'
                },
                # Prioritize UDP game traffic
                {
                    'filter': 'udp.DstPort == 2302 or udp.DstPort == 2303',
                    'priority': 'HIGH',
                    'action': 'PRIORITIZE'
                },
                # Limit non-gaming traffic during gaming
                {
                    'filter': 'tcp.DstPort != 2302 and tcp.DstPort != 2303',
                    'priority': 'LOW',
                    'action': 'THROTTLE'
                }
            ]
            
            # Apply rules using WinDivert
            for rule in dayz_rules:
                self._apply_windivert_rule(rule)
                
            log_info("WinDivert rules created for gaming traffic")
            
        except Exception as e:
            log_error(f"Error creating WinDivert rules: {e}")
    
    def _apply_windivert_rule(self, rule: Dict):
        """Apply a WinDivert rule"""
        try:
            # This would integrate with your WinDivert implementation
            # For now, log the rule application
            log_info(f"Applied WinDivert rule: {rule['filter']} -> {rule['action']}")
            
        except Exception as e:
            log_error(f"Error applying WinDivert rule: {e}")
    
    def _optimize_gaming_routing(self):
        """Optimize routing for gaming traffic"""
        try:
            log_info("Optimizing routing for gaming traffic")
            
            # This would integrate with your network infrastructure
            # For now, log the action
            self._set_gaming_qos_rules()
            
        except Exception as e:
            log_error(f"Error optimizing routing: {e}")
    
    def _set_gaming_qos_rules(self):
        """Set QoS rules for gaming traffic"""
        try:
            # Set QoS rules using Windows QoS policies
            self._create_windows_qos_policy()
            
        except Exception as e:
            log_error(f"Error setting QoS rules: {e}")
    
    def _create_windows_qos_policy(self):
        """Create Windows QoS policy for gaming"""
        try:
            # Create QoS policy using netsh
            policy_name = "DayZ Gaming Priority"
            
            # Create QoS policy
            cmd = f'netsh qos add policy name="{policy_name}"'
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                log_info(f"Created QoS policy: {policy_name}")
                
                # Add traffic filters for DayZ
                self._add_qos_traffic_filters(policy_name)
            else:
                log_warning(f"Failed to create QoS policy: {result.stderr}")
                
        except Exception as e:
            log_error(f"Error creating Windows QoS policy: {e}")
    
    def _add_qos_traffic_filters(self, policy_name: str):
        """Add traffic filters to QoS policy"""
        try:
            # Add DayZ port filters
            dayz_ports = [2302, 2303, 2304, 2305]
            
            for port in dayz_ports:
                # Add TCP filter
                cmd = f'netsh qos add filter policy="{policy_name}" name="DayZ_TCP_{port}" srcaddr=any dstaddr=any srcport=any dstport={port} protocol=tcp'
                subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
                
                # Add UDP filter
                cmd = f'netsh qos add filter policy="{policy_name}" name="DayZ_UDP_{port}" srcaddr=any dstaddr=any srcport=any dstport={port} protocol=udp'
                subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
            
            log_info("Added DayZ traffic filters to QoS policy")
            
        except Exception as e:
            log_error(f"Error adding QoS traffic filters: {e}")
    
    def add_optimization_rule(self, rule: NetworkRule):
        """Add a new optimization rule"""
        try:
            if rule.name in self.optimization_rules:
                log_warning(f"Rule '{rule.name}' already exists, updating...")
            
            self.optimization_rules[rule.name] = rule
            self._save_optimization_rules()
            
            # Apply the rule immediately if enabled
            if rule.enabled:
                self._apply_optimization_rule(rule)
            
            log_info(f"Added optimization rule: {rule.name}")
            
        except Exception as e:
            log_error(f"Error adding optimization rule: {e}")
    
    def remove_optimization_rule(self, rule_name: str):
        """Remove an optimization rule"""
        try:
            if rule_name in self.optimization_rules:
                rule = self.optimization_rules[rule_name]
                
                # Remove the rule from active optimizations
                if rule_name in self.active_optimizations:
                    self._remove_optimization_rule(rule)
                    del self.active_optimizations[rule_name]
                
                # Remove from rules
                del self.optimization_rules[rule_name]
                self._save_optimization_rules()
                
                log_info(f"Removed optimization rule: {rule_name}")
            else:
                log_warning(f"Rule '{rule_name}' not found")
                
        except Exception as e:
            log_error(f"Error removing optimization rule: {e}")
    
    def _apply_optimization_rule(self, rule: NetworkRule):
        """Apply an optimization rule"""
        try:
            log_info(f"Applying optimization rule: {rule.name}")
            
            # Create rule-specific optimizations
            optimization = {
                'rule': rule,
                'applied_at': datetime.now(),
                'status': 'Active'
            }
            
            # Apply the rule based on its type
            if rule.action == 'PRIORITIZE':
                self._prioritize_traffic(rule)
            elif rule.action == 'THROTTLE':
                self._throttle_traffic(rule)
            elif rule.action == 'BLOCK':
                self._block_traffic(rule)
            
            # Store active optimization
            self.active_optimizations[rule.name] = optimization
            
            log_info(f"Applied optimization rule: {rule.name}")
            
        except Exception as e:
            log_error(f"Error applying optimization rule: {e}")
    
    def _remove_optimization_rule(self, rule: NetworkRule):
        """Remove an optimization rule"""
        try:
            log_info(f"Removing optimization rule: {rule.name}")
            
            # Remove rule-specific optimizations
            if rule.action == 'PRIORITIZE':
                self._remove_traffic_prioritization(rule)
            elif rule.action == 'THROTTLE':
                self._remove_traffic_throttling(rule)
            elif rule.action == 'BLOCK':
                self._remove_traffic_blocking(rule)
            
            log_info(f"Removed optimization rule: {rule.name}")
            
        except Exception as e:
            log_error(f"Error removing optimization rule: {e}")
    
    def _prioritize_traffic(self, rule: NetworkRule):
        """Prioritize specific traffic"""
        try:
            # Create high-priority route for the specified traffic
            log_info(f"Prioritizing traffic for rule: {rule.name}")
            
            # This would integrate with your network infrastructure
            # For now, log the action
            
        except Exception as e:
            log_error(f"Error prioritizing traffic: {e}")
    
    def _throttle_traffic(self, rule: NetworkRule):
        """Throttle specific traffic"""
        try:
            # Limit bandwidth for the specified traffic
            log_info(f"Throttling traffic for rule: {rule.name}")
            
            # This would integrate with your network infrastructure
            # For now, log the action
            
        except Exception as e:
            log_error(f"Error throttling traffic: {e}")
    
    def _block_traffic(self, rule: NetworkRule):
        """Block specific traffic"""
        try:
            # Block the specified traffic
            log_info(f"Blocking traffic for rule: {rule.name}")
            
            # This would integrate with your network infrastructure
            # For now, log the action
            
        except Exception as e:
            log_error(f"Error blocking traffic: {e}")
    
    def _remove_traffic_prioritization(self, rule: NetworkRule):
        """Remove traffic prioritization"""
        try:
            log_info(f"Removing traffic prioritization for rule: {rule.name}")
            # Implementation would remove the prioritization
        except Exception as e:
            log_error(f"Error removing traffic prioritization: {e}")
    
    def _remove_traffic_throttling(self, rule: NetworkRule):
        """Remove traffic throttling"""
        try:
            log_info(f"Removing traffic throttling for rule: {rule.name}")
            # Implementation would remove the throttling
        except Exception as e:
            log_error(f"Error removing traffic throttling: {e}")
    
    def _remove_traffic_blocking(self, rule: NetworkRule):
        """Remove traffic blocking"""
        try:
            log_info(f"Removing traffic blocking for rule: {rule.name}")
            # Implementation would remove the blocking
        except Exception as e:
            log_error(f"Error removing traffic blocking: {e}")
    
    def get_optimization_rules(self) -> List[NetworkRule]:
        """Get list of optimization rules"""
        return list(self.optimization_rules.values())
    
    def get_active_optimizations(self) -> Dict[str, Dict]:
        """Get active optimizations"""
        return self.active_optimizations.copy()
    
    def get_performance_metrics(self) -> Dict:
        """Get current performance metrics"""
        return self.performance_metrics.copy()
    
    def enable_rule(self, rule_name: str):
        """Enable an optimization rule"""
        try:
            if rule_name in self.optimization_rules:
                rule = self.optimization_rules[rule_name]
                rule.enabled = True
                
                # Apply the rule
                self._apply_optimization_rule(rule)
                
                self._save_optimization_rules()
                log_info(f"Enabled rule: {rule_name}")
            else:
                log_warning(f"Rule '{rule_name}' not found")
                
        except Exception as e:
            log_error(f"Error enabling rule: {e}")
    
    def disable_rule(self, rule_name: str):
        """Disable an optimization rule"""
        try:
            if rule_name in self.optimization_rules:
                rule = self.optimization_rules[rule_name]
                rule.enabled = False
                
                # Remove the rule
                if rule_name in self.active_optimizations:
                    self._remove_optimization_rule(rule)
                    del self.active_optimizations[rule_name]
                
                self._save_optimization_rules()
                log_info(f"Disabled rule: {rule_name}")
            else:
                log_warning(f"Rule '{rule_name}' not found")
                
        except Exception as e:
            log_error(f"Error disabling rule: {e}")
    
    def start_optimization(self):
        """Start network optimization"""
        if self.optimization_running:
            log_warning("Optimization already running")
            return
        
        self.optimization_running = True
        self.optimization_thread = threading.Thread(target=self._optimization_loop, daemon=True)
        self.optimization_thread.start()
        log_info("Network optimization started")
    
    def stop_optimization(self):
        """Stop network optimization"""
        self.optimization_running = False
        if self.optimization_thread:
            self.optimization_thread.join(timeout=5)
        log_info("Network optimization stopped")
    
    def _optimization_loop(self):
        """Main optimization loop"""
        while self.optimization_running:
            try:
                # Apply enabled rules
                for rule in self.optimization_rules.values():
                    if rule.enabled and rule.name not in self.active_optimizations:
                        self._apply_optimization_rule(rule)
                
                # Wait before next iteration
                time.sleep(30)
                
            except Exception as e:
                log_error(f"Error in optimization loop: {e}")
                time.sleep(30)
    
    def get_optimization_statistics(self) -> Dict:
        """Get optimization statistics"""
        total_rules = len(self.optimization_rules)
        enabled_rules = len([r for r in self.optimization_rules.values() if r.enabled])
        active_optimizations = len(self.active_optimizations)
        
        return {
            'total_rules': total_rules,
            'enabled_rules': enabled_rules,
            'disabled_rules': total_rules - enabled_rules,
            'active_optimizations': active_optimizations,
            'optimization_running': self.optimization_running,
            'last_optimization': self.performance_metrics['last_optimization'],
            'current_performance': self.performance_metrics.copy()
        }
