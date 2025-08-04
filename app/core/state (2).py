# app/core/state.py

import json
import os
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass, asdict
from datetime import datetime
from app.logs.logger import log_info, log_error

@dataclass
class Device:
    ip: str
    mac: str
    vendor: str
    hostname: str
    local: bool
    traffic: int
    last_seen: str
    blocked: bool = False

@dataclass
class AppSettings:
    smart_mode: bool = False
    auto_scan: bool = True  # Enabled for better functionality
    scan_interval: int = 60  # seconds (faster updates)
    max_devices: int = 100
    log_level: str = "INFO"
    
    # Network settings
    ping_timeout: int = 2
    max_threads: int = 20
    quick_scan: bool = True
    auto_block: bool = False
    high_traffic_threshold: int = 1000
    connection_limit: int = 100
    suspicious_activity_threshold: int = 20
    block_duration: int = 30
    
    # UI settings
    theme: str = "dark"
    auto_refresh: bool = True
    refresh_interval: int = 120
    show_device_icons: bool = True
    show_status_indicators: bool = True
    compact_view: bool = False
    show_notifications: bool = True
    sound_alerts: bool = False
    
    # Advanced settings
    cache_duration: int = 60
    memory_limit: int = 200
    require_admin: bool = True
    encrypt_logs: bool = False
    debug_mode: bool = False
    verbose_logging: bool = False
    
    # Security settings
    whitelist: list = None
    
    def __post_init__(self):
        if self.whitelist is None:
            self.whitelist = []

class AppState:
    def __init__(self, config_file: str = "app/config/settings.json"):
        self.config_file = config_file
        self.devices: List[Device] = []
        self.selected_ip: Optional[str] = None
        self.blocking: bool = False
        self.settings = AppSettings()
        self.network_info: Dict = {}
        self.scan_in_progress: bool = False
        self._observers: List[Callable] = []
        
        # Load settings
        self.load_settings()
    
    def add_observer(self, callback: Callable):
        """Add an observer to be notified of state changes"""
        self._observers.append(callback)
    
    def notify_observers(self, event: str, data: any = None):
        """Notify all observers of a state change"""
        for observer in self._observers:
            try:
                observer(event, data)
            except Exception as e:
                log_error(f"Observer notification failed: {e}")
    
    def update_devices(self, devices: List[Dict]):
        """Update the device list"""
        self.devices = []
        for device_data in devices:
            device = Device(
                ip=device_data.get("ip", ""),
                mac=device_data.get("mac", "Unknown"),
                vendor=device_data.get("vendor", "Unknown"),
                hostname=device_data.get("hostname", ""),
                local=device_data.get("local", False),
                traffic=device_data.get("traffic", 0),
                last_seen=datetime.now().isoformat(),
                blocked=device_data.get("blocked", False)
            )
            self.devices.append(device)
        
        self.notify_observers("devices_updated", self.devices)
        log_info(f"Updated device list: {len(self.devices)} devices")
    
    def select_device(self, ip: str):
        """Select a device by IP"""
        self.selected_ip = ip
        self.notify_observers("device_selected", ip)
        log_info(f"Selected device: {ip}")
    
    def get_selected_device(self) -> Optional[Device]:
        """Get the currently selected device"""
        if not self.selected_ip:
            return None
        
        for device in self.devices:
            if device.ip == self.selected_ip:
                return device
        return None
    
    def toggle_blocking(self, ip: str = None) -> bool:
        """Toggle blocking for a device"""
        target_ip = ip or self.selected_ip
        if not target_ip:
            log_error("No device selected to toggle blocking")
            return False
        
        # Find and update device
        for device in self.devices:
            if device.ip == target_ip:
                device.blocked = not device.blocked
                self.blocking = device.blocked
                self.notify_observers("blocking_toggled", {
                    "ip": target_ip,
                    "blocked": device.blocked
                })
                log_info(f"Blocking {'enabled' if device.blocked else 'disabled'} for {target_ip}")
                return device.blocked
        
        log_error(f"Device {target_ip} not found")
        return False
    
    def update_network_info(self, info: Dict):
        """Update network information"""
        self.network_info = info
        self.notify_observers("network_updated", info)
    
    def set_scan_status(self, in_progress: bool):
        """Set scan status"""
        self.scan_in_progress = in_progress
        self.notify_observers("scan_status_changed", in_progress)
    
    def load_settings(self):
        """Load settings from file"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    data = json.load(f)
                    self.settings = AppSettings(**data)
                log_info("Settings loaded successfully")
        except Exception as e:
            log_error(f"Failed to load settings: {e}")
    
    def save_settings(self):
        """Save settings to file"""
        try:
            # Ensure the directory exists
            config_dir = os.path.dirname(self.config_file)
            if config_dir:
                os.makedirs(config_dir, exist_ok=True)
            
            with open(self.config_file, 'w') as f:
                json.dump(asdict(self.settings), f, indent=2)
            log_info("Settings saved successfully")
        except Exception as e:
            log_error(f"Failed to save settings: {e}")
    
    def update_setting(self, key: str, value: any):
        """Update a specific setting"""
        if hasattr(self.settings, key):
            setattr(self.settings, key, value)
            self.save_settings()
            self.notify_observers("setting_updated", {key: value})
            log_info(f"Setting updated: {key} = {value}")
    
    def get_device_by_ip(self, ip: str) -> Optional[Device]:
        """Get device by IP address"""
        for device in self.devices:
            if device.ip == ip:
                return device
        return None
    
    def get_blocked_devices(self) -> List[Device]:
        """Get list of blocked devices"""
        return [device for device in self.devices if device.blocked]
    
    def clear_devices(self):
        """Clear the device list"""
        self.devices = []
        self.notify_observers("devices_cleared")
        log_info("Device list cleared")
