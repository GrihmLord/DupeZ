# app/plugins/gaming_control.py

"""
Plugin: gaming_control
Category: Gaming
Description: Advanced gaming device control and management with DayZ optimization
Author: DupeZ Team
Version: 2.0.0
"""

from app.plugins.plugin_manager import PluginBase, PluginInfo, PluginRule
from datetime import datetime, time
from app.logs.logger import log_info, log_warning, log_error
import json
import requests
import threading
import time as time_module
from typing import Dict, List, Optional, Tuple

class GamingControlPlugin(PluginBase):
    """Enhanced gaming device control plugin with DayZ optimization"""
    
    def on_load(self):
        """Called when the plugin is loaded"""
        super().on_load()
        
        log_info("Enhanced Gaming Control Plugin loaded with DayZ optimization!")
        
        # Initialize gaming performance monitoring
        self._init_gaming_performance()
        
        # Add enhanced gaming-specific rules
        self._add_enhanced_gaming_rules()
        
        # Start DayZ server monitoring
        self._start_dayz_monitoring()
    
    def _init_gaming_performance(self):
        """Initialize gaming performance monitoring"""
        self.gaming_performance = {
            'dayz_servers': {},
            'gaming_traffic_stats': {},
            'performance_metrics': {},
            'last_optimization': None
        }
        
        # Initialize performance monitoring thread
        self.performance_monitor_thread = threading.Thread(
            target=self._monitor_gaming_performance,
            daemon=True
        )
        self.performance_monitor_thread.start()
    
    def _add_enhanced_gaming_rules(self):
        """Add enhanced gaming-specific rules with DayZ optimization"""
        
        # Rule 1: DayZ Gaming Traffic Priority
        dayz_priority_rule = PluginRule(
            name="DayZ Traffic Priority",
            description="Prioritize DayZ gaming traffic for optimal performance",
            plugin_name=self.info.name,
            rule_type="optimization",
            conditions=[
                {
                    "type": "application",
                    "value": "DayZ"
                },
                {
                    "type": "traffic_type",
                    "value": "gaming"
                }
            ],
            actions=[
                {
                    "type": "set_traffic_priority",
                    "value": "high"
                },
                {
                    "type": "reserve_bandwidth",
                    "value": 50  # 50 Mbps reserved for DayZ
                },
                {
                    "type": "optimize_latency"
                }
            ],
            priority=95
        )
        self.add_rule(dayz_priority_rule)
        
        # Rule 2: Gaming Device Performance Monitoring
        gaming_performance_rule = PluginRule(
            name="Gaming Performance Monitor",
            description="Monitor and optimize gaming device performance",
            plugin_name=self.info.name,
            rule_type="monitoring",
            conditions=[
                {
                    "type": "device_type",
                    "value": "gaming"
                }
            ],
            actions=[
                {
                    "type": "monitor_performance",
                    "metrics": ["latency", "bandwidth", "packet_loss"]
                },
                {
                    "type": "auto_optimize",
                    "threshold": 100  # ms latency threshold
                }
            ],
            priority=70
        )
        self.add_rule(gaming_performance_rule)
        
        # Rule 3: Anti-DDoS Protection for Gaming
        gaming_ddos_protection = PluginRule(
            name="Gaming DDoS Protection",
            description="Protect gaming sessions from DDoS attacks",
            plugin_name=self.info.name,
            rule_type="security",
            conditions=[
                {
                    "type": "threat_detected",
                    "value": "ddos"
                },
                {
                    "type": "device_type",
                    "value": "gaming"
                }
            ],
            actions=[
                {
                    "type": "activate_protection",
                    "method": "rate_limiting"
                },
                {
                    "type": "isolate_gaming_traffic"
                },
                {
                    "type": "send_alert",
                    "message": "DDoS protection activated for gaming devices"
                }
            ],
            priority=100
        )
        self.add_rule(gaming_ddos_protection)
        
        # Rule 4: Work Hours Gaming Block (Enhanced)
        work_hours_rule = PluginRule(
            name="Work Hours Gaming Block",
            description="Automatically block gaming devices during work hours (9 AM - 5 PM)",
            plugin_name=self.info.name,
            rule_type="blocking",
            conditions=[
                {
                    "type": "device_type",
                    "value": "gaming"
                },
                {
                    "type": "time_of_day",
                    "value": {
                        "start": 9,
                        "end": 17
                    }
                }
            ],
            actions=[
                {
                    "type": "block_device"
                },
                {
                    "type": "send_alert",
                    "message": "Gaming device blocked during work hours"
                }
            ],
            priority=80
        )
        self.add_rule(work_hours_rule)
        
        # Rule 5: School Hours Gaming Block (Enhanced)
        school_hours_rule = PluginRule(
            name="School Hours Gaming Block",
            description="Block gaming devices during school hours (8 AM - 3 PM) on weekdays",
            plugin_name=self.info.name,
            rule_type="blocking",
            conditions=[
                {
                    "type": "device_type",
                    "value": "gaming"
                },
                {
                    "type": "time_of_day",
                    "value": {
                        "start": 8,
                        "end": 15
                    }
                }
            ],
            actions=[
                {
                    "type": "block_device"
                },
                {
                    "type": "send_alert",
                    "message": "Gaming device blocked during school hours"
                }
            ],
            priority=90
        )
        self.add_rule(school_hours_rule)
        
        # Rule 6: Monitor high-bandwidth gaming traffic
        bandwidth_monitor_rule = PluginRule(
            name="Gaming Bandwidth Monitor",
            description="Monitor gaming devices for excessive bandwidth usage",
            plugin_name=self.info.name,
            rule_type="monitoring",
            conditions=[
                {
                    "type": "device_type",
                    "value": "gaming"
                },
                {
                    "type": "traffic_threshold",
                    "value": 500  # 500 KB/s
                }
            ],
            actions=[
                {
                    "type": "send_alert",
                    "message": "High bandwidth usage detected on gaming device"
                },
                {
                    "type": "log_event",
                    "message": "Gaming device using excessive bandwidth"
                }
            ],
            priority=60
        )
        self.add_rule(bandwidth_monitor_rule)
        
        # Rule 7: Night time gaming restrictions
        night_gaming_rule = PluginRule(
            name="Night Gaming Restrictions",
            description="Restrict gaming devices during late night hours (11 PM - 6 AM)",
            plugin_name=self.info.name,
            rule_type="blocking",
            conditions=[
                {
                    "type": "device_type",
                    "value": "gaming"
                },
                {
                    "type": "time_of_day",
                    "value": {
                        "start": 23,
                        "end": 6
                    }
                }
            ],
            actions=[
                {
                    "type": "block_device"
                },
                {
                    "type": "send_alert",
                    "message": "Gaming device blocked during night hours"
                }
            ],
            priority=85
        )
        self.add_rule(night_gaming_rule)
    
    def _start_dayz_monitoring(self):
        """Start DayZ server monitoring"""
        try:
            # Start DayZ server monitoring thread
            self.dayz_monitor_thread = threading.Thread(
                target=self._monitor_dayz_servers,
                daemon=True
            )
            self.dayz_monitor_thread.start()
            log_info("DayZ server monitoring started")
        except Exception as e:
            log_error(f"Failed to start DayZ monitoring: {e}")
    
    def _monitor_dayz_servers(self):
        """Monitor DayZ servers for performance and status"""
        while self.is_loaded:
            try:
                # Get DayZ server list from settings
                dayz_servers = self.get_setting('dayz_servers', [])
                
                for server in dayz_servers:
                    self._check_dayz_server_status(server)
                
                # Update every 30 seconds
                time_module.sleep(30)
                
            except Exception as e:
                log_error(f"Error in DayZ server monitoring: {e}")
                time_module.sleep(60)  # Wait longer on error
    
    def _check_dayz_server_status(self, server: dict):
        """Check status of a specific DayZ server"""
        try:
            server_ip = server.get('ip')
            server_port = server.get('port', 2302)
            
            # Check server connectivity
            latency = self._ping_server(server_ip, server_port)
            
            # Update server status
            if server_ip not in self.gaming_performance['dayz_servers']:
                self.gaming_performance['dayz_servers'][server_ip] = {}
            
            self.gaming_performance['dayz_servers'][server_ip].update({
                'last_check': datetime.now().isoformat(),
                'latency': latency,
                'status': 'Online' if latency > 0 else 'Offline',
                'performance_score': self._calculate_performance_score(latency)
            })
            
            # Log significant changes
            if latency > 200:  # High latency warning
                log_warning(f"High latency detected on DayZ server {server_ip}: {latency}ms")
            
        except Exception as e:
            log_error(f"Error checking DayZ server {server.get('ip', 'Unknown')}: {e}")
    
    def _ping_server(self, ip: str, port: int) -> int:
        """Ping a server and return latency in milliseconds"""
        try:
            import socket
            start_time = time_module.time()
            
            # Try to connect to the server
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((ip, port))
            sock.close()
            
            if result == 0:
                latency = int((time_module.time() - start_time) * 1000)
                return latency
            else:
                return -1  # Connection failed
                
        except Exception:
            return -1
    
    def _calculate_performance_score(self, latency: int) -> str:
        """Calculate performance score based on latency"""
        if latency < 0:
            return "Offline"
        elif latency < 50:
            return "Excellent"
        elif latency < 100:
            return "Good"
        elif latency < 200:
            return "Fair"
        else:
            return "Poor"
    
    def _monitor_gaming_performance(self):
        """Monitor overall gaming performance metrics"""
        while self.is_loaded:
            try:
                # Update gaming performance metrics
                self._update_performance_metrics()
                
                # Check if optimization is needed
                self._check_optimization_needed()
                
                # Update every 10 seconds
                time_module.sleep(10)
                
            except Exception as e:
                log_error(f"Error in gaming performance monitoring: {e}")
                time_module.sleep(30)
    
    def _update_performance_metrics(self):
        """Update gaming performance metrics"""
        try:
            # Get current gaming devices
            gaming_devices = self._get_gaming_devices()
            
            for device in gaming_devices:
                device_ip = device.get('ip', 'unknown')
                
                # Update device performance metrics
                if device_ip not in self.gaming_performance['gaming_traffic_stats']:
                    self.gaming_performance['gaming_traffic_stats'][device_ip] = {}
                
                # Simulate performance data (in real implementation, this would come from network monitoring)
                self.gaming_performance['gaming_traffic_stats'][device_ip].update({
                    'last_update': datetime.now().isoformat(),
                    'bandwidth_usage': self._get_device_bandwidth(device_ip),
                    'latency': self._get_device_latency(device_ip),
                    'packet_loss': self._get_device_packet_loss(device_ip)
                })
                
        except Exception as e:
            log_error(f"Error updating performance metrics: {e}")
    
    def _get_device_bandwidth(self, device_ip: str) -> float:
        """Get current bandwidth usage for a device (MB/s)"""
        # This would integrate with your network monitoring system
        # For now, return a simulated value
        import random
        return round(random.uniform(1.0, 10.0), 2)
    
    def _get_device_latency(self, device_ip: str) -> int:
        """Get current latency for a device (ms)"""
        # This would integrate with your network monitoring system
        # For now, return a simulated value
        import random
        return random.randint(20, 150)
    
    def _get_device_packet_loss(self, device_ip: str) -> float:
        """Get current packet loss for a device (%)"""
        # This would integrate with your network monitoring system
        # For now, return a simulated value
        import random
        return round(random.uniform(0.0, 2.0), 2)
    
    def _check_optimization_needed(self):
        """Check if network optimization is needed for gaming"""
        try:
            total_devices = len(self.gaming_performance['gaming_traffic_stats'])
            if total_devices == 0:
                return
            
            # Calculate average performance metrics
            total_latency = 0
            total_packet_loss = 0
            device_count = 0
            
            for device_ip, stats in self.gaming_performance['gaming_traffic_stats'].items():
                if 'latency' in stats and 'packet_loss' in stats:
                    total_latency += stats['latency']
                    total_packet_loss += stats['packet_loss']
                    device_count += 1
            
            if device_count > 0:
                avg_latency = total_latency / device_count
                avg_packet_loss = total_packet_loss / device_count
                
                # Check if optimization is needed
                if avg_latency > 100 or avg_packet_loss > 1.0:
                    self._trigger_network_optimization()
                    
        except Exception as e:
            log_error(f"Error checking optimization needs: {e}")
    
    def _trigger_network_optimization(self):
        """Trigger network optimization for gaming"""
        try:
            log_info("Triggering network optimization for gaming performance")
            
            # Update last optimization time
            self.gaming_performance['last_optimization'] = datetime.now().isoformat()
            
            # Apply gaming traffic prioritization
            self._apply_gaming_traffic_prioritization()
            
            # Optimize routing for gaming devices
            self._optimize_gaming_routing()
            
            log_info("Network optimization completed for gaming")
            
        except Exception as e:
            log_error(f"Error during network optimization: {e}")
    
    def _apply_gaming_traffic_prioritization(self):
        """Apply traffic prioritization for gaming"""
        try:
            # This would integrate with your firewall/network control system
            # For now, log the action
            log_info("Applied gaming traffic prioritization")
            
            # Set QoS rules for gaming traffic
            self._set_gaming_qos_rules()
            
        except Exception as e:
            log_error(f"Error applying traffic prioritization: {e}")
    
    def _set_gaming_qos_rules(self):
        """Set QoS rules for gaming traffic"""
        try:
            # This would integrate with your network infrastructure
            # For now, log the action
            log_info("Set QoS rules: Gaming traffic gets high priority")
            
        except Exception as e:
            log_error(f"Error setting QoS rules: {e}")
    
    def _optimize_gaming_routing(self):
        """Optimize routing for gaming devices"""
        try:
            # This would integrate with your network infrastructure
            # For now, log the action
            log_info("Optimized routing for gaming devices")
            
        except Exception as e:
            log_error(f"Error optimizing routing: {e}")
    
    def add_dayz_server(self, server_info: dict):
        """Add a DayZ server for monitoring"""
        try:
            servers = self.get_setting('dayz_servers', [])
            
            # Check if server already exists
            existing_server = next(
                (s for s in servers if s.get('ip') == server_info.get('ip')), 
                None
            )
            
            if existing_server:
                # Update existing server
                existing_server.update(server_info)
                log_info(f"Updated DayZ server: {server_info.get('ip')}")
            else:
                # Add new server
                servers.append(server_info)
                log_info(f"Added new DayZ server: {server_info.get('ip')}")
            
            self.set_setting('dayz_servers', servers)
            
        except Exception as e:
            log_error(f"Error adding DayZ server: {e}")
    
    def remove_dayz_server(self, server_ip: str):
        """Remove a DayZ server from monitoring"""
        try:
            servers = self.get_setting('dayz_servers', [])
            servers = [s for s in servers if s.get('ip') != server_ip]
            self.set_setting('dayz_servers', servers)
            
            # Remove from performance monitoring
            if server_ip in self.gaming_performance['dayz_servers']:
                del self.gaming_performance['dayz_servers'][server_ip]
            
            log_info(f"Removed DayZ server: {server_ip}")
            
        except Exception as e:
            log_error(f"Error removing DayZ server: {e}")
    
    def get_gaming_performance_report(self) -> dict:
        """Get comprehensive gaming performance report"""
        try:
            return {
                'dayz_servers': self.gaming_performance['dayz_servers'],
                'gaming_devices': self.gaming_performance['gaming_traffic_stats'],
                'performance_metrics': self.gaming_performance['performance_metrics'],
                'last_optimization': self.gaming_performance['last_optimization'],
                'optimization_status': 'Active' if self.is_loaded else 'Inactive',
                'total_gaming_devices': len(self.gaming_performance['gaming_traffic_stats']),
                'total_dayz_servers': len(self.gaming_performance['dayz_servers'])
            }
        except Exception as e:
            log_error(f"Error generating performance report: {e}")
            return {}
    
    def optimize_gaming_network(self):
        """Manually trigger gaming network optimization"""
        try:
            log_info("Manual gaming network optimization triggered")
            self._trigger_network_optimization()
            return True
        except Exception as e:
            log_error(f"Error during manual optimization: {e}")
            return False
    
    def get_dayz_server_status(self, server_ip: str) -> dict:
        """Get status of a specific DayZ server"""
        try:
            return self.gaming_performance['dayz_servers'].get(server_ip, {})
        except Exception as e:
            log_error(f"Error getting server status: {e}")
            return {}
    
    def set_gaming_priority(self, device_ip: str, priority: str):
        """Set gaming priority for a specific device"""
        try:
            # This would integrate with your network control system
            log_info(f"Set gaming priority for {device_ip}: {priority}")
            
            # Store priority setting
            priorities = self.get_setting('device_priorities', {})
            priorities[device_ip] = priority
            self.set_setting('device_priorities', priorities)
            
        except Exception as e:
            log_error(f"Error setting gaming priority: {e}")
    
    def on_device_detected(self, device):
        """Called when a new device is detected"""
        if device.is_gaming_device:
            log_info(f"Gaming device detected: {device.ip} ({device.hostname})")
            
            # Check if it's during restricted hours
            current_hour = datetime.now().hour
            if self._is_restricted_hour(current_hour):
                log_warning(f"Gaming device detected during restricted hours: {device.ip}")
    
    def on_device_blocked(self, device):
        """Called when a device is blocked"""
        if device.is_gaming_device:
            log_info(f"Gaming device blocked: {device.ip}")
            
            # Store blocking information
            self._log_gaming_block(device, "blocked")
    
    def on_device_unblocked(self, device):
        """Called when a device is unblocked"""
        if device.is_gaming_device:
            log_info(f"Gaming device unblocked: {device.ip}")
            
            # Store unblocking information
            self._log_gaming_block(device, "unblocked")
    
    def on_traffic_anomaly(self, anomaly):
        """Called when a traffic anomaly is detected"""
        if anomaly.device_ip in self._get_gaming_devices():
            log_warning(f"Traffic anomaly on gaming device: {anomaly.device_ip} - {anomaly.description}")
    
    def on_network_scan_complete(self, devices):
        """Called when a network scan completes"""
        gaming_devices = [d for d in devices if d.is_gaming_device]
        if gaming_devices:
            log_info(f"Found {len(gaming_devices)} gaming devices in network scan")
            
            # Update gaming device statistics
            self._update_gaming_stats(gaming_devices)
    
    def _is_restricted_hour(self, hour: int) -> bool:
        """Check if current hour is in restricted gaming hours"""
        # Work hours: 9 AM - 5 PM
        work_hours = 9 <= hour <= 17
        
        # School hours: 8 AM - 3 PM
        school_hours = 8 <= hour <= 15
        
        # Night hours: 11 PM - 6 AM
        night_hours = hour >= 23 or hour <= 6
        
        return work_hours or school_hours or night_hours
    
    def _get_gaming_devices(self):
        """Get list of gaming device IPs"""
        # This would typically query the device list from the controller
        # For now, return an empty list
        return []
    
    def _log_gaming_block(self, device, action: str):
        """Log gaming device blocking/unblocking"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] Gaming device {action}: {device.ip} ({device.hostname})"
        
        # Store in plugin settings for history
        history = self.get_settings().get('block_history', [])
        history.append(log_entry)
        
        # Keep only last 100 entries
        if len(history) > 100:
            history = history[-100:]
        
        self.set_setting('block_history', history)
    
    def _update_gaming_stats(self, gaming_devices):
        """Update gaming device statistics"""
        stats = {
            'total_gaming_devices': len(gaming_devices),
            'blocked_gaming_devices': len([d for d in gaming_devices if d.is_blocked]),
            'active_gaming_devices': len([d for d in gaming_devices if not d.is_blocked]),
            'last_updated': datetime.now().isoformat()
        }
        
        self.set_setting('gaming_stats', stats)
    
    def get_gaming_report(self) -> dict:
        """Generate a gaming device report"""
        stats = self.get_settings().get('gaming_stats', {})
        history = self.get_settings().get('block_history', [])
        
        return {
            'statistics': stats,
            'recent_activity': history[-10:] if history else [],
            'rules_active': len(self.rules),
            'plugin_status': 'Active' if self.is_loaded else 'Inactive'
        }
    
    def set_gaming_schedule(self, schedule: dict):
        """Set custom gaming schedule"""
        self.set_setting('custom_schedule', schedule)
        log_info(f"Gaming schedule updated: {schedule}")
    
    def get_gaming_schedule(self) -> dict:
        """Get current gaming schedule"""
        return self.get_settings().get('custom_schedule', {
            'work_hours': {'start': 9, 'end': 17},
            'school_hours': {'start': 8, 'end': 15},
            'night_hours': {'start': 23, 'end': 6}
        }) 
