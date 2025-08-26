# app/gui/sidebar.py

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QPushButton, QLabel, 
                             QFrame, QHBoxLayout, QProgressBar, QGroupBox, QSizePolicy)
from PyQt6.QtCore import pyqtSignal, QTimer, Qt, QSize
from PyQt6.QtGui import QFont, QPalette, QColor
from typing import Dict, Optional
from app.logs.logger import log_info, log_error

# Global instance tracking to prevent duplicates
_sidebar_instances = set()

class Sidebar(QWidget):
    """Enhanced sidebar with status indicators and controls"""
    
    # Signals
    smart_mode_toggled = pyqtSignal()
    settings_requested = pyqtSignal()
    scan_requested = pyqtSignal()
    clear_data_requested = pyqtSignal()
    quick_scan_requested = pyqtSignal()
    search_requested = pyqtSignal()
    mass_block_requested = pyqtSignal()
    mass_unblock_requested = pyqtSignal()
    
    def __init__(self, controller=None):
        super().__init__()
        
        # Check if this instance already exists to prevent duplicates
        if id(self) in _sidebar_instances:
            log_info("Sidebar instance already exists, preventing duplicate initialization")
            return
        
        # Add this instance to tracking set
        _sidebar_instances.add(id(self))
        
        self.controller = controller
        self.smart_mode_active = False
        self.scanning = False
        self.blocking_active = False
        self.device_count = 0
        self.update_timer = None
        
        # Prevent multiple initializations within the same instance
        if hasattr(self, '_initialized'):
            log_info("Sidebar already initialized, skipping duplicate setup")
            return
        self._initialized = True
        
        # Add duplicate prevention for updates
        self._last_network_info = None
        self._last_device_count = None
        self._last_smart_mode = None
        self._last_blocking_status = None
        self._updating = False
        
        # Set responsive sizing with better integration
        self.setMinimumWidth(200)
        self.setMaximumWidth(500)  # Increased maximum for better responsiveness
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        
        # Store preferred width for responsive behavior
        self._preferred_width = 250  # Default preferred width
        
        # Set unique object name for proper identification
        self.setObjectName("main_sidebar")
        
        log_info("Initializing sidebar with cohesive system integration")
        self.init_ui()
        self.start_status_updates()
    
    def init_ui(self):
        """Initialize the user interface with improved organization and readability"""
        layout = QVBoxLayout()
        layout.setContentsMargins(8, 8, 8, 8)  # Reduced margins for compact layout
        layout.setSpacing(8)  # Reduced spacing for better organization
        
        # Apply cleaner, more readable styling
        self.setStyleSheet("""
            QWidget {
                background-color: #1e1e1e;
                color: #ffffff;
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 10px;
            }
            QGroupBox {
                font-weight: bold;
                font-size: 11px;
                border: 1px solid #444444;
                border-radius: 6px;
                margin-top: 8px;
                padding: 8px;
                background-color: #2a2a2a;
                color: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 5px 0 5px;
                color: #ffffff;
                font-size: 11px;
                font-weight: bold;
            }
            QLabel {
                color: #ffffff;
                font-size: 10px;
                padding: 2px;
                margin: 1px;
            }
            QPushButton {
                background-color: #3a3a3a;
                color: #ffffff;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 6px 8px;
                font-weight: bold;
                font-size: 10px;
                min-height: 18px;
                max-height: 28px;
            }
            QPushButton:hover {
                background-color: #4a4a4a;
                border-color: #666666;
            }
            QPushButton:pressed {
                background-color: #2a2a2a;
            }
        """)
        
        # Compact title with improved styling
        title_label = QLabel("⚡ DUPEZ ⚡")
        title_label.setObjectName("title_label")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("""
            QLabel {
                font-size: 14pt;
                font-weight: bold;
                color: #00ffff;
                border: 2px solid #00ffff;
                padding: 8px;
                background-color: #1a1a1a;
                border-radius: 8px;
                margin: 2px;
            }
        """)
        layout.addWidget(title_label)
        
        # Network Info Group
        network_group = QGroupBox("🌐 NETWORK STATUS")
        network_layout = QVBoxLayout()
        
        # Compact network information display
        self.network_info_label = QLabel("Initializing network...")
        self.network_info_label.setObjectName("network_info")
        self.network_info_label.setWordWrap(True)
        self.network_info_label.setStyleSheet("""
            QLabel {
                color: #ffffff;
                font-weight: bold;
                font-size: 9px;
                padding: 4px;
                background-color: #3a3a3a;
                border-radius: 4px;
                border: 1px solid #555555;
                min-height: 25px;
                max-height: 60px;
            }
        """)
        network_layout.addWidget(self.network_info_label)
        
        network_group.setLayout(network_layout)
        layout.addWidget(network_group)
        
        # Status Group
        status_group = QGroupBox("SYSTEM STATUS")
        status_layout = QVBoxLayout()
        
        # Compact, organized status displays
        self.device_count_label = QLabel("📱 Devices: 0")
        self.device_count_label.setObjectName("device_count")
        self.device_count_label.setStyleSheet("""
            QLabel {
                color: #ffffff;
                font-weight: bold;
                font-size: 10px;
                padding: 4px 6px;
                background-color: #3a3a3a;
                border-radius: 4px;
                border: 1px solid #555555;
                margin: 1px;
            }
        """)
        status_layout.addWidget(self.device_count_label)
        
        # Smart mode status
        self.smart_mode_status = QLabel("🧠 Smart Mode: OFF")
        self.smart_mode_status.setObjectName("status_label")
        self.smart_mode_status.setStyleSheet("""
            QLabel {
                color: #ff6b6b;
                font-weight: bold;
                font-size: 10px;
                padding: 4px 6px;
                background-color: #3a3a3a;
                border-radius: 4px;
                border: 1px solid #555555;
                margin: 1px;
            }
        """)
        status_layout.addWidget(self.smart_mode_status)
        
        # Blocking status
        self.blocking_status = QLabel("🔒 Blocking: None")
        self.blocking_status.setObjectName("status_label")
        self.blocking_status.setStyleSheet("""
            QLabel {
                color: #4ecdc4;
                font-weight: bold;
                font-size: 10px;
                padding: 4px 6px;
                background-color: #3a3a3a;
                border-radius: 4px;
                border: 1px solid #555555;
                margin: 1px;
            }
        """)
        status_layout.addWidget(self.blocking_status)
        
        # Scan status
        self.scan_status = QLabel("🔍 Scan: Ready")
        self.scan_status.setObjectName("status_label")
        self.scan_status.setStyleSheet("""
            QLabel {
                color: #95e1d3;
                font-weight: bold;
                font-size: 10px;
                padding: 4px 6px;
                background-color: #3a3a3a;
                border-radius: 4px;
                border: 1px solid #555555;
                margin: 1px;
            }
        """)
        status_layout.addWidget(self.scan_status)
        
        # Traffic display removed for optimization
        
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)
        
        # Controls Group
        controls_group = QGroupBox("🎛️ LAGSWITCH CONTROLS")
        controls_group.setVisible(True)  # Ensure visibility
        controls_layout = QVBoxLayout()
        
        # Compact, organized control buttons
        self.smart_mode_btn = QPushButton("🧠 Smart Mode")
        self.smart_mode_btn.setObjectName("smart_mode_btn")
        self.smart_mode_btn.setCheckable(True)
        self.smart_mode_btn.setMaximumHeight(26)
        self.smart_mode_btn.clicked.connect(self.toggle_smart_mode)
        controls_layout.addWidget(self.smart_mode_btn)
        
        # Scan button
        self.scan_btn = QPushButton("🔍 Scan Network")
        self.scan_btn.setObjectName("scan_btn")
        self.scan_btn.setMaximumHeight(26)
        self.scan_btn.clicked.connect(self.request_scan)
        controls_layout.addWidget(self.scan_btn)
        
        # Quick scan button
        self.quick_scan_btn = QPushButton("⚡ Quick Scan")
        self.quick_scan_btn.setObjectName("scan_btn")
        self.quick_scan_btn.setMaximumHeight(26)
        self.quick_scan_btn.clicked.connect(self.request_quick_scan)
        controls_layout.addWidget(self.quick_scan_btn)
        
        # PS5 restoration button
        self.ps5_restore_btn = QPushButton("🎮 Restore PS5")
        self.ps5_restore_btn.setObjectName("block_btn")
        self.ps5_restore_btn.setMaximumHeight(26)
        self.ps5_restore_btn.setStyleSheet("""
            QPushButton {
                background-color: #ff6b6b;
                color: #ffffff;
                font-weight: bold;
                border: 1px solid #ff5252;
            }
            QPushButton:hover {
                background-color: #ff5252;
                border-color: #ff1744;
            }
        """)
        self.ps5_restore_btn.clicked.connect(self.restore_ps5_internet)
        controls_layout.addWidget(self.ps5_restore_btn)
        
        # Clear data button
        self.clear_btn = QPushButton("🗑️ Clear Data")
        self.clear_btn.setObjectName("block_btn")
        self.clear_btn.setMaximumHeight(26)
        self.clear_btn.clicked.connect(self.clear_data)
        controls_layout.addWidget(self.clear_btn)
        
        # Settings button
        self.settings_btn = QPushButton("⚙️ Settings")
        self.settings_btn.setObjectName("refresh_btn")
        self.settings_btn.setMaximumHeight(26)
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
        
        # Set object name for styling (already set in __init__)
        # self.setObjectName("main_sidebar")
    
    def set_controller(self, controller):
        """Set the controller and connect to its events"""
        self.controller = controller
        if controller:
            # Connect to controller state changes
            controller.state.add_observer(self.on_controller_state_change)
    
    def setPreferredWidth(self, width):
        """Set the preferred width for responsive sizing"""
        try:
            # Ensure width is within bounds
            if width < 200:
                width = 200
            elif width > 500:
                width = 500
            
            self._preferred_width = width
            
            # Update the widget's size hint
            self.updateGeometry()
            
            # Force a resize to apply the new preferred width
            self.resize(width, self.height())
            
            log_info(f"Sidebar preferred width set to {width}px")
            
        except Exception as e:
            log_error(f"Error setting sidebar preferred width: {e}")
    
    def sizeHint(self):
        """Return the preferred size hint for responsive sizing"""
        try:
            # Return size hint based on preferred width
            return QSize(self._preferred_width, super().sizeHint().height())
        except Exception as e:
            log_error(f"Error in sidebar sizeHint: {e}")
            return super().sizeHint()
    
    def on_controller_state_change(self, event: str, data):
        """Handle controller state changes"""
        try:
            if event == "devices_updated":
                QTimer.singleShot(0, lambda: self.update_device_count(len(data)))
            elif event == "scan_status_changed":
                QTimer.singleShot(0, lambda: self.update_scan_status(data))
            elif event == "blocking_toggled":
                # Handle new blocking data structure
                if isinstance(data, dict):
                    # New format with detailed blocking info
                    blocked = data.get("blocked", False)
                    QTimer.singleShot(0, lambda: self.update_blocking_status(blocked))
                else:
                    # Legacy format - boolean only
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
                interface_name = network_info['interface']
                # Add Ethernet support indicator
                if 'ethernet' in interface_name.lower() or 'eth' in interface_name.lower():
                    info_text += f"🔌 Interface: {interface_name} (Ethernet)<br>"
                elif 'wifi' in interface_name.lower() or 'wlan' in interface_name.lower():
                    info_text += f"📶 Interface: {interface_name} (WiFi)<br>"
                else:
                    info_text += f"📡 Interface: {interface_name}<br>"
            
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
            
            # Add multi-interface support indicator
            info_text += f"🔌 <b>Multi-Interface Support:</b> Ethernet + WiFi<br>"
            
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
                        border: 2px solid #45a049;
                        padding: 10px;
                        border-radius: 6px;
                        font-weight: bold;
                        font-size: 11px;
                        min-height: 25px;
                    }
                    QPushButton:hover {
                        background-color: #45a049;
                        border-color: #4CAF50;
                    }
                """)
            else:
                self.smart_mode_btn.setText("🧠 Smart Mode: OFF")
                self.smart_mode_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #f44336;
                        color: white;
                        border: 2px solid #d32f2f;
                        padding: 10px;
                        border-radius: 6px;
                        font-weight: bold;
                        font-size: 11px;
                        min-height: 25px;
                    }
                    QPushButton:hover {
                        background-color: #da190b;
                        border-color: #f44336;
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
                        border: 2px solid #f57c00;
                        padding: 10px;
                        border-radius: 6px;
                        font-weight: bold;
                        font-size: 11px;
                        min-height: 25px;
                    }
                """)
            else:
                self.scan_btn.setText("🔍 Scan Network")
                self.scan_btn.setEnabled(True)
                self.scan_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #2196F3;
                        color: white;
                        border: 2px solid #1976D2;
                        padding: 10px;
                        border-radius: 6px;
                        font-weight: bold;
                        font-size: 11px;
                        min-height: 25px;
                    }
                    QPushButton:hover {
                        background-color: #1976D2;
                        border-color: #2196F3;
                    }
                """)
                
        except Exception as e:
            log_error(f"Error updating scan status: {e}")
    
    def update_blocking_status(self, blocking: bool):
        """Update blocking status display with enhanced information"""
        try:
            self.blocking_active = blocking
            
            if self.controller:
                # Get current blocking statistics
                devices = self.controller.get_devices()
                blocked_devices = [d for d in devices if d.blocked]
                total_devices = len(devices)
                blocked_count = len(blocked_devices)
                
                if blocked_count == 0:
                    self.blocking_status.setText("🔒 BLOCKING: NONE")
                    self.blocking_status.setStyleSheet("""
                        QLabel {
                            color: #4caf50;
                            font-weight: bold;
                            padding: 8px;
                            background-color: #1b5e20;
                            border-radius: 6px;
                            border: 1px solid #4caf50;
                            font-size: 12px;
                        }
                    """)
                else:
                    block_percentage = (blocked_count / total_devices * 100) if total_devices > 0 else 0
                    self.blocking_status.setText(f"🚫 BLOCKING: {blocked_count}/{total_devices} ({block_percentage:.1f}%)")
                    
                    # Color code based on blocking intensity
                    if block_percentage < 25:
                        color = "#ff9800"  # Orange for light blocking
                        bg_color = "#e65100"
                    elif block_percentage < 50:
                        color = "#ff5722"  # Deep orange for moderate blocking
                        bg_color = "#bf360c"
                    else:
                        color = "#f44336"  # Red for heavy blocking
                        bg_color = "#b71c1c"
                    
                    self.blocking_status.setStyleSheet(f"""
                        QLabel {{
                            color: {color};
                            font-weight: bold;
                            padding: 8px;
                            background-color: {bg_color};
                            border-radius: 6px;
                            border: 1px solid {color};
                            font-size: 12px;
                        }}
                    """)
            else:
                # Fallback when no controller
                if blocking:
                    self.blocking_status.setText("🚫 BLOCKING: ACTIVE")
                    self.blocking_status.setStyleSheet("""
                        QLabel {
                            color: #f44336;
                            font-weight: bold;
                            padding: 8px;
                            background-color: #b71c1c;
                            border-radius: 6px;
                            border: 1px solid #f44336;
                            font-size: 12px;
                        }
                    """)
                else:
                    self.blocking_status.setText("🔒 BLOCKING: NONE")
                    self.blocking_status.setStyleSheet("""
                        QLabel {
                            color: #4caf50;
                            font-weight: bold;
                            padding: 8px;
                            background-color: #1b5e20;
                            border-radius: 6px;
                            border: 1px solid #4caf50;
                            font-size: 12px;
                        }
                    """)
                    
        except Exception as e:
            log_error(f"Error updating blocking status: {e}")
            self.blocking_status.setText("�� BLOCKING: ERROR")
    
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
        """Update status information with REAL system data"""
        if self.controller:
            try:
                # Update network info with real data
                network_info = self.controller.get_network_info()
                if network_info:
                    self.update_network_info(network_info)
                
                # Update device count with real devices
                devices = self.controller.get_devices()
                self.update_device_count(len(devices))
                
                # Update smart mode status with real status
                try:
                    smart_status = self.controller.get_smart_mode_status()
                    if smart_status and isinstance(smart_status, dict):
                        enabled = smart_status.get("enabled", False)
                        self.update_smart_mode_status(enabled)
                        if enabled:
                            self.smart_mode_status.setText("🧠 SMART MODE: ON")
                            self.smart_mode_status.setStyleSheet("""
            QLabel {
                color: #00ff00;
                font-weight: bold;
                font-size: 12px;
                padding: 8px;
                background-color: #1b5e20;
                border-radius: 6px;
                border: 1px solid #00ff00;
            }
        """)
                        else:
                            self.smart_mode_status.setText("🧠 SMART MODE: OFF")
                            self.smart_mode_status.setStyleSheet("""
            QLabel {
                color: #ff0000;
                font-weight: bold;
                font-size: 12px;
                padding: 8px;
                background-color: #b71c1c;
                border-radius: 6px;
                border: 1px solid #ff0000;
            }
        """)
                    else:
                        self.smart_mode_status.setText("🧠 SMART MODE: ERROR")
                        self.smart_mode_status.setStyleSheet("""
            QLabel {
                color: #ff8800;
                font-weight: bold;
                font-size: 12px;
                padding: 8px;
                background-color: #e65100;
                border-radius: 6px;
                border: 1px solid #ff8800;
            }
        """)
                except Exception as e:
                    log_error(f"Smart mode status error: {e}")
                    self.smart_mode_status.setText("🧠 SMART MODE: ERROR")
                    self.smart_mode_status.setStyleSheet("""
            QLabel {
                color: #ff8800;
                font-weight: bold;
                font-size: 12px;
                padding: 8px;
                background-color: #e65100;
                border-radius: 6px;
                border: 1px solid #ff8800;
            }
        """)
                
                # Update blocking status with real blocked devices
                try:
                    blocked_devices = self.controller.get_blocked_devices()
                    if blocked_devices and len(blocked_devices) > 0:
                        self.update_blocking_status(True)
                        self.blocking_status.setText(f"🔒 BLOCKING: {len(blocked_devices)} DEVICES")
                        self.blocking_status.setStyleSheet("""
            QLabel {
                color: #ff0000;
                font-weight: bold;
                font-size: 12px;
                padding: 8px;
                background-color: #b71c1c;
                border-radius: 6px;
                border: 1px solid #ff0000;
            }
        """)
                    else:
                        self.update_blocking_status(False)
                        self.blocking_status.setText("🔒 BLOCKING: NONE")
                        self.blocking_status.setStyleSheet("""
            QLabel {
                color: #00ff00;
                font-weight: bold;
                font-size: 12px;
                padding: 8px;
                background-color: #1b5e20;
                border-radius: 6px;
                border: 1px solid #00ff00;
            }
        """)
                except Exception as e:
                    log_error(f"Blocking status error: {e}")
                    self.blocking_status.setText("🔒 BLOCKING: ERROR")
                    self.blocking_status.setStyleSheet("""
            QLabel {
                color: #ff8800;
                font-weight: bold;
                font-size: 12px;
                padding: 8px;
                background-color: #e65100;
                border-radius: 6px;
                border: 1px solid #ff8800;
            }
        """)
                
                # Traffic status removed for optimization
                
                # Update scan status
                try:
                    if self.controller.is_scanning():
                        self.update_scan_status(True)
                        self.scan_status.setText("🔍 SCAN: IN PROGRESS")
                        self.scan_status.setStyleSheet("""
            QLabel {
                color: #ffff00;
                font-weight: bold;
                font-size: 12px;
                padding: 8px;
                background-color: #f57f17;
                border-radius: 6px;
                border: 1px solid #ffff00;
            }
        """)
                    else:
                        self.update_scan_status(False)
                        self.scan_status.setText("🔍 SCAN: READY")
                        self.scan_status.setStyleSheet("""
            QLabel {
                color: #00ff00;
                font-weight: bold;
                font-size: 12px;
                padding: 8px;
                background-color: #1b5e20;
                border-radius: 6px;
                border: 1px solid #00ff00;
            }
        """)
                except Exception as e:
                    log_error(f"Scan status error: {e}")
                    self.scan_status.setText("🔍 SCAN: ERROR")
                    self.scan_status.setStyleSheet("""
            QLabel {
                color: #ff8800;
                font-weight: bold;
                font-size: 12px;
                padding: 8px;
                background-color: #e65100;
                border-radius: 6px;
                border: 1px solid #ff8800;
            }
        """)
                    
            except Exception as e:
                log_error(f"Error updating status: {e}")
    
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
            self.update_timer.deleteLater()
            self.update_timer = None
    
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
    
    def restore_ps5_internet(self):
        """Restore PS5 internet access"""
        try:
            from PyQt6.QtWidgets import QMessageBox
            
            # Show confirmation dialog
            reply = QMessageBox.question(
                None, "PS5 Internet Restoration",
                "This will restore your PS5's internet access by clearing all PulseDrop blocks.\n\n"
                "Do you want to continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                log_info("PS5 internet restoration requested")
                
                # Run the restoration script
                import subprocess
                import sys
                
                try:
                    # Run the restoration script
                    result = subprocess.run(
                        [sys.executable, "scripts/network/restore_ps5_internet.py"],
                        capture_output=True,
                        text=True,
                        timeout=60
                    )
                    
                    if result.returncode == 0:
                        QMessageBox.information(
                            None, "PS5 Restoration Complete",
                            "✅ PS5 internet access has been restored!\n\n"
                            "Your PS5 should now have internet access.\n"
                            "If it still doesn't work, try restarting your PS5."
                        )
                        log_info("PS5 internet restoration completed successfully")
                    else:
                        QMessageBox.warning(
                            None, "PS5 Restoration Warning",
                            "⚠️ PS5 restoration completed with warnings.\n\n"
                            "Some steps may have failed. Check the console output for details.\n"
                            "You may need to run the script as administrator."
                        )
                        log_error(f"PS5 restoration failed: {result.stderr}")
                        
                except subprocess.TimeoutExpired:
                    QMessageBox.warning(
                        None, "PS5 Restoration Timeout",
                        "⏰ PS5 restoration timed out.\n\n"
                        "The process took too long to complete.\n"
                        "Try running the script manually as administrator."
                    )
                    log_error("PS5 restoration timed out")
                    
                except Exception as e:
                    QMessageBox.critical(
                        None, "PS5 Restoration Error",
                        f"💥 PS5 restoration failed: {e}\n\n"
                        "Try running the script manually as administrator."
                    )
                    log_error(f"PS5 restoration error: {e}")
                    
        except Exception as e:
            log_error(f"Error in PS5 restoration: {e}")
            QMessageBox.critical(None, "Error", f"Failed to restore PS5 internet: {e}")

    @classmethod
    def get_instance_count(cls):
        """Get the number of active sidebar instances"""
        return len(_sidebar_instances)
    
    @classmethod
    def clear_all_instances(cls):
        """Clear all sidebar instances (for testing/debugging)"""
        global _sidebar_instances
        _sidebar_instances.clear()
        log_info("All sidebar instances cleared")
    
    def is_duplicate(self):
        """Check if this sidebar instance is a duplicate"""
        return len(_sidebar_instances) > 1
    
    def get_system_integration_status(self):
        """Get the integration status with the system"""
        return {
            'instance_id': id(self),
            'total_instances': len(_sidebar_instances),
            'is_duplicate': self.is_duplicate(),
            'has_controller': self.controller is not None,
            'is_initialized': hasattr(self, '_initialized'),
            'object_name': self.objectName(),
            'responsive_sizing': {
                'current_width': self.width(),
                'preferred_width': self._preferred_width,
                'minimum_width': self.minimumWidth(),
                'maximum_width': self.maximumWidth(),
                'size_policy': str(self.sizePolicy().horizontalPolicy())
            }
        }
    
    def cleanup(self):
        """Clean up resources to prevent memory leaks and rendering issues"""
        try:
            self.stop_updates()
            if hasattr(self, '_initialized'):
                delattr(self, '_initialized')
            
            # Clear duplicate prevention cache
            self._last_network_info = None
            self._last_device_count = None
            self._last_smart_mode = None
            self._last_blocking_status = None
            self._updating = False
            
            # Remove from global instance tracking
            if id(self) in _sidebar_instances:
                _sidebar_instances.remove(id(self))
                log_info("Sidebar instance removed from tracking")
            
        except Exception as e:
            log_error(f"Error cleaning up sidebar: {e}")
    
    def closeEvent(self, event):
        """Handle close event to ensure proper cleanup"""
        try:
            self.cleanup()
            event.accept()
        except Exception as e:
            log_error(f"Error in sidebar close event: {e}")
            event.accept()
