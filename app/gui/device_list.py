# app/gui/device_list.py

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QListWidget, QPushButton, 
                             QLabel, QHBoxLayout, QListWidgetItem, QFrame, 
                             QProgressBar, QMenu, QMessageBox, QLineEdit, QComboBox)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QIcon, QAction, QColor
from typing import List, Dict, Optional
from app.logs.logger import log_info, log_error
from app.utils.helpers import format_bytes

class DeviceList(QWidget):
    """Enhanced device list widget with real-time updates and better UI"""
    
    # Signals
    device_selected = pyqtSignal(str)  # Emit device IP when selected
    device_blocked = pyqtSignal(str, bool)  # Emit device IP and blocked status
    
    def __init__(self, controller=None):
        super().__init__()
        self.controller = controller
        self.devices = []
        self.selected_device = None
        self.update_timer = None
        self.scan_in_progress = False
        self.filtered_devices = []  # Store filtered devices
        self.search_text = ""  # Store current search text
        self.search_field = "all"  # Store current search field
        
        self.init_ui()
        self.start_auto_updates()
    
    def init_ui(self):
        """Initialize the user interface with lagswitch styling"""
        layout = QVBoxLayout()
        
        # Header with lagswitch controls
        header_layout = QHBoxLayout()
        self.title_label = QLabel("🎯 TARGET DEVICES")
        self.title_label.setObjectName("title_label")
        self.title_label.setStyleSheet("""
            QLabel {
                font-size: 14pt;
                font-weight: bold;
                color: #00ffff;
                border: 2px solid #00ffff;
                padding: 6px;
                background-color: #1a1a1a;
            }
        """)
        header_layout.addWidget(self.title_label)
        
        # Search functionality
        search_layout = QHBoxLayout()
        
        # Search field dropdown
        self.search_field_combo = QComboBox()
        self.search_field_combo.setObjectName("search_field_combo")
        self.search_field_combo.addItems(["All Fields", "IP Address", "Hostname", "Vendor", "MAC Address"])
        self.search_field_combo.currentTextChanged.connect(self.on_search_field_changed)
        search_layout.addWidget(QLabel("🔍 Search:"))
        search_layout.addWidget(self.search_field_combo)
        
        # Search input
        self.search_input = QLineEdit()
        self.search_input.setObjectName("search_input")
        self.search_input.setPlaceholderText("Enter search term...")
        self.search_input.textChanged.connect(self.on_search_text_changed)
        self.search_input.setStyleSheet("""
            QLineEdit {
                background-color: #1a1a1a;
                color: #00ff00;
                border: 2px solid #00ff00;
                padding: 6px;
                font-family: 'Courier New', monospace;
                font-size: 12px;
            }
            QLineEdit:focus {
                border: 2px solid #00ffff;
            }
        """)
        search_layout.addWidget(self.search_input)
        
        # Clear search button
        self.clear_search_btn = QPushButton("❌")
        self.clear_search_btn.setObjectName("clear_search_btn")
        self.clear_search_btn.setToolTip("Clear search")
        self.clear_search_btn.clicked.connect(self.clear_search)
        self.clear_search_btn.setStyleSheet("""
            QPushButton {
                background-color: #ff4444;
                color: white;
                border: none;
                padding: 6px;
                border-radius: 3px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #cc3333;
            }
        """)
        search_layout.addWidget(self.clear_search_btn)
        
        header_layout.addLayout(search_layout)
        
        # Lagswitch control buttons
        self.hide_sensitive_btn = QPushButton("🔒 HIDE SENSITIVE")
        self.hide_sensitive_btn.setObjectName("block_btn")
        self.hide_sensitive_btn.setCheckable(True)
        self.hide_sensitive_btn.clicked.connect(self.toggle_sensitive_info)
        header_layout.addWidget(self.hide_sensitive_btn)
        
        self.encrypt_data_btn = QPushButton("🔐 ENCRYPT DATA")
        self.encrypt_data_btn.setObjectName("scan_btn")
        self.encrypt_data_btn.setCheckable(True)
        self.encrypt_data_btn.clicked.connect(self.toggle_data_encryption)
        header_layout.addWidget(self.encrypt_data_btn)
        
        # Quick action buttons
        self.select_all_btn = QPushButton("☑️ SELECT ALL")
        self.select_all_btn.setObjectName("refresh_btn")
        self.select_all_btn.clicked.connect(self.select_all_devices)
        header_layout.addWidget(self.select_all_btn)
        
        self.block_selected_btn = QPushButton("🚫 BLOCK SELECTED")
        self.block_selected_btn.setObjectName("block_btn")
        self.block_selected_btn.clicked.connect(self.block_selected_devices)
        header_layout.addWidget(self.block_selected_btn)
        
        self.status_label = QLabel("READY")
        self.status_label.setObjectName("status_label")
        header_layout.addStretch()
        header_layout.addWidget(self.status_label)
        
        layout.addLayout(header_layout)
        
        # Device list with enhanced header
        self.device_list = QListWidget()
        self.device_list.setAlternatingRowColors(True)
        self.device_list.itemClicked.connect(self.on_device_selected)
        self.device_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.device_list.customContextMenuRequested.connect(self.show_context_menu)
        
        # Enhanced header with better spacing and readability
        header_text = "Status  Type  Device  IP Address        |  MAC Address         |  Vendor               |  Hostname         |  Last Seen"
        header_item = QListWidgetItem(header_text)
        header_item.setBackground(QColor(240, 240, 240))  # Light gray background
        header_item.setFlags(header_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)  # Make header non-selectable
        self.device_list.addItem(header_item)
        
        layout.addWidget(self.device_list)
        
        # Progress bar for scanning
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        # Enhanced action buttons with better styling
        self.refresh_btn = QPushButton("🔄 Refresh")
        self.refresh_btn.setObjectName("refresh_btn")
        self.refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #009688;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #00796B;
            }
            QPushButton:pressed {
                background-color: #004D40;
            }
        """)
        self.refresh_btn.clicked.connect(self.refresh_devices)
        button_layout.addWidget(self.refresh_btn)
        
        self.block_btn = QPushButton("🚫 Block Selected")
        self.block_btn.setObjectName("block_btn")
        self.block_btn.setStyleSheet("""
            QPushButton {
                background-color: #F44336;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #D32F2F;
            }
            QPushButton:pressed {
                background-color: #B71C1C;
            }
            QPushButton:disabled {
                background-color: #BDBDBD;
                color: #757575;
            }
        """)
        self.block_btn.clicked.connect(self.toggle_selected_device_blocking)
        self.block_btn.setEnabled(False)
        button_layout.addWidget(self.block_btn)
        
        self.auto_refresh_btn = QPushButton("⏰ Auto Refresh")
        self.auto_refresh_btn.setCheckable(True)
        self.auto_refresh_btn.setChecked(True)
        self.auto_refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:checked {
                background-color: #4CAF50;
            }
            QPushButton:hover {
                background-color: #F57C00;
            }
            QPushButton:checked:hover {
                background-color: #45a049;
            }
        """)
        self.auto_refresh_btn.clicked.connect(self.toggle_auto_refresh)
        button_layout.addWidget(self.auto_refresh_btn)
        
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
    
    def set_controller(self, controller):
        """Set the controller and connect to its events"""
        self.controller = controller
        if controller:
            # Connect to controller state changes
            controller.state.add_observer(self.on_controller_state_change)
            # Trigger initial device list update
            devices = controller.get_devices()
            if devices:
                self.update_device_list(devices)
    
    def on_controller_state_change(self, event: str, data):
        """Handle controller state changes"""
        try:
            if event == "devices_updated":
                # Ensure UI updates happen on main thread
                QTimer.singleShot(0, lambda: self.update_device_list(data))
            elif event == "device_selected":
                QTimer.singleShot(0, lambda: self.highlight_device(data))
            elif event == "scan_status_changed":
                QTimer.singleShot(0, lambda: self.update_scan_status(data))
            elif event == "blocking_toggled":
                QTimer.singleShot(0, lambda: self.update_device_blocking_status(data))
        except Exception as e:
            log_error(f"Error in controller state change: {e}")
    
    def update_device_list(self, devices):
        """Update the device list with new data"""
        try:
            self.devices = devices or []
            
            # Apply current search filter if any
            if self.search_text:
                self.apply_search_filter()
            else:
                # Clear and rebuild list normally
                self.device_list.clear()
                
                # Add enhanced header row back with better readability
                header_text = "Status  Type  Device  IP Address        |  MAC Address         |  Vendor               |  Hostname         |  Last Seen"
                header_item = QListWidgetItem(header_text)
                header_item.setBackground(QColor(240, 240, 240))  # Light gray background
                header_item.setFlags(header_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)  # Make header non-selectable
                self.device_list.addItem(header_item)
                
                if devices:
                    for device in devices:
                        item = self.create_device_item(device)
                        self.device_list.addItem(item)
                    
                    self.status_label.setText(f"{len(devices)} devices found")
                    log_info(f"Updated device list: {len(devices)} devices")
                else:
                    self.status_label.setText("No devices found")
                    log_info("Device list cleared")
            
        except Exception as e:
            log_error(f"Error updating device list: {e}")
            self.status_label.setText("Error loading devices")
    
    def create_device_item(self, device) -> QListWidgetItem:
        """Create a detailed device list item with enhanced information"""
        # Create main item
        item = QListWidgetItem()
        
        # Enhanced device information display
        status_icon = "🟢" if not device.blocked else "🔴"
        vendor_icon = self._get_vendor_icon(device.vendor)
        
        # More detailed device information
        device_text = f"{status_icon} {device.ip}\n"
        device_text += f"   {vendor_icon} {device.vendor}\n"
        
        if device.hostname and device.hostname != "Unknown":
            device_text += f"   📱 {device.hostname}\n"
        
        if device.mac and device.mac != "Unknown":
            # Show only first 8 characters of MAC for privacy
            mac_display = device.mac[:8] + "..." if len(device.mac) > 8 else device.mac
            device_text += f"   🔗 {mac_display}\n"
        
        device_text += f"   📊 Traffic: {self._format_traffic(device.traffic)}\n"
        device_text += f"   ⏰ Last seen: {device.last_seen}"
        
        item.setText(device_text)
        item.setData(Qt.ItemDataRole.UserRole, device.ip)
        
        # Set item properties for better styling
        item.setData(Qt.ItemDataRole.ToolTipRole, self._create_device_tooltip(device))
        
        # Color coding for different device types
        if device.local:
            item.setBackground(QColor(240, 248, 255))  # Light blue for local device
        elif "PlayStation" in device.vendor or "Xbox" in device.vendor or "Nintendo" in device.vendor:
            item.setBackground(QColor(255, 248, 220))  # Light yellow for gaming devices
        elif device.blocked:
            item.setBackground(QColor(255, 240, 240))  # Light red for blocked devices
        
        return item
    
    def _get_vendor_icon(self, vendor: str) -> str:
        """Get appropriate icon for vendor"""
        vendor_lower = vendor.lower()
        if "playstation" in vendor_lower or "sony" in vendor_lower:
            return "🎮"
        elif "xbox" in vendor_lower or "microsoft" in vendor_lower:
            return "🎮"
        elif "nintendo" in vendor_lower or "switch" in vendor_lower:
            return "🎮"
        elif "apple" in vendor_lower or "iphone" in vendor_lower or "ipad" in vendor_lower:
            return "🍎"
        elif "samsung" in vendor_lower or "android" in vendor_lower:
            return "📱"
        elif "cisco" in vendor_lower or "router" in vendor_lower:
            return "🌐"
        elif "unknown" in vendor_lower:
            return "❓"
        else:
            return "💻"
    
    def _format_traffic(self, traffic: int) -> str:
        """Format traffic data for display"""
        if traffic == 0:
            return "0 B"
        elif traffic < 1024:
            return f"{traffic} B"
        elif traffic < 1024 * 1024:
            return f"{traffic / 1024:.1f} KB"
        else:
            return f"{traffic / (1024 * 1024):.1f} MB"
    
    def _create_device_tooltip(self, device) -> str:
        """Create detailed tooltip for device"""
        tooltip = f"<b>Device Information</b><br>"
        tooltip += f"<b>IP Address:</b> {device.ip}<br>"
        tooltip += f"<b>Vendor:</b> {device.vendor}<br>"
        
        if device.hostname and device.hostname != "Unknown":
            tooltip += f"<b>Hostname:</b> {device.hostname}<br>"
        
        if device.mac and device.mac != "Unknown":
            tooltip += f"<b>MAC Address:</b> {device.mac}<br>"
        
        tooltip += f"<b>Traffic:</b> {self._format_traffic(device.traffic)}<br>"
        tooltip += f"<b>Last Seen:</b> {device.last_seen}<br>"
        tooltip += f"<b>Status:</b> {'Blocked' if device.blocked else 'Active'}<br>"
        tooltip += f"<b>Local Device:</b> {'Yes' if device.local else 'No'}"
        
        return tooltip
    
    def on_device_selected(self, item):
        """Handle device selection"""
        ip = item.data(Qt.ItemDataRole.UserRole)
        if ip:
            self.selected_device = ip
            self.block_btn.setEnabled(True)
            self.device_selected.emit(ip)
            
            if self.controller:
                self.controller.select_device(ip)
    
    def highlight_device(self, ip: str):
        """Highlight a specific device in the list"""
        for i in range(self.device_list.count()):
            item = self.device_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == ip:
                self.device_list.setCurrentItem(item)
                break
    
    def update_scan_status(self, in_progress: bool):
        """Update scan status UI"""
        self.scan_in_progress = in_progress
        self.refresh_btn.setEnabled(not in_progress)
        
        if in_progress:
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 0)  # Indeterminate progress
            self.status_label.setText("Scanning...")
        else:
            self.progress_bar.setVisible(False)
    
    def update_device_blocking_status(self, data: Dict):
        """Update device blocking status in the UI"""
        ip = data.get("ip")
        blocked = data.get("blocked")
        
        for i in range(self.device_list.count()):
            item = self.device_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == ip:
                # Update the item display
                text = item.text()
                if blocked:
                    text = text.replace("🟢", "🔴")
                    item.setBackground(QColor(255, 220, 220))  # Very light red
                else:
                    text = text.replace("🔴", "🟢")
                    item.setBackground(QColor(0, 0, 0, 0))  # Transparent
                item.setText(text)
                break
    
    def refresh_devices(self):
        """Manually refresh the device list"""
        if not self.controller:
            QMessageBox.warning(self, "Warning", "No controller available")
            return
        
        try:
            self.controller.scan_devices()
        except Exception as e:
            log_error(f"Error refreshing devices: {e}")
            QMessageBox.critical(self, "Error", f"Failed to refresh devices: {e}")
    
    def toggle_selected_device_blocking(self):
        """Toggle blocking for the selected device"""
        if not self.selected_device:
            QMessageBox.warning(self, "Warning", "No device selected")
            return
        
        if not self.controller:
            QMessageBox.warning(self, "Warning", "No controller available")
            return
        
        try:
            blocked = self.controller.toggle_lag(self.selected_device)
            status = "blocked" if blocked else "unblocked"
            log_info(f"Device {self.selected_device} {status}")
        except Exception as e:
            log_error(f"Error toggling device blocking: {e}")
            QMessageBox.critical(self, "Error", f"Failed to toggle blocking: {e}")
    
    def toggle_auto_refresh(self):
        """Toggle automatic refresh"""
        if self.auto_refresh_btn.isChecked():
            self.start_auto_updates()
        else:
            self.stop_auto_updates()
    
    def start_auto_updates(self):
        """Start automatic updates"""
        if not self.update_timer:
            self.update_timer = QTimer()
            self.update_timer.timeout.connect(self.auto_refresh)
            self.update_timer.start(30000)  # 30 seconds (much faster updates)
    
    def stop_auto_updates(self):
        """Stop automatic updates"""
        if self.update_timer:
            self.update_timer.stop()
            self.update_timer = None
    
    def auto_refresh(self):
        """Automatic refresh triggered by timer"""
        if self.controller and not self.scan_in_progress:
            # Use quick scan to avoid blocking the UI
            try:
                self.controller.scan_devices(quick=True)
            except Exception as e:
                log_error(f"Auto-refresh failed: {e}")
    
    def show_context_menu(self, position):
        """Show context menu for device list"""
        item = self.device_list.itemAt(position)
        if not item:
            return
        
        ip = item.data(Qt.ItemDataRole.UserRole)
        if not ip:
            return
        
        menu = QMenu(self)
        
        # Device info action
        info_action = QAction("📋 Device Info", self)
        info_action.triggered.connect(lambda: self.show_device_info(ip))
        menu.addAction(info_action)
        
        # Block/unblock action
        device = self.get_device_by_ip(ip)
        if device:
            if device.blocked:
                block_action = QAction("🔓 Unblock Device", self)
                block_action.triggered.connect(lambda: self.block_device(ip, False))
            else:
                block_action = QAction("🔒 Block Device", self)
                block_action.triggered.connect(lambda: self.block_device(ip, True))
            menu.addAction(block_action)
        
        # Ping action
        ping_action = QAction("🏓 Ping Device", self)
        ping_action.triggered.connect(lambda: self.ping_device(ip))
        menu.addAction(ping_action)
        
        menu.exec(self.device_list.mapToGlobal(position))
    
    def show_device_info_legacy(self, ip: str):
        """Legacy method for backward compatibility"""
        self.show_device_info(ip)
    
    def block_device(self, ip: str, block: bool):
        """Block or unblock a device"""
        if self.controller:
            try:
                # Find the device and toggle its blocking status
                device = self.get_device_by_ip(ip)
                if device:
                    device.blocked = block
                    self.controller.toggle_lag(ip)
            except Exception as e:
                log_error(f"Error blocking device {ip}: {e}")
    
    def ping_device(self, ip: str):
        """Ping a device to check connectivity"""
        try:
            from app.utils.helpers import ping_host
            success, response_time = ping_host(ip)
            
            if success:
                QMessageBox.information(self, "Ping Result", 
                                      f"Device {ip} is reachable\nResponse time: {response_time:.2f}ms")
            else:
                QMessageBox.warning(self, "Ping Result", 
                                   f"Device {ip} is not reachable")
        except Exception as e:
            log_error(f"Error pinging device {ip}: {e}")
            QMessageBox.critical(self, "Error", f"Failed to ping device: {e}")
    
    def get_device_by_ip(self, ip: str):
        """Get device object by IP address"""
        for device in self.devices:
            if device.ip == ip:
                return device
        return None
    
    def clear_devices(self):
        """Clear the device list"""
        self.device_list.clear()
        self.devices = []
        self.selected_device = None
        self.block_btn.setEnabled(False)
        self.status_label.setText("No devices")
    
    def get_selected_device(self):
        """Get the currently selected device"""
        return self.selected_device
    
    def toggle_sensitive_info(self):
        """Toggle hiding of sensitive information"""
        try:
            if self.devices:
                self.update_device_list(self.devices)
                log_info("Sensitive information toggled")
        except Exception as e:
            log_error(f"Error toggling sensitive info: {e}")
    
    def toggle_data_encryption(self):
        """Toggle data encryption for stored information"""
        try:
            if self.encrypt_data_btn.isChecked():
                log_info("Data encryption enabled")
                # TODO: Implement actual encryption
            else:
                log_info("Data encryption disabled")
        except Exception as e:
            log_error(f"Error toggling data encryption: {e}")
    
    def get_device_full_data(self, item) -> dict:
        """Get full device data from item (for security)"""
        try:
            return item.data(Qt.ItemDataRole.UserRole + 1) or {}
        except Exception as e:
            log_error(f"Error getting device full data: {e}")
            return {}
    
    def show_device_info(self, ip: str):
        """Show detailed device information with security checks"""
        try:
            # Find the item with this IP
            for i in range(self.device_list.count()):
                item = self.device_list.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == ip:
                    full_data = self.get_device_full_data(item)
                    if full_data:
                        # Check if sensitive info should be hidden
                        if hasattr(self, 'hide_sensitive_btn') and self.hide_sensitive_btn.isChecked():
                            mac_display = "***.***.***.***" if full_data.get('mac') != "Unknown" else "Unknown"
                            hostname_display = "***" if full_data.get('hostname') != "Unknown" else "Unknown"
                        else:
                            mac_display = full_data.get('mac', 'Unknown')
                            hostname_display = full_data.get('hostname', 'Unknown')
                        
                        info = f"""
Device Information:
IP Address: {full_data.get('ip', 'Unknown')}
MAC Address: {mac_display}
Vendor: {full_data.get('vendor', 'Unknown')}
Hostname: {hostname_display}
Local Device: {'Yes' if full_data.get('local', False) else 'No'}
Blocked: {'Yes' if full_data.get('blocked', False) else 'No'}
Last Seen: {full_data.get('last_seen', 'Unknown')}
                        """
                        
                        QMessageBox.information(self, "Device Info", info.strip())
                        break
        except Exception as e:
            log_error(f"Error showing device info: {e}")
            QMessageBox.critical(self, "Error", f"Failed to show device info: {e}")
    
    # New lagswitch functionality methods
    def select_all_devices(self):
        """Select all devices in the list"""
        try:
            self.device_list.selectAll()
            log_info("All devices selected")
        except Exception as e:
            log_error(f"Error selecting all devices: {e}")
    
    def block_selected_devices(self):
        """Block all selected devices"""
        try:
            selected_items = self.device_list.selectedItems()
            if not selected_items:
                QMessageBox.warning(self, "Warning", "No devices selected")
                return
            
            blocked_count = 0
            for item in selected_items:
                device_ip = item.data(Qt.ItemDataRole.UserRole)
                if device_ip and self.controller:
                    device = self.get_device_by_ip(device_ip)
                    if device and not device.local and not device.blocked:
                        self.controller.toggle_lag(device_ip)
                        blocked_count += 1
            
            if blocked_count > 0:
                self.status_label.setText(f"BLOCKED {blocked_count} DEVICES")
                log_info(f"Blocked {blocked_count} selected devices")
            else:
                self.status_label.setText("NO DEVICES BLOCKED")
        except Exception as e:
            log_error(f"Error blocking selected devices: {e}")
            QMessageBox.critical(self, "Error", f"Failed to block devices: {e}")
    
    def get_selected_devices(self):
        """Get list of selected device IPs"""
        try:
            selected_items = self.device_list.selectedItems()
            return [item.data(Qt.ItemDataRole.UserRole) for item in selected_items if item.data(Qt.ItemDataRole.UserRole)]
        except Exception as e:
            log_error(f"Error getting selected devices: {e}")
            return []
    
    def highlight_gaming_devices(self):
        """Highlight gaming devices in the list"""
        try:
            for i in range(self.device_list.count()):
                item = self.device_list.item(i)
                device_ip = item.data(Qt.ItemDataRole.UserRole)
                if device_ip:
                    device = self.get_device_by_ip(device_ip)
                    if device:
                        # Check if it's a gaming device
                        vendor_lower = device.vendor.lower()
                        if any(gaming in vendor_lower for gaming in ['playstation', 'xbox', 'nintendo', 'sony', 'microsoft']):
                            item.setBackground(QColor(255, 255, 0, 50))  # Light yellow for gaming devices
                            item.setForeground(QColor(255, 255, 0))  # Yellow text
            log_info("Gaming devices highlighted")
        except Exception as e:
            log_error(f"Error highlighting gaming devices: {e}")
    
    def filter_devices_by_type(self, device_type: str):
        """Filter devices by type (gaming, local, blocked, etc.)"""
        try:
            if device_type == "all":
                # Show all devices
                for i in range(self.device_list.count()):
                    self.device_list.item(i).setHidden(False)
            elif device_type == "gaming":
                # Show only gaming devices
                for i in range(self.device_list.count()):
                    item = self.device_list.item(i)
                    device_ip = item.data(Qt.ItemDataRole.UserRole)
                    if device_ip:
                        device = self.get_device_by_ip(device_ip)
                        if device:
                            vendor_lower = device.vendor.lower()
                            is_gaming = any(gaming in vendor_lower for gaming in ['playstation', 'xbox', 'nintendo', 'sony', 'microsoft'])
                            item.setHidden(not is_gaming)
            elif device_type == "blocked":
                # Show only blocked devices
                for i in range(self.device_list.count()):
                    item = self.device_list.item(i)
                    device_ip = item.data(Qt.ItemDataRole.UserRole)
                    if device_ip:
                        device = self.get_device_by_ip(device_ip)
                        if device:
                            item.setHidden(not device.blocked)
            elif device_type == "local":
                # Show only local devices
                for i in range(self.device_list.count()):
                    item = self.device_list.item(i)
                    device_ip = item.data(Qt.ItemDataRole.UserRole)
                    if device_ip:
                        device = self.get_device_by_ip(device_ip)
                        if device:
                            item.setHidden(not device.local)
            
            log_info(f"Devices filtered by type: {device_type}")
        except Exception as e:
            log_error(f"Error filtering devices: {e}")
    
    # Search functionality methods
    def on_search_field_changed(self, field: str):
        """Handle search field dropdown change"""
        try:
            field_mapping = {
                "All Fields": "all",
                "IP Address": "ip",
                "Hostname": "hostname", 
                "Vendor": "vendor",
                "MAC Address": "mac"
            }
            self.search_field = field_mapping.get(field, "all")
            self.apply_search_filter()
            log_info(f"Search field changed to: {field}")
        except Exception as e:
            log_error(f"Error changing search field: {e}")
    
    def on_search_text_changed(self, text: str):
        """Handle search text input change"""
        try:
            self.search_text = text.lower().strip()
            self.apply_search_filter()
        except Exception as e:
            log_error(f"Error changing search text: {e}")
    
    def clear_search(self):
        """Clear the search and show all devices"""
        try:
            self.search_input.clear()
            self.search_field_combo.setCurrentText("All Fields")
            self.search_text = ""
            self.search_field = "all"
            self.apply_search_filter()
            log_info("Search cleared")
        except Exception as e:
            log_error(f"Error clearing search: {e}")
    
    def apply_search_filter(self):
        """Apply search filter to device list"""
        try:
            if not self.devices:
                return
            
            # Clear current list
            self.device_list.clear()
            
            # Add header back
            header_text = "Status  Type  Device  IP Address        |  MAC Address         |  Vendor               |  Hostname         |  Last Seen"
            header_item = QListWidgetItem(header_text)
            header_item.setBackground(QColor(240, 240, 240))
            header_item.setFlags(header_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.device_list.addItem(header_item)
            
            # Filter devices based on search criteria
            filtered_devices = []
            
            for device in self.devices:
                if self.matches_search_criteria(device):
                    filtered_devices.append(device)
            
            # Add filtered devices to list
            for device in filtered_devices:
                item = self.create_device_item(device)
                self.device_list.addItem(item)
            
            # Update status
            if self.search_text:
                self.status_label.setText(f"{len(filtered_devices)} devices found (filtered from {len(self.devices)})")
            else:
                self.status_label.setText(f"{len(filtered_devices)} devices found")
            
            self.filtered_devices = filtered_devices
            log_info(f"Search filter applied: {len(filtered_devices)} devices match criteria")
            
        except Exception as e:
            log_error(f"Error applying search filter: {e}")
    
    def matches_search_criteria(self, device) -> bool:
        """Check if device matches current search criteria"""
        try:
            if not self.search_text:
                return True
            
            search_text = self.search_text.lower()
            
            if self.search_field == "all":
                # Search in all fields
                return (search_text in device.ip.lower() or
                        search_text in device.vendor.lower() or
                        (device.hostname and search_text in device.hostname.lower()) or
                        (device.mac and search_text in device.mac.lower()))
            
            elif self.search_field == "ip":
                return search_text in device.ip.lower()
            
            elif self.search_field == "hostname":
                return device.hostname and search_text in device.hostname.lower()
            
            elif self.search_field == "vendor":
                return search_text in device.vendor.lower()
            
            elif self.search_field == "mac":
                return device.mac and search_text in device.mac.lower()
            
            return True
            
        except Exception as e:
            log_error(f"Error checking search criteria: {e}")
            return True
    
    def get_filtered_devices(self) -> List:
        """Get currently filtered devices"""
        return self.filtered_devices if self.filtered_devices else self.devices
    
    def search_for_device(self, search_term: str, field: str = "all") -> List:
        """Search for devices with specific criteria"""
        try:
            self.search_input.setText(search_term)
            self.search_field_combo.setCurrentText(field)
            return self.get_filtered_devices()
        except Exception as e:
            log_error(f"Error searching for device: {e}")
            return []
    
    def highlight_search_results(self):
        """Highlight search results in the list"""
        try:
            if not self.search_text:
                # Remove highlighting
                for i in range(self.device_list.count()):
                    item = self.device_list.item(i)
                    if item:
                        item.setBackground(QColor(0, 0, 0, 0))  # Transparent
                return
            
            # Highlight matching items
            for i in range(self.device_list.count()):
                item = self.device_list.item(i)
                if item and item.data(Qt.ItemDataRole.UserRole):  # Skip header
                    device_ip = item.data(Qt.ItemDataRole.UserRole)
                    device = self.get_device_by_ip(device_ip)
                    if device and self.matches_search_criteria(device):
                        # Highlight with a subtle green background
                        item.setBackground(QColor(0, 255, 0, 30))  # Light green
                    else:
                        item.setBackground(QColor(0, 0, 0, 0))  # Transparent
            
            log_info("Search results highlighted")
        except Exception as e:
            log_error(f"Error highlighting search results: {e}")
    
    def quick_search(self, term: str):
        """Quick search function for external calls"""
        try:
            self.search_input.setText(term)
            self.search_field_combo.setCurrentText("All Fields")
            log_info(f"Quick search performed for: {term}")
        except Exception as e:
            log_error(f"Error in quick search: {e}")
    
    def export_search_results(self):
        """Export current search results to file"""
        try:
            filtered_devices = self.get_filtered_devices()
            if not filtered_devices:
                QMessageBox.warning(self, "Warning", "No devices to export")
                return
            
            from PyQt6.QtWidgets import QFileDialog
            filename, _ = QFileDialog.getSaveFileName(
                self, "Export Search Results", 
                f"search_results_{len(filtered_devices)}_devices.txt",
                "Text Files (*.txt);;CSV Files (*.csv)"
            )
            
            if filename:
                with open(filename, 'w') as f:
                    f.write(f"Search Results - {len(filtered_devices)} devices\n")
                    f.write(f"Search Term: {self.search_text}\n")
                    f.write(f"Search Field: {self.search_field}\n")
                    f.write("=" * 50 + "\n\n")
                    
                    for device in filtered_devices:
                        f.write(f"IP: {device.ip}\n")
                        f.write(f"Vendor: {device.vendor}\n")
                        f.write(f"Hostname: {device.hostname or 'Unknown'}\n")
                        f.write(f"MAC: {device.mac or 'Unknown'}\n")
                        f.write(f"Status: {'Blocked' if device.blocked else 'Active'}\n")
                        f.write("-" * 30 + "\n")
                
                QMessageBox.information(self, "Export Complete", 
                                      f"Exported {len(filtered_devices)} devices to {filename}")
                log_info(f"Search results exported to {filename}")
        except Exception as e:
            log_error(f"Error exporting search results: {e}")
            QMessageBox.critical(self, "Error", f"Failed to export search results: {e}")
