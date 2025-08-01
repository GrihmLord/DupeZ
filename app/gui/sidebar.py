# app/gui/sidebar.py

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QPushButton, QLabel, 
                             QFrame, QHBoxLayout, QProgressBar, QGroupBox)
from PyQt6.QtCore import pyqtSignal, QTimer, Qt
from PyQt6.QtGui import QFont, QPalette, QColor
from typing import Dict, Optional
from app.logs.logger import log_info, log_error

class Sidebar(QWidget):
    """Enhanced sidebar with status indicators and controls"""
    
    # Signals
    smart_mode_toggled = pyqtSignal()
    settings_requested = pyqtSignal()
    scan_requested = pyqtSignal()
    clear_data_requested = pyqtSignal()
    quick_scan_requested = pyqtSignal()
    mass_block_requested = pyqtSignal()
    mass_unblock_requested = pyqtSignal()
    search_requested = pyqtSignal()
    
    def __init__(self, controller=None):
        super().__init__()
        self.controller = controller
        self.smart_mode_active = False
        self.scanning = False
        self.blocking_active = False
        self.device_count = 0
        self.update_timer = None
        
        self.init_ui()
        self.start_status_updates()
    
    def init_ui(self):
        """Initialize the user interface with lagswitch styling"""
        layout = QVBoxLayout()
        layout.setContentsMargins(8, 8, 8, 8)  # Reduced margins for more space
        layout.setSpacing(8)  # Reduced spacing for more compact layout
        
        # Title with hacker styling
        title_label = QLabel("⚡ PULSEDROP PRO ⚡")
        title_label.setObjectName("title_label")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("""
            QLabel {
                font-size: 14pt;
                font-weight: bold;
                color: #00ffff;
                border: 2px solid #00ffff;
                padding: 6px;
                background-color: #1a1a1a;
            }
        """)
        layout.addWidget(title_label)
        
        # Network Info Group
        network_group = QGroupBox("🌐 NETWORK STATUS")
        network_layout = QVBoxLayout()
        
        # Network information display
        self.network_info_label = QLabel("Initializing...")
        self.network_info_label.setObjectName("network_info")
        self.network_info_label.setWordWrap(True)
        network_layout.addWidget(self.network_info_label)
        
        network_group.setLayout(network_layout)
        layout.addWidget(network_group)
        
        # Status Group
        status_group = QGroupBox("📊 SYSTEM STATUS")
        status_layout = QVBoxLayout()
        
        # Device count with enhanced display
        self.device_count_label = QLabel("📱 DEVICES: 0")
        self.device_count_label.setObjectName("device_count")
        status_layout.addWidget(self.device_count_label)
        
        # Smart mode status
        self.smart_mode_status = QLabel("🧠 SMART MODE: OFF")
        self.smart_mode_status.setObjectName("status_label")
        status_layout.addWidget(self.smart_mode_status)
        
        # Blocking status
        self.blocking_status = QLabel("🔒 BLOCKING: NONE")
        self.blocking_status.setObjectName("status_label")
        status_layout.addWidget(self.blocking_status)
        
        # Scan status
        self.scan_status = QLabel("🔍 SCAN: READY")
        self.scan_status.setObjectName("status_label")
        status_layout.addWidget(self.scan_status)
        
        # Traffic display
        self.traffic_label = QLabel("📊 TRAFFIC: 0 KB/s")
        self.traffic_label.setObjectName("traffic_display")
        status_layout.addWidget(self.traffic_label)
        
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)
        
        # Controls Group
        controls_group = QGroupBox("🎛️ LAGSWITCH CONTROLS")
        controls_group.setVisible(True)  # Ensure visibility
        controls_layout = QVBoxLayout()
        
        # Enhanced control buttons with terminal styling - more compact
        self.smart_mode_btn = QPushButton("🧠 SMART MODE")
        self.smart_mode_btn.setObjectName("smart_mode_btn")
        self.smart_mode_btn.setCheckable(True)
        self.smart_mode_btn.setMaximumHeight(35)  # Compact height
        self.smart_mode_btn.clicked.connect(self.toggle_smart_mode)
        controls_layout.addWidget(self.smart_mode_btn)
        
        # Scan button
        self.scan_btn = QPushButton("🔍 SCAN NETWORK")
        self.scan_btn.setObjectName("scan_btn")
        self.scan_btn.setMaximumHeight(35)  # Compact height
        self.scan_btn.clicked.connect(self.request_scan)
        controls_layout.addWidget(self.scan_btn)
        
        # Quick scan button
        self.quick_scan_btn = QPushButton("⚡ QUICK SCAN")
        self.quick_scan_btn.setObjectName("scan_btn")
        self.quick_scan_btn.setMaximumHeight(35)  # Compact height
        self.quick_scan_btn.clicked.connect(self.request_quick_scan)
        controls_layout.addWidget(self.quick_scan_btn)
        
        # Mass block button
        self.mass_block_btn = QPushButton("🚫 MASS BLOCK")
        self.mass_block_btn.setObjectName("block_btn")
        self.mass_block_btn.setMaximumHeight(35)  # Compact height
        self.mass_block_btn.clicked.connect(self.request_mass_block)
        controls_layout.addWidget(self.mass_block_btn)
        
        # Mass unblock button
        self.mass_unblock_btn = QPushButton("✅ MASS UNBLOCK")
        self.mass_unblock_btn.setObjectName("refresh_btn")
        self.mass_unblock_btn.setMaximumHeight(35)  # Compact height
        self.mass_unblock_btn.clicked.connect(self.request_mass_unblock)
        controls_layout.addWidget(self.mass_unblock_btn)
        
        # Search devices button
        self.search_btn = QPushButton("🔍 SEARCH DEVICES")
        self.search_btn.setObjectName("scan_btn")
        self.search_btn.setMaximumHeight(35)  # Compact height
        self.search_btn.clicked.connect(self.request_search)
        controls_layout.addWidget(self.search_btn)
        
        # Clear data button
        self.clear_btn = QPushButton("🗑️ CLEAR DATA")
        self.clear_btn.setObjectName("block_btn")
        self.clear_btn.setMaximumHeight(35)  # Compact height
        self.clear_btn.clicked.connect(self.clear_data)
        controls_layout.addWidget(self.clear_btn)
        
        # Settings button
        self.settings_btn = QPushButton("⚙️ SETTINGS")
        self.settings_btn.setObjectName("refresh_btn")
        self.settings_btn.setMaximumHeight(35)  # Compact height
        self.settings_btn.clicked.connect(self.settings_requested.emit)
        controls_layout.addWidget(self.settings_btn)
        
        controls_group.setLayout(controls_layout)
        layout.addWidget(controls_group)
        
        # Debug: Log that controls are created
        from app.logs.logger import log_info
        log_info("Lagswitch controls created and added to sidebar")
        
        # Progress bar for operations
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        layout.addStretch()
        self.setLayout(layout)
        
        # Set object name for styling
        self.setObjectName("sidebar")
    
    def set_controller(self, controller):
        """Set the controller and connect to its events"""
        self.controller = controller
        if controller:
            # Connect to controller state changes
            controller.state.add_observer(self.on_controller_state_change)
    
    def on_controller_state_change(self, event: str, data):
        """Handle controller state changes"""
        try:
            if event == "devices_updated":
                QTimer.singleShot(0, lambda: self.update_device_count(len(data)))
            elif event == "scan_status_changed":
                QTimer.singleShot(0, lambda: self.update_scan_status(data))
            elif event == "blocking_toggled":
                QTimer.singleShot(0, lambda: self.update_blocking_status(data))
            elif event == "network_updated":
                QTimer.singleShot(0, lambda: self.update_network_info(data))
            elif event == "setting_updated":
                QTimer.singleShot(0, lambda: self.update_setting_status(data))
        except Exception as e:
            log_error(f"Error in sidebar state change: {e}")
    
    def update_network_info(self, network_info: Dict):
        """Update network information display with enhanced details"""
        try:
            if not network_info:
                return
            
            # Enhanced network information display
            info_text = f"🌐 <b>Network Information</b><br>"
            
            if 'interface' in network_info:
                info_text += f"📡 Interface: {network_info['interface']}<br>"
            
            if 'ip' in network_info:
                info_text += f"📍 IP Address: {network_info['ip']}<br>"
            
            if 'subnet' in network_info:
                info_text += f"🔗 Subnet: {network_info['subnet']}<br>"
            
            if 'gateway' in network_info:
                info_text += f"🚪 Gateway: {network_info['gateway']}<br>"
            
            if 'dns' in network_info:
                info_text += f"🔍 DNS: {network_info['dns']}<br>"
            
            if 'speed' in network_info:
                info_text += f"⚡ Speed: {network_info['speed']}<br>"
            
            if 'status' in network_info:
                status_icon = "🟢" if network_info['status'] == 'Connected' else "🔴"
                info_text += f"{status_icon} Status: {network_info['status']}<br>"
            
            # Add connection quality indicator
            if 'latency' in network_info:
                latency = network_info['latency']
                if latency < 50:
                    quality = "🟢 Excellent"
                elif latency < 100:
                    quality = "🟡 Good"
                elif latency < 200:
                    quality = "🟠 Fair"
                else:
                    quality = "🔴 Poor"
                info_text += f"📊 Quality: {quality} ({latency}ms)<br>"
            
            self.network_info_label.setText(info_text)
            
        except Exception as e:
            log_error(f"Error updating network info: {e}")
    
    def update_device_count(self, count: int):
        """Update device count with enhanced display"""
        try:
            # Enhanced device count display
            if count == 0:
                self.device_count_label.setText("📱 <b>Devices:</b> None found")
            elif count == 1:
                self.device_count_label.setText("📱 <b>Devices:</b> 1 device")
            else:
                self.device_count_label.setText(f"📱 <b>Devices:</b> {count} devices")
            
            # Update scan button text
            if hasattr(self, 'scan_btn'):
                self.scan_btn.setText(f"🔍 Scan ({count})")
                
        except Exception as e:
            log_error(f"Error updating device count: {e}")
    
    def update_smart_mode_status(self, enabled: bool):
        """Update smart mode status with enhanced display"""
        try:
            self.smart_mode_active = enabled
            
            if enabled:
                self.smart_mode_btn.setText("🧠 Smart Mode: ON")
                self.smart_mode_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #4CAF50;
                        color: white;
                        border: none;
                        padding: 8px;
                        border-radius: 4px;
                        font-weight: bold;
                    }
                    QPushButton:hover {
                        background-color: #45a049;
                    }
                """)
            else:
                self.smart_mode_btn.setText("🧠 Smart Mode: OFF")
                self.smart_mode_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #f44336;
                        color: white;
                        border: none;
                        padding: 8px;
                        border-radius: 4px;
                        font-weight: bold;
                    }
                    QPushButton:hover {
                        background-color: #da190b;
                    }
                """)
                
        except Exception as e:
            log_error(f"Error updating smart mode status: {e}")
    
    def update_scan_status(self, in_progress: bool):
        """Update scan status with enhanced display"""
        try:
            self.scanning = in_progress
            
            if in_progress:
                self.scan_btn.setText("⏳ Scanning...")
                self.scan_btn.setEnabled(False)
                self.scan_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #ff9800;
                        color: white;
                        border: none;
                        padding: 8px;
                        border-radius: 4px;
                        font-weight: bold;
                    }
                """)
            else:
                self.scan_btn.setText("🔍 Scan Network")
                self.scan_btn.setEnabled(True)
                self.scan_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #2196F3;
                        color: white;
                        border: none;
                        padding: 8px;
                        border-radius: 4px;
                        font-weight: bold;
                    }
                    QPushButton:hover {
                        background-color: #1976D2;
                    }
                """)
                
        except Exception as e:
            log_error(f"Error updating scan status: {e}")
    
    def update_blocking_status(self, blocking: bool):
        """Update blocking status with enhanced display"""
        try:
            self.blocking_active = blocking
            
            if blocking:
                self.blocking_btn.setText("🔒 Blocking: ACTIVE")
                self.blocking_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #f44336;
                        color: white;
                        border: none;
                        padding: 8px;
                        border-radius: 4px;
                        font-weight: bold;
                    }
                    QPushButton:hover {
                        background-color: #da190b;
                    }
                """)
            else:
                self.blocking_btn.setText("🔓 Blocking: INACTIVE")
                self.blocking_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #4CAF50;
                        color: white;
                        border: none;
                        padding: 8px;
                        border-radius: 4px;
                        font-weight: bold;
                    }
                    QPushButton:hover {
                        background-color: #45a049;
                    }
                """)
                
        except Exception as e:
            log_error(f"Error updating blocking status: {e}")
    
    def update_setting_status(self, data: Dict):
        """Update setting status displays"""
        for key, value in data.items():
            if key == "smart_mode":
                self.update_smart_mode_status(value)
    
    def toggle_smart_mode(self):
        """Toggle smart mode"""
        log_info("SMART MODE BUTTON CLICKED - Toggling smart mode")
        if self.controller:
            try:
                self.controller.toggle_smart_mode()
                log_info("Smart mode toggle sent to controller successfully")
            except Exception as e:
                log_error(f"Error toggling smart mode: {e}")
        else:
            log_error("No controller available - emitting signal")
            # Emit signal for backward compatibility
            self.smart_mode_toggled.emit()
    
    def request_scan(self):
        """Request a network scan"""
        log_info("SCAN BUTTON CLICKED - Starting network scan")
        if self.controller:
            try:
                self.controller.scan_devices()
                log_info("Scan request sent to controller successfully")
            except Exception as e:
                log_error(f"Error requesting scan: {e}")
        else:
            log_error("No controller available - emitting signal")
            # Emit signal for backward compatibility
            self.scan_requested.emit()
    
    def clear_data(self):
        """Clear all data"""
        if self.controller:
            try:
                self.controller.clear_devices()
                log_info("Data cleared")
            except Exception as e:
                log_error(f"Error clearing data: {e}")
        else:
            # Emit signal for backward compatibility
            self.clear_data_requested.emit()
    
    def start_status_updates(self):
        """Start periodic status updates"""
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_status)
        self.update_timer.start(5000)  # Update every 5 seconds (much faster updates)
    
    def update_status(self):
        """Update status information"""
        if self.controller:
            # Update network info if not already set
            network_info = self.controller.get_network_info()
            if network_info:
                self.update_network_info(network_info)
            
            # Update device count
            devices = self.controller.get_devices()
            self.update_device_count(len(devices))
            
            # Update smart mode status
            smart_status = self.controller.get_smart_mode_status()
            if smart_status:
                self.update_smart_mode_status(smart_status.get("enabled", False))
    
    def get_smart_mode_status(self) -> bool:
        """Get current smart mode status"""
        return self.smart_mode_active
    
    def get_scan_status(self) -> bool:
        """Get current scan status"""
        return self.scanning
    
    def get_blocking_status(self) -> bool:
        """Get current blocking status"""
        return self.blocking_active
    
    def get_device_count(self) -> int:
        """Get current device count"""
        return self.device_count
    
    def stop_updates(self):
        """Stop status updates"""
        if self.update_timer:
            self.update_timer.stop()
    
    def set_network_info(self, network_info: Dict):
        """Set network information manually"""
        self.update_network_info(network_info)
    
    def set_smart_mode(self, enabled: bool):
        """Set smart mode status"""
        self.update_smart_mode_status(enabled)
    
    def set_scan_status(self, in_progress: bool):
        """Set scan status"""
        self.update_scan_status(in_progress)
    
    def set_blocking_status(self, ip: str, blocked: bool):
        """Set blocking status"""
        self.update_blocking_status({"ip": ip, "blocked": blocked})
    
    # New lagswitch functionality methods
    def request_quick_scan(self):
        """Request a quick network scan"""
        if self.controller:
            try:
                self.controller.scan_devices(quick=True)
                log_info("Quick scan requested")
            except Exception as e:
                log_error(f"Error requesting quick scan: {e}")
        else:
            # Emit signal for backward compatibility
            self.quick_scan_requested.emit()
    
    def request_mass_block(self):
        """Request mass block of all non-local devices"""
        if self.controller:
            try:
                devices = self.controller.get_devices()
                blocked_count = 0
                for device in devices:
                    if not device.local and not device.blocked:
                        self.controller.toggle_lag(device.ip)
                        blocked_count += 1
                log_info(f"Mass blocked {blocked_count} devices")
            except Exception as e:
                log_error(f"Error requesting mass block: {e}")
        else:
            # Emit signal for backward compatibility
            self.mass_block_requested.emit()
    
    def request_mass_unblock(self):
        """Request mass unblock of all devices"""
        if self.controller:
            try:
                devices = self.controller.get_devices()
                unblocked_count = 0
                for device in devices:
                    if device.blocked:
                        self.controller.toggle_lag(device.ip)
                        unblocked_count += 1
                log_info(f"Mass unblocked {unblocked_count} devices")
            except Exception as e:
                log_error(f"Error requesting mass unblock: {e}")
        else:
            # Emit signal for backward compatibility
            self.mass_unblock_requested.emit()
    
    def request_search(self):
        """Request search operation"""
        try:
            self.search_requested.emit()
            log_info("Search requested from sidebar")
        except Exception as e:
            log_error(f"Error requesting search: {e}")
