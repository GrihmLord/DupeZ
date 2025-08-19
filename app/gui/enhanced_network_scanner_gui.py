#!/usr/bin/env python3
"""
Enhanced Network Scanner GUI for DupeZ
Provides comprehensive device discovery with multiple protocols
"""

import sys
import time
import threading
from datetime import datetime
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QTableWidget, QTableWidgetItem, QLabel, QProgressBar,
                             QComboBox, QCheckBox, QGroupBox, QTextEdit, QTabWidget,
                             QHeaderView, QMessageBox, QFileDialog, QSpinBox)
from PyQt6.QtCore import QTimer, QThread, pyqtSignal, Qt
from PyQt6.QtGui import QFont, QColor

# Import the enhanced scanner
try:
    from app.network.enhanced_multi_protocol_scanner import EnhancedMultiProtocolScanner, DeviceInfo
except ImportError:
    print("Warning: Enhanced scanner not available, using fallback")
    EnhancedMultiProtocolScanner = None

class ScannerThread(QThread):
    """Background thread for network scanning"""
    scan_progress = pyqtSignal(str)
    scan_complete = pyqtSignal()
    device_found = pyqtSignal(object)
    
    def __init__(self, scanner, methods):
        super().__init__()
        self.scanner = scanner
        self.methods = methods
        self.is_running = False
    
    def run(self):
        """Run the network scan"""
        self.is_running = True
        
        try:
            # Start the scan
            if self.scanner.start_scan(self.methods):
                # Monitor progress
                while self.scanner.is_scanning and self.is_running:
                    status = self.scanner.get_scan_status()
                    self.scan_progress.emit(f"Scanning... Found {status['total_devices']} devices")
                    time.sleep(0.5)
                
                # Get final results
                devices = self.scanner.get_discovered_devices()
                for device in devices:
                    self.device_found.emit(device)
                
                self.scan_complete.emit()
            else:
                self.scan_progress.emit("Scan failed to start")
        except Exception as e:
            self.scan_progress.emit(f"Scan error: {e}")
        finally:
            self.is_running = False
    
    def stop(self):
        """Stop the scan"""
        self.is_running = False
        if self.scanner:
            self.scanner.stop_scan()

class EnhancedNetworkScannerGUI(QWidget):
    """Enhanced Network Scanner GUI"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scanner = None
        self.scanner_thread = None
        self.devices = {}
        
        # Initialize scanner
        self._init_scanner()
        
        # Setup UI
        self.setup_ui()
        self.setup_connections()
        self.apply_styling()
        
        # Update timer - reduced frequency to save memory
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_device_table)
        self.update_timer.start(5000)  # Update every 5 seconds to reduce memory usage
    
    def _init_scanner(self):
        """Initialize the enhanced scanner"""
        try:
            if EnhancedMultiProtocolScanner:
                self.scanner = EnhancedMultiProtocolScanner()
                print("Enhanced scanner initialized successfully")
            else:
                print("Enhanced scanner not available")
        except Exception as e:
            print(f"Error initializing scanner: {e}")
            self.scanner = None
    
    def setup_ui(self):
        """Setup the user interface"""
        self.setWindowTitle("🕵️ Enhanced Network Scanner - DupeZ")
        self.setMinimumSize(1000, 700)
        
        # Main layout
        main_layout = QVBoxLayout()
        
        # Header
        header = self.create_header()
        main_layout.addWidget(header)
        
        # Control panel
        control_panel = self.create_control_panel()
        main_layout.addWidget(control_panel)
        
        # Main content area
        content_tabs = QTabWidget()
        
        # Devices tab
        devices_tab = self.create_devices_tab()
        content_tabs.addTab(devices_tab, "📱 Discovered Devices")
        
        # Scan methods tab
        methods_tab = self.create_methods_tab()
        content_tabs.addTab(methods_tab, "🔍 Scan Methods")
        
        # Statistics tab
        stats_tab = self.create_statistics_tab()
        content_tabs.addTab(stats_tab, "📊 Statistics")
        
        main_layout.addWidget(content_tabs)
        
        # Status bar
        status_bar = self.create_status_bar()
        main_layout.addWidget(status_bar)
        
        self.setLayout(main_layout)
    
    def create_header(self):
        """Create the header section"""
        header = QGroupBox()
        header.setStyleSheet("QGroupBox { border: none; }")
        
        layout = QHBoxLayout()
        
        # Title
        title = QLabel("🕵️ Enhanced Network Scanner")
        title.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        title.setStyleSheet("color: #2c3e50;")
        
        # Subtitle
        subtitle = QLabel("Multi-protocol device discovery with intelligent caching")
        subtitle.setStyleSheet("color: #7f8c8d; font-size: 12px;")
        
        # Right side info
        info_layout = QVBoxLayout()
        info_layout.addWidget(title)
        info_layout.addWidget(subtitle)
        
        layout.addLayout(info_layout)
        layout.addStretch()
        
        # Quick stats
        stats_layout = QVBoxLayout()
        self.total_devices_label = QLabel("Total: 0")
        self.active_devices_label = QLabel("Active: 0")
        self.last_scan_label = QLabel("Last Scan: Never")
        
        for label in [self.total_devices_label, self.active_devices_label, self.last_scan_label]:
            label.setStyleSheet("color: #34495e; font-size: 11px;")
            stats_layout.addWidget(label)
        
        layout.addLayout(stats_layout)
        header.setLayout(layout)
        return header
    
    def create_control_panel(self):
        """Create the control panel"""
        panel = QGroupBox("🎛️ Scan Controls")
        layout = QHBoxLayout()
        
        # Scan methods selection
        methods_group = QGroupBox("Discovery Methods")
        methods_layout = QVBoxLayout()
        
        self.method_checkboxes = {}
        methods = ['arp', 'ping', 'netbios', 'mdns', 'snmp', 'port_scan']
        method_names = {
            'arp': 'ARP Discovery',
            'ping': 'ICMP Ping',
            'netbios': 'NetBIOS',
            'mdns': 'mDNS',
            'snmp': 'SNMP',
            'port_scan': 'Port Scan'
        }
        
        for method in methods:
            checkbox = QCheckBox(method_names[method])
            checkbox.setChecked(True)
            self.method_checkboxes[method] = checkbox
            methods_layout.addWidget(checkbox)
        
        methods_group.setLayout(methods_layout)
        layout.addWidget(methods_group)
        
        # Scan controls
        controls_group = QGroupBox("Scan Controls")
        controls_layout = QVBoxLayout()
        
        # Start/Stop button
        self.scan_button = QPushButton("🚀 Start Scan")
        self.scan_button.setStyleSheet("""
            QPushButton {
                background-color: #27ae60;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2ecc71;
            }
            QPushButton:pressed {
                background-color: #229954;
            }
        """)
        
        # Stop button
        self.stop_button = QPushButton("⏹️ Stop Scan")
        self.stop_button.setEnabled(False)
        self.stop_button.setStyleSheet("""
            QPushButton {
                background-color: #e74c3c;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #ec7063;
            }
            QPushButton:pressed {
                background-color: #c0392b;
            }
        """)
        
        # Clear cache button
        self.clear_cache_button = QPushButton("🗑️ Clear Cache")
        self.clear_cache_button.setStyleSheet("""
            QPushButton {
                background-color: #95a5a6;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #bdc3c7;
            }
        """)
        
        # Export button
        self.export_button = QPushButton("📤 Export Devices")
        self.export_button.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #5dade2;
            }
        """)
        
        controls_layout.addWidget(self.scan_button)
        controls_layout.addWidget(self.stop_button)
        controls_layout.addWidget(self.clear_cache_button)
        controls_layout.addWidget(self.export_button)
        controls_layout.addStretch()
        
        controls_group.setLayout(controls_layout)
        layout.addWidget(controls_group)
        
        # Progress and status
        status_group = QGroupBox("Scan Status")
        status_layout = QVBoxLayout()
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        
        self.status_label = QLabel("Ready to scan")
        self.status_label.setStyleSheet("color: #2c3e50; font-weight: bold;")
        
        status_layout.addWidget(self.progress_bar)
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)
        
        panel.setLayout(layout)
        return panel
    
    def create_devices_tab(self):
        """Create the devices tab"""
        tab = QWidget()
        layout = QVBoxLayout()
        
        # Device table
        self.device_table = QTableWidget()
        self.device_table.setColumnCount(8)
        self.device_table.setHorizontalHeaderLabels([
            "IP Address", "MAC Address", "Device Type", "Vendor", 
            "Services", "Ports", "Last Seen", "Discovery Methods"
        ])
        
        # Set table properties
        header = self.device_table.horizontalHeader()
        for i in range(8):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        
        self.device_table.setAlternatingRowColors(True)
        self.device_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        
        layout.addWidget(self.device_table)
        tab.setLayout(layout)
        return tab
    
    def create_methods_tab(self):
        """Create the scan methods tab"""
        tab = QWidget()
        layout = QVBoxLayout()
        
        # Method descriptions
        methods_info = QTextEdit()
        methods_info.setReadOnly(True)
        methods_info.setMaximumHeight(200)
        
        methods_text = """
🔍 **Scan Methods Overview:**

**ARP Discovery**: Fast local network device discovery using Address Resolution Protocol
**ICMP Ping**: Traditional ping-based device detection with response time measurement
**NetBIOS**: Windows device identification through SMB ports (139, 445)
**mDNS**: Apple/Android device discovery using multicast DNS (port 5353)
**SNMP**: Network infrastructure device discovery (ports 161, 162)
**Port Scan**: Service identification through common port scanning

💡 **Tips for Better Discovery:**
• Use all methods for comprehensive scanning
• ARP + Ping provide fastest results
• NetBIOS + mDNS identify specific device types
• SNMP finds routers, switches, and network devices
• Port scanning reveals running services
        """
        
        methods_info.setPlainText(methods_text)
        layout.addWidget(methods_info)
        
        # Method configuration
        config_group = QGroupBox("Method Configuration")
        config_layout = QVBoxLayout()
        
        # Network range
        range_layout = QHBoxLayout()
        range_layout.addWidget(QLabel("Network Range:"))
        self.network_range_input = QComboBox()
        self.network_range_input.addItems([
            "192.168.1.0/24", "192.168.0.0/24", "10.0.0.0/24", "172.16.0.0/24"
        ])
        range_layout.addWidget(self.network_range_input)
        range_layout.addStretch()
        
        config_layout.addLayout(range_layout)
        
        # Scan intervals
        interval_layout = QHBoxLayout()
        interval_layout.addWidget(QLabel("Auto-scan Interval (minutes):"))
        self.auto_scan_interval = QSpinBox()
        self.auto_scan_interval.setRange(1, 60)
        self.auto_scan_interval.setValue(5)
        interval_layout.addWidget(self.auto_scan_interval)
        interval_layout.addStretch()
        
        config_layout.addLayout(interval_layout)
        
        config_group.setLayout(config_layout)
        layout.addWidget(config_group)
        
        layout.addStretch()
        tab.setLayout(layout)
        return tab
    
    def create_statistics_tab(self):
        """Create the statistics tab"""
        tab = QWidget()
        layout = QVBoxLayout()
        
        # Statistics display
        self.stats_text = QTextEdit()
        self.stats_text.setReadOnly(True)
        layout.addWidget(self.stats_text)
        
        # Update stats
        self.update_statistics()
        
        tab.setLayout(layout)
        return tab
    
    def create_status_bar(self):
        """Create the status bar"""
        status_bar = QGroupBox()
        status_bar.setStyleSheet("QGroupBox { border: none; }")
        
        layout = QHBoxLayout()
        
        self.scan_progress_label = QLabel("Ready")
        self.scan_progress_label.setStyleSheet("color: #7f8c8d;")
        
        layout.addWidget(self.scan_progress_label)
        layout.addStretch()
        
        # Device count
        self.device_count_label = QLabel("Devices: 0")
        self.device_count_label.setStyleSheet("color: #34495e; font-weight: bold;")
        layout.addWidget(self.device_count_label)
        
        status_bar.setLayout(layout)
        return status_bar
    
    def setup_connections(self):
        """Setup signal connections"""
        self.scan_button.clicked.connect(self.start_scan)
        self.stop_button.clicked.connect(self.stop_scan)
        self.clear_cache_button.clicked.connect(self.clear_cache)
        self.export_button.clicked.connect(self.export_devices)
    
    def apply_styling(self):
        """Apply styling to the GUI"""
        self.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #bdc3c7;
                border-radius: 5px;
                margin-top: 1ex;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
            QTableWidget {
                gridline-color: #bdc3c7;
                selection-background-color: #3498db;
            }
            QTableWidget::item {
                padding: 5px;
            }
        """)
    
    def start_scan(self):
        """Start the network scan"""
        if not self.scanner:
            QMessageBox.warning(self, "Scanner Error", "Enhanced scanner not available")
            return
        
        # Get selected methods
        selected_methods = []
        for method, checkbox in self.method_checkboxes.items():
            if checkbox.isChecked():
                selected_methods.append(method)
        
        if not selected_methods:
            QMessageBox.warning(self, "No Methods Selected", "Please select at least one discovery method")
            return
        
        # Update UI
        self.scan_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.status_label.setText("Starting scan...")
        
        # Start scanner thread
        self.scanner_thread = ScannerThread(self.scanner, selected_methods)
        self.scanner_thread.scan_progress.connect(self.update_scan_progress)
        self.scanner_thread.scan_complete.connect(self.scan_completed)
        self.scanner_thread.device_found.connect(self.device_discovered)
        self.scanner_thread.start()
    
    def stop_scan(self):
        """Stop the network scan"""
        if self.scanner_thread:
            self.scanner_thread.stop()
            self.scanner_thread.wait()
        
        # Update UI
        self.scan_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.status_label.setText("Scan stopped")
    
    def update_scan_progress(self, message: str):
        """Update scan progress"""
        self.status_label.setText(message)
        self.scan_progress_label.setText(message)
    
    def scan_completed(self):
        """Handle scan completion"""
        self.scan_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.status_label.setText("Scan completed")
        
        # Update device table
        self.update_device_table()
        
        # Update statistics
        self.update_statistics()
    
    def device_discovered(self, device: DeviceInfo):
        """Handle newly discovered device"""
        self.devices[device.ip] = device
        self.update_device_table()
    
    def update_device_table(self):
        """Update the device table"""
        if not self.scanner:
            return
        
        devices = self.scanner.get_discovered_devices()
        self.device_table.setRowCount(len(devices))
        
        for row, device in enumerate(devices):
            # IP Address
            self.device_table.setItem(row, 0, QTableWidgetItem(device.ip))
            
            # MAC Address
            self.device_table.setItem(row, 1, QTableWidgetItem(device.mac or "Unknown"))
            
            # Device Type
            self.device_table.setItem(row, 2, QTableWidgetItem(device.device_type))
            
            # Vendor
            self.device_table.setItem(row, 3, QTableWidgetItem(device.vendor or "Unknown"))
            
            # Services
            services_text = ", ".join(device.services) if device.services else "None"
            self.device_table.setItem(row, 4, QTableWidgetItem(services_text))
            
            # Ports
            ports_text = ", ".join(map(str, device.ports)) if device.ports else "None"
            self.device_table.setItem(row, 5, QTableWidgetItem(ports_text))
            
            # Last Seen
            if device.last_seen > 0:
                last_seen = datetime.fromtimestamp(device.last_seen).strftime("%H:%M:%S")
                self.device_table.setItem(row, 6, QTableWidgetItem(last_seen))
            else:
                self.device_table.setItem(row, 6, QTableWidgetItem("Never"))
            
            # Discovery Methods
            methods_text = ", ".join(device.discovery_methods) if device.discovery_methods else "None"
            self.device_table.setItem(row, 7, QTableWidgetItem(methods_text))
        
        # Update labels
        self.device_count_label.setText(f"Devices: {len(devices)}")
        self.total_devices_label.setText(f"Total: {len(devices)}")
        
        active_count = len([d for d in devices if d.is_active])
        self.active_devices_label.setText(f"Active: {active_count}")
        
        if devices:
            last_scan = max([d.last_seen for d in devices])
            if last_scan > 0:
                last_scan_time = datetime.fromtimestamp(last_scan).strftime("%Y-%m-%d %H:%M:%S")
                self.last_scan_label.setText(f"Last Scan: {last_scan_time}")
    
    def update_statistics(self):
        """Update statistics display"""
        if not self.scanner:
            return
        
        devices = self.scanner.get_discovered_devices()
        
        # Device type breakdown
        device_types = {}
        for device in devices:
            device_type = device.device_type
            device_types[device_type] = device_types.get(device_type, 0) + 1
        
        # Service breakdown
        services = {}
        for device in devices:
            for service in device.services:
                services[service] = services.get(service, 0) + 1
        
        # Generate statistics text
        stats_text = f"""
📊 **Network Scanner Statistics**

**Device Discovery:**
• Total Devices: {len(devices)}
• Active Devices: {len([d for d in devices if d.is_active])}

**Device Types:**
"""
        
        for device_type, count in device_types.items():
            stats_text += f"• {device_type}: {count}\n"
        
        stats_text += f"""
**Services Detected:**
"""
        
        for service, count in services.items():
            stats_text += f"• {service}: {count}\n"
        
        if devices:
            stats_text += f"""
**Network Information:**
• Network Range: {self.scanner.network_range if self.scanner else 'Unknown'}
• Last Scan: {datetime.fromtimestamp(max([d.last_seen for d in devices])).strftime('%Y-%m-%d %H:%M:%S')}
• Discovery Methods Used: {', '.join(set([method for d in devices for method in d.discovery_methods]))}
"""
        
        self.stats_text.setPlainText(stats_text)
    
    def clear_cache(self):
        """Clear the device cache"""
        if not self.scanner:
            return
        
        reply = QMessageBox.question(
            self, "Clear Cache", 
            "Are you sure you want to clear all cached device information?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.scanner.clear_cache()
            self.devices.clear()
            self.update_device_table()
            self.update_statistics()
            self.status_label.setText("Cache cleared")
    
    def export_devices(self):
        """Export device information"""
        if not self.scanner or not self.devices:
            QMessageBox.information(self, "Export", "No devices to export")
            return
        
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export Devices", 
            f"network_devices_{int(time.time())}.json",
            "JSON Files (*.json);;All Files (*)"
        )
        
        if filename:
            exported_file = self.scanner.export_devices(filename)
            if exported_file:
                QMessageBox.information(self, "Export Success", f"Devices exported to: {exported_file}")
            else:
                QMessageBox.critical(self, "Export Error", "Failed to export devices")
    
    def closeEvent(self, event):
        """Handle application close"""
        if self.scanner_thread and self.scanner_thread.isRunning():
            self.scanner_thread.stop()
            self.scanner_thread.wait()
        
        if self.scanner:
            self.scanner.stop_scan()
        
        event.accept()
