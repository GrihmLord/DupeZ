# app/plugins/gaming_control.py

"""
Plugin: gaming_control
Category: Gaming
Description: Advanced gaming device control and management
Author: DupeZ Team
Version: 1.0.0
"""

from app.plugins.plugin_manager import PluginBase, PluginInfo, PluginRule
from datetime import datetime, time
from app.logs.logger import log_info, log_warning

class GamingControlPlugin(PluginBase):
    """Gaming device control plugin implementation"""
    
    def on_load(self):
        """Called when the plugin is loaded"""
        super().on_load()
        
        log_info("Gaming Control Plugin loaded!")
        
        # Add gaming-specific rules
        self._add_gaming_rules()
    
    def _add_gaming_rules(self):
        """Add gaming-specific rules"""
        
        # Rule 1: Block gaming devices during work hours
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
        
        # Rule 2: Block gaming devices during school hours
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
        
        # Rule 3: Monitor high-bandwidth gaming traffic
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
        
        # Rule 4: Night time gaming restrictions
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