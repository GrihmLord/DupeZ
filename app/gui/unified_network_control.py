#!/usr/bin/env python3
"""
Unified Network Control GUI
Combines DayZ Firewall and Network Manipulator functionality into one comprehensive tab
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, 
    QPushButton, QSpinBox, QCheckBox, QComboBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QFrame, QGroupBox, QLineEdit,
    QMessageBox, QInputDialog, QProgressBar, QTextEdit, QTabWidget,
    QSlider, QDateEdit
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QDate
from PyQt6.QtGui import QFont, QColor, QPalette
from typing import List, Dict, Optional
import time
import json
import os
from datetime import datetime, timedelta

# Import all required components
from app.firewall.dayz_firewall_controller import dayz_firewall, DayZFirewallRule
from app.network.network_manipulator import get_network_manipulator, NetworkRule
from app.firewall.clumsy_network_disruptor import clumsy_network_disruptor
from app.firewall.enterprise_network_disruptor import enterprise_network_disruptor
from app.firewall.blocker import is_admin
from app.logs.logger import log_info, log_error

class UnifiedNetworkControl(QWidget):
    """Unified GUI combining DayZ Firewall and Network Manipulator functionality"""
    
    # Signals
    firewall_started = pyqtSignal()
    firewall_stopped = pyqtSignal()
    manipulation_started = pyqtSignal(str, str)
    manipulation_stopped = pyqtSignal(str, str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.manipulator = get_network_manipulator()
        self.history_file = "network_manipulator_history.json"
        self.ip_history = self.load_history()
        self.setup_ui()
        self.connect_signals()
        self.start_status_timer()
        
    def setup_ui(self):
        """Setup the main UI"""
        layout = QVBoxLayout()
        
        # Title
        title = QLabel("🌐 Unified Network Control Center")
        title.setFont(QFont("Arial", 18, QFont.Weight.Bold))
        title.setStyleSheet("color: #ffffff; margin: 15px; text-align: center;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # Create tab widget
        self.tab_widget = QTabWidget()
        
        # Main control tab
        self.tab_widget.addTab(self.create_main_control_tab(), "🎯 Main Control")
        
        # DayZ Firewall tab
        self.tab_widget.addTab(self.create_dayz_firewall_tab(), "🛡️ DayZ Firewall")
        
        # Network Manipulation tab
        self.tab_widget.addTab(self.create_network_manipulation_tab(), "🌊 Network Manipulation")
        
        # Rules management tab
        self.tab_widget.addTab(self.create_rules_tab(), "📋 Rules Management")
        
        # Status and monitoring tab
        self.tab_widget.addTab(self.create_status_tab(), "📊 Status & Monitoring")
        
        layout.addWidget(self.tab_widget)
        self.setLayout(layout)
        self.apply_styling()
        
    def create_main_control_tab(self) -> QWidget:
        """Create the main control tab with quick access to key features"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Quick status overview
        status_group = QGroupBox("🚦 Quick Status Overview")
        status_layout = QGridLayout()
        
        # DayZ Firewall status
        self.dayz_fw_status = QLabel("🔴 DayZ Firewall: INACTIVE")
        self.dayz_fw_status.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        self.dayz_fw_status.setStyleSheet("color: #f44336; padding: 8px; border: 2px solid #f44336; border-radius: 5px;")
        status_layout.addWidget(self.dayz_fw_status, 0, 0)
        
        # Network Manipulator status
        self.net_manip_status = QLabel("🔴 Network Manipulator: INACTIVE")
        self.net_manip_status.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        self.net_manip_status.setStyleSheet("color: #f44336; padding: 8px; border: 2px solid #f44336; border-radius: 5px;")
        status_layout.addWidget(self.net_manip_status, 0, 1)
        
        # Clumsy status
        self.clumsy_status = QLabel("🔴 Clumsy: INACTIVE")
        self.clumsy_status.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        self.clumsy_status.setStyleSheet("color: #f44336; padding: 8px; border: 2px solid #f44336; border-radius: 5px;")
        status_layout.addWidget(self.clumsy_status, 1, 0)
        
        # Enterprise disruptor status
        self.enterprise_status = QLabel("🔴 Enterprise: INACTIVE")
        self.enterprise_status.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        self.enterprise_status.setStyleSheet("color: #4caf50; padding: 8px; border: 2px solid #4caf50; border-radius: 5px;")
        status_layout.addWidget(self.enterprise_status, 1, 1)
        
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)
        
        # Quick actions
        actions_group = QGroupBox("⚡ Quick Actions")
        actions_layout = QGridLayout()
        
        # DayZ Firewall controls
        self.start_dayz_fw_btn = QPushButton("🚀 Start DayZ Firewall")
        self.start_dayz_fw_btn.setStyleSheet("background-color: #4caf50; color: white; padding: 10px; font-weight: bold;")
        self.stop_dayz_fw_btn = QPushButton("🛑 Stop DayZ Firewall")
        self.stop_dayz_fw_btn.setStyleSheet("background-color: #f44336; color: white; padding: 10px; font-weight: bold;")
        
        actions_layout.addWidget(self.start_dayz_fw_btn, 0, 0)
        actions_layout.addWidget(self.stop_dayz_fw_btn, 0, 1)
        
        # Network manipulation controls
        self.quick_block_btn = QPushButton("🚫 Quick Block IP")
        self.quick_block_btn.setStyleSheet("background-color: #ff9800; color: white; padding: 10px; font-weight: bold;")
        self.quick_unblock_btn = QPushButton("✅ Quick Unblock All")
        self.quick_unblock_btn.setStyleSheet("background-color: #2196f3; color: white; padding: 10px; font-weight: bold;")
        
        actions_layout.addWidget(self.quick_block_btn, 1, 0)
        actions_layout.addWidget(self.quick_unblock_btn, 1, 1)
        
        actions_group.setLayout(actions_layout)
        layout.addWidget(actions_group)
        
        # Quick IP input
        ip_group = QGroupBox("🎯 Quick Target IP")
        ip_layout = QHBoxLayout()
        
        ip_layout.addWidget(QLabel("Target IP:"))
        self.quick_ip_input = QLineEdit()
        self.quick_ip_input.setPlaceholderText("192.168.1.100")
        ip_layout.addWidget(self.quick_ip_input)
        
        self.quick_disconnect_btn = QPushButton("🔌 Quick Disconnect")
        self.quick_disconnect_btn.setStyleSheet("background-color: #9c27b0; color: white; padding: 8px; font-weight: bold;")
        ip_layout.addWidget(self.quick_disconnect_btn)
        
        ip_group.setLayout(ip_layout)
        layout.addWidget(ip_group)
        
        # Status bar
        self.main_status_label = QLabel("Ready for network control operations")
        self.main_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.main_status_label.setStyleSheet("color: #4CAF50; font-weight: bold; padding: 10px;")
        layout.addWidget(self.main_status_label)
        
        widget.setLayout(layout)
        return widget
        
    def create_dayz_firewall_tab(self) -> QWidget:
        """Create the DayZ Firewall tab"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Status group
        status_group = QGroupBox("🎮 DayZ Firewall Status")
        status_layout = QGridLayout()
        
        self.dayz_status_label = QLabel("🔴 INACTIVE")
        self.dayz_status_label.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        self.dayz_status_label.setStyleSheet("color: #f44336; padding: 10px; border: 2px solid #f44336; border-radius: 5px; background-color: #1b5e20;")
        status_layout.addWidget(self.dayz_status_label, 0, 0, 1, 2)
        
        # Timer info
        self.dayz_timer_label = QLabel("⏰ Timer: Not Active")
        self.dayz_timer_label.setFont(QFont("Arial", 10))
        status_layout.addWidget(self.dayz_timer_label, 1, 0, 1, 2)
        
        # Active rules info
        self.dayz_rules_label = QLabel("📋 Active Rules: 0")
        self.dayz_rules_label.setFont(QFont("Arial", 10))
        status_layout.addWidget(self.dayz_rules_label, 2, 0, 1, 2)
        
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)
        
        # Control group
        control_group = QGroupBox("🎛️ Firewall Control")
        control_layout = QGridLayout()
        
        # Timer control
        control_layout.addWidget(QLabel("Timer (seconds):"), 0, 0)
        self.dayz_timer_spinbox = QSpinBox()
        self.dayz_timer_spinbox.setRange(0, 3600)
        self.dayz_timer_spinbox.setValue(0)
        self.dayz_timer_spinbox.setToolTip("0 = no timer, manual stop only")
        control_layout.addWidget(self.dayz_timer_spinbox, 0, 1)
        
        # Keybind control
        control_layout.addWidget(QLabel("Keybind:"), 1, 0)
        self.dayz_keybind_combo = QComboBox()
        self.dayz_keybind_combo.addItems(["F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12"])
        self.dayz_keybind_combo.setCurrentText("F1")
        control_layout.addWidget(self.dayz_keybind_combo, 1, 1)
        
        # Control buttons
        button_layout = QHBoxLayout()
        
        self.dayz_start_btn = QPushButton("🚀 Start DayZ Firewall")
        self.dayz_start_btn.setStyleSheet("background-color: #4caf50; color: white; padding: 10px; font-weight: bold;")
        self.dayz_stop_btn = QPushButton("🛑 Stop DayZ Firewall")
        self.dayz_stop_btn.setStyleSheet("background-color: #f44336; color: white; padding: 10px; font-weight: bold;")
        
        button_layout.addWidget(self.dayz_start_btn)
        button_layout.addWidget(self.dayz_stop_btn)
        
        control_layout.addLayout(button_layout, 2, 0, 1, 2)
        
        control_group.setLayout(control_layout)
        layout.addWidget(control_group)
        
        widget.setLayout(layout)
        return widget
        
    def create_network_manipulation_tab(self) -> QWidget:
        """Create the Network Manipulation tab"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # IP blocking section
        blocking_group = QGroupBox("🚫 IP Blocking")
        blocking_layout = QVBoxLayout()
        
        # IP input
        ip_layout = QHBoxLayout()
        ip_layout.addWidget(QLabel("Target IP:"))
        self.block_ip_input = QLineEdit()
        self.block_ip_input.setPlaceholderText("192.168.1.100")
        ip_layout.addWidget(self.block_ip_input)
        
        blocking_layout.addLayout(ip_layout)
        
        # Blocking options
        options_layout = QHBoxLayout()
        
        self.permanent_block = QCheckBox("Permanent Block")
        self.permanent_block.setChecked(False)
        options_layout.addWidget(self.permanent_block)
        
        self.aggressive_block = QCheckBox("Aggressive Blocking")
        self.aggressive_block.setChecked(True)
        options_layout.addWidget(self.aggressive_block)
        
        blocking_layout.addLayout(options_layout)
        
        # Blocking buttons
        button_layout = QHBoxLayout()
        
        self.block_button = QPushButton("🚫 Block IP")
        self.block_button.setStyleSheet("background-color: #f44336; color: white; padding: 8px; font-weight: bold;")
        self.unblock_button = QPushButton("✅ Unblock IP")
        self.unblock_button.setStyleSheet("background-color: #4caf50; color: white; padding: 8px; font-weight: bold;")
        self.unblock_all_button = QPushButton("🔄 Unblock All")
        self.unblock_all_button.setStyleSheet("background-color: #2196f3; color: white; padding: 8px; font-weight: bold;")
        
        button_layout.addWidget(self.block_button)
        button_layout.addWidget(self.unblock_button)
        button_layout.addWidget(self.unblock_all_button)
        
        blocking_layout.addLayout(button_layout)
        blocking_group.setLayout(blocking_layout)
        layout.addWidget(blocking_group)
        
        # Traffic control section
        traffic_group = QGroupBox("🌊 Traffic Control")
        traffic_layout = QGridLayout()
        
        # Throttling controls
        traffic_layout.addWidget(QLabel("Throttle Rate (%):"), 0, 0)
        self.throttle_slider = QSlider(Qt.Orientation.Horizontal)
        self.throttle_slider.setRange(0, 100)
        self.throttle_slider.setValue(50)
        self.throttle_slider.setToolTip("0% = no throttling, 100% = complete blocking")
        traffic_layout.addWidget(self.throttle_slider, 0, 1)
        
        self.throttle_label = QLabel("50%")
        self.throttle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        traffic_layout.addWidget(self.throttle_label, 0, 2)
        
        # Throttle buttons
        throttle_btn_layout = QHBoxLayout()
        
        self.start_throttle_btn = QPushButton("🌊 Start Throttling")
        self.start_throttle_btn.setStyleSheet("background-color: #ff9800; color: white; padding: 8px; font-weight: bold;")
        self.stop_throttle_btn = QPushButton("⏹️ Stop Throttling")
        self.stop_throttle_btn.setStyleSheet("background-color: #9e9e9e; color: white; padding: 8px; font-weight: bold;")
        
        throttle_btn_layout.addWidget(self.start_throttle_btn)
        throttle_btn_layout.addWidget(self.stop_throttle_btn)
        
        traffic_layout.addLayout(throttle_btn_layout, 1, 0, 1, 3)
        
        traffic_group.setLayout(traffic_layout)
        layout.addWidget(traffic_group)
        
        widget.setLayout(layout)
        return widget
        
    def create_rules_tab(self) -> QWidget:
        """Create the rules management tab"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Rules table
        self.rules_table = QTableWidget()
        self.rules_table.setColumnCount(6)
        self.rules_table.setHorizontalHeaderLabels([
            "Type", "Target", "Action", "Status", "Created", "Actions"
        ])
        
        # Set table properties
        header = self.rules_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.rules_table.setAlternatingRowColors(True)
        self.rules_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        
        layout.addWidget(self.rules_table)
        
        # Rules management buttons
        button_layout = QHBoxLayout()
        
        self.add_rule_btn = QPushButton("➕ Add Rule")
        self.remove_rule_btn = QPushButton("➖ Remove Rule")
        self.edit_rule_btn = QPushButton("✏️ Edit Rule")
        self.refresh_rules_btn = QPushButton("🔄 Refresh")
        
        button_layout.addWidget(self.add_rule_btn)
        button_layout.addWidget(self.remove_rule_btn)
        button_layout.addWidget(self.edit_rule_btn)
        button_layout.addWidget(self.refresh_rules_btn)
        
        layout.addLayout(button_layout)
        
        widget.setLayout(layout)
        return widget
        
    def create_status_tab(self) -> QWidget:
        """Create the status and monitoring tab"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # System status
        status_group = QGroupBox("💻 System Status")
        status_layout = QGridLayout()
        
        # Admin privileges
        admin_status = "✅ Administrator" if is_admin() else "❌ Limited User"
        self.admin_label = QLabel(f"Privileges: {admin_status}")
        self.admin_label.setStyleSheet("font-weight: bold; padding: 5px;")
        status_layout.addWidget(self.admin_label, 0, 0)
        
        # Clumsy status
        clumsy_status = "✅ Available" if os.path.exists("app/firewall/clumsy.exe") else "❌ Not Found"
        self.clumsy_label = QLabel(f"Clumsy: {clumsy_status}")
        self.clumsy_label.setStyleSheet("font-weight: bold; padding: 5px;")
        status_layout.addWidget(self.clumsy_label, 0, 1)
        
        # WinDivert status
        windivert_status = "✅ Available" if os.path.exists("app/firewall/WinDivert.dll") else "❌ Not Found"
        self.windivert_label = QLabel(f"WinDivert: {windivert_status}")
        self.windivert_label.setStyleSheet("font-weight: bold; padding: 5px;")
        status_layout.addWidget(self.windivert_label, 1, 0)
        
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)
        
        # Active connections
        connections_group = QGroupBox("🔗 Active Connections")
        connections_layout = QVBoxLayout()
        
        self.connections_text = QTextEdit()
        self.connections_text.setReadOnly(True)
        self.connections_text.setMaximumHeight(200)
        connections_layout.addWidget(self.connections_text)
        
        connections_group.setLayout(connections_layout)
        layout.addWidget(connections_group)
        
        # Log viewer
        log_group = QGroupBox("📝 Recent Logs")
        log_layout = QVBoxLayout()
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(200)
        log_layout.addWidget(self.log_text)
        
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)
        
        widget.setLayout(layout)
        return widget
        
    def connect_signals(self):
        """Connect all signals"""
        try:
            # Main control signals
            self.start_dayz_fw_btn.clicked.connect(self.start_dayz_firewall)
            self.stop_dayz_fw_btn.clicked.connect(self.stop_dayz_firewall)
            self.quick_block_btn.clicked.connect(self.quick_block_ip)
            self.quick_unblock_btn.clicked.connect(self.quick_unblock_all)
            self.quick_disconnect_btn.clicked.connect(self.quick_disconnect_ip)
            
            # DayZ Firewall signals
            self.dayz_start_btn.clicked.connect(self.start_dayz_firewall)
            self.dayz_stop_btn.clicked.connect(self.stop_dayz_firewall)
            self.dayz_timer_spinbox.valueChanged.connect(self.update_dayz_timer)
            self.dayz_keybind_combo.currentTextChanged.connect(self.update_dayz_keybind)
            
            # Network manipulation signals
            self.block_button.clicked.connect(self.block_ip)
            self.unblock_button.clicked.connect(self.unblock_ip)
            self.unblock_all_button.clicked.connect(self.unblock_all_ips)
            self.start_throttle_btn.clicked.connect(self.start_throttling)
            self.stop_throttle_btn.clicked.connect(self.stop_throttling)
            self.throttle_slider.valueChanged.connect(self.update_throttle_label)
            
            # Rules management signals
            self.add_rule_btn.clicked.connect(self.add_rule)
            self.remove_rule_btn.clicked.connect(self.remove_rule)
            self.edit_rule_btn.clicked.connect(self.edit_rule)
            self.refresh_rules_btn.clicked.connect(self.refresh_rules)
            
        except Exception as e:
            log_error(f"Failed to connect signals: {e}")
    
    def start_status_timer(self):
        """Start the status update timer"""
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.update_status)
        self.status_timer.start(2000)  # Update every 2 seconds
    
    def update_status(self):
        """Update all status displays"""
        try:
            # Update DayZ Firewall status
            if dayz_firewall.is_running:
                self.dayz_fw_status.setText("🟢 DayZ Firewall: ACTIVE")
                self.dayz_fw_status.setStyleSheet("color: #4caf50; padding: 8px; border: 2px solid #4caf50; border-radius: 5px;")
                self.dayz_status_label.setText("🟢 ACTIVE")
                self.dayz_status_label.setStyleSheet("color: #4caf50; padding: 10px; border: 2px solid #4caf50; border-radius: 5px; background-color: #1b5e20;")
            else:
                self.dayz_fw_status.setText("🔴 DayZ Firewall: INACTIVE")
                self.dayz_fw_status.setStyleSheet("color: #f44336; padding: 8px; border: 2px solid #f44336; border-radius: 5px;")
                self.dayz_status_label.setText("🔴 INACTIVE")
                self.dayz_status_label.setStyleSheet("color: #f44336; padding: 10px; border: 2px solid #f44336; border-radius: 5px; background-color: #1b5e20;")
            
            # Update Network Manipulator status
            if hasattr(self.manipulator, 'is_running') and self.manipulator.is_running:
                self.net_manip_status.setText("🟢 Network Manipulator: ACTIVE")
                self.net_manip_status.setStyleSheet("color: #4caf50; padding: 8px; border: 2px solid #4caf50; border-radius: 5px;")
            else:
                self.net_manip_status.setText("🔴 Network Manipulator: INACTIVE")
                self.net_manip_status.setStyleSheet("color: #f44336; padding: 8px; border: 2px solid #f44336; border-radius: 5px;")
            
            # Update Clumsy status
            if clumsy_network_disruptor.is_running:
                self.clumsy_status.setText("🟢 Clumsy: ACTIVE")
                self.clumsy_status.setStyleSheet("color: #4caf50; padding: 8px; border: 2px solid #4caf50; border-radius: 5px;")
            else:
                self.clumsy_status.setText("🔴 Clumsy: INACTIVE")
                self.clumsy_status.setStyleSheet("color: #f44336; padding: 8px; border: 2px solid #f44336; border-radius: 5px;")
            
            # Update Enterprise status
            if enterprise_network_disruptor.is_running:
                self.enterprise_status.setText("🟢 Enterprise: ACTIVE")
                self.enterprise_status.setStyleSheet("color: #4caf50; padding: 8px; border: 2px solid #4caf50; border-radius: 5px;")
            else:
                self.enterprise_status.setText("🔴 Enterprise: INACTIVE")
                self.enterprise_status.setStyleSheet("color: #4caf50; padding: 8px; border: 2px solid #4caf50; border-radius: 5px;")
            
            # Update admin status
            admin_status = "✅ Administrator" if is_admin() else "❌ Limited User"
            self.admin_label.setText(f"Privileges: {admin_status}")
            
        except Exception as e:
            log_error(f"Error updating status: {e}")
    
    def start_dayz_firewall(self):
        """Start the DayZ Firewall"""
        try:
            timer_duration = self.dayz_timer_spinbox.value()
            keybind = self.dayz_keybind_combo.currentText()
            
            if dayz_firewall.start_firewall(timer_duration=timer_duration, keybind=keybind):
                self.firewall_started.emit()
                self.main_status_label.setText("DayZ Firewall started successfully")
                log_info("DayZ Firewall started successfully")
            else:
                self.main_status_label.setText("Failed to start DayZ Firewall")
                log_error("Failed to start DayZ Firewall")
                
        except Exception as e:
            log_error(f"Error starting DayZ Firewall: {e}")
            self.main_status_label.setText(f"Error: {str(e)}")
    
    def stop_dayz_firewall(self):
        """Stop the DayZ Firewall"""
        try:
            if dayz_firewall.stop_firewall():
                self.firewall_stopped.emit()
                self.main_status_label.setText("DayZ Firewall stopped successfully")
                log_info("DayZ Firewall stopped successfully")
            else:
                self.main_status_label.setText("Failed to stop DayZ Firewall")
                log_error("Failed to stop DayZ Firewall")
                
        except Exception as e:
            log_error(f"Error stopping DayZ Firewall: {e}")
            self.main_status_label.setText(f"Error: {str(e)}")
    
    def update_dayz_timer(self, value: int):
        """Update DayZ Firewall timer"""
        try:
            dayz_firewall.set_timer_duration(value)
        except Exception as e:
            log_error(f"Error updating DayZ timer: {e}")
    
    def update_dayz_keybind(self, keybind: str):
        """Update DayZ Firewall keybind"""
        try:
            dayz_firewall.set_keybind(keybind)
        except Exception as e:
            log_error(f"Error updating DayZ keybind: {e}")
    
    def quick_block_ip(self):
        """Quick block an IP address"""
        try:
            ip = self.quick_ip_input.text().strip()
            if not ip:
                QMessageBox.warning(self, "Warning", "Please enter an IP address")
                return
            
            if self.manipulator.block_ip(ip, permanent=self.permanent_block.isChecked()):
                self.main_status_label.setText(f"IP {ip} blocked successfully")
                self.add_to_history(ip, "blocked")
                log_info(f"IP {ip} blocked successfully")
            else:
                self.main_status_label.setText(f"Failed to block IP {ip}")
                log_error(f"Failed to block IP {ip}")
                
        except Exception as e:
            log_error(f"Error blocking IP: {e}")
            self.main_status_label.setText(f"Error: {str(e)}")
    
    def quick_unblock_all(self):
        """Quick unblock all IPs"""
        try:
            if self.manipulator.unblock_all_ips():
                self.main_status_label.setText("All IPs unblocked successfully")
                log_info("All IPs unblocked successfully")
            else:
                self.main_status_label.setText("Failed to unblock all IPs")
                log_error("Failed to unblock all IPs")
                
        except Exception as e:
            log_error(f"Error unblocking all IPs: {e}")
            self.main_status_label.setText(f"Error: {str(e)}")
    
    def quick_disconnect_ip(self):
        """Quick disconnect an IP using Clumsy"""
        try:
            ip = self.quick_ip_input.text().strip()
            if not ip:
                QMessageBox.warning(self, "Warning", "Please enter an IP address")
                return
            
            if not is_admin():
                QMessageBox.warning(self, "Administrator Required", 
                                  "Network disruption requires Administrator privileges")
                return
            
            # Try Clumsy first, then Enterprise as fallback
            if clumsy_network_disruptor.disconnect_device_clumsy(ip, ["drop", "lag"]):
                self.main_status_label.setText(f"IP {ip} disconnected with Clumsy")
                log_info(f"IP {ip} disconnected with Clumsy")
            elif enterprise_network_disruptor.disconnect_device_enterprise(ip, ["arp_spoof", "icmp_flood"]):
                self.main_status_label.setText(f"IP {ip} disconnected with Enterprise")
                log_info(f"IP {ip} disconnected with Enterprise")
            else:
                self.main_status_label.setText(f"Failed to disconnect IP {ip}")
                log_error(f"Failed to disconnect IP {ip}")
                
        except Exception as e:
            log_error(f"Error disconnecting IP: {e}")
            self.main_status_label.setText(f"Error: {str(e)}")
    
    def block_ip(self):
        """Block an IP address"""
        try:
            ip = self.block_ip_input.text().strip()
            if not ip:
                QMessageBox.warning(self, "Warning", "Please enter an IP address")
                return
            
            if self.manipulator.block_ip(ip, permanent=self.permanent_block.isChecked()):
                self.main_status_label.setText(f"IP {ip} blocked successfully")
                self.add_to_history(ip, "blocked")
                log_info(f"IP {ip} blocked successfully")
            else:
                self.main_status_label.setText(f"Failed to block IP {ip}")
                log_error(f"Failed to block IP {ip}")
                
        except Exception as e:
            log_error(f"Error blocking IP: {e}")
            self.main_status_label.setText(f"Error: {str(e)}")
    
    def unblock_ip(self):
        """Unblock an IP address"""
        try:
            ip = self.block_ip_input.text().strip()
            if not ip:
                QMessageBox.warning(self, "Warning", "Please enter an IP address")
                return
            
            if self.manipulator.unblock_ip(ip):
                self.main_status_label.setText(f"IP {ip} unblocked successfully")
                self.add_to_history(ip, "unblocked")
                log_info(f"IP {ip} unblocked successfully")
            else:
                self.main_status_label.setText(f"Failed to unblock IP {ip}")
                log_error(f"Failed to unblock IP {ip}")
                
        except Exception as e:
            log_error(f"Error unblocking IP: {e}")
            self.main_status_label.setText(f"Error: {str(e)}")
    
    def unblock_all_ips(self):
        """Unblock all IP addresses"""
        try:
            if self.manipulator.unblock_all_ips():
                self.main_status_label.setText("All IPs unblocked successfully")
                log_info("All IPs unblocked successfully")
            else:
                self.main_status_label.setText("Failed to unblock all IPs")
                log_error("Failed to unblock all IPs")
                
        except Exception as e:
            log_error(f"Error unblocking all IPs: {e}")
            self.main_status_label.setText(f"Error: {str(e)}")
    
    def start_throttling(self):
        """Start traffic throttling"""
        try:
            rate = self.throttle_slider.value()
            if self.manipulator.start_throttling(rate):
                self.main_status_label.setText(f"Traffic throttling started at {rate}%")
                log_info(f"Traffic throttling started at {rate}%")
            else:
                self.main_status_label.setText("Failed to start traffic throttling")
                log_error("Failed to start traffic throttling")
                
        except Exception as e:
            log_error(f"Error starting throttling: {e}")
            self.main_status_label.setText(f"Error: {str(e)}")
    
    def stop_throttling(self):
        """Stop traffic throttling"""
        try:
            if self.manipulator.stop_throttling():
                self.main_status_label.setText("Traffic throttling stopped")
                log_info("Traffic throttling stopped")
            else:
                self.main_status_label.setText("Failed to stop traffic throttling")
                log_error("Failed to stop traffic throttling")
                
        except Exception as e:
            log_error(f"Error stopping throttling: {e}")
            self.main_status_label.setText(f"Error: {str(e)}")
    
    def update_throttle_label(self, value: int):
        """Update throttle label when slider changes"""
        self.throttle_label.setText(f"{value}%")
    
    def add_rule(self):
        """Add a new network rule"""
        try:
            # Implementation for adding rules
            QMessageBox.information(self, "Info", "Add rule functionality coming soon")
        except Exception as e:
            log_error(f"Error adding rule: {e}")
    
    def remove_rule(self):
        """Remove a network rule"""
        try:
            # Implementation for removing rules
            QMessageBox.information(self, "Info", "Remove rule functionality coming soon")
        except Exception as e:
            log_error(f"Error removing rule: {e}")
    
    def edit_rule(self):
        """Edit a network rule"""
        try:
            # Implementation for editing rules
            QMessageBox.information(self, "Info", "Edit rule functionality coming soon")
        except Exception as e:
            log_error(f"Error editing rule: {e}")
    
    def refresh_rules(self):
        """Refresh the rules table"""
        try:
            # Implementation for refreshing rules
            QMessageBox.information(self, "Info", "Refresh rules functionality coming soon")
        except Exception as e:
            log_error(f"Error refreshing rules: {e}")
    
    def load_history(self) -> Dict:
        """Load IP manipulation history"""
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r') as f:
                    return json.load(f)
            return {}
        except Exception as e:
            log_error(f"Error loading history: {e}")
            return {}
    
    def add_to_history(self, ip: str, action: str):
        """Add an action to the IP history"""
        try:
            timestamp = datetime.now().isoformat()
            if ip not in self.ip_history:
                self.ip_history[ip] = []
            
            self.ip_history[ip].append({
                'action': action,
                'timestamp': timestamp
            })
            
            # Save history
            with open(self.history_file, 'w') as f:
                json.dump(self.ip_history, f, indent=2)
                
        except Exception as e:
            log_error(f"Error adding to history: {e}")
    
    def apply_styling(self):
        """Apply styling to the widget"""
        self.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #404040;
                border-radius: 5px;
                margin-top: 1ex;
                padding-top: 10px;
                color: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: #ffffff;
            }
            QLabel {
                color: #ffffff;
                font-size: 11px;
            }
            QPushButton {
                background-color: #2a2a2a;
                border: 1px solid #404040;
                border-radius: 3px;
                padding: 5px;
                color: #ffffff;
                min-height: 20px;
            }
            QPushButton:hover {
                background-color: #404040;
                border-color: #555555;
            }
            QLineEdit {
                background-color: #2a2a2a;
                border: 1px solid #404040;
                border-radius: 3px;
                padding: 5px;
                color: #ffffff;
                min-height: 20px;
            }
            QSpinBox {
                background-color: #2a2a2a;
                border: 1px solid #404040;
                border-radius: 3px;
                padding: 5px;
                color: #ffffff;
                min-height: 20px;
            }
            QComboBox {
                background-color: #2a2a2a;
                border: 1px solid #404040;
                border-radius: 3px;
                padding: 5px;
                color: #ffffff;
                min-height: 20px;
            }
            QCheckBox {
                color: #ffffff;
                font-size: 11px;
            }
            QTableWidget {
                background-color: #1a1a1a;
                alternate-background-color: #2a2a2a;
                gridline-color: #404040;
                color: #ffffff;
                border: 1px solid #404040;
            }
            QHeaderView::section {
                background-color: #2a2a2a;
                color: #ffffff;
                padding: 5px;
                border: 1px solid #404040;
            }
            QTextEdit {
                background-color: #1a1a1a;
                border: 1px solid #404040;
                color: #ffffff;
            }
            QSlider::groove:horizontal {
                border: 1px solid #404040;
                height: 8px;
                background: #2a2a2a;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #4caf50;
                border: 1px solid #388e3c;
                width: 18px;
                margin: -2px 0;
                border-radius: 9px;
            }
        """)

    def cleanup(self):
        """Cleanup resources when closing"""
        try:
            # Stop any active operations
            if hasattr(self, 'status_timer'):
                self.status_timer.stop()
            
            # Cleanup any active disruptions
            if hasattr(self, 'manipulator'):
                try:
                    self.manipulator.cleanup()
                except:
                    pass
            
            log_info("Unified Network Control cleanup completed")
            
        except Exception as e:
            log_error(f"Error during cleanup: {e}")
    
    def on_network_rule_created(self, rule_id: str, rule_type: str):
        """Handle network rule creation"""
        try:
            log_info(f"Network rule created: {rule_id} ({rule_type})")
            self.main_status_label.setText(f"Rule created: {rule_id}")
        except Exception as e:
            log_error(f"Error handling rule creation: {e}")
    
    def on_network_rule_removed(self, rule_id: str):
        """Handle network rule removal"""
        try:
            log_info(f"Network rule removed: {rule_id}")
            self.main_status_label.setText(f"Rule removed: {rule_id}")
        except Exception as e:
            log_error(f"Error handling rule removal: {e}")
    
    def on_manipulation_started(self, ip: str, action: str):
        """Handle manipulation start"""
        try:
            log_info(f"Network manipulation started: {action} on {ip}")
            self.main_status_label.setText(f"Manipulation started: {action} on {ip}")
        except Exception as e:
            log_error(f"Error handling manipulation start: {e}")
    
    def on_manipulation_stopped(self, ip: str, action: str):
        """Handle manipulation stop"""
        try:
            log_info(f"Network manipulation stopped: {action} on {ip}")
            self.main_status_label.setText(f"Manipulation stopped: {action} on {ip}")
        except Exception as e:
            log_error(f"Error handling manipulation stop: {e}")
    
    # Add the missing signals that the dashboard expects
    rule_created = pyqtSignal(str, str)  # rule_id, rule_type
    rule_removed = pyqtSignal(str)  # rule_id
