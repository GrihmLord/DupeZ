#!/usr/bin/env python3
"""
DayZ Firewall GUI - DayZPCFW Integration
Advanced GUI for managing DayZ firewall with timer, keybind, and button controls
Based on DayZPCFW's Visual Basic .NET interface
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, 
    QPushButton, QSpinBox, QCheckBox, QComboBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QFrame, QGroupBox, QLineEdit,
    QMessageBox, QInputDialog, QProgressBar, QTextEdit, QTabWidget
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor, QPalette
from typing import List, Dict, Optional
from app.firewall.dayz_firewall_controller import dayz_firewall, DayZFirewallRule
from app.logs.logger import log_info, log_error

class DayZFirewallGUI(QWidget):
    """Advanced GUI for DayZ firewall management with DayZPCFW integration"""
    
    # Signals
    firewall_started = pyqtSignal()
    firewall_stopped = pyqtSignal()
    rule_added = pyqtSignal(str)
    rule_removed = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        self.connect_signals()
        self.refresh_status()
        self.start_status_timer()
        
    def setup_ui(self):
        """Setup the main UI"""
        layout = QVBoxLayout()
        
        # Title
        title = QLabel("🎮 DayZ Firewall Controller (DayZPCFW)")
        title.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        title.setStyleSheet("color: #ffffff; margin: 10px;")
        layout.addWidget(title)
        
        # Create tab widget
        self.tab_widget = QTabWidget()
        
        # Main control tab
        self.tab_widget.addTab(self.create_main_control_tab(), "🎯 Main Control")
        
        # Rules management tab
        self.tab_widget.addTab(self.create_rules_tab(), "📋 Rules Management")
        
        # Settings tab
        self.tab_widget.addTab(self.create_settings_tab(), "⚙️ Settings")
        
        # Status tab
        self.tab_widget.addTab(self.create_status_tab(), "📊 Status")
        
        layout.addWidget(self.tab_widget)
        self.setLayout(layout)
        self.apply_styling()
        
    def create_main_control_tab(self) -> QWidget:
        """Create the main control tab"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Status group
        status_group = QGroupBox("🎮 Firewall Status")
        status_layout = QGridLayout()
        
        self.status_label = QLabel("🟢 ACTIVE" if dayz_firewall.is_running else "🔴 INACTIVE")
        self.status_label.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        self.status_label.setStyleSheet("""
            QLabel {
                color: #4caf50;
                padding: 10px;
                border: 2px solid #4caf50;
                border-radius: 5px;
                background-color: #1b5e20;
            }
        """)
        status_layout.addWidget(self.status_label, 0, 0, 1, 2)
        
        # Timer info
        self.timer_label = QLabel("⏰ Timer: Not Active")
        self.timer_label.setFont(QFont("Arial", 10))
        status_layout.addWidget(self.timer_label, 1, 0, 1, 2)
        
        # Active rules info
        self.rules_label = QLabel("📋 Active Rules: 0")
        self.rules_label.setFont(QFont("Arial", 10))
        status_layout.addWidget(self.rules_label, 2, 0, 1, 2)
        
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)
        
        # Control group
        control_group = QGroupBox("🎮 Control Panel")
        control_layout = QGridLayout()
        
        # Start/Stop button
        self.toggle_button = QPushButton("🚀 START FIREWALL")
        self.toggle_button.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        self.toggle_button.setStyleSheet("""
            QPushButton {
                background-color: #4caf50;
                color: white;
                border: none;
                padding: 15px;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
        """)
        control_layout.addWidget(self.toggle_button, 0, 0, 1, 2)
        
        # Timer control
        timer_label = QLabel("Timer (seconds):")
        self.timer_spinbox = QSpinBox()
        self.timer_spinbox.setRange(0, 3600)
        self.timer_spinbox.setValue(dayz_firewall.global_timer_duration)
        self.timer_spinbox.setToolTip("0 = no timer, manual stop only")
        
        control_layout.addWidget(timer_label, 1, 0)
        control_layout.addWidget(self.timer_spinbox, 1, 1)
        
        # Button mode toggle
        self.button_mode_cb = QCheckBox("Button Mode (vs Keybind Mode)")
        self.button_mode_cb.setChecked(dayz_firewall.button_mode)
        control_layout.addWidget(self.button_mode_cb, 2, 0, 1, 2)
        
        # Auto-stop toggle
        self.auto_stop_cb = QCheckBox("Auto-stop when timer expires")
        self.auto_stop_cb.setChecked(dayz_firewall.auto_stop)
        control_layout.addWidget(self.auto_stop_cb, 3, 0, 1, 2)
        
        control_group.setLayout(control_layout)
        layout.addWidget(control_group)
        
        # Keybind group
        keybind_group = QGroupBox("⌨️ Keybind Control")
        keybind_layout = QGridLayout()
        
        keybind_label = QLabel("Global Keybind:")
        self.keybind_combo = QComboBox()
        self.keybind_combo.addItems(["F12", "F11", "F10", "F9", "F8", "F7", "F6", "F5", "F4", "F3", "F2", "F1"])
        self.keybind_combo.setCurrentText(dayz_firewall.global_keybind)
        
        keybind_layout.addWidget(keybind_label, 0, 0)
        keybind_layout.addWidget(self.keybind_combo, 0, 1)
        
        # Keybind info
        self.keybind_info = QLabel(f"Press {dayz_firewall.global_keybind} to toggle firewall")
        self.keybind_info.setFont(QFont("Arial", 9))
        self.keybind_info.setStyleSheet("color: #888888;")
        keybind_layout.addWidget(self.keybind_info, 1, 0, 1, 2)
        
        keybind_group.setLayout(keybind_layout)
        layout.addWidget(keybind_group)
        
        widget.setLayout(layout)
        return widget
        
    def create_rules_tab(self) -> QWidget:
        """Create the rules management tab"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Rules table
        self.rules_table = QTableWidget()
        self.rules_table.setColumnCount(7)
        self.rules_table.setHorizontalHeaderLabels([
            "Name", "IP", "Port", "Protocol", "Action", "Timer", "Keybind"
        ])
        self.rules_table.horizontalHeader().setStretchLastSection(True)
        self.rules_table.setAlternatingRowColors(True)
        
        layout.addWidget(self.rules_table)
        
        # Rule management buttons
        button_layout = QHBoxLayout()
        
        self.add_rule_btn = QPushButton("➕ Add Rule")
        self.add_rule_btn.clicked.connect(self.add_rule_dialog)
        button_layout.addWidget(self.add_rule_btn)
        
        self.edit_rule_btn = QPushButton("✏️ Edit Rule")
        self.edit_rule_btn.clicked.connect(self.edit_rule_dialog)
        button_layout.addWidget(self.edit_rule_btn)
        
        self.remove_rule_btn = QPushButton("🗑️ Remove Rule")
        self.remove_rule_btn.clicked.connect(self.remove_rule)
        button_layout.addWidget(self.remove_rule_btn)
        
        self.refresh_rules_btn = QPushButton("🔄 Refresh")
        self.refresh_rules_btn.clicked.connect(self.refresh_rules)
        button_layout.addWidget(self.refresh_rules_btn)
        
        layout.addLayout(button_layout)
        widget.setLayout(layout)
        return widget
        
    def create_settings_tab(self) -> QWidget:
        """Create the settings tab"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # General settings
        general_group = QGroupBox("⚙️ General Settings")
        general_layout = QGridLayout()
        
        # Default timer
        default_timer_label = QLabel("Default Timer (seconds):")
        self.default_timer_spinbox = QSpinBox()
        self.default_timer_spinbox.setRange(0, 3600)
        self.default_timer_spinbox.setValue(dayz_firewall.global_timer_duration)
        
        general_layout.addWidget(default_timer_label, 0, 0)
        general_layout.addWidget(self.default_timer_spinbox, 0, 1)
        
        # Default keybind
        default_keybind_label = QLabel("Default Keybind:")
        self.default_keybind_combo = QComboBox()
        self.default_keybind_combo.addItems(["F12", "F11", "F10", "F9", "F8", "F7", "F6", "F5", "F4", "F3", "F2", "F1"])
        self.default_keybind_combo.setCurrentText(dayz_firewall.global_keybind)
        
        general_layout.addWidget(default_keybind_label, 1, 0)
        general_layout.addWidget(self.default_keybind_combo, 1, 1)
        
        general_group.setLayout(general_layout)
        layout.addWidget(general_group)
        
        # DayZ settings
        dayz_group = QGroupBox("🎮 DayZ Settings")
        dayz_layout = QGridLayout()
        
        # DayZ ports
        ports_label = QLabel("DayZ Ports:")
        self.ports_text = QLineEdit("2302, 2303, 2304, 2305, 27015, 27016, 27017, 27018")
        self.ports_text.setToolTip("Comma-separated list of DayZ ports")
        
        dayz_layout.addWidget(ports_label, 0, 0)
        dayz_layout.addWidget(self.ports_text, 0, 1)
        
        # Default protocol
        protocol_label = QLabel("Default Protocol:")
        self.protocol_combo = QComboBox()
        self.protocol_combo.addItems(["UDP", "TCP", "Both"])
        self.protocol_combo.setCurrentText("UDP")
        
        dayz_layout.addWidget(protocol_label, 1, 0)
        dayz_layout.addWidget(self.protocol_combo, 1, 1)
        
        dayz_group.setLayout(dayz_layout)
        layout.addWidget(dayz_group)
        
        # Save button
        self.save_settings_btn = QPushButton("💾 Save Settings")
        self.save_settings_btn.clicked.connect(self.save_settings)
        layout.addWidget(self.save_settings_btn)
        
        widget.setLayout(layout)
        return widget
        
    def create_status_tab(self) -> QWidget:
        """Create the status tab"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Status text
        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setFont(QFont("Consolas", 9))
        self.status_text.setStyleSheet("""
            QTextEdit {
                background-color: #1a1a1a;
                color: #00ff00;
                border: 1px solid #333333;
            }
        """)
        
        layout.addWidget(self.status_text)
        
        # Refresh button
        self.refresh_status_btn = QPushButton("🔄 Refresh Status")
        self.refresh_status_btn.clicked.connect(self.refresh_status)
        layout.addWidget(self.refresh_status_btn)
        
        widget.setLayout(layout)
        return widget
        
    def connect_signals(self):
        """Connect all signals"""
        # Main control signals
        self.toggle_button.clicked.connect(self.toggle_firewall)
        self.timer_spinbox.valueChanged.connect(self.update_timer)
        self.button_mode_cb.toggled.connect(self.toggle_button_mode)
        self.auto_stop_cb.toggled.connect(self.toggle_auto_stop)
        self.keybind_combo.currentTextChanged.connect(self.update_keybind)
        
        # Settings signals
        self.default_timer_spinbox.valueChanged.connect(self.update_default_timer)
        self.default_keybind_combo.currentTextChanged.connect(self.update_default_keybind)
        
    def start_status_timer(self):
        """Start timer for status updates"""
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.refresh_status)
        self.status_timer.start(1000)  # Update every second
        
    def refresh_status(self):
        """Refresh the status display"""
        try:
            status = dayz_firewall.get_status()
            
            # Update main status
            if status["is_running"]:
                self.status_label.setText("🟢 ACTIVE")
                self.status_label.setStyleSheet("""
                    QLabel {
                        color: #4caf50;
                        padding: 10px;
                        border: 2px solid #4caf50;
                        border-radius: 5px;
                        background-color: #1b5e20;
                    }
                """)
                self.toggle_button.setText("[STOP] FIREWALL")
                self.toggle_button.setStyleSheet("""
                    QPushButton {
                        background-color: #f44336;
                        color: white;
                        border: none;
                        padding: 15px;
                        border-radius: 5px;
                        font-weight: bold;
                    }
                    QPushButton:hover {
                        background-color: #da190b;
                    }
                    QPushButton:pressed {
                        background-color: #c62828;
                    }
                """)
            else:
                self.status_label.setText("🔴 INACTIVE")
                self.status_label.setStyleSheet("""
                    QLabel {
                        color: #f44336;
                        padding: 10px;
                        border: 2px solid #f44336;
                        border-radius: 5px;
                        background-color: #b71c1c;
                    }
                """)
                self.toggle_button.setText("🚀 START FIREWALL")
                self.toggle_button.setStyleSheet("""
                    QPushButton {
                        background-color: #4caf50;
                        color: white;
                        border: none;
                        padding: 15px;
                        border-radius: 5px;
                        font-weight: bold;
                    }
                    QPushButton:hover {
                        background-color: #45a049;
                    }
                    QPushButton:pressed {
                        background-color: #3d8b40;
                    }
                """)
            
            # Update timer info
            if status["timer_active"]:
                self.timer_label.setText(f"⏰ Timer: Active ({status['global_timer_duration']}s)")
            else:
                self.timer_label.setText("⏰ Timer: Not Active")
            
            # Update rules info
            self.rules_label.setText(f"📋 Active Rules: {status['active_rules']}/{status['enabled_rules']}")
            
            # Update keybind info
            self.keybind_info.setText(f"Press {status['global_keybind']} to toggle firewall")
            
            # Update status text
            status_text = f"""
🎮 DayZ Firewall Status
=======================
Status: {'🟢 ACTIVE' if status['is_running'] else '🔴 INACTIVE'}
Timer: {'⏰ Active' if status['timer_active'] else '⏰ Not Active'}
            Button Mode: {'[ENABLED]' if status['button_mode'] else '[DISABLED]'}
Global Keybind: {status['global_keybind']}
Global Timer: {status['global_timer_duration']}s
Active Rules: {status['active_rules']}
Total Rules: {status['total_rules']}
Enabled Rules: {status['enabled_rules']}

📋 Firewall Rules:
"""
            
            rules = dayz_firewall.get_rules()
            for rule in rules:
                status_text += f"• {rule.name}: {rule.ip}:{rule.port} ({rule.protocol}) - {rule.action.upper()}\n"
            
            self.status_text.setText(status_text)
            
            # Refresh rules table
            self.refresh_rules()
            
        except Exception as e:
            log_error(f"Error refreshing status: {e}")
    
    def toggle_firewall(self):
        """Toggle firewall on/off"""
        try:
            if dayz_firewall.is_running:
                if dayz_firewall.stop_firewall():
                    self.firewall_stopped.emit()
                    log_info("🎮 Firewall stopped via button")
            else:
                timer_duration = self.timer_spinbox.value()
                if dayz_firewall.start_firewall(timer_duration):
                    self.firewall_started.emit()
                    log_info("🎮 Firewall started via button")
                    
        except Exception as e:
            log_error(f"Error toggling firewall: {e}")
            QMessageBox.critical(self, "Error", f"Failed to toggle firewall: {e}")
    
    def update_timer(self, value: int):
        """Update timer duration"""
        dayz_firewall.set_global_timer(value)
    
    def toggle_button_mode(self, enabled: bool):
        """Toggle button mode"""
        dayz_firewall.toggle_button_mode(enabled)
    
    def toggle_auto_stop(self, enabled: bool):
        """Toggle auto-stop setting"""
        dayz_firewall.auto_stop = enabled
        dayz_firewall.save_config()
    
    def update_keybind(self, keybind: str):
        """Update global keybind"""
        dayz_firewall.set_global_keybind(keybind)
    
    def update_default_timer(self, value: int):
        """Update default timer setting"""
        dayz_firewall.global_timer_duration = value
        dayz_firewall.save_config()
    
    def update_default_keybind(self, keybind: str):
        """Update default keybind setting"""
        dayz_firewall.global_keybind = keybind
        dayz_firewall.save_config()
    
    def add_rule_dialog(self):
        """Show dialog to add a new rule"""
        try:
            name, ok = QInputDialog.getText(self, "Add Rule", "Rule Name:")
            if not ok or not name:
                return
                
            ip, ok = QInputDialog.getText(self, "Add Rule", "IP Address (0.0.0.0 for all):")
            if not ok:
                return
                
            port, ok = QInputDialog.getInt(self, "Add Rule", "Port:", 2302, 1, 65535)
            if not ok:
                return
                
            protocol, ok = QInputDialog.getItem(self, "Add Rule", "Protocol:", ["UDP", "TCP"], 0, False)
            if not ok:
                return
                
            action, ok = QInputDialog.getItem(self, "Add Rule", "Action:", ["block", "allow"], 0, False)
            if not ok:
                return
                
            timer, ok = QInputDialog.getInt(self, "Add Rule", "Timer (seconds, 0 = no timer):", 0, 0, 3600)
            if not ok:
                return
                
            keybind, ok = QInputDialog.getItem(self, "Add Rule", "Keybind:", ["F12", "F11", "F10", "F9", "F8", "F7", "F6", "F5", "F4", "F3", "F2", "F1"], 0, False)
            if not ok:
                return
                
            if dayz_firewall.add_rule(name, ip, port, protocol, action, timer, keybind):
                self.rule_added.emit(name)
                self.refresh_rules()
                QMessageBox.information(self, "Success", f"Rule '{name}' added successfully!")
            else:
                QMessageBox.critical(self, "Error", "Failed to add rule!")
                
        except Exception as e:
            log_error(f"Error adding rule: {e}")
            QMessageBox.critical(self, "Error", f"Failed to add rule: {e}")
    
    def edit_rule_dialog(self):
        """Show dialog to edit selected rule"""
        try:
            current_row = self.rules_table.currentRow()
            if current_row < 0:
                QMessageBox.warning(self, "Warning", "Please select a rule to edit!")
                return
                
            # Get selected rule
            rule_name = self.rules_table.item(current_row, 0).text()
            rules = dayz_firewall.get_rules()
            rule = None
            for r in rules:
                if r.name == rule_name:
                    rule = r
                    break
                    
            if not rule:
                QMessageBox.warning(self, "Warning", "Selected rule not found!")
                return
                
            # Show edit dialog (simplified - just toggle enabled)
            enabled, ok = QInputDialog.getItem(self, "Edit Rule", f"Enable rule '{rule.name}'?", ["Yes", "No"], 0, False)
            if ok:
                rule.enabled = (enabled == "Yes")
                dayz_firewall.save_config()
                self.refresh_rules()
                QMessageBox.information(self, "Success", f"Rule '{rule.name}' updated!")
                
        except Exception as e:
            log_error(f"Error editing rule: {e}")
            QMessageBox.critical(self, "Error", f"Failed to edit rule: {e}")
    
    def remove_rule(self):
        """Remove selected rule"""
        try:
            current_row = self.rules_table.currentRow()
            if current_row < 0:
                QMessageBox.warning(self, "Warning", "Please select a rule to remove!")
                return
                
            rule_name = self.rules_table.item(current_row, 0).text()
            
            reply = QMessageBox.question(self, "Confirm", f"Remove rule '{rule_name}'?", 
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            
            if reply == QMessageBox.StandardButton.Yes:
                if dayz_firewall.remove_rule(rule_name):
                    self.rule_removed.emit(rule_name)
                    self.refresh_rules()
                    QMessageBox.information(self, "Success", f"Rule '{rule_name}' removed!")
                else:
                    QMessageBox.critical(self, "Error", "Failed to remove rule!")
                    
        except Exception as e:
            log_error(f"Error removing rule: {e}")
            QMessageBox.critical(self, "Error", f"Failed to remove rule: {e}")
    
    def refresh_rules(self):
        """Refresh the rules table"""
        try:
            rules = dayz_firewall.get_rules()
            self.rules_table.setRowCount(len(rules))
            
            for row, rule in enumerate(rules):
                self.rules_table.setItem(row, 0, QTableWidgetItem(rule.name))
                self.rules_table.setItem(row, 1, QTableWidgetItem(rule.ip))
                self.rules_table.setItem(row, 2, QTableWidgetItem(str(rule.port)))
                self.rules_table.setItem(row, 3, QTableWidgetItem(rule.protocol))
                self.rules_table.setItem(row, 4, QTableWidgetItem(rule.action.upper()))
                self.rules_table.setItem(row, 5, QTableWidgetItem(f"{rule.timer_duration}s" if rule.timer_duration > 0 else "No timer"))
                self.rules_table.setItem(row, 6, QTableWidgetItem(rule.keybind))
                
                # Color code based on enabled status
                if rule.enabled:
                    for col in range(7):
                        item = self.rules_table.item(row, col)
                        if item:
                            item.setBackground(QColor(50, 150, 50))
                else:
                    for col in range(7):
                        item = self.rules_table.item(row, col)
                        if item:
                            item.setBackground(QColor(150, 50, 50))
                            
        except Exception as e:
            log_error(f"Error refreshing rules: {e}")
    
    def save_settings(self):
        """Save all settings"""
        try:
            dayz_firewall.save_config()
            QMessageBox.information(self, "Success", "Settings saved successfully!")
            
        except Exception as e:
            log_error(f"Error saving settings: {e}")
            QMessageBox.critical(self, "Error", f"Failed to save settings: {e}")
    
    def apply_styling(self):
        """Apply styling to the GUI"""
        self.setStyleSheet("""
            QWidget {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QGroupBox {
                font-weight: bold;
                border: 2px solid #555555;
                border-radius: 5px;
                margin-top: 1ex;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
            QPushButton {
                background-color: #4a4a4a;
                border: 1px solid #555555;
                border-radius: 3px;
                padding: 5px;
                color: white;
            }
            QPushButton:hover {
                background-color: #5a5a5a;
            }
            QPushButton:pressed {
                background-color: #3a3a3a;
            }
            QSpinBox, QComboBox, QLineEdit {
                background-color: #3a3a3a;
                border: 1px solid #555555;
                border-radius: 3px;
                padding: 3px;
                color: white;
            }
            QTableWidget {
                background-color: #1a1a1a;
                alternate-background-color: #2a2a2a;
                gridline-color: #555555;
            }
            QHeaderView::section {
                background-color: #4a4a4a;
                color: white;
                padding: 5px;
                border: 1px solid #555555;
            }
        """)
    
    def cleanup(self):
        """Cleanup resources"""
        try:
            if hasattr(self, 'status_timer'):
                self.status_timer.stop()
            log_info("[SUCCESS] DayZ Firewall GUI cleaned up")
            
        except Exception as e:
            log_error(f"Error during GUI cleanup: {e}") 