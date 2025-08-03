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
        
        # Connect resize event for responsive design
        self.resizeEvent = self.on_resize
        
    def setup_ui(self):
        """Setup the enhanced device list UI with responsive design"""
        layout = QVBoxLayout()
        layout.setSpacing(10)  # Add spacing between elements
        layout.setContentsMargins(10, 10, 10, 10)  # Add margins
        self.setLayout(layout)
        
        # Title with responsive font
        title = QLabel("🔍 Enhanced Network Scanner")
        title.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("padding: 10px; margin-bottom: 10px;")
        layout.addWidget(title)
        
        # Control panel
        control_panel = self.create_control_panel()
        layout.addWidget(control_panel)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #404040;
                border-radius: 5px;
                text-align: center;
                font-weight: bold;
                height: 20px;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                border-radius: 3px;
            }
        """)
        layout.addWidget(self.progress_bar)
        
        # Device table with responsive sizing
        self.device_table = QTableWidget()
        self.setup_device_table()
        layout.addWidget(self.device_table, 1)  # Give table more space
        
        # Status indicators in a horizontal layout
        status_layout = QHBoxLayout()
        
        # Status bar
        self.status_label = QLabel("Ready to scan network")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.status_label.setStyleSheet("""
            color: #4CAF50; 
            font-weight: bold; 
            padding: 5px;
            background-color: rgba(76, 175, 80, 0.1);
            border-radius: 3px;
        """)
        status_layout.addWidget(self.status_label)
        
        # Blocking status indicator
        self.blocking_status = QLabel("🔒 Blocking: Inactive")
        self.blocking_status.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.blocking_status.setStyleSheet("""
            color: #FF9800; 
            font-weight: bold; 
            padding: 5px;
            background-color: rgba(255, 152, 0, 0.1);
            border-radius: 3px;
        """)
        self.blocking_status.setToolTip("Shows current blocking status. Double-click IP addresses to toggle blocking.")
        status_layout.addWidget(self.blocking_status)
        
        layout.addLayout(status_layout)
        
        # Apply responsive styling
        self.apply_styling()
    
    def on_resize(self, event):
        """Handle resize events for responsive design"""
        super().resizeEvent(event)
        
        # Update table column widths when window is resized
        if hasattr(self, 'device_table') and self.device_table:
            total_width = self.device_table.width()
            if total_width > 0:
                # Recalculate responsive column widths
                column_widths = {
                    0: int(total_width * 0.12),  # IP Address
                    1: int(total_width * 0.15),  # MAC Address
                    2: int(total_width * 0.20),  # Hostname (stretch)
                    3: int(total_width * 0.15),  # Vendor
                    4: int(total_width * 0.12),  # Device Type
                    5: int(total_width * 0.10),  # Interface
                    6: int(total_width * 0.08),  # Open Ports
                    7: int(total_width * 0.08)   # Status
                }
                
                # Apply new column widths
                header = self.device_table.horizontalHeader()
                for col, width in column_widths.items():
                    if col != 2:  # Don't resize stretch column
                        self.device_table.setColumnWidth(col, width)
    
    def create_control_panel(self) -> QWidget:
        """Create the control panel with responsive scan options"""
        panel = QWidget()
        panel.setStyleSheet("""
            QWidget {
                background-color: #2d2d2d;
                border: 2px solid #404040;
                border-radius: 8px;
                padding: 10px;
                margin: 5px;
            }
        """)
        
        # Use QGridLayout for better organization
        layout = QGridLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)
        panel.setLayout(layout)
        
        # Row 1: Main scan controls
        self.scan_button = QPushButton("🔍 Start Enhanced Scan")
        self.scan_button.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        self.scan_button.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: 2px solid #45a049;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
                min-height: 30px;
            }
            QPushButton:hover {
                background-color: #45a049;
                border-color: #3d8b40;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
        """)
        self.scan_button.clicked.connect(self.start_scan)
        layout.addWidget(self.scan_button, 0, 0, 1, 2)
        
        self.stop_button = QPushButton("⏹️ Stop Scan")
        self.stop_button.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        self.stop_button.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border: 2px solid #d32f2f;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
                min-height: 30px;
            }
            QPushButton:hover {
                background-color: #d32f2f;
                border-color: #c62828;
            }
            QPushButton:pressed {
                background-color: #c62828;
            }
        """)
        self.stop_button.clicked.connect(self.stop_scan)
        self.stop_button.setEnabled(False)
        layout.addWidget(self.stop_button, 0, 2, 1, 2)
        
        # Row 2: Scan settings
        thread_label = QLabel("Threads:")
        thread_label.setStyleSheet("color: #ffffff; font-weight: bold;")
        layout.addWidget(thread_label, 1, 0)
        
        self.thread_spinbox = QSpinBox()
        self.thread_spinbox.setRange(10, 100)
        self.thread_spinbox.setValue(50)
        self.thread_spinbox.setToolTip("Number of concurrent scan threads")
        self.thread_spinbox.setStyleSheet("""
            QSpinBox {
                background-color: #3d3d3d;
                color: #ffffff;
                border: 2px solid #404040;
                border-radius: 4px;
                padding: 5px;
                min-height: 25px;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                background-color: #505050;
                border: 1px solid #404040;
                border-radius: 2px;
            }
        """)
        layout.addWidget(self.thread_spinbox, 1, 1)
        
        timeout_label = QLabel("Timeout (ms):")
        timeout_label.setStyleSheet("color: #ffffff; font-weight: bold;")
        layout.addWidget(timeout_label, 1, 2)
        
        self.timeout_spinbox = QSpinBox()
        self.timeout_spinbox.setRange(500, 5000)
        self.timeout_spinbox.setValue(1000)
        self.timeout_spinbox.setSuffix(" ms")
        self.timeout_spinbox.setToolTip("Scan timeout per IP")
        self.timeout_spinbox.setStyleSheet("""
            QSpinBox {
                background-color: #3d3d3d;
                color: #ffffff;
                border: 2px solid #404040;
                border-radius: 4px;
                padding: 5px;
                min-height: 25px;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                background-color: #505050;
                border: 1px solid #404040;
                border-radius: 2px;
            }
        """)
        layout.addWidget(self.timeout_spinbox, 1, 3)
        
        # Row 3: Options and actions
        self.advanced_checkbox = QCheckBox("Advanced Scan")
        self.advanced_checkbox.setToolTip("Use advanced scanning methods")
        self.advanced_checkbox.setChecked(True)
        self.advanced_checkbox.setStyleSheet("""
            QCheckBox {
                color: #ffffff;
                font-weight: bold;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border: 2px solid #404040;
                border-radius: 3px;
                background-color: #3d3d3d;
            }
            QCheckBox::indicator:checked {
                background-color: #4CAF50;
                border-color: #4CAF50;
            }
        """)
        layout.addWidget(self.advanced_checkbox, 2, 0)
        
        self.clear_button = QPushButton("🗑️ Clear")
        self.clear_button.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        self.clear_button.setStyleSheet("""
            QPushButton {
                background-color: #ff9800;
                color: white;
                border: 2px solid #f57c00;
                border-radius: 6px;
                padding: 6px 12px;
                font-weight: bold;
                min-height: 25px;
            }
            QPushButton:hover {
                background-color: #f57c00;
                border-color: #ef6c00;
            }
        """)
        self.clear_button.clicked.connect(self.clear_devices)
        layout.addWidget(self.clear_button, 2, 1)
        
        self.block_button = QPushButton("🚫 Block Selected")
        self.block_button.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        self.block_button.setStyleSheet("""
            QPushButton {
                background-color: #e91e63;
                color: white;
                border: 2px solid #c2185b;
                border-radius: 6px;
                padding: 6px 12px;
                font-weight: bold;
                min-height: 25px;
            }
            QPushButton:hover {
                background-color: #c2185b;
                border-color: #ad1457;
            }
        """)
        self.block_button.clicked.connect(self.block_selected)
        layout.addWidget(self.block_button, 2, 2)
        
        # Global blocking controls
        layout.addWidget(QLabel("|"))
        
        # Global block/unblock all button
        self.global_block_button = QPushButton("🔒 Block All")
        self.global_block_button.setFont(QFont("Arial", 12))
        self.global_block_button.clicked.connect(self.block_all_devices)
        layout.addWidget(self.global_block_button)
        
        self.global_unblock_button = QPushButton("🔓 Unblock All")
        self.global_unblock_button.setFont(QFont("Arial", 12))
        self.global_unblock_button.clicked.connect(self.unblock_all_devices)
        layout.addWidget(self.global_unblock_button)
        
        # Clear all blocks button
        self.clear_blocks_button = QPushButton("🧹 Clear All Blocks")
        self.clear_blocks_button.setFont(QFont("Arial", 12))
        self.clear_blocks_button.clicked.connect(self.clear_all_blocks)
        layout.addWidget(self.clear_blocks_button)
        
        # Internet drop toggle
        layout.addWidget(QLabel("|"))
        
        self.internet_drop_button = QPushButton("🌐 Drop Internet")
        self.internet_drop_button.setFont(QFont("Arial", 12))
        self.internet_drop_button.setStyleSheet("""
            QPushButton {
                background-color: #ff4444;
                color: white;
                border: 2px solid #cc0000;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #ff6666;
                border-color: #ff0000;
            }
            QPushButton:pressed {
                background-color: #cc0000;
                border-color: #990000;
            }
        """)
        self.internet_drop_button.clicked.connect(self.toggle_internet_drop)
        layout.addWidget(self.internet_drop_button)
        
        layout.addStretch()
        return panel
    
    def setup_device_table(self):
        """Setup the device table with responsive columns"""
        # Set up table headers
        headers = [
            "IP Address", "MAC Address", "Hostname", "Vendor", 
            "Device Type", "Interface", "Open Ports", "Status"
        ]
        self.device_table.setColumnCount(len(headers))
        self.device_table.setHorizontalHeaderLabels(headers)
        
        # Set up table properties
        self.device_table.setAlternatingRowColors(True)
        self.device_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.device_table.setSortingEnabled(True)
        self.device_table.setWordWrap(True)  # Enable word wrapping
        self.device_table.setShowGrid(True)
        self.device_table.setGridStyle(Qt.PenStyle.SolidLine)
        
        # Set responsive column widths
        header = self.device_table.horizontalHeader()
        header.setStretchLastSection(False)
        
        # Calculate responsive column widths
        total_width = self.device_table.width() if self.device_table.width() > 0 else 1200
        column_widths = {
            0: int(total_width * 0.12),  # IP Address
            1: int(total_width * 0.15),  # MAC Address
            2: int(total_width * 0.20),  # Hostname (stretch)
            3: int(total_width * 0.15),  # Vendor
            4: int(total_width * 0.12),  # Device Type
            5: int(total_width * 0.10),  # Interface
            6: int(total_width * 0.08),  # Open Ports
            7: int(total_width * 0.08)   # Status
        }
        
        # Apply column widths
        for col, width in column_widths.items():
            self.device_table.setColumnWidth(col, width)
            if col == 2:  # Hostname column stretches
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
            else:
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
        
        # Set table styling
        self.device_table.setStyleSheet("""
            QTableWidget {
                background-color: #2d2d2d;
                color: #ffffff;
                gridline-color: #404040;
                border: 2px solid #404040;
                border-radius: 6px;
                font-size: 10pt;
                selection-background-color: #4CAF50;
                selection-color: #ffffff;
            }
            QTableWidget::item {
                padding: 6px;
                border-bottom: 1px solid #404040;
            }
            QTableWidget::item:selected {
                background-color: #4CAF50;
                color: #ffffff;
            }
            QHeaderView::section {
                background-color: #3d3d3d;
                color: #ffffff;
                padding: 8px;
                border: 1px solid #404040;
                font-weight: bold;
                font-size: 11pt;
            }
            QHeaderView::section:hover {
                background-color: #505050;
            }
            QScrollBar:vertical {
                background-color: #2d2d2d;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #404040;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #505050;
            }
        """)
        
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
            
            # Get interface information
            interface_info = device.get('interface', {})
            interface_display = f"{interface_info.get('name', 'Unknown')} ({interface_info.get('type', 'Unknown')})"
            
            # Create table items
            items = [
                QTableWidgetItem(device.get('ip', '')),
                QTableWidgetItem(device.get('mac', '')),
                QTableWidgetItem(device.get('hostname', '')),
                QTableWidgetItem(device.get('vendor', '')),
                QTableWidgetItem(device.get('device_type', '')),
                QTableWidgetItem(interface_display),
                QTableWidgetItem(', '.join(map(str, device.get('open_ports', [])))),
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
            status_item = self.device_table.item(row, 7) # Changed from 8 to 7
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
        """Color code device based on type"""
        try:
            device_type = device.get('device_type', '').lower()
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
                
                self.device_table.setItem(row, 7, status_item) # Changed from 8 to 7
                
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
                
                self.device_table.setItem(row, 7, status_item) # Changed from 8 to 7
                
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
        """Actually block/unblock a device using REAL network disruption"""
        try:
            log_info(f"🔍 Starting blocking process for {ip} (block={block})")
            
            if self.controller:
                log_info(f"✅ Controller found, using toggle_lag method")
                # Use the controller's REAL blocking mechanism
                # toggle_lag returns the new blocked state
                new_blocked_state = self.controller.toggle_lag(ip)
                log_info(f"📊 toggle_lag returned: {new_blocked_state}")
                
                if block:
                    # We want to block the device
                    if new_blocked_state:
                        log_info(f"✅ Device {ip} blocked using REAL network disruption")
                        self.update_status(f"Successfully blocked {ip}")
                    else:
                        log_error(f"❌ Failed to block device {ip}")
                        self.update_status(f"Failed to block {ip}")
                else:
                    # We want to unblock the device
                    if not new_blocked_state:
                        log_info(f"✅ Device {ip} unblocked successfully")
                        self.update_status(f"Successfully unblocked {ip}")
                    else:
                        log_error(f"❌ Failed to unblock device {ip}")
                        self.update_status(f"Failed to unblock {ip}")
                
                # Update the device's blocked status in our local list
                for device in self.devices:
                    if device.get('ip') == ip:
                        device['blocked'] = new_blocked_state
                        log_info(f"📝 Updated device {ip} blocked status to {new_blocked_state}")
                        break
                
            else:
                # Fallback to direct firewall blocking
                log_error("❌ No controller available, using fallback blocking")
                self.aggressive_block_device(ip, block)
                
            # Update blocking status indicator
            self.update_blocking_status()
            
        except Exception as e:
            log_error(f"❌ Error blocking device {ip}: {e}")
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
                    self.device_table.setItem(row, 7, status_item) # Changed from 8 to 7
                    
                    # Emit signal
                    self.device_blocked.emit(ip, True)
            
            self.update_status(f"Blocked {len(selected_rows)} selected device(s)")
            
        except Exception as e:
            log_error(f"Error blocking devices: {e}")
    
    def block_all_devices(self):
        """Block all devices in the list"""
        try:
            if not self.devices:
                self.update_status("No devices to block")
                return
            
            # Import PS5 blocker
            from app.firewall.ps5_blocker import ps5_blocker
            
            blocked_count = 0
            ps5_ips = []
            
            for i, device in enumerate(self.devices):
                ip = device.get('ip', '')
                if ip and not device.get('blocked', False):
                    # Check if it's a PS5
                    if self._is_ps5_device(device):
                        ps5_ips.append(ip)
                    
                    # Block this device
                    self.actually_block_device(ip, True)
                    device['blocked'] = True
                    device['status'] = 'Blocked'
                    
                    # Update table display
                    status_item = QTableWidgetItem('Blocked')
                    status_item.setBackground(QColor(255, 100, 100))  # Red
                    status_item.setForeground(QColor(255, 255, 255))  # White text
                    self.device_table.setItem(i, 7, status_item)
                    
                    blocked_count += 1
            
            # Block PS5s specifically
            if ps5_ips:
                ps5_blocker.block_all_ps5s(ps5_ips)
                self.update_status(f"Blocked {blocked_count} devices (including {len(ps5_ips)} PS5s)")
            else:
                self.update_status(f"Blocked {blocked_count} devices")
            
            self.update_blocking_status()
            
        except Exception as e:
            log_error(f"Error blocking all devices: {e}")
            self.update_status(f"Error blocking all devices: {e}")
    
    def _is_ps5_device(self, device: dict) -> bool:
        """Check if device is a PS5"""
        try:
            # Check vendor name
            vendor = device.get('vendor', '').lower()
            if 'sony' in vendor or 'playstation' in vendor or 'ps5' in vendor:
                return True
            
            # Check hostname
            hostname = device.get('hostname', '').lower()
            if 'ps5' in hostname or 'playstation' in hostname:
                return True
            
            # Check MAC address (Sony's OUI)
            mac = device.get('mac', '').lower()
            if mac.startswith(('00:50:c2', '00:1f:a7', '00:19:c5')):
                return True
            
            return False
        except:
            return False
    
    def toggle_internet_drop(self):
        """Toggle internet drop functionality"""
        try:
            from app.firewall.internet_dropper import internet_dropper
            
            if internet_dropper.is_internet_dropped():
                # Restore internet
                success = internet_dropper.restore_internet()
                if success:
                    self.internet_drop_button.setText("🌐 Drop Internet")
                    self.internet_drop_button.setStyleSheet("""
                        QPushButton {
                            background-color: #ff4444;
                            color: white;
                            border: 2px solid #cc0000;
                            border-radius: 6px;
                            padding: 8px 16px;
                            font-weight: bold;
                        }
                        QPushButton:hover {
                            background-color: #ff6666;
                            border-color: #ff0000;
                        }
                        QPushButton:pressed {
                            background-color: #cc0000;
                            border-color: #990000;
                        }
                    """)
                    self.update_status("✅ Internet restored successfully")
                else:
                    self.update_status("❌ Failed to restore internet")
            else:
                # Drop internet
                success = internet_dropper.drop_internet()
                if success:
                    self.internet_drop_button.setText("🌐 Restore Internet")
                    self.internet_drop_button.setStyleSheet("""
                        QPushButton {
                            background-color: #44ff44;
                            color: white;
                            border: 2px solid #00cc00;
                            border-radius: 6px;
                            padding: 8px 16px;
                            font-weight: bold;
                        }
                        QPushButton:hover {
                            background-color: #66ff66;
                            border-color: #00ff00;
                        }
                        QPushButton:pressed {
                            background-color: #00cc00;
                            border-color: #009900;
                        }
                    """)
                    self.update_status("🛑 Internet dropped successfully")
                else:
                    self.update_status("❌ Failed to drop internet")
                    
        except Exception as e:
            log_error(f"Error toggling internet drop: {e}")
            self.update_status(f"Error toggling internet drop: {e}")
    
    def unblock_all_devices(self):
        """Unblock all devices in the list"""
        try:
            if not self.devices:
                self.update_status("No devices to unblock")
                return
            
            # Import PS5 blocker
            from app.firewall.ps5_blocker import ps5_blocker
            
            unblocked_count = 0
            ps5_ips = []
            
            for i, device in enumerate(self.devices):
                ip = device.get('ip', '')
                if ip and device.get('blocked', False):
                    # Check if it's a PS5
                    if self._is_ps5_device(device):
                        ps5_ips.append(ip)
                    
                    # Unblock this device
                    self.actually_block_device(ip, False)
                    device['blocked'] = False
                    device['status'] = 'Online'
                    
                    # Update table display
                    status_item = QTableWidgetItem('Online')
                    status_item.setBackground(QColor(100, 255, 100))  # Green
                    status_item.setForeground(QColor(0, 0, 0))  # Black text
                    self.device_table.setItem(i, 7, status_item)
                    
                    unblocked_count += 1
            
            # Unblock PS5s specifically
            if ps5_ips:
                ps5_blocker.unblock_all_ps5s(ps5_ips)
                self.update_status(f"Unblocked {unblocked_count} devices (including {len(ps5_ips)} PS5s)")
            else:
                self.update_status(f"Unblocked {unblocked_count} devices")
            
            self.update_blocking_status()
            
        except Exception as e:
            log_error(f"Error unblocking all devices: {e}")
            self.update_status(f"Error unblocking all devices: {e}")
    
    def clear_all_blocks(self):
        """Clear all blocks and restore network"""
        try:
            from app.firewall.blocker import clear_all_blocks
            from app.firewall.ps5_blocker import ps5_blocker
            
            # Clear all blocks using the blocker module
            success = clear_all_blocks()
            
            # Clear PS5 blocks specifically
            ps5_success = ps5_blocker.clear_all_ps5_blocks()
            
            if success and ps5_success:
                # Update all devices to unblocked status
                for i, device in enumerate(self.devices):
                    device['blocked'] = False
                    device['status'] = 'Online'
                    
                    # Update table display
                    status_item = QTableWidgetItem('Online')
                    status_item.setBackground(QColor(100, 255, 100))  # Green
                    status_item.setForeground(QColor(0, 0, 0))  # Black text
                    self.device_table.setItem(i, 7, status_item)
                
                self.update_status("All blocks cleared successfully (including PS5s)")
                self.update_blocking_status()
            else:
                self.update_status("Failed to clear all blocks")
                
        except Exception as e:
            log_error(f"Error clearing all blocks: {e}")
            self.update_status(f"Error clearing blocks: {e}")
    
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