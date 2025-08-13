# app/core/controller.py

import threading
import time
import psutil
import subprocess
from typing import List, Dict, Optional
from app.network import device_scan
from app.firewall import blocker
from app.logs.logger import log_info, log_error, log_performance, log_network_scan, log_blocking_event
from app.core.state import AppState, Device, AppSettings
from app.core.smart_mode import smart_mode, enable_smart_mode, disable_smart_mode, get_smart_mode_status
from app.core.traffic_analyzer import AdvancedTrafficAnalyzer
from app.plugins.plugin_manager import PluginManager
from app.core.data_persistence import persistence_manager, settings_manager, device_manager, account_manager, marker_manager, save_all_data

class AppController:
    def __init__(self):
        self.state = AppState()
        self.scan_thread = None
        self.stop_scanning = False
        self.auto_scan_enabled = True
        
        # Initialize advanced features
        self.traffic_analyzer = None
        self.plugin_manager = None
        
        # Initialize smart mode
        self.state.add_observer(self._on_state_change)
        
        # Initialize advanced features
        self._init_advanced_features()
        
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
        """Scan for REAL devices on the network - no mock data"""
        start_time = time.time()
        try:
            self.state.set_scan_status(True)
            log_info(f"🔍 Starting REAL device scan ({'quick' if quick else 'full'})...")
            
            # Get network info
            network_info = device_scan.get_network_info()
            self.state.update_network_info(network_info)
            
            # Use enhanced scanner for real device detection
            from app.network.enhanced_scanner import EnhancedNetworkScanner
            scanner = EnhancedNetworkScanner()
            
            # Connect signals for proper communication
            scanner.scan_complete.connect(self._on_scan_complete)
            scanner.scan_error.connect(self._on_scan_error)
            scanner.status_update.connect(self._on_scan_status)
            
            # Start scanning
            scanner.start()
            
            # Wait for scan to complete (with timeout)
            if not scanner.wait(10000):  # 10 second timeout
                scanner.stop_scan()
                log_warning("Scan timeout - stopping scanner")
            
            # Get real devices from scanner
            devices = scanner.devices if hasattr(scanner, 'devices') else []
            
            # Filter out any mock/fake devices
            real_devices = []
            for device in devices:
                # Only include devices that actually responded to our scans
                if device.get('ip') and device.get('ip') != '127.0.0.1':
                    # Verify device is actually reachable
                    if self._verify_device_exists(device.get('ip')):
                        real_devices.append(device)
                        log_info(f"✅ Found real device: {device.get('ip')} - {device.get('hostname', 'Unknown')}")
                    else:
                        log_info(f"❌ Device {device.get('ip')} not reachable - excluding")
            
            # Update state with only real devices
            self.state.update_devices(real_devices)
            
            # Update smart mode with new devices
            self._update_smart_mode_devices()
            
            duration = time.time() - start_time
            log_network_scan(len(real_devices), duration)
            log_performance("Real device scan", duration)
            
            self.state.set_scan_status(False)
            return real_devices
            
        except Exception as e:
            log_error(f"Real device scan failed: {e}")
            self.state.set_scan_status(False)
            return []
    
    def _on_scan_complete(self, devices: list):
        """Handle scan completion"""
        try:
            log_info(f"Scan completed with {len(devices)} devices")
            
            # Convert device dictionaries to Device objects and update state
            from app.core.state import Device
            device_objects = []
            
            for device_dict in devices:
                try:
                    device = Device(
                        ip=device_dict.get('ip', ''),
                        mac=device_dict.get('mac', ''),
                        hostname=device_dict.get('hostname', ''),
                        vendor=device_dict.get('vendor', ''),
                        local=device_dict.get('local', False),
                        traffic=device_dict.get('traffic', 0),
                        last_seen=device_dict.get('last_seen', ''),
                        blocked=device_dict.get('blocked', False)
                    )
                    device_objects.append(device)
                except Exception as e:
                    log_error(f"Error converting device {device_dict.get('ip', 'Unknown')}: {e}")
                    continue
            
            # Update state with new devices
            self.state.devices = device_objects
            self.state.notify_observers("devices_updated", device_objects)
            
            log_info(f"Updated state with {len(device_objects)} devices")
            
        except Exception as e:
            log_error(f"Error handling scan completion: {e}")
    
    def _on_scan_error(self, error_msg: str):
        """Handle scan error"""
        try:
            log_error(f"Scan error: {error_msg}")
        except Exception as e:
            log_error(f"Error handling scan error: {e}")
    
    def _on_scan_status(self, status_msg: str):
        """Handle scan status update"""
        try:
            log_info(f"Scan status: {status_msg}")
        except Exception as e:
            log_error(f"Error handling scan status: {e}")
    
    def _verify_device_exists(self, ip: str) -> bool:
        """Verify that a device actually exists on the network"""
        try:
            # Quick TCP connection test
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            
            # Try common ports
            common_ports = [80, 443, 22, 21, 23, 25, 53, 110, 143, 993, 995, 8080]
            for port in common_ports:
                try:
                    result = sock.connect_ex((ip, port))
                    sock.close()
                    if result == 0:
                        return True
                except:
                    continue
            
            sock.close()
            return False
            
        except Exception as e:
            log_error(f"Device verification failed for {ip}: {e}")
            return False
    
    def quick_scan_devices(self) -> List[Dict]:
        """Quick scan for devices"""
        return self.scan_devices(quick=True)
    
    def full_scan_devices(self) -> List[Dict]:
        """Full scan for devices"""
        return self.scan_devices(quick=False)
    
    def select_device(self, ip: str):
        """Select a device"""
        self.state.select_device(ip)
    
    def get_selected_device(self) -> Optional[Device]:
        """Get the currently selected device"""
        return self.state.get_selected_device()
    
    def toggle_lag(self, ip: str = None) -> bool:
        """Toggle lag for a device - TEMPORARY until manually toggled - OPTIMIZED"""
        start_time = time.time()
        try:
            if ip:
                device = self.state.get_device_by_ip(ip)
                if device:
                    # Check current blocked status
                    current_blocked = device.blocked
                    success = False
                    
                    # Apply the opposite of current status - TEMPORARY, not permanent
                    if current_blocked:
                        # Device is currently blocked, so unblock it
                        success = self._remove_blocking(ip)
                        if success:
                            device.blocked = False
                            # Performance optimization: Reduce logging
                            if hasattr(self, '_last_log_time') and time.time() - getattr(self, '_last_log_time', 0) > 1.0:
                                log_info(f"Successfully unblocked device: {ip} - TEMPORARY")
                                self._last_log_time = time.time()
                        else:
                            log_error(f"Failed to unblock device: {ip}")
                    else:
                        # Device is not blocked, so block it
                        success = self._apply_blocking(ip)
                        if success:
                            device.blocked = True
                            # Performance optimization: Reduce logging
                            if hasattr(self, '_last_log_time') and time.time() - getattr(self, '_last_log_time', 0) > 1.0:
                                log_info(f"Successfully blocked device: {ip} - TEMPORARY")
                                self._last_log_time = time.time()
                        else:
                            log_error(f"Failed to block device: {ip}")
                    
                    # Emit state change event for UI updates
                    if success:
                        self._on_blocking_toggled({
                            "ip": ip,
                            "blocked": device.blocked,
                            "success": success,
                            "persistent": False  # Changed from True to False - TEMPORARY
                        })
                    
                    duration = time.time() - start_time
                    # Performance optimization: Only log performance for slow operations
                    if duration > 0.1:  # Only log if operation takes more than 100ms
                        log_performance("Toggle lag", duration)
                    
                    return device.blocked  # Return the new blocked state
                else:
                    # Device not found in state, try to block it anyway
                    if hasattr(self, '_last_log_time') and time.time() - getattr(self, '_last_log_time', 0) > 1.0:
                        log_info(f"Device {ip} not found in state, attempting to block directly")
                        self._last_log_time = time.time()
                    success = self._apply_blocking(ip)
                    if success:
                        if hasattr(self, '_last_log_time') and time.time() - getattr(self, '_last_log_time', 0) > 1.0:
                            log_info(f"Successfully blocked device: {ip} (not in state)")
                            self._last_log_time = time.time()
                        return True
                    else:
                        log_error(f"Failed to block device: {ip} (not in state)")
                        return False
            return False
        except Exception as e:
            log_error(f"Toggle lag failed: {e}")
            return False
    
    def _apply_blocking(self, ip: str):
        """Apply enterprise-level blocking with performance monitoring"""
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
        """Remove enterprise-level blocking with performance monitoring"""
        start_time = time.time()
        try:
            success = blocker.unblock_device(ip)
            duration = time.time() - start_time
            log_performance("Remove blocking", duration)
            return success
        except Exception as e:
            log_error(f"Remove blocking failed: {e}")
            return False
    
    def toggle_smart_mode(self) -> bool:
        """Toggle smart mode with enterprise-level functionality"""
        try:
            if not hasattr(self, 'smart_mode'):
                from app.core.smart_mode import SmartModeEngine
                self.smart_mode = SmartModeEngine()
            
            if self.smart_mode.enabled:
                # Disable smart mode
                self.smart_mode.enabled = False
                self.smart_mode.stop_monitoring()
                log_info("Smart mode disabled")
            else:
                # Enable smart mode
                self.smart_mode.enabled = True
                self.smart_mode.start_monitoring()
                log_info("Smart mode enabled")
            
            # Save setting
            self.state.settings.smart_mode = self.smart_mode.enabled
            self.state.save_settings()
            
            # Emit state change
            self.state.notify_observers("smart_mode_toggled", {
                "enabled": self.smart_mode.enabled,
                "status": self.smart_mode.get_smart_mode_status()
            })
            
            return self.smart_mode.enabled
            
        except Exception as e:
            log_error(f"Toggle smart mode failed: {e}")
            return False
    
    def get_smart_mode_status(self) -> Dict:
        """Get smart mode status with enterprise-level details"""
        try:
            if hasattr(self, 'smart_mode'):
                return {
                    "enabled": self.smart_mode.enabled,
                    "status": self.smart_mode.get_smart_mode_status(),
                    "devices_monitored": len(self.smart_mode.monitored_devices) if hasattr(self.smart_mode, 'monitored_devices') else 0,
                    "rules_active": len(self.smart_mode.active_rules) if hasattr(self.smart_mode, 'active_rules') else 0
                }
            else:
                return {
                    "enabled": False,
                    "status": "Not initialized",
                    "devices_monitored": 0,
                    "rules_active": 0
                }
        except Exception as e:
            log_error(f"Get smart mode status failed: {e}")
            return {"enabled": False, "status": "Error"}
    
    def open_settings(self):
        """Open settings dialog"""
        # This would open a settings dialog
        pass
    
    def update_settings(self, new_settings: AppSettings):
        """Update application settings"""
        try:
            # Update the settings
            self.state.settings = new_settings
            self.state.save_settings()
            
            # Apply the new settings immediately
            self._apply_settings_changes(new_settings)
            
            log_info("Settings updated successfully")
        except Exception as e:
            log_error(f"Error updating settings: {e}")
    
    def _apply_settings_changes(self, settings: AppSettings):
        """Apply settings changes to the running application"""
        try:
            # Apply auto-scan changes
            if settings.auto_scan != self.auto_scan_enabled:
                if settings.auto_scan:
                    self.start_auto_scan()
                else:
                    self.stop_auto_scan()
            
            # Apply smart mode changes
            if hasattr(self, 'state') and hasattr(self.state, 'settings'):
                if settings.smart_mode != self.state.settings.smart_mode:
                    if settings.smart_mode:
                        from app.core.smart_mode import enable_smart_mode
                        enable_smart_mode()
                    else:
                        from app.core.smart_mode import disable_smart_mode
                        disable_smart_mode()
            
            # Apply scan interval changes
            if hasattr(self, 'scan_thread') and self.scan_thread and self.scan_thread.is_alive():
                # The scan interval will be applied on the next scan cycle
                pass
            
            log_info("Settings changes applied successfully")
            
        except Exception as e:
            log_error(f"Error applying settings changes: {e}")
    
    def apply_additional_settings(self, additional_settings: dict):
        """Apply additional settings"""
        for key, value in additional_settings.items():
            if hasattr(self.state.settings, key):
                setattr(self.state.settings, key, value)
        self.state.save_settings()
        log_info("Additional settings applied")
    
    def start_auto_scan(self):
        """Start automatic scanning"""
        self.auto_scan_enabled = True
        if not self.scan_thread or not self.scan_thread.is_alive():
            self.scan_thread = threading.Thread(target=self._auto_scan_loop, daemon=True)
            self.scan_thread.start()
        log_info("Auto-scan started")
    
    def stop_auto_scan(self):
        """Stop automatic scanning"""
        self.auto_scan_enabled = False
        self.stop_scanning = True
        log_info("Auto-scan stopped")
    
    def _auto_scan_loop(self):
        """Auto-scan loop"""
        while self.auto_scan_enabled and not self.stop_scanning:
            try:
                self.quick_scan_devices()
                time.sleep(30)  # Scan every 30 seconds
            except Exception as e:
                log_error(f"Auto-scan error: {e}")
                time.sleep(60)  # Wait longer on error
    
    def get_network_info(self) -> Dict:
        """Get enterprise-level network information"""
        try:
            # Get real network information using psutil
            network_info = {}
            
            # Get network interfaces
            interfaces = psutil.net_if_addrs()
            active_interfaces = []
            
            for interface_name, interface_addresses in interfaces.items():
                for addr in interface_addresses:
                    if addr.family == 2:  # AF_INET
                        active_interfaces.append({
                            "name": interface_name,
                            "ip": addr.address,
                            "netmask": addr.netmask
                        })
            
            network_info["interfaces"] = active_interfaces
            
            # Get network statistics
            net_io = psutil.net_io_counters()
            network_info["bytes_sent"] = net_io.bytes_sent
            network_info["bytes_recv"] = net_io.bytes_recv
            network_info["packets_sent"] = net_io.packets_sent
            network_info["packets_recv"] = net_io.packets_recv
            
            # Get current bandwidth
            network_info["current_bandwidth"] = self._calculate_current_bandwidth()
            
            return network_info
            
        except Exception as e:
            log_error(f"Get network info failed: {e}")
            return {}
    
    def _calculate_current_bandwidth(self) -> float:
        """Calculate current bandwidth usage"""
        try:
            # Get network I/O counters
            net_io = psutil.net_io_counters()
            
            # Calculate total bytes
            total_bytes = net_io.bytes_sent + net_io.bytes_recv
            
            # Convert to KB/s (rough approximation)
            return total_bytes / 1024.0
            
        except Exception as e:
            log_error(f"Calculate bandwidth failed: {e}")
            return 0.0
    
    def get_devices(self) -> List[Device]:
        """Get all devices"""
        return self.state.devices
    
    def get_blocked_devices(self) -> List[Device]:
        """Get enterprise-level blocked devices information"""
        try:
            # Get devices that are marked as blocked in state
            blocked_devices = [device for device in self.state.devices if device.blocked]
            
            # Also check the network disruptor for real blocked devices
            from app.firewall.network_disruptor import network_disruptor
            disrupted_ips = network_disruptor.get_disrupted_devices()
            
            # Update device states based on network disruptor
            for device in self.state.devices:
                if device.ip in disrupted_ips:
                    device.blocked = True
                    if device not in blocked_devices:
                        blocked_devices.append(device)
                elif device.ip not in disrupted_ips and device.blocked:
                    # Device is marked as blocked but not actually disrupted
                    device.blocked = False
                    if device in blocked_devices:
                        blocked_devices.remove(device)
            
            return blocked_devices
            
        except Exception as e:
            log_error(f"Get blocked devices failed: {e}")
            return []
    
    def update_setting(self, key: str, value: any):
        """Update a specific setting"""
        if hasattr(self.state.settings, key):
            setattr(self.state.settings, key, value)
            self.state.save_settings()
    
    def get_settings(self):
        """Get current settings"""
        return self.state.settings
    
    def is_scanning(self) -> bool:
        """Check if scanning is in progress"""
        return self.state.scan_in_progress
    
    def is_blocking(self) -> bool:
        """Check if any blocking is active"""
        return len(self.get_blocked_devices()) > 0
    
    def get_device_by_ip(self, ip: str) -> Optional[Device]:
        """Get device by IP address"""
        return self.state.get_device_by_ip(ip)
    
    def clear_devices(self):
        """Clear all devices"""
        self.state.devices = []
        self.state.notify_observers("devices_updated", [])
    
    def shutdown(self):
        """Shutdown the controller and clean up resources"""
        try:
            log_info("Starting application shutdown...")
            
            # Stop auto-scan
            self.stop_auto_scan()
            
            # Stop smart mode properly
            if hasattr(self, 'smart_mode') and self.smart_mode:
                try:
                    if hasattr(self.smart_mode, 'stop_monitoring') and callable(self.smart_mode.stop_monitoring):
                        self.smart_mode.stop_monitoring()
                    else:
                        self.smart_mode.disable()
                except Exception as e:
                    log_error(f"Smart mode shutdown error: {e}")
            
            # Stop traffic analyzer
            if hasattr(self, 'traffic_analyzer') and self.traffic_analyzer:
                try:
                    self.traffic_analyzer.stop()
                except Exception as e:
                    log_error(f"Traffic analyzer shutdown error: {e}")
            
            # Stop plugin manager
            if hasattr(self, 'plugin_manager') and self.plugin_manager:
                try:
                    self.plugin_manager.shutdown()
                except Exception as e:
                    log_error(f"Plugin manager shutdown error: {e}")
            
            # Stop network disruptor
            if hasattr(self, 'network_disruptor') and self.network_disruptor:
                try:
                    self.network_disruptor.stop()
                except Exception as e:
                    log_error(f"Network disruptor shutdown error: {e}")
            
            # Save all pending data before shutdown
            log_info("Saving all pending data...")
            save_all_data()
            
            log_info("Controller shutdown completed")
            
        except Exception as e:
            log_error(f"Controller shutdown error: {e}")
    
    def _init_advanced_features(self):
        """Initialize enterprise-level advanced features"""
        try:
            log_info("🔧 Starting advanced features initialization...")
            
            # Initialize traffic analyzer
            log_info("📊 Initializing traffic analyzer...")
            self.traffic_analyzer = AdvancedTrafficAnalyzer()
            self.traffic_analyzer.start()
            log_info("✅ Traffic analyzer initialized")
            
            # Initialize plugin manager
            log_info("🔌 Initializing plugin manager...")
            self.plugin_manager = PluginManager()
            self.plugin_manager.load_all_plugins()
            log_info("✅ Plugin manager initialized")
            
            # Initialize network disruptor
            log_info("🌐 Initializing network disruptor...")
            from app.firewall.network_disruptor import network_disruptor
            self.network_disruptor = network_disruptor
            log_info(f"📡 Network disruptor imported: {self.network_disruptor}")
            
            if self.network_disruptor.initialize():
                self.network_disruptor.start()
                log_info("✅ Enterprise Network Disruptor initialized and started")
            else:
                log_error("❌ Failed to initialize Enterprise Network Disruptor")
            
            log_info("✅ Advanced features initialized successfully")
            
        except Exception as e:
            log_error(f"❌ Advanced features initialization failed: {e}")
            import traceback
            log_error(f"❌ Traceback: {traceback.format_exc()}")
    
    def get_traffic_analysis(self) -> Dict:
        """Get enterprise-level traffic analysis"""
        try:
            if self.traffic_analyzer:
                return self.traffic_analyzer.get_analysis()
            else:
                # Fallback to basic traffic analysis
                return self._get_basic_traffic_analysis()
        except Exception as e:
            log_error(f"Get traffic analysis failed: {e}")
            return {}
    
    def _get_basic_traffic_analysis(self) -> Dict:
        """Get basic traffic analysis using psutil"""
        try:
            # Get network I/O counters
            net_io = psutil.net_io_counters()
            
            # Get per-interface statistics
            net_io_per_nic = psutil.net_io_counters(pernic=True)
            
            # Calculate bandwidth
            current_bandwidth = (net_io.bytes_sent + net_io.bytes_recv) / 1024.0  # KB/s
            
            return {
                "current_bandwidth": current_bandwidth,
                "bytes_sent": net_io.bytes_sent,
                "bytes_recv": net_io.bytes_recv,
                "packets_sent": net_io.packets_sent,
                "packets_recv": net_io.packets_recv,
                "interfaces": net_io_per_nic,
                "timestamp": time.time()
            }
        except Exception as e:
            log_error(f"Basic traffic analysis failed: {e}")
            return {
                "current_bandwidth": 0.0,
                "bytes_sent": 0,
                "bytes_recv": 0,
                "packets_sent": 0,
                "packets_recv": 0,
                "interfaces": {},
                "timestamp": time.time()
            }
    
    def get_plugin_info(self) -> List:
        """Get plugin information"""
        if self.plugin_manager:
            return self.plugin_manager.get_plugin_info()
        return []
    
    def enable_plugin(self, plugin_name: str) -> bool:
        """Enable a plugin"""
        if self.plugin_manager:
            return self.plugin_manager.enable_plugin(plugin_name)
        return False
    
    def disable_plugin(self, plugin_name: str) -> bool:
        """Disable a plugin"""
        if self.plugin_manager:
            return self.plugin_manager.disable_plugin(plugin_name)
        return False
    
    def create_plugin_template(self, plugin_name: str, category: str = "General") -> str:
        """Create a plugin template"""
        if self.plugin_manager:
            return self.plugin_manager.create_template(plugin_name, category)
        return ""
    
    def export_traffic_report(self, filename: str = None) -> str:
        """Export traffic analysis report"""
        if self.traffic_analyzer:
            return self.traffic_analyzer.export_report(filename)
        return ""
    
    def get_traffic_recommendations(self) -> List[str]:
        """Get traffic optimization recommendations"""
        if self.traffic_analyzer:
            return self.traffic_analyzer.get_recommendations()
        return []
