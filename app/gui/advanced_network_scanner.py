# app/gui/advanced_network_scanner.py

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QListWidget, QListWidgetItem,
                             QProgressBar, QTextEdit, QSplitter, QFrame,
                             QHeaderView, QTableWidget, QTableWidgetItem,
                             QComboBox, QSpinBox, QCheckBox, QGroupBox,
                             QSlider, QTabWidget, QTreeWidget, QTreeWidgetItem,
                             QMenu, QInputDialog, QMessageBox)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread
from PyQt6.QtGui import QFont, QColor, QIcon, QPixmap, QAction
import time
import json
import os
from typing import List, Dict, Optional

from app.network.enhanced_scanner import get_enhanced_scanner, cleanup_enhanced_scanner
from app.logs.logger import log_info, log_error

class AdvancedNetworkScanner(QWidget):
    """Advanced network scanner with Angry IP Scanner + Clumsy 3.0 features"""
    
    # Signals
    device_selected = pyqtSignal(dict)
    device_blocked = pyqtSignal(str, bool)
    scan_started = pyqtSignal()
    scan_finished = pyqtSignal(list)
    traffic_control = pyqtSignal(str, dict)  # IP, traffic settings
    
    def __init__(self, controller=None):
        super().__init__()
        self.controller = controller
        self.scanner = get_enhanced_scanner()
        self.devices = []
        self.scan_profiles = self.load_scan_profiles()
        self.traffic_profiles = self.load_traffic_profiles()
        self.setup_ui()
        self.connect_signals()
        
    def setup_ui(self):
        """Setup the advanced scanner UI with Angry IP Scanner + Clumsy 3.0 features"""
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        # Title with Angry IP Scanner style
        title = QLabel("⚡ Advanced Network Scanner - Angry IP Scanner + Clumsy 3.0")
        title.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #FF6B35; margin: 10px;")
        layout.addWidget(title)
        
        # Main splitter for Angry IP Scanner layout
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(main_splitter)
        
        # Left panel - Scan controls (Angry IP Scanner style)
        left_panel = self.create_scan_controls()
        main_splitter.addWidget(left_panel)
        
        # Right panel - Results and traffic control
        right_panel = self.create_results_panel()
        main_splitter.addWidget(right_panel)
        
        # Set splitter proportions (Angry IP Scanner style)
        main_splitter.setSizes([300, 700])
        
        # Status bar
        self.status_label = QLabel("Ready to scan network")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold; padding: 5px;")
        layout.addWidget(self.status_label)
        
        # Apply styling
        self.apply_angry_ip_style()
        
    def create_scan_controls(self) -> QWidget:
        """Create scan controls panel (Angry IP Scanner style)"""
        panel = QWidget()
        layout = QVBoxLayout()
        panel.setLayout(layout)
        
        # Scan range group
        range_group = QGroupBox("📡 Scan Range")
        range_layout = QVBoxLayout()
        range_group.setLayout(range_layout)
        
        # IP range inputs
        ip_layout = QHBoxLayout()
        ip_layout.addWidget(QLabel("From:"))
        self.ip_from = QComboBox()
        self.ip_from.setEditable(True)
        self.ip_from.addItems(["192.168.1.1", "10.0.0.1", "172.16.0.1"])
        ip_layout.addWidget(self.ip_from)
        
        ip_layout.addWidget(QLabel("To:"))
        self.ip_to = QComboBox()
        self.ip_to.setEditable(True)
        self.ip_to.addItems(["192.168.1.254", "10.0.0.254", "172.16.0.254"])
        ip_layout.addWidget(self.ip_to)
        range_layout.addLayout(ip_layout)
        
        # Quick range buttons
        quick_layout = QHBoxLayout()
        quick_layout.addWidget(QPushButton("Local Network", clicked=lambda: self.set_local_range()))
        quick_layout.addWidget(QPushButton("Custom Range", clicked=lambda: self.set_custom_range()))
        range_layout.addLayout(quick_layout)
        layout.addWidget(range_group)
        
        # Scan options group
        options_group = QGroupBox("⚙️ Scan Options")
        options_layout = QVBoxLayout()
        options_group.setLayout(options_layout)
        
        # Thread count
        thread_layout = QHBoxLayout()
        thread_layout.addWidget(QLabel("Threads:"))
        self.thread_slider = QSlider(Qt.Orientation.Horizontal)
        self.thread_slider.setRange(10, 200)
        self.thread_slider.setValue(50)
        self.thread_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.thread_slider.setTickInterval(10)
        thread_layout.addWidget(self.thread_slider)
        self.thread_label = QLabel("50")
        self.thread_slider.valueChanged.connect(lambda v: self.thread_label.setText(str(v)))
        thread_layout.addWidget(self.thread_label)
        options_layout.addLayout(thread_layout)
        
        # Timeout
        timeout_layout = QHBoxLayout()
        timeout_layout.addWidget(QLabel("Timeout (ms):"))
        self.timeout_spinbox = QSpinBox()
        self.timeout_spinbox.setRange(100, 10000)
        self.timeout_spinbox.setValue(1000)
        self.timeout_spinbox.setSuffix(" ms")
        timeout_layout.addWidget(self.timeout_spinbox)
        options_layout.addLayout(timeout_layout)
        
        # Scan methods
        methods_group = QGroupBox("🔍 Scan Methods")
        methods_layout = QVBoxLayout()
        methods_group.setLayout(methods_layout)
        
        self.ping_checkbox = QCheckBox("Ping (ICMP)")
        self.ping_checkbox.setChecked(True)
        methods_layout.addWidget(self.ping_checkbox)
        
        self.tcp_checkbox = QCheckBox("TCP Connect")
        self.tcp_checkbox.setChecked(True)
        methods_layout.addWidget(self.tcp_checkbox)
        
        self.arp_checkbox = QCheckBox("ARP Scan")
        self.arp_checkbox.setChecked(True)
        methods_layout.addWidget(self.arp_checkbox)
        
        self.udp_checkbox = QCheckBox("UDP Scan")
        self.udp_checkbox.setChecked(False)
        methods_layout.addWidget(self.udp_checkbox)
        
        options_layout.addWidget(methods_group)
        layout.addWidget(options_group)
        
        # Scan profiles
        profiles_group = QGroupBox("📋 Scan Profiles")
        profiles_layout = QVBoxLayout()
        profiles_group.setLayout(profiles_layout)
        
        self.profile_combo = QComboBox()
        self.profile_combo.addItems(list(self.scan_profiles.keys()))
        self.profile_combo.currentTextChanged.connect(self.load_profile)
        profiles_layout.addWidget(self.profile_combo)
        
        profile_buttons = QHBoxLayout()
        profile_buttons.addWidget(QPushButton("Save Profile", clicked=self.save_profile))
        profile_buttons.addWidget(QPushButton("Delete Profile", clicked=self.delete_profile))
        profiles_layout.addLayout(profile_buttons)
        layout.addWidget(profiles_group)
        
        # Control buttons
        control_group = QGroupBox("🎮 Controls")
        control_layout = QVBoxLayout()
        control_group.setLayout(control_layout)
        
        self.scan_button = QPushButton("🔍 Start Scan")
        self.scan_button.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        self.scan_button.clicked.connect(self.start_scan)
        control_layout.addWidget(self.scan_button)
        
        self.stop_button = QPushButton("⏹️ Stop Scan")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_scan)
        control_layout.addWidget(self.stop_button)
        
        self.clear_button = QPushButton("🗑️ Clear Results")
        self.clear_button.clicked.connect(self.clear_results)
        control_layout.addWidget(self.clear_button)
        
        layout.addWidget(control_group)
        layout.addStretch()
        
        return panel
        
    def create_results_panel(self) -> QWidget:
        """Create results panel with traffic control"""
        panel = QWidget()
        layout = QVBoxLayout()
        panel.setLayout(layout)
        
        # Results tabs
        self.results_tabs = QTabWidget()
        layout.addWidget(self.results_tabs)
        
        # Devices tab
        self.devices_tab = self.create_devices_tab()
        self.results_tabs.addTab(self.devices_tab, "📱 Devices")
        
        # Traffic control tab (Clumsy 3.0 style)
        self.traffic_tab = self.create_traffic_tab()
        self.results_tabs.addTab(self.traffic_tab, "🌊 Traffic Control")
        
        # Statistics tab
        self.stats_tab = self.create_stats_tab()
        self.results_tabs.addTab(self.stats_tab, "📊 Statistics")
        
        return panel
        
    def create_devices_tab(self) -> QWidget:
        """Create devices tab with Angry IP Scanner style table"""
        tab = QWidget()
        layout = QVBoxLayout()
        tab.setLayout(layout)
        
        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.addWidget(QPushButton("Export", clicked=self.export_devices))
        toolbar.addWidget(QPushButton("Block Selected", clicked=self.block_selected))
        toolbar.addWidget(QPushButton("Unblock All", clicked=self.unblock_all))
        toolbar.addStretch()
        layout.addLayout(toolbar)
        
        # Device table
        self.device_table = QTableWidget()
        self.setup_device_table()
        layout.addWidget(self.device_table)
        
        return tab
        
    def create_traffic_tab(self) -> QWidget:
        """Create traffic control tab (Clumsy 3.0 style)"""
        tab = QWidget()
        layout = QVBoxLayout()
        tab.setLayout(layout)
        
        # Traffic control group
        control_group = QGroupBox("🌊 Traffic Control (Clumsy 3.0 Style)")
        control_layout = QVBoxLayout()
        control_group.setLayout(control_layout)
        
        # Latency control
        latency_layout = QHBoxLayout()
        latency_layout.addWidget(QLabel("Latency (ms):"))
        self.latency_slider = QSlider(Qt.Orientation.Horizontal)
        self.latency_slider.setRange(0, 1000)
        self.latency_slider.setValue(0)
        latency_layout.addWidget(self.latency_slider)
        self.latency_label = QLabel("0ms")
        self.latency_slider.valueChanged.connect(lambda v: self.latency_label.setText(f"{v}ms"))
        latency_layout.addWidget(self.latency_label)
        control_layout.addLayout(latency_layout)
        
        # Jitter control
        jitter_layout = QHBoxLayout()
        jitter_layout.addWidget(QLabel("Jitter (ms):"))
        self.jitter_slider = QSlider(Qt.Orientation.Horizontal)
        self.jitter_slider.setRange(0, 500)
        self.jitter_slider.setValue(0)
        jitter_layout.addWidget(self.jitter_slider)
        self.jitter_label = QLabel("0ms")
        self.jitter_slider.valueChanged.connect(lambda v: self.jitter_label.setText(f"{v}ms"))
        jitter_layout.addWidget(self.jitter_label)
        control_layout.addLayout(jitter_layout)
        
        # Bandwidth control
        bandwidth_layout = QHBoxLayout()
        bandwidth_layout.addWidget(QLabel("Bandwidth Limit (Mbps):"))
        self.bandwidth_slider = QSlider(Qt.Orientation.Horizontal)
        self.bandwidth_slider.setRange(1, 1000)
        self.bandwidth_slider.setValue(1000)
        bandwidth_layout.addWidget(self.bandwidth_slider)
        self.bandwidth_label = QLabel("1000 Mbps")
        self.bandwidth_slider.valueChanged.connect(lambda v: self.bandwidth_label.setText(f"{v} Mbps"))
        bandwidth_layout.addWidget(self.bandwidth_label)
        control_layout.addLayout(bandwidth_layout)
        
        # Packet loss control
        loss_layout = QHBoxLayout()
        loss_layout.addWidget(QLabel("Packet Loss (%):"))
        self.loss_slider = QSlider(Qt.Orientation.Horizontal)
        self.loss_slider.setRange(0, 50)
        self.loss_slider.setValue(0)
        loss_layout.addWidget(self.loss_slider)
        self.loss_label = QLabel("0%")
        self.loss_slider.valueChanged.connect(lambda v: self.loss_label.setText(f"{v}%"))
        loss_layout.addWidget(self.loss_label)
        control_layout.addLayout(loss_layout)
        
        # Traffic control buttons
        traffic_buttons = QHBoxLayout()
        self.apply_traffic_button = QPushButton("Apply Traffic Control")
        self.apply_traffic_button.clicked.connect(self.apply_traffic_control)
        traffic_buttons.addWidget(self.apply_traffic_button)
        
        self.clear_traffic_button = QPushButton("Clear Traffic Control")
        self.clear_traffic_button.clicked.connect(self.clear_traffic_control)
        traffic_buttons.addWidget(self.clear_traffic_button)
        control_layout.addLayout(traffic_buttons)
        
        layout.addWidget(control_group)
        
        # Traffic profiles
        profiles_group = QGroupBox("📋 Traffic Profiles")
        profiles_layout = QVBoxLayout()
        profiles_group.setLayout(profiles_layout)
        
        self.traffic_profile_combo = QComboBox()
        self.traffic_profile_combo.addItems(list(self.traffic_profiles.keys()))
        self.traffic_profile_combo.currentTextChanged.connect(self.load_traffic_profile)
        profiles_layout.addWidget(self.traffic_profile_combo)
        
        profile_buttons = QHBoxLayout()
        profile_buttons.addWidget(QPushButton("Save Profile", clicked=self.save_traffic_profile))
        profile_buttons.addWidget(QPushButton("Delete Profile", clicked=self.delete_traffic_profile))
        profiles_layout.addLayout(profile_buttons)
        
        layout.addWidget(profiles_group)
        layout.addStretch()
        
        return tab
        
    def create_stats_tab(self) -> QWidget:
        """Create statistics tab"""
        tab = QWidget()
        layout = QVBoxLayout()
        tab.setLayout(layout)
        
        # Statistics display
        self.stats_text = QTextEdit()
        self.stats_text.setReadOnly(True)
        layout.addWidget(self.stats_text)
        
        return tab
        
    def setup_device_table(self):
        """Setup device table with Angry IP Scanner columns"""
        headers = [
            "IP Address", "MAC Address", "Hostname", "Vendor", 
            "Device Type", "Open Ports", "Status", "Traffic Control"
        ]
        self.device_table.setColumnCount(len(headers))
        self.device_table.setHorizontalHeaderLabels(headers)
        
        # Table properties
        self.device_table.setAlternatingRowColors(True)
        self.device_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.device_table.setSortingEnabled(True)
        self.device_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.device_table.customContextMenuRequested.connect(self.show_context_menu)
        
        # Column widths
        header = self.device_table.horizontalHeader()
        for i in range(len(headers)):
            if i == 2:  # Hostname
                header.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
            else:
                header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
                
    def apply_angry_ip_style(self):
        """Apply Angry IP Scanner styling"""
        self.setStyleSheet("""
            QWidget {
                background-color: #2d2d2d;
                color: #ffffff;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
            QGroupBox {
                font-weight: bold;
                border: 2px solid #4a4a4a;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: #FF6B35;
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
                border-color: #FF6B35;
            }
            QPushButton:pressed {
                background-color: #FF6B35;
                border-color: #FF6B35;
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
                background-color: #FF6B35;
                color: #ffffff;
            }
            QHeaderView::section {
                background-color: #3d3d3d;
                color: #ffffff;
                padding: 8px;
                border: 1px solid #4a4a4a;
                font-weight: bold;
            }
            QSlider::groove:horizontal {
                border: 1px solid #4a4a4a;
                height: 8px;
                background: #1e1e1e;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #FF6B35;
                border: 1px solid #FF6B35;
                width: 18px;
                margin: -2px 0;
                border-radius: 9px;
            }
            QSlider::sub-page:horizontal {
                background: #FF6B35;
                border-radius: 4px;
            }
        """)
        
    def load_scan_profiles(self) -> Dict:
        """Load scan profiles"""
        profiles = {
            "Quick Scan": {"threads": 50, "timeout": 1000, "methods": ["ping", "tcp"]},
            "Full Scan": {"threads": 100, "timeout": 2000, "methods": ["ping", "tcp", "arp", "udp"]},
            "Stealth Scan": {"threads": 20, "timeout": 3000, "methods": ["tcp"]},
            "Gaming Network": {"threads": 75, "timeout": 1500, "methods": ["ping", "tcp", "arp"]}
        }
        return profiles
        
    def load_traffic_profiles(self) -> Dict:
        """Load traffic profiles (Clumsy 3.0 style)"""
        profiles = {
            "Gaming Lag": {"latency": 100, "jitter": 50, "bandwidth": 100, "loss": 5},
            "Network Stress": {"latency": 500, "jitter": 200, "bandwidth": 50, "loss": 20},
            "Smooth Gaming": {"latency": 20, "jitter": 10, "bandwidth": 500, "loss": 0},
            "Custom": {"latency": 0, "jitter": 0, "bandwidth": 1000, "loss": 0}
        }
        return profiles 

    def connect_signals(self):
        """Connect scanner signals to UI updates"""
        self.scanner.device_found.connect(self.add_device_to_table)
        self.scanner.scan_progress.connect(self.update_progress)
        self.scanner.scan_complete.connect(self.on_scan_complete)
        self.scanner.scan_error.connect(self.on_scan_error)
        self.scanner.status_update.connect(self.update_status)
        
    def load_profile(self, profile_name: str):
        """Load a scan profile"""
        if profile_name in self.scan_profiles:
            profile = self.scan_profiles[profile_name]
            self.thread_slider.setValue(profile.get('threads', 50))
            self.timeout_spinbox.setValue(profile.get('timeout', 1000))
            
            # Set scan methods
            methods = profile.get('methods', [])
            self.ping_checkbox.setChecked('ping' in methods)
            self.tcp_checkbox.setChecked('tcp' in methods)
            self.arp_checkbox.setChecked('arp' in methods)
            self.udp_checkbox.setChecked('udp' in methods)
            
    def save_profile(self):
        """Save current settings as a new profile"""
        name, ok = QInputDialog.getText(self, "Save Profile", "Profile name:")
        if ok and name:
            profile = {
                'threads': self.thread_slider.value(),
                'timeout': self.timeout_spinbox.value(),
                'methods': []
            }
            
            if self.ping_checkbox.isChecked():
                profile['methods'].append('ping')
            if self.tcp_checkbox.isChecked():
                profile['methods'].append('tcp')
            if self.arp_checkbox.isChecked():
                profile['methods'].append('arp')
            if self.udp_checkbox.isChecked():
                profile['methods'].append('udp')
                
            self.scan_profiles[name] = profile
            self.profile_combo.addItem(name)
            self.profile_combo.setCurrentText(name)
            
    def delete_profile(self):
        """Delete the current profile"""
        current = self.profile_combo.currentText()
        if current in self.scan_profiles:
            reply = QMessageBox.question(self, "Delete Profile", 
                                       f"Delete profile '{current}'?",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                del self.scan_profiles[current]
                self.profile_combo.removeItem(self.profile_combo.currentIndex())
                
    def set_local_range(self):
        """Set scan range to local network"""
        self.ip_from.setCurrentText("192.168.1.1")
        self.ip_to.setCurrentText("192.168.1.254")
        
    def set_custom_range(self):
        """Set custom scan range"""
        from_ip, ok1 = QInputDialog.getText(self, "Custom Range", "From IP:")
        to_ip, ok2 = QInputDialog.getText(self, "Custom Range", "To IP:")
        if ok1 and ok2:
            self.ip_from.setCurrentText(from_ip)
            self.ip_to.setCurrentText(to_ip)
            
    def start_scan(self):
        """Start the network scan"""
        try:
            # Clear previous results
            self.device_table.setRowCount(0)
            self.devices = []
            
            # Update scanner settings
            self.scanner.max_threads = self.thread_slider.value()
            self.scanner.timeout = self.timeout_spinbox.value() / 1000.0
            
            # Update UI state
            self.scan_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            
            # Start scan
            self.scanner.start()
            self.scan_started.emit()
            
            log_info("Advanced network scan started")
            
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
            
    def clear_results(self):
        """Clear scan results"""
        self.device_table.setRowCount(0)
        self.devices = []
        self.update_status("Results cleared")
        
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
                QTableWidgetItem(', '.join(map(str, device.get('open_ports', [])))),
                QTableWidgetItem(device.get('status', 'Online')),
                QTableWidgetItem("None")
            ]
            
            # Set items in table
            for col, item in enumerate(items):
                self.device_table.setItem(row, col, item)
                
            # Store device data
            self.devices.append(device)
            
        except Exception as e:
            log_error(f"Error adding device to table: {e}")
            
    def update_progress(self, current: int, total: int):
        """Update progress bar"""
        try:
            if total > 0:
                progress = int((current / total) * 100)
                self.update_status(f"Scanning: {progress}% ({current}/{total})")
        except Exception as e:
            log_error(f"Error updating progress: {e}")
            
    def on_scan_complete(self, devices: List[Dict]):
        """Handle scan completion"""
        try:
            # Update UI state
            self.scan_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            
            # Update status
            self.update_status(f"Scan complete! Found {len(devices)} devices")
            
            # Emit signal
            self.scan_finished.emit(devices)
            
            log_info(f"Advanced scan completed with {len(devices)} devices")
            
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
                self.status_label.setStyleSheet("color: #f44336; font-weight: bold; padding: 5px;")
            elif "complete" in message.lower():
                self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold; padding: 5px;")
            elif "scanning" in message.lower():
                self.status_label.setStyleSheet("color: #FF9800; font-weight: bold; padding: 5px;")
            else:
                self.status_label.setStyleSheet("color: #2196F3; font-weight: bold; padding: 5px;")
                
        except Exception as e:
            log_error(f"Error updating status: {e}")
            
    def export_devices(self):
        """Export devices to file"""
        try:
            if not self.devices:
                self.update_status("No devices to export")
                return
                
            # Simple export to text file
            filename = f"devices_export_{int(time.time())}.txt"
            with open(filename, 'w') as f:
                f.write("IP Address\tMAC Address\tHostname\tVendor\tDevice Type\tOpen Ports\tStatus\n")
                for device in self.devices:
                    f.write(f"{device.get('ip', '')}\t{device.get('mac', '')}\t{device.get('hostname', '')}\t{device.get('vendor', '')}\t{device.get('device_type', '')}\t{', '.join(map(str, device.get('open_ports', [])))}\t{device.get('status', 'Online')}\n")
                    
            self.update_status(f"Devices exported to {filename}")
            
        except Exception as e:
            log_error(f"Error exporting devices: {e}")
            self.update_status(f"Error exporting devices: {e}")
            
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
            
    def unblock_all(self):
        """Unblock all devices"""
        try:
            for i, device in enumerate(self.devices):
                if device.get('blocked', False):
                    ip = device.get('ip', '')
                    
                    # Update device status
                    device['blocked'] = False
                    device['status'] = 'Online'
                    
                    # Update table
                    status_item = QTableWidgetItem('Online')
                    status_item.setBackground(QColor(100, 255, 100))
                    self.device_table.setItem(i, 8, status_item)
                    
                    # Emit signal
                    self.device_blocked.emit(ip, False)
                    
            self.update_status("All devices unblocked")
            
        except Exception as e:
            log_error(f"Error unblocking devices: {e}")
            
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
                
                # Emit signal
                self.device_blocked.emit(ip, new_blocked)
                
                # Update status message
                action = "blocked" if new_blocked else "unblocked"
                self.update_status(f"Device {ip} {action}")
                
        except Exception as e:
            log_error(f"Error toggling device blocking: {e}")
            
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
            
    def load_traffic_profile(self, profile_name: str):
        """Load a traffic profile"""
        if profile_name in self.traffic_profiles:
            profile = self.traffic_profiles[profile_name]
            self.latency_slider.setValue(profile.get('latency', 0))
            self.jitter_slider.setValue(profile.get('jitter', 0))
            self.bandwidth_slider.setValue(profile.get('bandwidth', 1000))
            self.loss_slider.setValue(profile.get('loss', 0))
            
    def save_traffic_profile(self):
        """Save current traffic settings as a new profile"""
        name, ok = QInputDialog.getText(self, "Save Traffic Profile", "Profile name:")
        if ok and name:
            profile = {
                'latency': self.latency_slider.value(),
                'jitter': self.jitter_slider.value(),
                'bandwidth': self.bandwidth_slider.value(),
                'loss': self.loss_slider.value()
            }
            
            self.traffic_profiles[name] = profile
            self.traffic_profile_combo.addItem(name)
            self.traffic_profile_combo.setCurrentText(name)
            
    def delete_traffic_profile(self):
        """Delete the current traffic profile"""
        current = self.traffic_profile_combo.currentText()
        if current in self.traffic_profiles:
            reply = QMessageBox.question(self, "Delete Traffic Profile", 
                                       f"Delete profile '{current}'?",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                del self.traffic_profiles[current]
                self.traffic_profile_combo.removeItem(self.traffic_profile_combo.currentIndex())
                
    def apply_traffic_control(self):
        """Apply traffic control settings"""
        try:
            settings = {
                'latency': self.latency_slider.value(),
                'jitter': self.jitter_slider.value(),
                'bandwidth': self.bandwidth_slider.value(),
                'loss': self.loss_slider.value()
            }
            
            # Emit traffic control signal
            self.traffic_control.emit("all", settings)
            
            self.update_status(f"Traffic control applied: {settings['latency']}ms latency, {settings['jitter']}ms jitter, {settings['bandwidth']} Mbps, {settings['loss']}% loss")
            
        except Exception as e:
            log_error(f"Error applying traffic control: {e}")
            self.update_status(f"Error applying traffic control: {e}")
            
    def clear_traffic_control(self):
        """Clear traffic control settings"""
        try:
            # Reset sliders
            self.latency_slider.setValue(0)
            self.jitter_slider.setValue(0)
            self.bandwidth_slider.setValue(1000)
            self.loss_slider.setValue(0)
            
            # Emit clear signal
            self.traffic_control.emit("all", {'latency': 0, 'jitter': 0, 'bandwidth': 1000, 'loss': 0})
            
            self.update_status("Traffic control cleared")
            
        except Exception as e:
            log_error(f"Error clearing traffic control: {e}")
            self.update_status(f"Error clearing traffic control: {e}") 