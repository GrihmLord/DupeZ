# app/core/controller.py

import threading
import time
from typing import List, Dict, Optional
from app.network import device_scan
from app.firewall import blocker
from app.logs.logger import log_info, log_error, log_performance, log_network_scan, log_device_action
from app.core.state import AppState, Device, AppSettings
from app.core.smart_mode import smart_mode, enable_smart_mode, disable_smart_mode, get_smart_mode_status

class AppController:
    def __init__(self):
        self.state = AppState()
        self.scan_thread = None
        self.stop_scanning = False
        self.auto_scan_enabled = True
        
        # Initialize smart mode
        self.state.add_observer(self._on_state_change)
        
        # Start auto-scan if enabled
        if self.state.settings.auto_scan:
            self.start_auto_scan()
    
    def _on_state_change(self, event: str, data: any):
        """Handle state change events"""
        if event == "devices_updated":
            self._update_smart_mode_devices()
        elif event == "device_selected":
            self._on_device_selected(data)
        elif event == "blocking_toggled":
            self._on_blocking_toggled(data)
        elif event == "setting_updated":
            self._on_setting_updated(data)
    
    def _update_smart_mode_devices(self):
        """Update smart mode with current device list"""
        if smart_mode.is_enabled():
            for device in self.state.devices:
                # Update smart mode with device info
                pass
    
    def _on_device_selected(self, ip: str):
        """Handle device selection"""
        device = self.state.get_device_by_ip(ip)
        if device:
            log_info(f"Selected device: {device.ip} ({device.vendor})")
    
    def _on_blocking_toggled(self, data: Dict):
        """Handle blocking toggle events"""
        ip = data.get("ip")
        blocked = data.get("blocked")
        
        if blocked:
            self._apply_blocking(ip)
        else:
            self._remove_blocking(ip)
    
    def _on_setting_updated(self, data: Dict):
        """Handle setting updates"""
        for key, value in data.items():
            if key == "smart_mode":
                if value:
                    enable_smart_mode()
                else:
                    disable_smart_mode()
            elif key == "auto_scan":
                self.auto_scan_enabled = value
                if value:
                    self.start_auto_scan()
                else:
                    self.stop_auto_scan()
    
    def scan_devices(self, quick: bool = True) -> List[Dict]:
        """Scan for devices on the network with performance monitoring"""
        start_time = time.time()
        try:
            self.state.set_scan_status(True)
            log_info("Starting device scan...")
            
            # Get network info
            network_info = device_scan.get_network_info()
            self.state.update_network_info(network_info)
            
            # Scan for devices (quick scan by default)
            devices = device_scan.scan_devices(quick=quick)
            
            # Update state with new devices
            self.state.update_devices(devices)
            
            scan_duration = time.time() - start_time
            log_network_scan(len(devices), scan_duration)
            log_performance("Device scan", scan_duration)
            
            return devices
            
        except Exception as e:
            log_error(f"Device scan failed: {e}")
            return []
        finally:
            self.state.set_scan_status(False)
    
    def select_device(self, ip: str):
        """Select a device by IP address"""
        self.state.select_device(ip)
    
    def get_selected_device(self) -> Optional[Device]:
        """Get the currently selected device"""
        return self.state.get_selected_device()
    
    def toggle_lag(self, ip: str = None) -> bool:
        """Toggle lag for a device with performance monitoring"""
        start_time = time.time()
        try:
            if ip:
                device = self.state.get_device_by_ip(ip)
                if device:
                    device.blocked = not device.blocked
                    success = self._apply_blocking(ip) if device.blocked else self._remove_blocking(ip)
                    
                    duration = time.time() - start_time
                    log_device_action("Toggle lag", ip, success)
                    log_performance("Toggle lag", duration)
                    
                    return success
            return False
        except Exception as e:
            log_error(f"Toggle lag failed: {e}")
            return False
    
    def _apply_blocking(self, ip: str):
        """Apply blocking with performance monitoring"""
        start_time = time.time()
        try:
            success = blocker.block_device(ip)
            duration = time.time() - start_time
            log_performance("Apply blocking", duration)
            return success
        except Exception as e:
            log_error(f"Apply blocking failed: {e}")
            return False
    
    def _remove_blocking(self, ip: str):
        """Remove blocking with performance monitoring"""
        start_time = time.time()
        try:
            success = blocker.unblock_device(ip)
            duration = time.time() - start_time
            log_performance("Remove blocking", duration)
            return success
        except Exception as e:
            log_error(f"Remove blocking failed: {e}")
            return False
    
    def toggle_smart_mode(self):
        """Toggle smart mode"""
        current_status = smart_mode.is_enabled()
        if current_status:
            disable_smart_mode()
            self.state.update_setting("smart_mode", False)
        else:
            enable_smart_mode()
            self.state.update_setting("smart_mode", True)
        
        return not current_status
    
    def get_smart_mode_status(self) -> Dict:
        """Get smart mode status and statistics"""
        return get_smart_mode_status()
    
    def open_settings(self):
        """Open application settings dialog"""
        log_info("Settings dialog requested")
        return True
    
    def update_settings(self, new_settings: AppSettings):
        """Update application settings"""
        try:
            self.state.update_settings(new_settings)
            log_info("Settings updated successfully")
        except Exception as e:
            log_error(f"Error updating settings: {e}")
    
    def apply_additional_settings(self, additional_settings: dict):
        """Apply additional settings to the application"""
        try:
            # Apply additional settings to state
            for key, value in additional_settings.items():
                self.state.update_setting(key, value)
            log_info("Additional settings applied")
        except Exception as e:
            log_error(f"Error applying additional settings: {e}")
    
    def start_auto_scan(self):
        """Start automatic device scanning"""
        if self.scan_thread and self.scan_thread.is_alive():
            return
        
        self.auto_scan_enabled = True
        self.scan_thread = threading.Thread(target=self._auto_scan_loop, daemon=True)
        self.scan_thread.start()
        log_info("Auto-scan started")
    
    def stop_auto_scan(self):
        """Stop automatic device scanning"""
        self.auto_scan_enabled = False
        self.stop_scanning = True
        if self.scan_thread:
            self.scan_thread.join(timeout=5)
        log_info("Auto-scan stopped")
    
    def _auto_scan_loop(self):
        """Auto-scan loop"""
        scan_count = 0
        while self.auto_scan_enabled and not self.stop_scanning:
            try:
                # Use quick scan most of the time, full scan every 3rd time (reduced from 5th)
                quick_scan = (scan_count % 3) != 0
                self.scan_devices(quick=quick_scan)
                scan_count += 1
                time.sleep(self.state.settings.scan_interval)
            except Exception as e:
                log_error(f"Auto-scan error: {e}")
                time.sleep(30)  # Reduced wait time on error (from 60)
    
    def get_network_info(self) -> Dict:
        """Get current network information"""
        return self.state.network_info
    
    def get_devices(self) -> List[Device]:
        """Get current device list"""
        return self.state.devices
    
    def get_blocked_devices(self) -> List[Device]:
        """Get list of blocked devices"""
        return self.state.get_blocked_devices()
    
    def update_setting(self, key: str, value: any):
        """Update an application setting"""
        self.state.update_setting(key, value)
    
    def get_settings(self):
        """Get current application settings"""
        return self.state.settings
    
    def is_scanning(self) -> bool:
        """Check if a scan is in progress"""
        return self.state.scan_in_progress
    
    def is_blocking(self) -> bool:
        """Check if any device is currently blocked"""
        return self.state.blocking
    
    def get_device_by_ip(self, ip: str) -> Optional[Device]:
        """Get device by IP address"""
        return self.state.get_device_by_ip(ip)
    
    def clear_devices(self):
        """Clear the device list"""
        self.state.clear_devices()
    
    def shutdown(self):
        """Cleanup on application shutdown"""
        try:
            # Stop auto-scan first
            self.stop_auto_scan()
            
            # Disable smart mode
            try:
                disable_smart_mode()
            except Exception as e:
                log_error(f"Error disabling smart mode: {e}")
            
            # Unblock any blocked devices
            try:
                for device in self.get_blocked_devices():
                    self._remove_blocking(device.ip)
            except Exception as e:
                log_error(f"Error unblocking devices: {e}")
            
            log_info("Controller shutdown complete")
        except Exception as e:
            log_error(f"Error during shutdown: {e}")
