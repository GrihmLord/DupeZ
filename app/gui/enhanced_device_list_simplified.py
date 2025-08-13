"""
Simplified Network Scanner - Clumsy/NetCut Style
Individual device disconnect/reconnect only - no bulk operations
"""

import sys
import time
import platform
import subprocess
from typing import List, Dict, Optional
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QProgressBar, QHeaderView, QMessageBox,
    QAbstractItemView, QMenu, QApplication
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QAction, QColor

# Import network disruptors
try:
    from app.firewall.clumsy_network_disruptor import ClumsyNetworkDisruptor
    from app.firewall.enterprise_network_disruptor import EnterpriseNetworkDisruptor
except ImportError as e:
    print(f"Warning: Could not import network disruptors: {e}")
    ClumsyNetworkDisruptor = None
    EnterpriseNetworkDisruptor = None

# Import utility functions
try:
    from app.utils.logging_utils import log_info, log_error, log_warning
    from app.firewall.blocker import is_admin
except ImportError as e:
    print(f"Warning: Could not import utility functions: {e}")
    # Fallback logging functions
    def log_info(msg): print(f"INFO: {msg}")
    def log_error(msg): print(f"ERROR: {msg}")
    def log_warning(msg): print(f"WARNING: {msg}")
    def is_admin(): return True  # Assume admin for now


class NetworkScannerThread(QThread):
    """Thread for network scanning to prevent UI freezing"""
    device_found = pyqtSignal(dict)
    scan_progress = pyqtSignal(int)
    scan_complete = pyqtSignal()
    scan_error = pyqtSignal(str)
    
    def __init__(self, network_range: str, thread_count: int = 50, timeout: int = 1000):
        super().__init__()
        self.network_range = network_range
        self.thread_count = thread_count
        self.timeout = timeout
        self.running = False
        
    def run(self):
        """Run the network scan"""
        try:
            self.running = True
            self._scan_network()
        except Exception as e:
            self.scan_error.emit(str(e))
        finally:
            self.running = False
            
    def stop(self):
        """Stop the scan"""
        self.running = False
        
    def _scan_network(self):
        """Perform the actual network scan"""
        try:
            # Simple ping-based scan for demonstration
            # In a real implementation, you'd use more sophisticated scanning
            base_ip = self.network_range.rsplit('.', 1)[0]
            
            for i in range(1, 255):
                if not self.running:
                    break
                    
                ip = f"{base_ip}.{i}"
                if self._ping_host(ip):
                    device_info = {
                        'ip': ip,
                        'mac': self._get_mac_address(ip),
                        'hostname': self._get_hostname(ip),
                        'status': 'Online',
                        'disconnected': False,
                        'last_seen': time.strftime('%H:%M:%S')
                    }
                    self.device_found.emit(device_info)
                
                # Update progress
                progress = int((i / 254) * 100)
                self.scan_progress.emit(progress)
                
                # Small delay to prevent overwhelming
                time.sleep(0.01)
                
            self.scan_complete.emit()
            
        except Exception as e:
            self.scan_error.emit(f"Scan error: {str(e)}")
            
    def _ping_host(self, ip: str) -> bool:
        """Ping a host to check if it's online"""
        try:
            if platform.system() == "Windows":
                cmd = f"ping -n 1 -w {self.timeout} {ip}"
            else:
                cmd = f"ping -c 1 -W {self.timeout//1000} {ip}"
                
            result = subprocess.run(cmd, shell=True, capture_output=True, timeout=5)
            return result.returncode == 0
        except:
            return False
            
    def _get_mac_address(self, ip: str) -> str:
        """Get MAC address for an IP (simplified)"""
        try:
            if platform.system() == "Windows":
                cmd = f"arp -a {ip}"
                result = subprocess.run(cmd, shell=True, capture_output=True, timeout=3)
                if result.returncode == 0:
                    lines = result.stdout.decode().split('\n')
                    for line in lines:
                        if ip in line and 'dynamic' in line.lower():
                            parts = line.split()
                            if len(parts) >= 2:
                                return parts[1]
        except:
            pass
        return "Unknown"
        
    def _get_hostname(self, ip: str) -> str:
        """Get hostname for an IP (simplified)"""
        try:
            if platform.system() == "Windows":
                cmd = f"nbtstat -A {ip}"
                result = subprocess.run(cmd, shell=True, capture_output=True, timeout=3)
                if result.returncode == 0:
                    lines = result.stdout.decode().split('\n')
                    for line in lines:
                        if 'UNIQUE' in line and '<00>' in line:
                            parts = line.split()
                            if len(parts) >= 1:
                                return parts[0]
        except:
            pass
        return "Unknown"


class SimplifiedNetworkScanner(QWidget):
    """Simplified network scanner with Clumsy/NetCut style interface"""
    
    def __init__(self):
        super().__init__()
        self.devices = []
        self.scanner_thread = None
        self.clumsy_network_disruptor = None
        self.enterprise_network_disruptor = None
        
        # Initialize network disruptors
        self._initialize_disruptors()
        
        # Setup UI
        self.setup_ui()
        
        # Connect signals
        self.connect_signals()
        
    def _initialize_disruptors(self):
        """Initialize network disruptors"""
        try:
            if ClumsyNetworkDisruptor:
                self.clumsy_network_disruptor = ClumsyNetworkDisruptor()
                if self.clumsy_network_disruptor.initialize():
                    log_info("Clumsy network disruptor initialized successfully")
                else:
                    log_warning("Clumsy network disruptor initialization failed")
                    self.clumsy_network_disruptor = None
        except Exception as e:
            log_error(f"Error initializing Clumsy disruptor: {e}")
            
        try:
            if EnterpriseNetworkDisruptor:
                self.enterprise_network_disruptor = EnterpriseNetworkDisruptor()
                if self.enterprise_network_disruptor.initialize():
                    log_info("Enterprise network disruptor initialized successfully")
                else:
                    log_warning("Enterprise network disruptor initialization failed")
                    self.enterprise_network_disruptor = None
        except Exception as e:
            log_error(f"Error initializing Enterprise disruptor: {e}")
    
    def setup_ui(self):
        """Setup a simple, Clumsy-like network scanner UI"""
        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(8, 8, 8, 8)
        self.setLayout(layout)
        
        # Simple title
        title = QLabel("🔍 Network Scanner")
        title.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #ffffff; padding: 8px; margin-bottom: 8px;")
        layout.addWidget(title)
        
        # Simple control panel
        control_panel = self.create_simple_control_panel()
        layout.addWidget(control_panel)
        
        # Simple progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #555555;
                border-radius: 3px;
                text-align: center;
                height: 16px;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                border-radius: 2px;
            }
        """)
        layout.addWidget(self.progress_bar)
        
        # Simple device table
        self.device_table = QTableWidget()
        self.setup_simple_device_table()
        layout.addWidget(self.device_table, 1)
        
        # Simple status bar
        self.status_label = QLabel("Ready to scan")
        self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold; padding: 4px;")
        layout.addWidget(self.status_label)
        
        # Apply simple styling
        self.apply_simple_styling()
        
        # Initialize admin status
        try:
            if is_admin():
                admin_label = QLabel("👑 Administrator Mode")
                admin_label.setStyleSheet("color: #4CAF50; font-weight: bold; font-size: 10px;")
                layout.addWidget(admin_label)
        except Exception as e:
            log_error(f"Failed to create admin status indicator: {e}")
    
    def create_simple_control_panel(self) -> QWidget:
        """Create a simple control panel like Clumsy"""
        panel = QWidget()
        panel.setStyleSheet("""
            QWidget {
                background-color: #2d2d2d;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 8px;
            }
        """)
        
        layout = QHBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(8, 8, 8, 8)
        panel.setLayout(layout)
        
        # Scan button
        self.scan_button = QPushButton("🔍 Scan Network")
        self.scan_button.setStyleSheet("""
            QPushButton {
                background-color: #4caf50;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
        """)
        layout.addWidget(self.scan_button)
        
        # Stop button
        self.stop_button = QPushButton("⏹️ Stop")
        self.stop_button.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #da190b;
            }
            QPushButton:pressed {
                background-color: #c62828;
            }
        """)
        self.stop_button.setEnabled(False)
        layout.addWidget(self.stop_button)
        
        # Disconnect selected device button
        self.disconnect_button = QPushButton("🔌 Disconnect Selected")
        self.disconnect_button.setStyleSheet("""
            QPushButton {
                background-color: #ff9800;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #f57c00;
            }
            QPushButton:pressed {
                background-color: #ef6c00;
            }
            QPushButton:disabled {
                background-color: #666666;
                color: #999999;
            }
        """)
        self.disconnect_button.setEnabled(False)
        layout.addWidget(self.disconnect_button)
        
        # Reconnect selected device button
        self.reconnect_button = QPushButton("🔌 Reconnect Selected")
        self.reconnect_button.setStyleSheet("""
            QPushButton {
                background-color: #2196f3;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1976d2;
            }
            QPushButton:pressed {
                background-color: #1565c0;
            }
            QPushButton:disabled {
                background-color: #666666;
                color: #999999;
            }
        """)
        self.reconnect_button.setEnabled(False)
        layout.addWidget(self.reconnect_button)
        
        # Clear all button
        self.clear_button = QPushButton("🗑️ Clear All")
        self.clear_button.setStyleSheet("""
            QPushButton {
                background-color: #9c27b0;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #7b1fa2;
            }
            QPushButton:pressed {
                background-color: #6a1b9a;
            }
        """)
        layout.addWidget(self.clear_button)
        
        layout.addStretch()
        return panel
    
    def setup_simple_device_table(self):
        """Setup a simple device table"""
        # Set table properties
        self.device_table.setColumnCount(6)
        self.device_table.setHorizontalHeaderLabels([
            "IP Address", "MAC Address", "Hostname", "Status", "Last Seen", "Actions"
        ])
        
        # Set table style
        self.device_table.setStyleSheet("""
            QTableWidget {
                background-color: #2d2d2d;
                color: #ffffff;
                gridline-color: #555555;
                border: 1px solid #555555;
                border-radius: 4px;
            }
            QTableWidget::item {
                padding: 4px;
                border-bottom: 1px solid #404040;
            }
            QTableWidget::item:selected {
                background-color: #4CAF50;
                color: white;
            }
            QHeaderView::section {
                background-color: #404040;
                color: #ffffff;
                padding: 8px;
                border: none;
                border-right: 1px solid #555555;
                border-bottom: 1px solid #555555;
                font-weight: bold;
            }
        """)
        
        # Enable selection
        self.device_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.device_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        
        # Set column widths
        header = self.device_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)  # IP
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)  # MAC
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)  # Hostname
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)  # Status
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)  # Last Seen
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)          # Actions
        
        # Connect selection change signal
        self.device_table.selectionModel().selectionChanged.connect(self.on_device_selection_changed)
    
    def apply_simple_styling(self):
        """Apply simple styling to the widget"""
        self.setStyleSheet("""
            QWidget {
                background-color: #1e1e1e;
                color: #ffffff;
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 10px;
            }
        """)
    
    def connect_signals(self):
        """Connect all button signals"""
        self.scan_button.clicked.connect(self.start_scan)
        self.stop_button.clicked.connect(self.stop_scan)
        self.disconnect_button.clicked.connect(self.disconnect_selected_device)
        self.reconnect_button.clicked.connect(self.reconnect_selected_device)
        self.clear_button.clicked.connect(self.clear_devices)
    
    def start_scan(self):
        """Start network scanning"""
        try:
            # Get network range (simplified - use local network)
            network_range = self._get_local_network()
            
            if not network_range:
                self.update_status("❌ Could not determine network range")
                return
            
            # Create and start scanner thread
            self.scanner_thread = NetworkScannerThread(network_range)
            self.scanner_thread.device_found.connect(self.add_device)
            self.scanner_thread.scan_progress.connect(self.update_progress)
            self.scanner_thread.scan_complete.connect(self.scan_finished)
            self.scanner_thread.scan_error.connect(self.scan_error)
            
            # Clear previous results
            self.devices.clear()
            self.device_table.setRowCount(0)
            
            # Update UI
            self.scan_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)
            self.update_status("🔍 Scanning network...")
            
            # Start scan
            self.scanner_thread.start()
            
        except Exception as e:
            log_error(f"Error starting scan: {e}")
            self.update_status(f"❌ Error: {str(e)}")
    
    def stop_scan(self):
        """Stop network scanning"""
        try:
            if self.scanner_thread and self.scanner_thread.isRunning():
                self.scanner_thread.stop()
                self.scanner_thread.wait(5000)  # Wait up to 5 seconds
                
            # Update UI
            self.scan_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.progress_bar.setVisible(False)
            self.update_status("⏹️ Scan stopped")
            
        except Exception as e:
            log_error(f"Error stopping scan: {e}")
    
    def add_device(self, device_info: dict):
        """Add a device to the table"""
        try:
            # Add to devices list
            self.devices.append(device_info)
            
            # Add to table
            row = self.device_table.rowCount()
            self.device_table.insertRow(row)
            
            # Set device data
            self.device_table.setItem(row, 0, QTableWidgetItem(device_info.get('ip', '')))
            self.device_table.setItem(row, 1, QTableWidgetItem(device_info.get('mac', '')))
            self.device_table.setItem(row, 2, QTableWidgetItem(device_info.get('hostname', '')))
            self.device_table.setItem(row, 3, QTableWidgetItem(device_info.get('status', '')))
            self.device_table.setItem(row, 4, QTableWidgetItem(device_info.get('last_seen', '')))
            
            # Create action buttons
            action_widget = self.create_action_buttons(row)
            self.device_table.setCellWidget(row, 5, action_widget)
            
            # Update status
            self.update_status(f"✅ Found device: {device_info.get('ip', '')}")
            
        except Exception as e:
            log_error(f"Error adding device: {e}")
    
    def create_action_buttons(self, row: int) -> QWidget:
        """Create action buttons for a device row"""
        widget = QWidget()
        layout = QHBoxLayout()
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        
        # Disconnect button
        disconnect_btn = QPushButton("🔌")
        disconnect_btn.setToolTip("Disconnect this device")
        disconnect_btn.setStyleSheet("""
            QPushButton {
                background-color: #ff9800;
                color: white;
                border: none;
                border-radius: 3px;
                padding: 4px;
                min-width: 20px;
                max-width: 20px;
                min-height: 20px;
                max-height: 20px;
            }
            QPushButton:hover {
                background-color: #f57c00;
            }
        """)
        disconnect_btn.clicked.connect(lambda: self.disconnect_device_at_row(row))
        layout.addWidget(disconnect_btn)
        
        # Reconnect button
        reconnect_btn = QPushButton("🔌")
        reconnect_btn.setToolTip("Reconnect this device")
        reconnect_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196f3;
                color: white;
                border: none;
                border-radius: 3px;
                padding: 4px;
                min-width: 20px;
                max-width: 20px;
                min-height: 20px;
                max-height: 20px;
            }
            QPushButton:hover {
                background-color: #1976d2;
            }
        """)
        reconnect_btn.clicked.connect(lambda: self.reconnect_device_at_row(row))
        layout.addWidget(reconnect_btn)
        
        layout.addStretch()
        widget.setLayout(layout)
        return widget
    
    def disconnect_device_at_row(self, row: int):
        """Disconnect device at specific row"""
        try:
            if row < len(self.devices):
                device = self.devices[row]
                ip = device.get('ip', '')
                
                if not ip:
                    self.update_status("❌ No IP address found for device")
                    return
                
                # Check if device is already disconnected
                if device.get('disconnected', False):
                    self.update_status(f"⚠️ Device {ip} is already disconnected")
                    return
                
                self.update_status(f"🔄 Disconnecting device {ip}...")
                
                # Try to disconnect using available disruptors
                success = False
                
                try:
                    if self.clumsy_network_disruptor:
                        if self.clumsy_network_disruptor.disconnect_device_clumsy(ip, ["drop", "lag"]):
                            success = True
                            log_info(f"Device {ip} disconnected using Clumsy")
                except Exception as e:
                    log_error(f"Clumsy disconnect error for {ip}: {e}")
                
                if not success and self.enterprise_network_disruptor:
                    try:
                        if self.enterprise_network_disruptor.disconnect_device_enterprise(ip, ["arp_spoof", "icmp_flood"]):
                            success = True
                            log_info(f"Device {ip} disconnected using Enterprise")
                    except Exception as e:
                        log_error(f"Enterprise disconnect error for {ip}: {e}")
                
                if success:
                    # Update device status
                    device['disconnected'] = True
                    device['status'] = 'Disconnected'
                    
                    # Update table display
                    self.update_device_row(row)
                    
                    # Update button states
                    self.on_device_selection_changed()
                    
                    self.update_status(f"✅ Device {ip} disconnected successfully")
                else:
                    self.update_status(f"❌ Failed to disconnect device {ip}")
                    
        except Exception as e:
            log_error(f"Error disconnecting device at row {row}: {e}")
            self.update_status(f"❌ Error: {str(e)}")
    
    def reconnect_device_at_row(self, row: int):
        """Reconnect device at specific row"""
        try:
            if row < len(self.devices):
                device = self.devices[row]
                ip = device.get('ip', '')
                
                if not ip:
                    self.update_status("❌ No IP address found for device")
                    return
                
                # Check if device is already connected
                if not device.get('disconnected', False):
                    self.update_status(f"⚠️ Device {ip} is already connected")
                    return
                
                self.update_status(f"🔄 Reconnecting device {ip}...")
                
                # Try to reconnect using available disruptors
                success = False
                
                try:
                    if self.clumsy_network_disruptor:
                        if self.clumsy_network_disruptor.reconnect_device_clumsy(ip):
                            success = True
                            log_info(f"Device {ip} reconnected using Clumsy")
                except Exception as e:
                    log_error(f"Clumsy reconnection error for {ip}: {e}")
                
                if not success and self.enterprise_network_disruptor:
                    try:
                        if self.enterprise_network_disruptor.reconnect_device_enterprise(ip):
                            success = True
                            log_info(f"Device {ip} reconnected using Enterprise")
                    except Exception as e:
                        log_error(f"Enterprise reconnection error for {ip}: {e}")
                
                if success:
                    # Update device status
                    device['disconnected'] = False
                    device['status'] = 'Online'
                    
                    # Update table display
                    self.update_device_row(row)
                    
                    # Update button states
                    self.on_device_selection_changed()
                    
                    self.update_status(f"✅ Device {ip} reconnected successfully")
                else:
                    self.update_status(f"❌ Failed to reconnect device {ip}")
                    
        except Exception as e:
            log_error(f"Error reconnecting device at row {row}: {e}")
            self.update_status(f"❌ Error: {str(e)}")
    
    def disconnect_selected_device(self):
        """Disconnect only the selected device (not all devices)"""
        try:
            selected_rows = self.device_table.selectionModel().selectedRows()
            if not selected_rows:
                self.update_status("❌ No device selected")
                return
            
            row = selected_rows[0].row()
            self.disconnect_device_at_row(row)
            
        except Exception as e:
            log_error(f"Error disconnecting selected device: {e}")
            self.update_status(f"❌ Error: {str(e)}")
    
    def reconnect_selected_device(self):
        """Reconnect only the selected device (not all devices)"""
        try:
            selected_rows = self.device_table.selectionModel().selectedRows()
            if not selected_rows:
                self.update_status("❌ No device selected")
                return
            
            row = selected_rows[0].row()
            self.reconnect_device_at_row(row)
            
        except Exception as e:
            log_error(f"Error reconnecting selected device: {e}")
            self.update_status(f"❌ Error: {str(e)}")
    
    def on_device_selection_changed(self):
        """Handle device selection change to enable/disable buttons"""
        try:
            selected_rows = self.device_table.selectionModel().selectedRows()
            has_selection = len(selected_rows) > 0
            
            # Enable/disable disconnect and reconnect buttons based on selection
            self.disconnect_button.setEnabled(has_selection)
            self.reconnect_button.setEnabled(has_selection)
            
            # If a device is selected, check its current status
            if has_selection:
                row = selected_rows[0].row()
                if row < len(self.devices):
                    device = self.devices[row]
                    is_disconnected = device.get('disconnected', False)
                    
                    # Enable appropriate button based on current status
                    self.disconnect_button.setEnabled(not is_disconnected)
                    self.reconnect_button.setEnabled(is_disconnected)
                    
        except Exception as e:
            log_error(f"Error handling device selection change: {e}")
    
    def update_device_row(self, row: int):
        """Update the display of a device row"""
        try:
            if row < len(self.devices):
                device = self.devices[row]
                
                # Update status column
                status_item = QTableWidgetItem(device.get('status', 'Unknown'))
                if device.get('disconnected', False):
                    status_item.setForeground(QColor('#ff9800'))  # Orange for disconnected
                else:
                    status_item.setForeground(QColor('#4caf50'))  # Green for online
                
                self.device_table.setItem(row, 3, status_item)
                
                # Update action buttons
                action_widget = self.create_action_buttons(row)
                self.device_table.setCellWidget(row, 5, action_widget)
                
        except Exception as e:
            log_error(f"Error updating device row {row}: {e}")
    
    def clear_devices(self):
        """Clear all devices from the table"""
        try:
            # Clear devices list
            self.devices.clear()
            
            # Clear table
            self.device_table.setRowCount(0)
            
            # Update status
            self.update_status("🗑️ All devices cleared")
            
            # Update button states
            self.on_device_selection_changed()
            
        except Exception as e:
            log_error(f"Error clearing devices: {e}")
            self.update_status(f"❌ Error: {str(e)}")
    
    def update_progress(self, value: int):
        """Update scan progress bar"""
        try:
            self.progress_bar.setValue(value)
        except Exception as e:
            log_error(f"Error updating progress: {e}")
    
    def scan_finished(self):
        """Handle scan completion"""
        try:
            # Update UI
            self.scan_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.progress_bar.setVisible(False)
            
            # Update status
            device_count = len(self.devices)
            if device_count > 0:
                self.update_status(f"✅ Scan complete! Found {device_count} devices")
            else:
                self.update_status("⚠️ Scan complete! No devices found")
                
        except Exception as e:
            log_error(f"Error handling scan completion: {e}")
    
    def scan_error(self, error_msg: str):
        """Handle scan error"""
        try:
            # Update UI
            self.scan_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.progress_bar.setVisible(False)
            
            # Update status
            self.update_status(f"❌ Scan error: {error_msg}")
            
        except Exception as e:
            log_error(f"Error handling scan error: {e}")
    
    def update_status(self, message: str):
        """Update status label"""
        try:
            self.status_label.setText(message)
            log_info(f"Status: {message}")
        except Exception as e:
            log_error(f"Error updating status: {e}")
    
    def _get_local_network(self) -> str:
        """Get local network range (simplified)"""
        try:
            # For Windows, try to get local network
            if platform.system() == "Windows":
                # Try to get local IP and determine network
                result = subprocess.run('ipconfig', shell=True, capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    lines = result.stdout.split('\n')
                    for line in lines:
                        if 'IPv4 Address' in line and '192.168.' in line:
                            # Extract IP and return network
                            parts = line.split(':')
                            if len(parts) > 1:
                                ip = parts[1].strip()
                                network = ip.rsplit('.', 1)[0]
                                return f"{network}.0/24"
            
            # Fallback to common local networks
            return "192.168.1.0/24"
            
        except Exception as e:
            log_error(f"Error getting local network: {e}")
            return "192.168.1.0/24"


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle('Fusion')  # Use Fusion style for consistent look
    
    # Create and show the scanner
    scanner = SimplifiedNetworkScanner()
    scanner.show()
    
    sys.exit(app.exec())

