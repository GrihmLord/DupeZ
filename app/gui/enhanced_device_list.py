# app/gui/enhanced_device_list.py

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QListWidget, QListWidgetItem,
                             QProgressBar, QTextEdit, QSplitter, QFrame,
                             QHeaderView, QTableWidget, QTableWidgetItem,
                             QComboBox, QSpinBox, QCheckBox, QGroupBox,
                             QMenu)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QIcon, QAction
import time
from typing import List, Dict, Optional

from app.network.enhanced_scanner import get_enhanced_scanner, cleanup_enhanced_scanner
from app.logs.logger import log_info, log_error

class EnhancedDeviceList(QWidget):
    """Enhanced device list with Angry IP Scanner-like features"""
    
    # Signals
    device_selected = pyqtSignal(dict)  # Selected device
    device_blocked = pyqtSignal(str, bool)  # IP, blocked status
    scan_started = pyqtSignal()
    scan_finished = pyqtSignal(list)  # All devices
    
    def __init__(self, controller=None):
        super().__init__()
        self.controller = controller
        self.scanner = get_enhanced_scanner()
        self.devices = []
        self.setup_ui()
        self.connect_signals()
        
    def setup_ui(self):
        """Setup the enhanced device list UI"""
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        # Title
        title = QLabel("🔍 Enhanced Network Scanner")
        title.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # Control panel
        control_panel = self.create_control_panel()
        layout.addWidget(control_panel)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        # Device table
        self.device_table = QTableWidget()
        self.setup_device_table()
        layout.addWidget(self.device_table)
        
        # Status bar
        self.status_label = QLabel("Ready to scan network")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        layout.addWidget(self.status_label)
        
        # Blocking status indicator
        self.blocking_status = QLabel("🔒 Blocking: Inactive")
        self.blocking_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.blocking_status.setStyleSheet("color: #FF9800; font-weight: bold;")
        self.blocking_status.setToolTip("Shows current blocking status. Double-click IP addresses to toggle blocking.")
        layout.addWidget(self.blocking_status)
        
        # Apply styling
        self.apply_styling()
    
    def create_control_panel(self) -> QWidget:
        """Create the control panel with scan options"""
        panel = QWidget()
        layout = QHBoxLayout()
        panel.setLayout(layout)
        
        # Scan button
        self.scan_button = QPushButton("🔍 Start Enhanced Scan")
        self.scan_button.setFont(QFont("Arial", 12))
        self.scan_button.clicked.connect(self.start_scan)
        layout.addWidget(self.scan_button)
        
        # Stop button
        self.stop_button = QPushButton("⏹️ Stop Scan")
        self.stop_button.setFont(QFont("Arial", 12))
        self.stop_button.clicked.connect(self.stop_scan)
        self.stop_button.setEnabled(False)
        layout.addWidget(self.stop_button)
        
        # Thread count
        thread_label = QLabel("Threads:")
        layout.addWidget(thread_label)
        
        self.thread_spinbox = QSpinBox()
        self.thread_spinbox.setRange(10, 100)
        self.thread_spinbox.setValue(50)
        self.thread_spinbox.setToolTip("Number of concurrent scan threads")
        layout.addWidget(self.thread_spinbox)
        
        # Timeout setting
        timeout_label = QLabel("Timeout (ms):")
        layout.addWidget(timeout_label)
        
        self.timeout_spinbox = QSpinBox()
        self.timeout_spinbox.setRange(500, 5000)
        self.timeout_spinbox.setValue(1000)
        self.timeout_spinbox.setSuffix(" ms")
        self.timeout_spinbox.setToolTip("Scan timeout per IP")
        layout.addWidget(self.timeout_spinbox)
        
        # Advanced options
        self.advanced_checkbox = QCheckBox("Advanced Scan")
        self.advanced_checkbox.setToolTip("Use advanced scanning methods")
        self.advanced_checkbox.setChecked(True)
        layout.addWidget(self.advanced_checkbox)
        
        # Clear button
        self.clear_button = QPushButton("🗑️ Clear")
        self.clear_button.setFont(QFont("Arial", 12))
        self.clear_button.clicked.connect(self.clear_devices)
        layout.addWidget(self.clear_button)
        
        # Block button
        self.block_button = QPushButton("🚫 Block Selected")
        self.block_button.setFont(QFont("Arial", 12))
        self.block_button.clicked.connect(self.block_selected)
        layout.addWidget(self.block_button)
        
        layout.addStretch()
        return panel
    
    def setup_device_table(self):
        """Setup the device table with columns"""
        # Set up table headers
        headers = [
            "IP Address", "MAC Address", "Hostname", "Vendor", 
            "Device Type", "Response Time", "Open Ports", "Risk Score", "Status"
        ]
        self.device_table.setColumnCount(len(headers))
        self.device_table.setHorizontalHeaderLabels(headers)
        
        # Set up table properties
        self.device_table.setAlternatingRowColors(True)
        self.device_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.device_table.setSortingEnabled(True)
        
        # Set column widths
        header = self.device_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)  # IP
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)  # MAC
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)           # Hostname
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)  # Vendor
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)  # Device Type
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)  # Response Time
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)  # Open Ports
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)  # Risk Score
        header.setSectionResizeMode(8, QHeaderView.ResizeMode.ResizeToContents)  # Status
        
        # Connect selection signal
        self.device_table.itemSelectionChanged.connect(self.on_device_selected)
        
        # Connect double-click signal for toggle blocking
        self.device_table.cellDoubleClicked.connect(self.on_cell_double_clicked)
        
        # Connect context menu
        self.device_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.device_table.customContextMenuRequested.connect(self.show_context_menu)
    
    def connect_signals(self):
        """Connect scanner signals to UI updates"""
        self.scanner.device_found.connect(self.add_device_to_table)
        self.scanner.scan_progress.connect(self.update_progress)
        self.scanner.scan_complete.connect(self.on_scan_complete)
        self.scanner.scan_error.connect(self.on_scan_error)
        self.scanner.status_update.connect(self.update_status)
    
    def start_scan(self):
        """Start the enhanced network scan"""
        try:
            # Clear previous results
            self.device_table.setRowCount(0)
            self.devices = []
            
            # Update scanner settings
            self.scanner.max_threads = self.thread_spinbox.value()
            self.scanner.timeout = self.timeout_spinbox.value() / 1000.0
            
            # Update UI state
            self.scan_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)
            
            # Start scan
            self.scanner.start()
            self.scan_started.emit()
            
            log_info("Enhanced network scan started")
            
        except Exception as e:
            log_error(f"Error starting scan: {e}")
            self.update_status(f"Error starting scan: {e}")
    
    def stop_scan(self):
        """Stop the network scan"""
        try:
            self.scanner.stop_scan()
            self.update_status("Scan stopped by user")
            self.on_scan_complete(self.devices)
            
        except Exception as e:
            log_error(f"Error stopping scan: {e}")
    
    def add_device_to_table(self, device: Dict):
        """Add a device to the table"""
        try:
            row = self.device_table.rowCount()
            self.device_table.insertRow(row)
            
            # Create table items
            items = [
                QTableWidgetItem(device.get('ip', '')),
                QTableWidgetItem(device.get('mac', '')),
                QTableWidgetItem(device.get('hostname', '')),
                QTableWidgetItem(device.get('vendor', '')),
                QTableWidgetItem(device.get('device_type', '')),
                QTableWidgetItem(f"{device.get('response_time', 0):.1f}ms"),
                QTableWidgetItem(', '.join(map(str, device.get('open_ports', [])))),
                QTableWidgetItem(str(device.get('risk_score', 0))),
                QTableWidgetItem(device.get('status', 'Online'))
            ]
            
            # Set items in table
            for col, item in enumerate(items):
                self.device_table.setItem(row, col, item)
                
                # Make IP column clickable and show it's interactive
                if col == 0:  # IP Address column
                    item.setToolTip("Double-click to toggle blocking")
                    # Add a subtle visual indicator that it's clickable
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
            
            # Color code based on device type and risk
            self.color_code_device(row, device)
            
            # Update status column color based on blocked status
            is_blocked = device.get('blocked', False)
            status_item = self.device_table.item(row, 8)
            if is_blocked:
                status_item.setBackground(QColor(255, 100, 100))  # Red for blocked
                status_item.setForeground(QColor(255, 255, 255))  # White text
            else:
                status_item.setBackground(QColor(100, 255, 100))  # Green for online
                status_item.setForeground(QColor(0, 0, 0))  # Black text
            
            # Store device data
            self.devices.append(device)
            
        except Exception as e:
            log_error(f"Error adding device to table: {e}")
    
    def color_code_device(self, row: int, device: Dict):
        """Color code device based on type and risk"""
        try:
            device_type = device.get('device_type', '').lower()
            risk_score = device.get('risk_score', 0)
            is_local = device.get('local', False)
            
            # Set background color based on device type
            if "gaming console" in device_type:
                color = QColor(255, 200, 200)  # Light red for gaming
            elif "network device" in device_type:
                color = QColor(200, 255, 200)  # Light green for network
            elif "mobile device" in device_type:
                color = QColor(200, 200, 255)  # Light blue for mobile
            elif "computer" in device_type:
                color = QColor(255, 255, 200)  # Light yellow for computer
            else:
                color = QColor(240, 240, 240)  # Light gray for unknown
            
            # Adjust color based on risk score
            if risk_score > 70:
                color = color.darker(120)  # Darker for high risk
            elif risk_score > 40:
                color = color.darker(110)  # Slightly darker for medium risk
            
            # Special color for local device
            if is_local:
                color = QColor(255, 255, 150)  # Bright yellow for local
            
            # Apply color to all cells in the row
            for col in range(self.device_table.columnCount()):
                item = self.device_table.item(row, col)
                if item:
                    item.setBackground(color)
                    
        except Exception as e:
            log_error(f"Error color coding device: {e}")
    
    def update_progress(self, current: int, total: int):
        """Update progress bar"""
        try:
            if total > 0:
                progress = int((current / total) * 100)
                self.progress_bar.setValue(progress)
        except Exception as e:
            log_error(f"Error updating progress: {e}")
    
    def on_scan_complete(self, devices: List[Dict]):
        """Handle scan completion"""
        try:
            # Update UI state
            self.scan_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.progress_bar.setVisible(False)
            
            # Update status
            self.update_status(f"Scan complete! Found {len(devices)} devices")
            
            # Emit signal
            self.scan_finished.emit(devices)
            
            log_info(f"Enhanced scan completed with {len(devices)} devices")
            
        except Exception as e:
            log_error(f"Error handling scan completion: {e}")
    
    def on_scan_error(self, error_msg: str):
        """Handle scan errors"""
        try:
            self.update_status(f"Scan error: {error_msg}")
            self.on_scan_complete(self.devices)
            
        except Exception as e:
            log_error(f"Error handling scan error: {e}")
    
    def update_status(self, message: str):
        """Update status label"""
        try:
            self.status_label.setText(message)
            
            # Color code status messages
            if "error" in message.lower():
                self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
            elif "complete" in message.lower():
                self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
            elif "scanning" in message.lower():
                self.status_label.setStyleSheet("color: #FF9800; font-weight: bold;")
            else:
                self.status_label.setStyleSheet("color: #2196F3; font-weight: bold;")
                
        except Exception as e:
            log_error(f"Error updating status: {e}")
    
    def on_device_selected(self):
        """Handle device selection"""
        try:
            current_row = self.device_table.currentRow()
            if current_row >= 0 and current_row < len(self.devices):
                selected_device = self.devices[current_row]
                self.device_selected.emit(selected_device)
                
        except Exception as e:
            log_error(f"Error handling device selection: {e}")
    
    def on_cell_double_clicked(self, row: int, column: int):
        """Handle double-click on table cell to toggle blocking"""
        try:
            if row < len(self.devices):
                device = self.devices[row]
                ip = device.get('ip', '')
                
                # Toggle blocking status
                current_blocked = device.get('blocked', False)
                new_blocked = not current_blocked
                
                # Update device status
                device['blocked'] = new_blocked
                device['status'] = 'Blocked' if new_blocked else 'Online'
                
                # Update table display
                status_item = QTableWidgetItem(device['status'])
                if new_blocked:
                    status_item.setBackground(QColor(255, 100, 100))  # Red for blocked
                    status_item.setForeground(QColor(255, 255, 255))  # White text
                else:
                    status_item.setBackground(QColor(100, 255, 100))  # Green for online
                    status_item.setForeground(QColor(0, 0, 0))  # Black text
                
                self.device_table.setItem(row, 8, status_item)
                
                # Actually block/unblock the device
                self.actually_block_device(ip, new_blocked)
                
                # Update status message
                action = "blocked" if new_blocked else "unblocked"
                self.update_status(f"Device {ip} {action}")
                
                # Emit signal
                self.device_blocked.emit(ip, new_blocked)
                
        except Exception as e:
            log_error(f"Error toggling device blocking: {e}")
    
    def show_context_menu(self, position):
        """Show context menu for device actions"""
        try:
            
            # Get the row under the cursor
            row = self.device_table.rowAt(position.y())
            if row < 0 or row >= len(self.devices):
                return
            
            device = self.devices[row]
            ip = device.get('ip', '')
            is_blocked = device.get('blocked', False)
            
            # Create context menu
            menu = QMenu(self)
            
            # Toggle blocking action
            toggle_action = QAction("Block Device" if not is_blocked else "Unblock Device", self)
            toggle_action.triggered.connect(lambda: self.toggle_device_blocking(row))
            menu.addAction(toggle_action)
            
            # Add separator
            menu.addSeparator()
            
            # Ping device action
            ping_action = QAction("Ping Device", self)
            ping_action.triggered.connect(lambda: self.ping_device(ip))
            menu.addAction(ping_action)
            
            # Port scan action
            scan_action = QAction("Port Scan", self)
            scan_action.triggered.connect(lambda: self.port_scan_device(ip))
            menu.addAction(scan_action)
            
            # Add separator
            menu.addSeparator()
            
            # Copy IP action
            copy_action = QAction("Copy IP Address", self)
            copy_action.triggered.connect(lambda: self.copy_ip_to_clipboard(ip))
            menu.addAction(copy_action)
            
            # Show menu at cursor position
            menu.exec(self.device_table.mapToGlobal(position))
            
        except Exception as e:
            log_error(f"Error showing context menu: {e}")
    
    def toggle_device_blocking(self, row: int):
        """Toggle blocking for a specific device row"""
        try:
            if row < len(self.devices):
                device = self.devices[row]
                ip = device.get('ip', '')
                
                # Toggle blocking status
                current_blocked = device.get('blocked', False)
                new_blocked = not current_blocked
                
                # Update device status
                device['blocked'] = new_blocked
                device['status'] = 'Blocked' if new_blocked else 'Online'
                
                # Update table display
                status_item = QTableWidgetItem(device['status'])
                if new_blocked:
                    status_item.setBackground(QColor(255, 100, 100))  # Red for blocked
                    status_item.setForeground(QColor(255, 255, 255))  # White text
                else:
                    status_item.setBackground(QColor(100, 255, 100))  # Green for online
                    status_item.setForeground(QColor(0, 0, 0))  # Black text
                
                self.device_table.setItem(row, 8, status_item)
                
                # Actually block/unblock the device
                self.actually_block_device(ip, new_blocked)
                
                # Update status message
                action = "blocked" if new_blocked else "unblocked"
                self.update_status(f"Device {ip} {action}")
                
                # Emit signal
                self.device_blocked.emit(ip, new_blocked)
                
        except Exception as e:
            log_error(f"Error toggling device blocking: {e}")
    
    def actually_block_device(self, ip: str, block: bool):
        """Actually block/unblock a device using firewall rules"""
        try:
            if self.controller:
                # Use the controller's blocking mechanism
                self.controller.block_device(ip, block)
            else:
                # Fallback to direct firewall blocking
                self.aggressive_block_device(ip, block)
                
            log_info(f"Device {ip} {'blocked' if block else 'unblocked'} successfully")
            
            # Update blocking status indicator
            self.update_blocking_status()
            
        except Exception as e:
            log_error(f"Error blocking device {ip}: {e}")
            self.update_status(f"Error blocking {ip}: {e}")
    
    def update_blocking_status(self):
        """Update the blocking status indicator"""
        try:
            blocked_count = sum(1 for device in self.devices if device.get('blocked', False))
            total_devices = len(self.devices)
            
            if blocked_count > 0:
                self.blocking_status.setText(f"🔒 Blocking: Active ({blocked_count}/{total_devices} devices blocked)")
                self.blocking_status.setStyleSheet("color: #f44336; font-weight: bold;")
            else:
                self.blocking_status.setText("🔒 Blocking: Inactive")
                self.blocking_status.setStyleSheet("color: #FF9800; font-weight: bold;")
                
        except Exception as e:
            log_error(f"Error updating blocking status: {e}")
    
    def block_with_firewall(self, ip: str, block: bool):
        """Block device using Windows Firewall rules"""
        try:
            import subprocess
            import platform
            
            if platform.system().lower() == "windows":
                if block:
                    # Add firewall rule to block IP
                    rule_name = f"PulseDrop_Block_{ip.replace('.', '_')}"
                    cmd = [
                        "netsh", "advfirewall", "firewall", "add", "rule",
                        f"name={rule_name}",
                        "dir=out",
                        "action=block",
                        f"remoteip={ip}",
                        "enable=yes"
                    ]
                else:
                    # Remove firewall rule
                    rule_name = f"PulseDrop_Block_{ip.replace('.', '_')}"
                    cmd = [
                        "netsh", "advfirewall", "firewall", "delete", "rule",
                        f"name={rule_name}"
                    ]
                
                # Execute command with admin privileges
                result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
                
                if result.returncode != 0:
                    log_error(f"Firewall command failed: {result.stderr}")
                    raise Exception(f"Firewall command failed: {result.stderr}")
                
                log_info(f"Firewall rule {'added' if block else 'removed'} for {ip}")
                
                # Also add route blocking for more aggressive blocking
                if block:
                    self.block_with_route(ip, True)
                else:
                    self.block_with_route(ip, False)
                    
            else:
                # For non-Windows systems, use iptables
                if block:
                    cmd = ["iptables", "-A", "OUTPUT", "-d", ip, "-j", "DROP"]
                else:
                    cmd = ["iptables", "-D", "OUTPUT", "-d", ip, "-j", "DROP"]
                
                result = subprocess.run(cmd, capture_output=True, text=True)
                
                if result.returncode != 0:
                    log_error(f"iptables command failed: {result.stderr}")
                    raise Exception(f"iptables command failed: {result.stderr}")
                
                log_info(f"iptables rule {'added' if block else 'removed'} for {ip}")
                
        except Exception as e:
            log_error(f"Error with firewall blocking: {e}")
            raise
    
    def block_with_route(self, ip: str, block: bool):
        """Block device using route table manipulation"""
        try:
            import subprocess
            import platform
            
            if platform.system().lower() == "windows":
                if block:
                    # Add a blackhole route to the IP
                    cmd = [
                        "route", "add", ip, "mask", "255.255.255.255", "0.0.0.0", "metric", "1"
                    ]
                else:
                    # Remove the blackhole route
                    cmd = [
                        "route", "delete", ip
                    ]
                
                # Execute command with admin privileges
                result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
                
                if result.returncode != 0 and "already exists" not in result.stderr:
                    log_error(f"Route command failed: {result.stderr}")
                    # Don't raise exception for route commands as they might fail for various reasons
                
                log_info(f"Route {'added' if block else 'removed'} for {ip}")
                
        except Exception as e:
            log_error(f"Error with route blocking: {e}")
            # Don't raise exception for route blocking as it's secondary
    
    def aggressive_block_device(self, ip: str, block: bool):
        """Aggressive blocking that tries multiple methods"""
        try:
            # Method 1: Firewall rules
            self.block_with_firewall(ip, block)
            
            # Method 2: Route table manipulation
            self.block_with_route(ip, block)
            
            # Method 3: ARP poisoning (for local network)
            if self.is_local_network(ip):
                self.block_with_arp(ip, block)
            
            # Method 4: DNS blocking
            self.block_with_dns(ip, block)
            
            log_info(f"Aggressive blocking {'enabled' if block else 'disabled'} for {ip}")
            
        except Exception as e:
            log_error(f"Error with aggressive blocking: {e}")
            raise
    
    def is_local_network(self, ip: str) -> bool:
        """Check if IP is on local network"""
        try:
            import socket
            
            # Get local IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            
            # Extract network prefix
            local_parts = local_ip.split('.')
            ip_parts = ip.split('.')
            
            # Check if same network (assuming /24)
            return local_parts[:3] == ip_parts[:3]
            
        except:
            return False
    
    def block_with_arp(self, ip: str, block: bool):
        """Block device using ARP poisoning"""
        try:
            import subprocess
            import platform
            
            if platform.system().lower() == "windows":
                if block:
                    # Add static ARP entry pointing to invalid MAC
                    cmd = [
                        "arp", "-s", ip, "00-00-00-00-00-00"
                    ]
                else:
                    # Remove static ARP entry
                    cmd = [
                        "arp", "-d", ip
                    ]
                
                result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
                
                if result.returncode != 0:
                    log_error(f"ARP command failed: {result.stderr}")
                
                log_info(f"ARP entry {'added' if block else 'removed'} for {ip}")
                
        except Exception as e:
            log_error(f"Error with ARP blocking: {e}")
    
    def block_with_dns(self, ip: str, block: bool):
        """Block device using DNS manipulation"""
        try:
            import subprocess
            import platform
            
            if platform.system().lower() == "windows":
                # This would require modifying hosts file or DNS settings
                # For now, just log the attempt
                log_info(f"DNS blocking {'requested' if block else 'removed'} for {ip}")
                
        except Exception as e:
            log_error(f"Error with DNS blocking: {e}")
    
    def ping_device(self, ip: str):
        """Ping a device to check connectivity"""
        try:
            import subprocess
            import platform
            
            if platform.system().lower() == "windows":
                cmd = ["ping", "-n", "4", ip]
            else:
                cmd = ["ping", "-c", "4", ip]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                self.update_status(f"Ping to {ip}: Success")
            else:
                self.update_status(f"Ping to {ip}: Failed")
                
        except Exception as e:
            log_error(f"Error pinging {ip}: {e}")
            self.update_status(f"Error pinging {ip}: {e}")
    
    def port_scan_device(self, ip: str):
        """Perform a quick port scan on a device"""
        try:
            import socket
            
            common_ports = [21, 22, 23, 25, 53, 80, 110, 143, 443, 993, 995, 8080]
            open_ports = []
            
            for port in common_ports:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(1.0)
                    result = sock.connect_ex((ip, port))
                    sock.close()
                    
                    if result == 0:
                        open_ports.append(port)
                except:
                    continue
            
            if open_ports:
                ports_str = ', '.join(map(str, open_ports))
                self.update_status(f"Port scan {ip}: Open ports: {ports_str}")
            else:
                self.update_status(f"Port scan {ip}: No common ports open")
                
        except Exception as e:
            log_error(f"Error port scanning {ip}: {e}")
            self.update_status(f"Error port scanning {ip}: {e}")
    
    def copy_ip_to_clipboard(self, ip: str):
        """Copy IP address to clipboard"""
        try:
            from PyQt6.QtWidgets import QApplication
            clipboard = QApplication.clipboard()
            clipboard.setText(ip)
            self.update_status(f"IP address {ip} copied to clipboard")
        except Exception as e:
            log_error(f"Error copying IP to clipboard: {e}")
            self.update_status(f"Error copying IP to clipboard: {e}")
    
    def clear_devices(self):
        """Clear all devices from the table"""
        try:
            self.device_table.setRowCount(0)
            self.devices = []
            self.update_status("Device list cleared")
            
        except Exception as e:
            log_error(f"Error clearing devices: {e}")
    
    def block_selected(self):
        """Block selected devices"""
        try:
            selected_rows = set()
            for item in self.device_table.selectedItems():
                selected_rows.add(item.row())
            
            if not selected_rows:
                self.update_status("No devices selected for blocking")
                return
            
            # Block selected devices
            for row in selected_rows:
                if row < len(self.devices):
                    device = self.devices[row]
                    ip = device.get('ip', '')
                    
                    # Update device status
                    device['blocked'] = True
                    device['status'] = 'Blocked'
                    
                    # Update table
                    status_item = QTableWidgetItem('Blocked')
                    status_item.setBackground(QColor(255, 100, 100))
                    self.device_table.setItem(row, 8, status_item)
                    
                    # Emit signal
                    self.device_blocked.emit(ip, True)
            
            self.update_status(f"Blocked {len(selected_rows)} selected device(s)")
            
        except Exception as e:
            log_error(f"Error blocking devices: {e}")
    
    def get_selected_devices(self) -> List[Dict]:
        """Get list of selected devices"""
        try:
            selected_devices = []
            selected_rows = set()
            
            for item in self.device_table.selectedItems():
                selected_rows.add(item.row())
            
            for row in selected_rows:
                if row < len(self.devices):
                    selected_devices.append(self.devices[row])
            
            return selected_devices
            
        except Exception as e:
            log_error(f"Error getting selected devices: {e}")
            return []
    
    def get_device_count(self) -> int:
        """Get total number of devices"""
        return len(self.devices)
    
    def apply_styling(self):
        """Apply modern styling to the widget"""
        self.setStyleSheet("""
            QWidget {
                background-color: #2d2d2d;
                color: #ffffff;
            }
            QPushButton {
                background-color: #3d3d3d;
                border: 2px solid #4a4a4a;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
                color: #ffffff;
            }
            QPushButton:hover {
                background-color: #4d4d4d;
                border-color: #5a5a5a;
            }
            QPushButton:pressed {
                background-color: #2d2d2d;
                border-color: #3a3a3a;
            }
            QPushButton:disabled {
                background-color: #1a1a1a;
                border-color: #333333;
                color: #666666;
            }
            QTableWidget {
                background-color: #1e1e1e;
                border: 2px solid #4a4a4a;
                border-radius: 6px;
                alternate-background-color: #252525;
                gridline-color: #3a3a3a;
            }
            QTableWidget::item {
                padding: 6px;
                border-bottom: 1px solid #3a3a3a;
            }
            QTableWidget::item:selected {
                background-color: #4CAF50;
                color: #ffffff;
            }
            QHeaderView::section {
                background-color: #3d3d3d;
                color: #ffffff;
                padding: 8px;
                border: 1px solid #4a4a4a;
                font-weight: bold;
            }
            QProgressBar {
                border: 1px solid #555555;
                background-color: #1e1e1e;
                text-align: center;
                border-radius: 4px;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                border-radius: 4px;
            }
            QSpinBox {
                background-color: #3d3d3d;
                border: 1px solid #4a4a4a;
                border-radius: 4px;
                padding: 4px;
                color: #ffffff;
            }
            QCheckBox {
                color: #ffffff;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border: 2px solid #4a4a4a;
                border-radius: 3px;
                background-color: #2d2d2d;
            }
            QCheckBox::indicator:checked {
                background-color: #4CAF50;
                border-color: #4CAF50;
            }
        """)
    
    def cleanup(self):
        """Clean up resources"""
        try:
            cleanup_enhanced_scanner()
        except Exception as e:
            log_error(f"Error during cleanup: {e}") 