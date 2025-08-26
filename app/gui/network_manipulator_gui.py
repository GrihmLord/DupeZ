# app/gui/network_manipulator_gui.py

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QTableWidget, QTableWidgetItem,
                             QGroupBox, QSlider, QSpinBox, QComboBox,
                             QLineEdit, QTextEdit, QMessageBox, QTabWidget,
                             QHeaderView, QProgressBar, QCheckBox, QDateEdit)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QDate
from PyQt6.QtGui import QFont, QColor, QIcon
import time
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from app.network.network_manipulator import get_network_manipulator, NetworkRule
from app.logs.logger import log_info, log_error

class NetworkManipulatorGUI(QWidget):
    """GUI for advanced network manipulation features"""
    
    # Signals
    rule_created = pyqtSignal(str, str)  # rule_id, rule_type
    rule_removed = pyqtSignal(str)  # rule_id
    manipulation_started = pyqtSignal(str, str)  # ip, action
    manipulation_stopped = pyqtSignal(str, str)  # ip, action
    
    def __init__(self, controller=None):
        super().__init__()
        self.controller = controller
        self.manipulator = get_network_manipulator()
        self.history_file = "network_manipulator_history.json"
        self.ip_history = self.load_history()
        self.setup_ui()
        self.connect_signals()
        self.start_updates()
        
    def setup_ui(self):
        """Setup the network manipulator UI"""
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        # Title
        title = QLabel("🌐 Advanced Network Manipulator")
        title.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # Create tab widget
        self.tab_widget = QTabWidget()
        # Enable movable tabs in existing app
        self.tab_widget.setMovable(True)
        self.tab_widget.setTabsClosable(False)
        layout.addWidget(self.tab_widget)
        
        # Create tabs
        self.tab_widget.addTab(self.create_blocking_tab(), "🛡️ IP Blocking")
        # Traffic Control and Redirect tabs removed for optimization
        self.tab_widget.addTab(self.create_packet_modify_tab(), "📦 Packet Modify")
        self.tab_widget.addTab(self.create_rules_tab(), "📋 Active Rules")
        self.tab_widget.addTab(self.create_history_tab(), "📜 IP History")
        self.tab_widget.addTab(self.create_network_info_tab(), "ℹ️ Network Info")
        
        # Status bar
        self.status_label = QLabel("Ready for network manipulation")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        layout.addWidget(self.status_label)
        
    def create_blocking_tab(self) -> QWidget:
        """Create IP blocking tab"""
        tab = QWidget()
        layout = QVBoxLayout()
        tab.setLayout(layout)
        
        # IP input
        ip_group = QGroupBox("IP Address")
        ip_layout = QHBoxLayout()
        ip_group.setLayout(ip_layout)
        
        ip_layout.addWidget(QLabel("Target IP:"))
        self.block_ip_input = QLineEdit()
        self.block_ip_input.setPlaceholderText("192.168.1.100")
        ip_layout.addWidget(self.block_ip_input)
        
        # Blocking options
        options_group = QGroupBox("Blocking Options")
        options_layout = QVBoxLayout()
        options_group.setLayout(options_layout)
        
        self.permanent_block = QCheckBox("Permanent Block (survives restart)")
        self.permanent_block.setChecked(False)
        options_layout.addWidget(self.permanent_block)
        
        self.aggressive_block = QCheckBox("Aggressive Blocking (multiple methods)")
        self.aggressive_block.setChecked(True)
        options_layout.addWidget(self.aggressive_block)
        
        # Blocking buttons
        button_layout = QHBoxLayout()
        
        self.block_button = QPushButton("🚫 Block IP")
        self.block_button.clicked.connect(self.block_selected_ip)
        button_layout.addWidget(self.block_button)
        
        self.unblock_button = QPushButton("✅ Unblock IP")
        self.unblock_button.clicked.connect(self.unblock_selected_ip)
        button_layout.addWidget(self.unblock_button)
        
        self.block_all_button = QPushButton("🚫 Block All")
        self.block_all_button.clicked.connect(self.block_all_ips)
        button_layout.addWidget(self.block_all_button)
        
        # Test individual methods button
        self.test_methods_button = QPushButton("🧪 Test Methods")
        self.test_methods_button.clicked.connect(self.test_disconnect_methods)
        button_layout.addWidget(self.test_methods_button)
        
        # Test UDP interruption button
        self.test_udp_button = QPushButton("Test UDP")
        self.test_udp_button.clicked.connect(self.test_udp_interruption)
        button_layout.addWidget(self.test_udp_button)
        
        # Add to layout
        layout.addWidget(ip_group)
        layout.addWidget(options_group)
        layout.addLayout(button_layout)
        layout.addStretch()
        
        return tab
    
    # create_throttling_tab removed for optimization
    
    # create_redirect_tab removed for optimization
    
    def create_packet_modify_tab(self) -> QWidget:
        """Create packet modification tab"""
        tab = QWidget()
        layout = QVBoxLayout()
        tab.setLayout(layout)
        
        # IP input
        ip_group = QGroupBox("Target IP")
        ip_layout = QHBoxLayout()
        ip_group.setLayout(ip_layout)
        
        ip_layout.addWidget(QLabel("IP Address:"))
        self.modify_ip_input = QLineEdit()
        self.modify_ip_input.setPlaceholderText("192.168.1.100")
        ip_layout.addWidget(self.modify_ip_input)
        
        # Modification options
        mod_group = QGroupBox("Packet Modifications")
        mod_layout = QVBoxLayout()
        mod_group.setLayout(mod_layout)
        
        # TTL modification
        ttl_layout = QHBoxLayout()
        ttl_layout.addWidget(QLabel("TTL:"))
        self.ttl_spinbox = QSpinBox()
        self.ttl_spinbox.setRange(1, 255)
        self.ttl_spinbox.setValue(64)
        ttl_layout.addWidget(self.ttl_spinbox)
        ttl_layout.addStretch()
        mod_layout.addLayout(ttl_layout)
        
        # Fragment packets
        self.fragment_checkbox = QCheckBox("Fragment Packets")
        self.fragment_checkbox.setChecked(False)
        mod_layout.addWidget(self.fragment_checkbox)
        
        # Corrupt packets
        self.corrupt_checkbox = QCheckBox("Corrupt Packets (Random)")
        self.corrupt_checkbox.setChecked(False)
        mod_layout.addWidget(self.corrupt_checkbox)
        
        # Modification buttons
        button_layout = QHBoxLayout()
        
        self.modify_button = QPushButton("📦 Apply Modifications")
        self.modify_button.clicked.connect(self.apply_packet_modifications)
        button_layout.addWidget(self.modify_button)
        
        self.clear_modify_button = QPushButton("❌ Clear Modifications")
        self.clear_modify_button.clicked.connect(self.clear_packet_modifications)
        button_layout.addWidget(self.clear_modify_button)
        
        # Add to layout
        layout.addWidget(ip_group)
        layout.addWidget(mod_group)
        layout.addLayout(button_layout)
        layout.addStretch()
        
        return tab
    
    def create_rules_tab(self) -> QWidget:
        """Create active rules tab"""
        tab = QWidget()
        layout = QVBoxLayout()
        tab.setLayout(layout)
        
        # Rules table
        self.rules_table = QTableWidget()
        self.rules_table.setColumnCount(6)
        self.rules_table.setHorizontalHeaderLabels([
            "Rule ID", "Type", "Target IP", "Action", "Status", "Created"
        ])
        self.rules_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.rules_table)
        
        # Rule management buttons
        button_layout = QHBoxLayout()
        
        self.refresh_rules_button = QPushButton("🔄 Refresh Rules")
        self.refresh_rules_button.clicked.connect(self.refresh_rules_table)
        button_layout.addWidget(self.refresh_rules_button)
        
        self.remove_rule_button = QPushButton("❌ Remove Selected")
        self.remove_rule_button.clicked.connect(self.remove_selected_rule)
        button_layout.addWidget(self.remove_rule_button)
        
        self.clear_all_rules_button = QPushButton("🗑️ Clear All Rules")
        self.clear_all_rules_button.clicked.connect(self.clear_all_rules)
        button_layout.addWidget(self.clear_all_rules_button)
        
        layout.addLayout(button_layout)
        
        return tab
    
    def create_network_info_tab(self) -> QWidget:
        """Create network information tab"""
        tab = QWidget()
        layout = QVBoxLayout()
        tab.setLayout(layout)
        
        # Network info display
        self.network_info_text = QTextEdit()
        self.network_info_text.setReadOnly(True)
        self.network_info_text.setFont(QFont("Consolas", 10))
        layout.addWidget(self.network_info_text)
        
        # Refresh button
        self.refresh_info_button = QPushButton("🔄 Refresh Network Info")
        self.refresh_info_button.clicked.connect(self.refresh_network_info)
        layout.addWidget(self.refresh_info_button)
        
        return tab
    
    def create_history_tab(self) -> QWidget:
        """Create IP history tab"""
        tab = QWidget()
        layout = QVBoxLayout()
        tab.setLayout(layout)
        
        # History controls
        controls_group = QGroupBox("📜 History Controls")
        controls_layout = QHBoxLayout()
        controls_group.setLayout(controls_layout)
        
        # Date range filter
        controls_layout.addWidget(QLabel("From:"))
        self.history_from_date = QDateEdit()
        self.history_from_date.setDate(QDate.currentDate().addDays(-7))
        self.history_from_date.setCalendarPopup(True)
        controls_layout.addWidget(self.history_from_date)
        
        controls_layout.addWidget(QLabel("To:"))
        self.history_to_date = QDateEdit()
        self.history_to_date.setDate(QDate.currentDate())
        self.history_to_date.setCalendarPopup(True)
        controls_layout.addWidget(self.history_to_date)
        
        # Filter by action type
        controls_layout.addWidget(QLabel("Action:"))
        self.history_action_filter = QComboBox()
        self.history_action_filter.addItems(["All", "Block", "Unblock", "Throttle", "Redirect", "Modify"])
        controls_layout.addWidget(self.history_action_filter)
        
        # Filter button
        filter_btn = QPushButton("🔍 Filter")
        filter_btn.clicked.connect(self.filter_history)
        controls_layout.addWidget(filter_btn)
        
        # Clear history button
        clear_history_btn = QPushButton("🗑️ Clear History")
        clear_history_btn.clicked.connect(self.clear_history)
        controls_layout.addWidget(clear_history_btn)
        
        layout.addWidget(controls_group)
        
        # History table
        self.history_table = QTableWidget()
        self.history_table.setColumnCount(6)
        self.history_table.setHorizontalHeaderLabels([
            "Date/Time", "IP Address", "Action", "Details", "Status", "Duration"
        ])
        
        # Set column widths
        header = self.history_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        
        layout.addWidget(self.history_table)
        
        # History stats
        stats_group = QGroupBox("History Statistics")
        stats_layout = QHBoxLayout()
        stats_group.setLayout(stats_layout)
        
        self.history_stats_label = QLabel("Total entries: 0 | Last 7 days: 0 | Last 30 days: 0")
        stats_layout.addWidget(self.history_stats_label)
        
        layout.addWidget(stats_group)
        
        # Load initial history
        self.refresh_history_table()
        
        return tab
    
    def connect_signals(self):
        """Connect UI signals"""
        try:
            # Most signals are already connected in the create_*_tab methods
            # Add any additional signal connections here if needed
            
            # Connect history filter
            if hasattr(self, 'history_action_filter'):
                self.history_action_filter.currentTextChanged.connect(self.filter_history)
            
            # Connect history refresh
            if hasattr(self, 'refresh_history_btn'):
                self.refresh_history_btn.clicked.connect(self.refresh_history_table)
            
            log_info("Network manipulator GUI signals connected successfully")
            
        except Exception as e:
            log_error(f"Error connecting network manipulator GUI signals: {e}")
    
    def start_updates(self):
        """Start periodic updates"""
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_ui)
        self.update_timer.start(2000)  # Update every 2 seconds
    
    def update_ui(self):
        """Update UI elements"""
        self.refresh_rules_table()
        self.refresh_network_info()
    
    def block_selected_ip(self):
        """Block the selected IP address using Clumsy network disruptor"""
        try:
            ip = self.block_ip_input.text().strip()
            if not ip:
                QMessageBox.warning(self, "Warning", "Please enter an IP address")
                return
            
            # Use Clumsy network disruptor
            from app.firewall.clumsy_network_disruptor import clumsy_network_disruptor
            from app.firewall.enterprise_network_disruptor import enterprise_network_disruptor
            
            # Initialize Clumsy if not running
            if not clumsy_network_disruptor.is_running:
                if not clumsy_network_disruptor.initialize():
                    QMessageBox.critical(self, "Error", "Failed to initialize Clumsy network disruptor")
                    return
                clumsy_network_disruptor.start_clumsy()
            
            # Initialize enterprise disruptor as backup
            if not enterprise_network_disruptor.is_running:
                if not enterprise_network_disruptor.initialize():
                    QMessageBox.critical(self, "Error", "Failed to initialize enterprise network disruptor")
                else:
                    enterprise_network_disruptor.start_enterprise()
            
            # Use Clumsy methods
            clumsy_methods = ["drop", "lag", "throttle", "duplicate", "corrupt", "rst"]
            
            # Try Clumsy first (primary method)
            success = clumsy_network_disruptor.disconnect_device_clumsy(ip, clumsy_methods)
            if success:
                self.status_label.setText(f"Successfully blocked IP: {ip} using Clumsy")
                self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
                self.block_ip_input.clear()
                self.rule_created.emit(f"block_{ip}", "clumsy_block")
                # Add to history
                self.add_history_entry(ip, "Clumsy Block", "Clumsy network disruptor", "Success")
            else:
                # Fallback to enterprise disruptor
                enterprise_methods = ["arp_spoof", "icmp_flood", "syn_flood", "udp_flood", "packet_drop"]
                success = enterprise_network_disruptor.disconnect_device_enterprise(ip, enterprise_methods)
                
                if success:
                    self.status_label.setText(f"Successfully blocked IP: {ip} using enterprise disruptor")
                    self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
                    self.block_ip_input.clear()
                    self.rule_created.emit(f"block_{ip}", "enterprise_block")
                    # Add to history
                    self.add_history_entry(ip, "Enterprise Block", "Enterprise network disruptor", "Success")
                else:
                    self.status_label.setText(f"Failed to block IP: {ip}")
                    self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
                    # Add to history
                    self.add_history_entry(ip, "Block Failed", "Clumsy + Enterprise disruptors", "Failed")
                
        except Exception as e:
            log_error(f"Error blocking IP: {e}", exception=e, category="FIREWALL", severity="HIGH", 
                     context={"ip": ip, "method": "clumsy_block"})
            QMessageBox.critical(self, "Error", f"Failed to block IP: {e}")
            # Add to history
            self.add_history_entry(ip, "Clumsy Block", "Clumsy network disruptor", "Error")
    
    def unblock_selected_ip(self):
        """Unblock the selected IP address using Clumsy network disruptor"""
        try:
            ip = self.block_ip_input.text().strip()
            if not ip:
                QMessageBox.warning(self, "Warning", "Please enter an IP address")
                return
            
            # Use Clumsy network disruptor
            from app.firewall.clumsy_network_disruptor import clumsy_network_disruptor
            from app.firewall.enterprise_network_disruptor import enterprise_network_disruptor
            
            # Try Clumsy reconnection first
            success = clumsy_network_disruptor.reconnect_device_clumsy(ip)
            if success:
                self.status_label.setText(f"Successfully unblocked IP: {ip} using Clumsy")
                self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
                self.block_ip_input.clear()
                # Add to history
                self.add_history_entry(ip, "Clumsy Unblock", "Clumsy network disruptor", "Success")
            else:
                # Fallback to enterprise disruptor
                success = enterprise_network_disruptor.reconnect_device_enterprise(ip)
                
                if success:
                    self.status_label.setText(f"Successfully unblocked IP: {ip} using enterprise disruptor")
                    self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
                    self.block_ip_input.clear()
                    # Add to history
                    self.add_history_entry(ip, "Enterprise Unblock", "Enterprise network disruptor", "Success")
                else:
                    self.status_label.setText(f"Failed to unblock IP: {ip}")
                    self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
                    # Add to history
                    self.add_history_entry(ip, "Unblock Failed", "Clumsy + Enterprise disruptors", "Failed")
                
        except Exception as e:
            log_error(f"Error unblocking IP: {e}", exception=e, category="FIREWALL", severity="HIGH", 
                     context={"ip": ip, "method": "clumsy_unblock"})
            QMessageBox.critical(self, "Error", f"Failed to unblock IP: {e}")
            # Add to history
            self.add_history_entry(ip, "Clumsy Unblock", "Clumsy network disruptor", "Error")
    
    def block_all_ips(self):
        """Block all IPs from the device list using Clumsy network disruptor"""
        try:
            if not self.controller:
                QMessageBox.warning(self, "Warning", "Controller not available")
                return
            
            devices = self.controller.get_devices()
            if not devices:
                QMessageBox.information(self, "Info", "No devices to block")
                return
            
            reply = QMessageBox.question(self, "Confirm", 
                                       f"Block all {len(devices)} devices using Clumsy network disruptor?",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            
            if reply == QMessageBox.StandardButton.Yes:
                # Use Clumsy network disruptor
                from app.firewall.clumsy_network_disruptor import clumsy_network_disruptor
                from app.firewall.enterprise_network_disruptor import enterprise_network_disruptor
                
                # Initialize Clumsy if not running
                if not clumsy_network_disruptor.is_running:
                    if not clumsy_network_disruptor.initialize():
                        QMessageBox.critical(self, "Error", "Failed to initialize Clumsy network disruptor")
                        return
                    clumsy_network_disruptor.start_clumsy()
                
                # Initialize enterprise disruptor as backup
                if not enterprise_network_disruptor.is_running:
                    if not enterprise_network_disruptor.initialize():
                        QMessageBox.critical(self, "Error", "Failed to initialize enterprise network disruptor")
                    else:
                        enterprise_network_disruptor.start_enterprise()
                
                # Use Clumsy methods
                clumsy_methods = ["drop", "lag", "throttle", "duplicate", "corrupt", "rst"]
                enterprise_methods = ["arp_spoof", "icmp_flood", "syn_flood", "udp_flood", "packet_drop"]
                
                blocked_count = 0
                for device in devices:
                    # Try Clumsy first
                    success = clumsy_network_disruptor.disconnect_device_clumsy(device.ip, clumsy_methods)
                    if success:
                        blocked_count += 1
                    else:
                        # Fallback to enterprise disruptor
                        success = enterprise_network_disruptor.disconnect_device_enterprise(device.ip, enterprise_methods)
                        if success:
                            blocked_count += 1
                
                self.status_label.setText(f"Blocked {blocked_count}/{len(devices)} devices using Clumsy + Enterprise disruptors")
                self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
                
        except Exception as e:
            log_error(f"Error blocking all IPs: {e}", exception=e, category="FIREWALL", severity="HIGH", 
                     context={"method": "clumsy_block_all", "device_count": len(devices) if devices else 0})
            QMessageBox.critical(self, "Error", f"Failed to block all IPs: {e}")
    
    def test_disconnect_methods(self):
        """Test individual disconnect methods to see which ones are working"""
        try:
            ip = self.block_ip_input.text().strip()
            if not ip:
                QMessageBox.warning(self, "Warning", "Please enter an IP address to test")
                return
            
            # Use Clumsy network disruptor
            from app.firewall.clumsy_network_disruptor import clumsy_network_disruptor
            from app.firewall.enterprise_network_disruptor import enterprise_network_disruptor
            
            # Initialize Clumsy if not running
            if not clumsy_network_disruptor.is_running:
                if not clumsy_network_disruptor.initialize():
                    QMessageBox.critical(self, "Error", "Failed to initialize Clumsy network disruptor")
                    return
                clumsy_network_disruptor.start_clumsy()
            
            # Initialize enterprise disruptor as backup
            if not enterprise_network_disruptor.is_running:
                if not enterprise_network_disruptor.initialize():
                    QMessageBox.critical(self, "Error", "Failed to initialize enterprise network disruptor")
                else:
                    enterprise_network_disruptor.start_enterprise()
            
            # Test Clumsy methods
            clumsy_methods = ["drop", "lag", "throttle", "duplicate", "corrupt", "rst"]
            enterprise_methods = ["arp_spoof", "icmp_flood", "syn_flood", "udp_flood", "packet_drop"]
            
            results = []
            
            # Test Clumsy methods
            for method in clumsy_methods:
                try:
                    success = clumsy_network_disruptor.disconnect_device_clumsy(ip, [method])
                    status = "✅ Working" if success else "❌ Failed"
                    results.append(f"Clumsy {method}: {status}")
                    
                    # Clean up after each test
                    clumsy_network_disruptor.reconnect_device_clumsy(ip)
                    
                except Exception as e:
                    results.append(f"Clumsy {method}: ❌ Error - {str(e)}")
            
            # Test Enterprise methods
            for method in enterprise_methods:
                try:
                    success = enterprise_network_disruptor.disconnect_device_enterprise(ip, [method])
                    status = "✅ Working" if success else "❌ Failed"
                    results.append(f"Enterprise {method}: {status}")
                    
                    # Clean up after each test
                    enterprise_network_disruptor.reconnect_device_enterprise(ip)
                    
                except Exception as e:
                    results.append(f"Enterprise {method}: ❌ Error - {str(e)}")
            
            # Test UDP interruption separately
            try:
                from app.firewall.udp_port_interrupter import udp_port_interrupter
                udp_success = udp_port_interrupter.start_udp_interruption([ip], drop_rate=50, duration=5)
                udp_status = "✅ Working" if udp_success else "❌ Failed"
                results.append(f"udp_interrupt: {udp_status}")
                
                # Stop UDP interruption after test
                udp_port_interrupter.stop_udp_interruption()
                
            except Exception as e:
                results.append(f"udp_interrupt: ❌ Error - {str(e)}")
            
            # Show results
            result_text = f"Test Results for {ip}:\n\n" + "\n".join(results)
            QMessageBox.information(self, "Method Test Results", result_text)
            
            # Update status
            working_count = sum(1 for r in results if "✅ Working" in r)
            self.status_label.setText(f"Tested {len(methods) + 1} methods: {working_count} working")
            self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
            
        except Exception as e:
            log_error(f"Error testing disconnect methods: {e}", exception=e, category="FIREWALL", severity="MEDIUM", 
                     context={"ip": ip, "method": "test_methods"})
            QMessageBox.critical(self, "Error", f"Failed to test methods: {e}")
    
    def test_udp_interruption(self):
        """Test UDP interruption specifically"""
        try:
            ip = self.block_ip_input.text().strip()
            if not ip:
                QMessageBox.warning(self, "Warning", "Please enter an IP address to test UDP interruption")
                return
            
            from app.firewall.udp_port_interrupter import udp_port_interrupter
            
            # Test UDP interruption
            success = udp_port_interrupter.start_udp_interruption([ip], drop_rate=50, duration=10)
            
            if success:
                QMessageBox.information(self, "UDP Test", 
                    f"UDP interruption started successfully for {ip}\n"
                    "Testing for 10 seconds...\n"
                    "Check if you notice any network disruption.")
                
                # Stop after 10 seconds
                import threading
                def stop_after_delay():
                    import time
                    time.sleep(10)
                    udp_port_interrupter.stop_udp_interruption()
                    self.status_label.setText("UDP interruption test completed")
                
                threading.Thread(target=stop_after_delay, daemon=True).start()
                
            else:
                QMessageBox.critical(self, "UDP Test Failed", 
                    f"Failed to start UDP interruption for {ip}\n"
                    "Check the logs for more details.")
                
        except Exception as e:
            log_error(f"Error testing UDP interruption: {e}", exception=e, category="FIREWALL", severity="MEDIUM", 
                     context={"ip": ip, "method": "test_udp"})
            QMessageBox.critical(self, "Error", f"Failed to test UDP interruption: {e}")
    
    def apply_throttling(self):
        """Apply traffic throttling to the selected IP"""
        try:
            ip = self.throttle_ip_input.text().strip()
            if not ip:
                QMessageBox.warning(self, "Warning", "Please enter an IP address")
                return
            
            bandwidth = self.bandwidth_slider.value()
            latency = self.latency_slider.value()
            jitter = self.jitter_slider.value()
            packet_loss = self.loss_slider.value()
            
            success = self.manipulator.throttle_connection(
                ip, bandwidth, latency, jitter, packet_loss
            )
            
            if success:
                self.status_label.setText(f"Applied throttling to {ip}")
                self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
                self.throttle_ip_input.clear()
                self.manipulation_started.emit(ip, "throttle")
                # Add to history
                details = f"Bandwidth: {bandwidth}Mbps, Latency: {latency}ms, Jitter: {jitter}ms, Loss: {packet_loss}%"
                self.add_history_entry(ip, "Throttle", details, "Success")
            else:
                self.status_label.setText(f"Failed to throttle {ip}")
                self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
                # Add to history
                self.add_history_entry(ip, "Throttle", "Traffic throttling", "Failed")
                
        except Exception as e:
            log_error(f"Error applying throttling: {e}")
            QMessageBox.critical(self, "Error", f"Failed to apply throttling: {e}")
            # Add to history
            self.add_history_entry(ip, "Throttle", "Traffic throttling", "Error")
    
    def clear_throttling(self):
        """Clear throttling for the selected IP"""
        try:
            ip = self.throttle_ip_input.text().strip()
            if not ip:
                QMessageBox.warning(self, "Warning", "Please enter an IP address")
                return
            
            # Remove throttling rules for this IP
            rules_to_remove = []
            for rule_id, rule in self.manipulator.rules.items():
                if rule.target_ip == ip and rule.rule_type == 'throttle':
                    rules_to_remove.append(rule_id)
            
            for rule_id in rules_to_remove:
                self.manipulator.remove_rule(rule_id)
            
            self.status_label.setText(f"Cleared throttling for {ip}")
            self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
            self.throttle_ip_input.clear()
            self.manipulation_stopped.emit(ip, "throttle")
            # Add to history
            self.add_history_entry(ip, "Throttle", "Cleared throttling", "Success")
            
        except Exception as e:
            log_error(f"Error clearing throttling: {e}")
            QMessageBox.critical(self, "Error", f"Failed to clear throttling: {e}")
            # Add to history
            self.add_history_entry(ip, "Throttle", "Cleared throttling", "Error")
    
    def apply_redirect(self):
        """Apply traffic redirect"""
        try:
            source_ip = self.source_ip_input.text().strip()
            target_ip = self.target_ip_input.text().strip()
            
            if not source_ip or not target_ip:
                QMessageBox.warning(self, "Warning", "Please enter both source and target IPs")
                return
            
            source_port = self.source_port_input.value() if self.source_port_input.value() > 0 else None
            target_port = self.target_port_input.value()
            
            success = self.manipulator.redirect_traffic(source_ip, target_ip, source_port)
            
            if success:
                self.status_label.setText(f"Redirected {source_ip} to {target_ip}")
                self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
                self.source_ip_input.clear()
                self.target_ip_input.clear()
                self.manipulation_started.emit(source_ip, "redirect")
                # Add to history
                details = f"Redirected to {target_ip}:{target_port}"
                self.add_history_entry(source_ip, "Redirect", details, "Success")
            else:
                self.status_label.setText(f"Failed to redirect {source_ip}")
                self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
                # Add to history
                self.add_history_entry(source_ip, "Redirect", "Traffic redirect", "Failed")
                
        except Exception as e:
            log_error(f"Error applying redirect: {e}")
            QMessageBox.critical(self, "Error", f"Failed to apply redirect: {e}")
            # Add to history
            self.add_history_entry(source_ip, "Redirect", "Traffic redirect", "Error")
    
    def clear_redirect(self):
        """Clear traffic redirect"""
        try:
            source_ip = self.source_ip_input.text().strip()
            if not source_ip:
                QMessageBox.warning(self, "Warning", "Please enter source IP")
                return
            
            # Remove redirect rules for this IP
            rules_to_remove = []
            for rule_id, rule in self.manipulator.rules.items():
                if rule.target_ip == source_ip and rule.rule_type == 'redirect':
                    rules_to_remove.append(rule_id)
            
            for rule_id in rules_to_remove:
                self.manipulator.remove_rule(rule_id)
            
            self.status_label.setText(f"Cleared redirect for {source_ip}")
            self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
            self.source_ip_input.clear()
            self.manipulation_stopped.emit(source_ip, "redirect")
            # Add to history
            self.add_history_entry(source_ip, "Redirect", "Cleared redirect", "Success")
            
        except Exception as e:
            log_error(f"Error clearing redirect: {e}")
            QMessageBox.critical(self, "Error", f"Failed to clear redirect: {e}")
            # Add to history
            self.add_history_entry(source_ip, "Redirect", "Cleared redirect", "Error")
    
    def apply_packet_modifications(self):
        """Apply packet modifications"""
        try:
            ip = self.modify_ip_input.text().strip()
            if not ip:
                QMessageBox.warning(self, "Warning", "Please enter an IP address")
                return
            
            modifications = {
                'ttl': self.ttl_spinbox.value(),
                'fragment': self.fragment_checkbox.isChecked(),
                'corrupt': self.corrupt_checkbox.isChecked()
            }
            
            success = self.manipulator.modify_packets(ip, modifications)
            
            if success:
                self.status_label.setText(f"Applied packet modifications to {ip}")
                self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
                self.modify_ip_input.clear()
                self.manipulation_started.emit(ip, "modify")
                # Add to history
                details = f"TTL: {modifications['ttl']}, Fragment: {modifications['fragment']}, Corrupt: {modifications['corrupt']}"
                self.add_history_entry(ip, "Modify", details, "Success")
            else:
                self.status_label.setText(f"Failed to modify packets for {ip}")
                self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
                # Add to history
                self.add_history_entry(ip, "Modify", "Packet modifications", "Failed")
                
        except Exception as e:
            log_error(f"Error applying packet modifications: {e}")
            QMessageBox.critical(self, "Error", f"Failed to apply packet modifications: {e}")
            # Add to history
            self.add_history_entry(ip, "Modify", "Packet modifications", "Error")
    
    def clear_packet_modifications(self):
        """Clear packet modifications"""
        try:
            ip = self.modify_ip_input.text().strip()
            if not ip:
                QMessageBox.warning(self, "Warning", "Please enter an IP address")
                return
            
            # Remove modification rules for this IP
            rules_to_remove = []
            for rule_id, rule in self.manipulator.rules.items():
                if rule.target_ip == ip and rule.rule_type == 'modify':
                    rules_to_remove.append(rule_id)
            
            for rule_id in rules_to_remove:
                self.manipulator.remove_rule(rule_id)
            
            self.status_label.setText(f"Cleared packet modifications for {ip}")
            self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
            self.modify_ip_input.clear()
            self.manipulation_stopped.emit(ip, "modify")
            # Add to history
            self.add_history_entry(ip, "Modify", "Cleared packet modifications", "Success")
            
        except Exception as e:
            log_error(f"Error clearing packet modifications: {e}")
            QMessageBox.critical(self, "Error", f"Failed to clear packet modifications: {e}")
            # Add to history
            self.add_history_entry(ip, "Modify", "Cleared packet modifications", "Error")
    
    def refresh_rules_table(self):
        """Refresh the rules table"""
        try:
            rules = self.manipulator.get_active_rules()
            self.rules_table.setRowCount(len(rules))
            
            for row, rule in enumerate(rules):
                self.rules_table.setItem(row, 0, QTableWidgetItem(rule['rule_id']))
                self.rules_table.setItem(row, 1, QTableWidgetItem(rule['rule_type']))
                self.rules_table.setItem(row, 2, QTableWidgetItem(rule['target_ip']))
                self.rules_table.setItem(row, 3, QTableWidgetItem(rule['action']))
                self.rules_table.setItem(row, 4, QTableWidgetItem("Active" if rule['enabled'] else "Inactive"))
                
                created_time = time.strftime("%H:%M:%S", time.localtime(rule['created_at']))
                self.rules_table.setItem(row, 5, QTableWidgetItem(created_time))
                
        except Exception as e:
            log_error(f"Error refreshing rules table: {e}")
    
    def remove_selected_rule(self):
        """Remove the selected rule"""
        try:
            current_row = self.rules_table.currentRow()
            if current_row < 0:
                QMessageBox.warning(self, "Warning", "Please select a rule to remove")
                return
            
            rule_id = self.rules_table.item(current_row, 0).text()
            
            reply = QMessageBox.question(self, "Confirm", 
                                       f"Remove rule '{rule_id}'?",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            
            if reply == QMessageBox.StandardButton.Yes:
                success = self.manipulator.remove_rule(rule_id)
                if success:
                    self.status_label.setText(f"Removed rule: {rule_id}")
                    self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
                    self.rule_removed.emit(rule_id)
                else:
                    self.status_label.setText(f"Failed to remove rule: {rule_id}")
                    self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
                    
        except Exception as e:
            log_error(f"Error removing rule: {e}")
            QMessageBox.critical(self, "Error", f"Failed to remove rule: {e}")
    
    def clear_all_rules(self):
        """Clear all network rules"""
        try:
            reply = QMessageBox.question(self, "Confirm", 
                                       "Clear all network rules?",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            
            if reply == QMessageBox.StandardButton.Yes:
                success = self.manipulator.clear_all_rules()
                if success:
                    self.status_label.setText("Cleared all network rules")
                    self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
                else:
                    self.status_label.setText("Failed to clear all rules")
                    self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
                    
        except Exception as e:
            log_error(f"Error clearing all rules: {e}")
            QMessageBox.critical(self, "Error", f"Failed to clear all rules: {e}")
    
    def refresh_network_info(self):
        """Refresh network information display"""
        try:
            info = self.manipulator.get_network_info()
            
            info_text = f"""
Network Information:
===================
Platform: {info.get('platform', 'Unknown')}
Admin Privileges: {'Yes' if info.get('is_admin', False) else 'No'}
Active Rules: {info.get('active_rules', 0)}
Active Manipulations: {info.get('active_manipulations', 0)}
Local IP: {info.get('local_ip', 'Unknown')}
Network Interface: {info.get('network_interface', 'Unknown')}
DNS Servers: {', '.join(info.get('dns_servers', []))}

Last Updated: {time.strftime('%H:%M:%S')}
            """.strip()
            
            self.network_info_text.setText(info_text)
            
        except Exception as e:
            log_error(f"Error refreshing network info: {e}")
            self.network_info_text.setText(f"Error loading network info: {e}")
    
    def set_controller(self, controller):
        """Set the controller for this component"""
        self.controller = controller
    
    def cleanup(self):
        """Cleanup resources"""
        try:
            if hasattr(self, 'update_timer'):
                self.update_timer.stop()
        except Exception as e:
            log_error(f"Error during cleanup: {e}")
    
    # History management methods
    def load_history(self) -> List[Dict]:
        """Load history from file"""
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r') as f:
                    history = json.load(f)
                    # Clean old entries (older than 30 days)
                    cutoff_date = datetime.now() - timedelta(days=30)
                    history = [entry for entry in history 
                             if datetime.fromisoformat(entry['timestamp']) > cutoff_date]
                    return history
            return []
        except Exception as e:
            log_error(f"Error loading history: {e}")
            return []
    
    def save_history(self):
        """Save history to file"""
        try:
            with open(self.history_file, 'w') as f:
                json.dump(self.ip_history, f, indent=2)
        except Exception as e:
            log_error(f"Error saving history: {e}")
    
    def add_history_entry(self, ip: str, action: str, details: str = "", status: str = "Success", duration: str = ""):
        """Add a new history entry"""
        try:
            entry = {
                'timestamp': datetime.now().isoformat(),
                'ip': ip,
                'action': action,
                'details': details,
                'status': status,
                'duration': duration
            }
            self.ip_history.append(entry)
            self.save_history()
            self.refresh_history_table()
            log_info(f"Added history entry: {action} on {ip}")
        except Exception as e:
            log_error(f"Error adding history entry: {e}")
    
    def refresh_history_table(self):
        """Refresh the history table with current data"""
        try:
            self.history_table.setRowCount(0)
            
            # Get filtered entries
            filtered_entries = self.get_filtered_history()
            
            for entry in filtered_entries:
                row = self.history_table.rowCount()
                self.history_table.insertRow(row)
                
                # Format timestamp
                timestamp = datetime.fromisoformat(entry['timestamp'])
                formatted_time = timestamp.strftime("%Y-%m-%d %H:%M:%S")
                
                # Set table items
                self.history_table.setItem(row, 0, QTableWidgetItem(formatted_time))
                self.history_table.setItem(row, 1, QTableWidgetItem(entry['ip']))
                self.history_table.setItem(row, 2, QTableWidgetItem(entry['action']))
                self.history_table.setItem(row, 3, QTableWidgetItem(entry['details']))
                
                # Color status based on success/failure
                status_item = QTableWidgetItem(entry['status'])
                if entry['status'] == 'Success':
                    status_item.setBackground(QColor(76, 175, 80))  # Green
                else:
                    status_item.setBackground(QColor(244, 67, 54))  # Red
                self.history_table.setItem(row, 4, status_item)
                
                self.history_table.setItem(row, 5, QTableWidgetItem(entry['duration']))
            
            # Update stats
            self.update_history_stats()
            
        except Exception as e:
            log_error(f"Error refreshing history table: {e}")
    
    def get_filtered_history(self) -> List[Dict]:
        """Get filtered history entries based on current filters"""
        try:
            filtered = self.ip_history.copy()
            
            # Filter by date range
            from_date = self.history_from_date.date().toPyDate()
            to_date = self.history_to_date.date().toPyDate()
            
            filtered = [entry for entry in filtered 
                       if from_date <= datetime.fromisoformat(entry['timestamp']).date() <= to_date]
            
            # Filter by action type
            action_filter = self.history_action_filter.currentText()
            if action_filter != "All":
                filtered = [entry for entry in filtered if entry['action'] == action_filter]
            
            return filtered
        except Exception as e:
            log_error(f"Error filtering history: {e}")
            return self.ip_history
    
    def filter_history(self):
        """Apply current filters to history"""
        self.refresh_history_table()
    
    def clear_history(self):
        """Clear all history entries"""
        try:
            reply = QMessageBox.question(
                self, "Clear History",
                "Are you sure you want to clear all history entries?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self.ip_history.clear()
                self.save_history()
                self.refresh_history_table()
                log_info("History cleared")
                
        except Exception as e:
            log_error(f"Error clearing history: {e}")
    
    def update_history_stats(self):
        """Update history statistics"""
        try:
            total_entries = len(self.ip_history)
            
            # Count entries from last 7 days
            seven_days_ago = datetime.now() - timedelta(days=7)
            last_7_days = len([entry for entry in self.ip_history 
                              if datetime.fromisoformat(entry['timestamp']) > seven_days_ago])
            
            # Count entries from last 30 days
            thirty_days_ago = datetime.now() - timedelta(days=30)
            last_30_days = len([entry for entry in self.ip_history 
                               if datetime.fromisoformat(entry['timestamp']) > thirty_days_ago])
            
            stats_text = f"Total entries: {total_entries} | Last 7 days: {last_7_days} | Last 30 days: {last_30_days}"
            self.history_stats_label.setText(stats_text)
            
        except Exception as e:
            log_error(f"Error updating history stats: {e}") 

    def export_history(self):
        """Export history to CSV file"""
        try:
            from PyQt6.QtWidgets import QFileDialog
            import csv
            from datetime import datetime
            
            # Get file path from user
            filename, _ = QFileDialog.getSaveFileName(
                self, 
                "Export History", 
                f"network_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                "CSV Files (*.csv)"
            )
            
            if filename:
                history = self.load_history()
                
                with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                    fieldnames = ['Date/Time', 'IP Address', 'Action', 'Details', 'Status', 'Duration']
                    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                    
                    writer.writeheader()
                    for entry in history:
                        writer.writerow(entry)
                
                self.status_label.setText(f"History exported to {filename}")
                self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
                
                log_info(f"History exported to {filename}")
                
        except Exception as e:
            log_error(f"Error exporting history: {e}")
            self.status_label.setText(f"Export failed: {e}")
            self.status_label.setStyleSheet("color: #f44336; font-weight: bold;") 