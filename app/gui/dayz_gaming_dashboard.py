#!/usr/bin/env python3
"""
DayZ Gaming Dashboard
Comprehensive interface for DayZ gaming performance management
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, 
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QGroupBox, QProgressBar, QLineEdit, QSpinBox, QComboBox,
    QTextEdit, QSplitter, QFrame, QMessageBox, QTabWidget
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QPalette
from typing import Dict, List, Optional
import json
from datetime import datetime

from app.logs.logger import log_info, log_error

class DayZGamingDashboard(QWidget):
    """DayZ Gaming Performance Dashboard"""
    
    # Signals
    server_added = pyqtSignal(dict)
    server_removed = pyqtSignal(str)
    optimization_triggered = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🎮 DayZ Gaming Dashboard")
        self.setMinimumSize(1000, 700)
        
        # Initialize data
        self.dayz_servers = []
        self.gaming_performance = {}
        self.optimization_history = []
        
        # Setup UI
        self.setup_ui()
        self.setup_timers()
        self.load_data()
        
    def setup_ui(self):
        """Setup the dashboard UI"""
        layout = QVBoxLayout()
        
        # Title
        title = QLabel("🎮 DayZ Gaming Performance Dashboard")
        title.setFont(QFont("Arial", 18, QFont.Weight.Bold))
        title.setStyleSheet("color: #00ff00; margin: 10px; text-align: center;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # Create tabs
        self.tabs = QTabWidget()
        
        # Server Management Tab
        server_tab = self.create_server_management_tab()
        self.tabs.addTab(server_tab, "🎯 Server Management")
        
        # Optimization Tab
        optimization_tab = self.create_optimization_tab()
        self.tabs.addTab(optimization_tab, "⚡ Optimization")
        
        # Gaming Rules Tab
        rules_tab = self.create_gaming_rules_tab()
        self.tabs.addTab(rules_tab, "📋 Gaming Rules")
        
        # Performance monitoring tab removed for optimization
        
        # Network Analysis Tab removed for optimization
        
        layout.addWidget(self.tabs)
        
        # Status bar
        status_layout = QHBoxLayout()
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #00ff00; font-weight: bold;")
        status_layout.addWidget(self.status_label)
        
        # Refresh button
        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.clicked.connect(self.refresh_data)
        status_layout.addWidget(refresh_btn)
        
        layout.addLayout(status_layout)
        self.setLayout(layout)
        
    def create_server_management_tab(self) -> QWidget:
        """Create the server management tab"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Add Server Section
        add_server_group = QGroupBox("➕ Add DayZ Server")
        add_server_layout = QGridLayout()
        
        # Server IP
        add_server_layout.addWidget(QLabel("Server IP:"), 0, 0)
        self.server_ip_input = QLineEdit()
        self.server_ip_input.setPlaceholderText("192.168.1.100")
        add_server_layout.addWidget(self.server_ip_input, 0, 1)
        
        # Server Port
        add_server_layout.addWidget(QLabel("Port:"), 0, 2)
        self.server_port_input = QSpinBox()
        self.server_port_input.setRange(1, 65535)
        self.server_port_input.setValue(2302)  # Default DayZ port
        add_server_layout.addWidget(self.server_port_input, 0, 3)
        
        # Server Name
        add_server_layout.addWidget(QLabel("Server Name:"), 1, 0)
        self.server_name_input = QLineEdit()
        self.server_name_input.setPlaceholderText("My DayZ Server")
        add_server_layout.addWidget(self.server_name_input, 1, 1)
        
        # Server Type
        add_server_layout.addWidget(QLabel("Server Type:"), 1, 2)
        self.server_type_combo = QComboBox()
        self.server_type_combo.addItems(["Official", "Community", "Modded", "Private"])
        add_server_layout.addWidget(self.server_type_combo, 1, 3)
        
        # Add button
        add_server_btn = QPushButton("Add Server")
        add_server_btn.clicked.connect(self.add_dayz_server)
        add_server_layout.addWidget(add_server_btn, 2, 0, 1, 4)
        
        add_server_group.setLayout(add_server_layout)
        layout.addWidget(add_server_group)
        
        # Server List Section
        server_list_group = QGroupBox("📋 DayZ Servers")
        server_list_layout = QVBoxLayout()
        
        # Server table
        self.server_table = QTableWidget()
        self.server_table.setColumnCount(7)
        self.server_table.setHorizontalHeaderLabels([
            "Server Name", "IP Address", "Port", "Type", "Status", "Latency", "Actions"
        ])
        
        # Set table properties
        header = self.server_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        
        self.server_table.setAlternatingRowColors(True)
        self.server_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        
        server_list_layout.addWidget(self.server_table)
        
        # Server controls
        server_controls_layout = QHBoxLayout()
        
        refresh_servers_btn = QPushButton("🔄 Refresh Servers")
        refresh_servers_btn.clicked.connect(self.refresh_server_status)
        server_controls_layout.addWidget(refresh_servers_btn)
        
        test_all_btn = QPushButton("🧪 Test All Servers")
        test_all_btn.clicked.connect(self.test_all_servers)
        server_controls_layout.addWidget(test_all_btn)
        
        server_controls_layout.addStretch()
        
        server_list_layout.addLayout(server_controls_layout)
        server_list_group.setLayout(server_list_layout)
        layout.addWidget(server_list_group)
        
        widget.setLayout(layout)
        return widget
    
    def create_optimization_tab(self) -> QWidget:
        """Create the optimization tab"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Optimization Controls
        controls_group = QGroupBox("🎛️ Optimization Controls")
        controls_layout = QVBoxLayout()
        
        # Auto-optimization toggle
        auto_opt_layout = QHBoxLayout()
        auto_opt_layout.addWidget(QLabel("Auto-optimization:"))
        self.auto_optimization_checkbox = QComboBox()
        self.auto_optimization_checkbox.addItems(["Disabled", "Conservative", "Aggressive", "Gaming Focused"])
        self.auto_optimization_checkbox.setCurrentText("Gaming Focused")
        auto_opt_layout.addWidget(self.auto_optimization_checkbox)
        controls_layout.addLayout(auto_opt_layout)
        
        # Manual optimization button
        manual_opt_layout = QHBoxLayout()
        self.optimize_now_btn = QPushButton("⚡ Optimize Now")
        self.optimize_now_btn.clicked.connect(self.trigger_optimization)
        self.optimize_now_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4CAF50, stop:0.5 #2196F3, stop:1 #9C27B0);
                color: white;
                border: none;
                padding: 15px;
                border-radius: 8px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #45a049, stop:0.5 #1976D2, stop:1 #7B1FA2);
            }
        """)
        manual_opt_layout.addWidget(self.optimize_now_btn)
        
        # Reset optimization button
        reset_opt_btn = QPushButton("🔄 Reset Optimization")
        reset_opt_btn.clicked.connect(self.reset_optimization)
        manual_opt_layout.addWidget(reset_opt_btn)
        
        controls_layout.addLayout(manual_opt_layout)
        controls_group.setLayout(controls_layout)
        layout.addWidget(controls_group)
        
        # Optimization Settings
        settings_group = QGroupBox("⚙️ Optimization Settings")
        settings_layout = QGridLayout()
        
        # Gaming traffic priority
        settings_layout.addWidget(QLabel("Gaming Traffic Priority:"), 0, 0)
        self.gaming_priority_combo = QComboBox()
        self.gaming_priority_combo.addItems(["Low", "Normal", "High", "Critical"])
        self.gaming_priority_combo.setCurrentText("High")
        settings_layout.addWidget(self.gaming_priority_combo, 0, 1)
        
        # Reserved bandwidth
        settings_layout.addWidget(QLabel("Reserved Bandwidth (Mbps):"), 1, 0)
        self.reserved_bandwidth_spin = QSpinBox()
        self.reserved_bandwidth_spin.setRange(10, 1000)
        self.reserved_bandwidth_spin.setValue(100)
        self.reserved_bandwidth_spin.setSuffix(" Mbps")
        settings_layout.addWidget(self.reserved_bandwidth_spin, 1, 1)
        
        # Latency threshold
        settings_layout.addWidget(QLabel("Latency Threshold (ms):"), 2, 0)
        self.latency_threshold_spin = QSpinBox()
        self.latency_threshold_spin.setRange(50, 500)
        self.latency_threshold_spin.setValue(100)
        self.latency_threshold_spin.setSuffix(" ms")
        settings_layout.addWidget(self.latency_threshold_spin, 2, 1)
        
        # Apply settings button
        apply_settings_btn = QPushButton("Apply Settings")
        apply_settings_btn.clicked.connect(self.apply_optimization_settings)
        settings_layout.addWidget(apply_settings_btn, 3, 0, 1, 2)
        
        settings_group.setLayout(settings_layout)
        layout.addWidget(settings_group)
        
        # Optimization History
        history_group = QGroupBox("📚 Optimization History")
        history_layout = QVBoxLayout()
        
        self.optimization_history_table = QTableWidget()
        self.optimization_history_table.setColumnCount(4)
        self.optimization_history_table.setHorizontalHeaderLabels([
            "Timestamp", "Type", "Status", "Details"
        ])
        
        header = self.optimization_history_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        
        self.optimization_history_table.setAlternatingRowColors(True)
        self.optimization_history_table.setMaximumHeight(200)
        
        history_layout.addWidget(self.optimization_history_table)
        history_group.setLayout(history_layout)
        layout.addWidget(history_group)
        
        widget.setLayout(layout)
        return widget
    
    def create_gaming_rules_tab(self) -> QWidget:
        """Create the gaming rules tab"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Active Rules
        rules_group = QGroupBox("🔒 Active Gaming Rules")
        rules_layout = QVBoxLayout()
        
        # Rules table
        self.rules_table = QTableWidget()
        self.rules_table.setColumnCount(5)
        self.rules_table.setHorizontalHeaderLabels([
            "Rule Name", "Type", "Priority", "Status", "Actions"
        ])
        
        header = self.rules_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        
        self.rules_table.setAlternatingRowColors(True)
        self.rules_table.setMaximumHeight(300)
        
        rules_layout.addWidget(self.rules_table)
        
        # Rule controls
        rule_controls_layout = QHBoxLayout()
        
        enable_all_btn = QPushButton("✅ Enable All")
        enable_all_btn.clicked.connect(self.enable_all_rules)
        rule_controls_layout.addWidget(enable_all_btn)
        
        disable_all_btn = QPushButton("❌ Disable All")
        disable_all_btn.clicked.connect(self.disable_all_rules)
        rule_controls_layout.addWidget(disable_all_btn)
        
        rule_controls_layout.addStretch()
        
        rules_layout.addLayout(rule_controls_layout)
        rules_group.setLayout(rules_layout)
        layout.addWidget(rules_group)
        
        # Rule Statistics
        stats_group = QGroupBox("Rule Statistics")
        stats_layout = QGridLayout()
        
        # Total rules
        stats_layout.addWidget(QLabel("Total Rules:"), 0, 0)
        self.total_rules_label = QLabel("--")
        self.total_rules_label.setStyleSheet("color: #00ff00; font-weight: bold;")
        stats_layout.addWidget(self.total_rules_label, 0, 1)
        
        # Active rules
        stats_layout.addWidget(QLabel("Active Rules:"), 1, 0)
        self.active_rules_label = QLabel("--")
        self.active_rules_label.setStyleSheet("color: #00ccff; font-weight: bold;")
        stats_layout.addWidget(self.active_rules_label, 1, 1)
        
        # Blocked devices
        stats_layout.addWidget(QLabel("Blocked Devices:"), 2, 0)
        self.blocked_devices_label = QLabel("--")
        self.blocked_devices_label.setStyleSheet("color: #ff0000; font-weight: bold;")
        stats_layout.addWidget(self.blocked_devices_label, 2, 1)
        
        # Last rule trigger
        stats_layout.addWidget(QLabel("Last Rule Trigger:"), 0, 2)
        self.last_rule_trigger_label = QLabel("Never")
        self.last_rule_trigger_label.setStyleSheet("color: #888888; font-size: 12px;")
        stats_layout.addWidget(self.last_rule_trigger_label, 0, 3)
        
        stats_group.setLayout(stats_layout)
        layout.addWidget(stats_group)
        
        widget.setLayout(layout)
        return widget
    
    # Network analysis tab fully removed for optimization
    
    def setup_timers(self):
        """Setup timers for data updates"""
        # Performance update timer removed for optimization
        
        # Server status timer
        self.server_timer = QTimer()
        self.server_timer.timeout.connect(self.update_server_status)
        self.server_timer.start(30000)  # Update every 30 seconds
    
    def load_data(self):
        """Load initial data"""
        try:
            # Load DayZ servers
            self.load_dayz_servers()
            
            # Load gaming performance data
            self.load_gaming_performance()
            
            # Load optimization history
            self.load_optimization_history()
            
            # Load gaming rules
            self.load_gaming_rules()
            
            self.status_label.setText("Data loaded successfully")
            
        except Exception as e:
            log_error(f"Error loading data: {e}")
            self.status_label.setText("Error loading data")
    
    def load_dayz_servers(self):
        """Load DayZ servers from settings"""
        try:
            # This would load from your plugin settings
            # For now, use sample data
            self.dayz_servers = [
                {
                    'name': 'Official DayZ Server',
                    'ip': '192.168.1.100',
                    'port': 2302,
                    'type': 'Official',
                    'status': 'Online',
                    'latency': 45
                },
                {
                    'name': 'Community Modded Server',
                    'ip': '192.168.1.101',
                    'port': 2303,
                    'type': 'Modded',
                    'status': 'Online',
                    'latency': 78
                }
            ]
            
            self.update_server_table()
            
        except Exception as e:
            log_error(f"Error loading DayZ servers: {e}")
    
    def load_gaming_performance(self):
        """Load gaming performance data"""
        try:
            # This would load from your plugin
            # For now, use sample data
            self.gaming_performance = {
                'network_performance': 'Excellent',
                'avg_latency': 65,
                'packet_loss': 0.2,
                'bandwidth_usage': 35,
                'gaming_devices': 3,
                'last_optimization': '2025-01-16 15:30:00'
            }
            
            # Performance display removed
            
        except Exception as e:
            log_error(f"Error loading gaming performance: {e}")
    
    def load_optimization_history(self):
        """Load optimization history"""
        try:
            # This would load from your plugin
            # For now, use sample data
            self.optimization_history = [
                {
                    'timestamp': '2025-01-16 15:30:00',
                    'type': 'Auto',
                    'status': 'Success',
                    'details': 'Network optimized for gaming performance'
                },
                {
                    'timestamp': '2025-01-16 14:15:00',
                    'type': 'Manual',
                    'status': 'Success',
                    'details': 'Gaming traffic prioritization applied'
                }
            ]
            
            self.update_optimization_history_table()
            
        except Exception as e:
            log_error(f"Error loading optimization history: {e}")
    
    def load_gaming_rules(self):
        """Load gaming rules"""
        try:
            # This would load from your plugin
            # For now, use sample data
            self.gaming_rules = [
                {
                    'name': 'DayZ Traffic Priority',
                    'type': 'Optimization',
                    'priority': 'High',
                    'status': 'Active'
                },
                {
                    'name': 'Anti-DDoS Protection',
                    'type': 'Security',
                    'priority': 'Critical',
                    'status': 'Active'
                }
            ]
            
            self.update_rules_table()
            
        except Exception as e:
            log_error(f"Error loading gaming rules: {e}")
    
    def update_server_table(self):
        """Update the server table display"""
        try:
            self.server_table.setRowCount(len(self.dayz_servers))
            
            for row, server in enumerate(self.dayz_servers):
                # Server Name
                name_item = QTableWidgetItem(server.get('name', '--'))
                self.server_table.setItem(row, 0, name_item)
                
                # IP Address
                ip_item = QTableWidgetItem(server.get('ip', '--'))
                self.server_table.setItem(row, 1, ip_item)
                
                # Port
                port_item = QTableWidgetItem(str(server.get('port', '--')))
                self.server_table.setItem(row, 2, port_item)
                
                # Type
                type_item = QTableWidgetItem(server.get('type', '--'))
                self.server_table.setItem(row, 3, type_item)
                
                # Status
                status_item = QTableWidgetItem(server.get('status', '--'))
                if server.get('status') == 'Online':
                    status_item.setBackground(QColor(0, 255, 0, 50))
                else:
                    status_item.setBackground(QColor(255, 0, 0, 50))
                self.server_table.setItem(row, 4, status_item)
                
                # Latency
                latency = server.get('latency', -1)
                if latency > 0:
                    latency_text = f"{latency} ms"
                    if latency < 50:
                        latency_color = QColor(0, 255, 0, 50)
                    elif latency < 100:
                        latency_color = QColor(255, 255, 0, 50)
                    else:
                        latency_color = QColor(255, 0, 0, 50)
                else:
                    latency_text = "Offline"
                    latency_color = QColor(128, 128, 128, 50)
                
                latency_item = QTableWidgetItem(latency_text)
                latency_item.setBackground(latency_color)
                self.server_table.setItem(row, 5, latency_item)
                
                # Actions
                actions_widget = QWidget()
                actions_layout = QHBoxLayout()
                
                test_btn = QPushButton("Test")
                test_btn.clicked.connect(lambda checked, ip=server.get('ip'): self.test_server(ip))
                actions_layout.addWidget(test_btn)
                
                remove_btn = QPushButton("Remove")
                remove_btn.clicked.connect(lambda checked, ip=server.get('ip'): self.remove_dayz_server(ip))
                actions_layout.addWidget(remove_btn)
                
                actions_widget.setLayout(actions_layout)
                self.server_table.setCellWidget(row, 6, actions_widget)
                
        except Exception as e:
            log_error(f"Error updating server table: {e}")
    
    # update_performance_display removed for optimization
    
    def update_optimization_history_table(self):
        """Update the optimization history table"""
        try:
            self.optimization_history_table.setRowCount(len(self.optimization_history))
            
            for row, entry in enumerate(self.optimization_history):
                # Timestamp
                timestamp_item = QTableWidgetItem(entry.get('timestamp', '--'))
                self.optimization_history_table.setItem(row, 0, timestamp_item)
                
                # Type
                type_item = QTableWidgetItem(entry.get('type', '--'))
                self.optimization_history_table.setItem(row, 1, type_item)
                
                # Status
                status_item = QTableWidgetItem(entry.get('status', '--'))
                if entry.get('status') == 'Success':
                    status_item.setBackground(QColor(0, 255, 0, 50))
                else:
                    status_item.setBackground(QColor(255, 0, 0, 50))
                self.optimization_history_table.setItem(row, 2, status_item)
                
                # Details
                details_item = QTableWidgetItem(entry.get('details', '--'))
                self.optimization_history_table.setItem(row, 3, details_item)
                
        except Exception as e:
            log_error(f"Error updating optimization history table: {e}")
    
    def update_rules_table(self):
        """Update the rules table"""
        try:
            self.rules_table.setRowCount(len(self.gaming_rules))
            
            for row, rule in enumerate(self.gaming_rules):
                # Rule Name
                name_item = QTableWidgetItem(rule.get('name', '--'))
                self.rules_table.setItem(row, 0, name_item)
                
                # Type
                type_item = QTableWidgetItem(rule.get('type', '--'))
                self.rules_table.setItem(row, 1, type_item)
                
                # Priority
                priority_item = QTableWidgetItem(rule.get('priority', '--'))
                self.rules_table.setItem(row, 2, priority_item)
                
                # Status
                status_item = QTableWidgetItem(rule.get('status', '--'))
                if rule.get('status') == 'Active':
                    status_item.setBackground(QColor(0, 255, 0, 50))
                else:
                    status_item.setBackground(QColor(255, 0, 0, 50))
                self.rules_table.setItem(row, 3, status_item)
                
                # Actions
                actions_widget = QWidget()
                actions_layout = QHBoxLayout()
                
                toggle_btn = QPushButton("Toggle")
                toggle_btn.clicked.connect(lambda checked, r=row: self.toggle_rule(r))
                actions_layout.addWidget(toggle_btn)
                
                actions_widget.setLayout(actions_layout)
                self.rules_table.setCellWidget(row, 4, actions_widget)
                
        except Exception as e:
            log_error(f"Error updating rules table: {e}")
    
    def add_dayz_server(self):
        """Add a new DayZ server"""
        try:
            server_ip = self.server_ip_input.text().strip()
            server_port = self.server_port_input.value()
            server_name = self.server_name_input.text().strip()
            server_type = self.server_type_combo.currentText()
            
            if not server_ip:
                QMessageBox.warning(self, "Warning", "Please enter a server IP address")
                return
            
            # Create server info
            server_info = {
                'name': server_name or f"DayZ Server {server_ip}",
                'ip': server_ip,
                'port': server_port,
                'type': server_type,
                'status': 'Unknown',
                'latency': -1
            }
            
            # Add to list
            self.dayz_servers.append(server_info)
            
            # Update table
            self.update_server_table()
            
            # Clear inputs
            self.server_ip_input.clear()
            self.server_name_input.clear()
            self.server_port_input.setValue(2302)
            
            # Emit signal
            self.server_added.emit(server_info)
            
            self.status_label.setText(f"Added server: {server_ip}")
            log_info(f"Added DayZ server: {server_ip}")
            
        except Exception as e:
            log_error(f"Error adding DayZ server: {e}")
            self.status_label.setText("Error adding server")
    
    def remove_dayz_server(self, server_ip: str):
        """Remove a DayZ server"""
        try:
            # Remove from list
            self.dayz_servers = [s for s in self.dayz_servers if s.get('ip') != server_ip]
            
            # Update table
            self.update_server_table()
            
            # Emit signal
            self.server_removed.emit(server_ip)
            
            self.status_label.setText(f"Removed server: {server_ip}")
            log_info(f"Removed DayZ server: {server_ip}")
            
        except Exception as e:
            log_error(f"Error removing DayZ server: {e}")
            self.status_label.setText("Error removing server")
    
    def test_server(self, server_ip: str):
        """Test a specific server"""
        try:
            self.status_label.setText(f"Testing server: {server_ip}")
            
            # Find server in list
            server = next((s for s in self.dayz_servers if s.get('ip') == server_ip), None)
            if server:
                # Simulate server test
                import random
                latency = random.randint(20, 200)
                
                # Update server status
                server['latency'] = latency
                server['status'] = 'Online' if latency > 0 else 'Offline'
                
                # Update table
                self.update_server_table()
                
                self.status_label.setText(f"Server {server_ip} tested: {latency}ms")
            else:
                self.status_label.setText(f"Server {server_ip} not found")
                
        except Exception as e:
            log_error(f"Error testing server: {e}")
            self.status_label.setText("Error testing server")
    
    def test_all_servers(self):
        """Test all servers"""
        try:
            self.status_label.setText("Testing all servers...")
            
            for server in self.dayz_servers:
                self.test_server(server.get('ip'))
            
            self.status_label.setText("All servers tested")
            
        except Exception as e:
            log_error(f"Error testing all servers: {e}")
            self.status_label.setText("Error testing servers")
    
    def trigger_optimization(self):
        """Trigger network optimization"""
        try:
            self.status_label.setText("Triggering network optimization...")
            
            # Add to history
            optimization_entry = {
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'type': 'Manual',
                'status': 'In Progress',
                'details': 'Manual optimization triggered'
            }
            
            self.optimization_history.insert(0, optimization_entry)
            self.update_optimization_history_table()
            
            # Simulate optimization
            import time
            time.sleep(2)
            
            # Update status
            optimization_entry['status'] = 'Success'
            optimization_entry['details'] = 'Network optimized for gaming performance'
            
            # Update performance data
            self.gaming_performance['last_optimization'] = optimization_entry['timestamp']
            
            # Emit signal
            self.optimization_triggered.emit()
            
            self.status_label.setText("Optimization completed successfully")
            log_info("Network optimization completed")
            
        except Exception as e:
            log_error(f"Error during optimization: {e}")
            self.status_label.setText("Error during optimization")
    
    def reset_optimization(self):
        """Reset network optimization"""
        try:
            self.status_label.setText("Resetting optimization...")
            
            # Add to history
            optimization_entry = {
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'type': 'Reset',
                'status': 'Success',
                'details': 'Network optimization reset to default'
            }
            
            self.optimization_history.insert(0, optimization_entry)
            self.update_optimization_history_table()
            
            # Reset performance data
            self.gaming_performance['last_optimization'] = 'Never'
            
            self.status_label.setText("Optimization reset successfully")
            log_info("Network optimization reset")
            
        except Exception as e:
            log_error(f"Error resetting optimization: {e}")
            self.status_label.setText("Error resetting optimization")
    
    def apply_optimization_settings(self):
        """Apply optimization settings"""
        try:
            # Get current settings
            priority = self.gaming_priority_combo.currentText()
            bandwidth = self.reserved_bandwidth_spin.value()
            latency = self.latency_threshold_spin.value()
            
            # Apply settings (this would integrate with your plugin)
            log_info(f"Applied optimization settings: Priority={priority}, Bandwidth={bandwidth}Mbps, Latency={latency}ms")
            
            self.status_label.setText("Settings applied successfully")
            
        except Exception as e:
            log_error(f"Error applying settings: {e}")
            self.status_label.setText("Error applying settings")
    
    def enable_all_rules(self):
        """Enable all gaming rules"""
        try:
            for rule in self.gaming_rules:
                rule['status'] = 'Active'
            
            self.update_rules_table()
            self.status_label.setText("All rules enabled")
            
        except Exception as e:
            log_error(f"Error enabling rules: {e}")
            self.status_label.setText("Error enabling rules")
    
    def disable_all_rules(self):
        """Disable all gaming rules"""
        try:
            for rule in self.gaming_rules:
                rule['status'] = 'Inactive'
            
            self.update_rules_table()
            self.status_label.setText("All rules disabled")
            
        except Exception as e:
            log_error(f"Error disabling rules: {e}")
            self.status_label.setText("Error disabling rules")
    
    def toggle_rule(self, rule_index: int):
        """Toggle a specific rule"""
        try:
            if rule_index < len(self.gaming_rules):
                rule = self.gaming_rules[rule_index]
                current_status = rule['status']
                
                # Toggle status
                rule['status'] = 'Inactive' if current_status == 'Active' else 'Active'
                
                # Update table
                self.update_rules_table()
                
                self.status_label.setText(f"Rule '{rule['name']}' {rule['status'].lower()}")
                
        except Exception as e:
            log_error(f"Error toggling rule: {e}")
            self.status_label.setText("Error toggling rule")
    
    def refresh_data(self):
        """Refresh all data"""
        try:
            self.load_data()
            self.status_label.setText("Data refreshed")
            
        except Exception as e:
            log_error(f"Error refreshing data: {e}")
            self.status_label.setText("Error refreshing data")
    
    def update_performance_data(self):
        """Update performance data from timer"""
        try:
            # This would get real-time data from your plugin
            # For now, simulate updates
            import random
            
            # Update latency
            current_latency = self.gaming_performance.get('avg_latency', 65)
            variation = random.randint(-10, 10)
            self.gaming_performance['avg_latency'] = max(20, min(200, current_latency + variation))
            
            # Update packet loss
            current_packet_loss = self.gaming_performance.get('packet_loss', 0.2)
            variation = random.uniform(-0.1, 0.1)
            self.gaming_performance['packet_loss'] = max(0.0, min(2.0, current_packet_loss + variation))
            
            # Update bandwidth
            current_bandwidth = self.gaming_performance.get('bandwidth_usage', 35)
            variation = random.randint(-5, 5)
            self.gaming_performance['bandwidth_usage'] = max(0, min(100, current_bandwidth + variation))
            
            # Performance display removed
            
        except Exception as e:
            log_error(f"Error updating performance data: {e}")
    
    def update_server_status(self):
        """Update server status from timer"""
        try:
            # This would get real-time server status from your plugin
            # For now, just log the update
            log_info("Server status update triggered")
            
        except Exception as e:
            log_error(f"Error updating server status: {e}")
    
    def refresh_server_status(self):
        """Refresh server status manually"""
        try:
            self.update_server_status()
            self.status_label.setText("Server status refreshed")
            
        except Exception as e:
            log_error(f"Error refreshing server status: {e}")
            self.status_label.setText("Error refreshing server status")
