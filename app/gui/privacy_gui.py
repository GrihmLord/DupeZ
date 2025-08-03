#!/usr/bin/env python3
"""
Privacy GUI Component for PulseDrop Pro
Provides user interface for privacy settings and controls
"""

import sys
import os
from typing import Dict, Optional
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, 
    QComboBox, QPushButton, QGroupBox, QTextEdit, QProgressBar,
    QSlider, QFrame, QMessageBox, QTabWidget
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QPalette, QColor

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.privacy.privacy_manager import privacy_manager
from app.logs.logger import log_info, log_error

class PrivacySettingsWidget(QWidget):
    """Privacy settings widget"""
    
    privacy_level_changed = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.update_privacy_report()
        
        # Timer for periodic privacy report updates
        self.report_timer = QTimer()
        self.report_timer.timeout.connect(self.update_privacy_report)
        self.report_timer.start(5000)  # Update every 5 seconds
        
    def init_ui(self):
        """Initialize the privacy settings UI"""
        layout = QVBoxLayout()
        
        # Privacy Level Selection
        level_group = QGroupBox("🛡️ Privacy Protection Level")
        level_layout = QVBoxLayout()
        
        self.privacy_combo = QComboBox()
        self.privacy_combo.addItems(["Low", "Medium", "High", "Maximum"])
        self.privacy_combo.setCurrentText("High")
        self.privacy_combo.currentTextChanged.connect(self.on_privacy_level_changed)
        
        level_desc = QLabel(
            "Low: Basic protection\n"
            "Medium: Standard anonymization\n"
            "High: Full privacy protection\n"
            "Maximum: Complete anonymity + VPN"
        )
        level_desc.setStyleSheet("color: #888; font-size: 10px;")
        
        level_layout.addWidget(QLabel("Select Privacy Level:"))
        level_layout.addWidget(self.privacy_combo)
        level_layout.addWidget(level_desc)
        level_group.setLayout(level_layout)
        
        # Privacy Features
        features_group = QGroupBox("🔒 Privacy Features")
        features_layout = QVBoxLayout()
        
        self.anonymize_mac = QCheckBox("Anonymize MAC Addresses")
        self.anonymize_mac.setChecked(True)
        self.anonymize_mac.toggled.connect(self.on_feature_toggled)
        
        self.anonymize_ip = QCheckBox("Anonymize IP Addresses")
        self.anonymize_ip.setChecked(True)
        self.anonymize_ip.toggled.connect(self.on_feature_toggled)
        
        self.anonymize_devices = QCheckBox("Anonymize Device Names")
        self.anonymize_devices.setChecked(True)
        self.anonymize_devices.toggled.connect(self.on_feature_toggled)
        
        self.encrypt_logs = QCheckBox("Encrypt Log Files")
        self.encrypt_logs.setChecked(True)
        self.encrypt_logs.toggled.connect(self.on_feature_toggled)
        
        self.clear_logs = QCheckBox("Clear Logs on Exit")
        self.clear_logs.setChecked(True)
        self.clear_logs.toggled.connect(self.on_feature_toggled)
        
        self.mask_activity = QCheckBox("Mask Network Activity")
        self.mask_activity.setChecked(True)
        self.mask_activity.toggled.connect(self.on_feature_toggled)
        
        features_layout.addWidget(self.anonymize_mac)
        features_layout.addWidget(self.anonymize_ip)
        features_layout.addWidget(self.anonymize_devices)
        features_layout.addWidget(self.encrypt_logs)
        features_layout.addWidget(self.clear_logs)
        features_layout.addWidget(self.mask_activity)
        features_group.setLayout(features_layout)
        
        # Privacy Actions
        actions_group = QGroupBox("⚡ Privacy Actions")
        actions_layout = QHBoxLayout()
        
        self.mask_button = QPushButton("🔄 Mask Activity")
        self.mask_button.clicked.connect(self.mask_network_activity)
        
        self.clear_button = QPushButton("🗑️ Clear Data")
        self.clear_button.clicked.connect(self.clear_privacy_data)
        
        self.report_button = QPushButton("📊 Privacy Report")
        self.report_button.clicked.connect(self.show_privacy_report)
        
        actions_layout.addWidget(self.mask_button)
        actions_layout.addWidget(self.clear_button)
        actions_layout.addWidget(self.report_button)
        actions_group.setLayout(actions_layout)
        
        # Privacy Status
        status_group = QGroupBox("📈 Privacy Status")
        status_layout = QVBoxLayout()
        
        self.status_label = QLabel("Privacy Status: Active")
        self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        
        self.session_label = QLabel("Session ID: Loading...")
        self.session_label.setStyleSheet("font-family: monospace; font-size: 10px;")
        
        self.events_label = QLabel("Events Logged: 0")
        
        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.session_label)
        status_layout.addWidget(self.events_label)
        status_group.setLayout(status_layout)
        
        # Add all groups to main layout
        layout.addWidget(level_group)
        layout.addWidget(features_group)
        layout.addWidget(actions_group)
        layout.addWidget(status_group)
        
        self.setLayout(layout)
        
    def on_privacy_level_changed(self, level: str):
        """Handle privacy level change"""
        level_lower = level.lower()
        privacy_manager.set_privacy_level(level_lower)
        
        # Update checkboxes based on level
        if level_lower == "low":
            self.anonymize_mac.setChecked(False)
            self.anonymize_ip.setChecked(False)
            self.anonymize_devices.setChecked(False)
            self.encrypt_logs.setChecked(False)
            self.clear_logs.setChecked(False)
            self.mask_activity.setChecked(False)
        elif level_lower == "medium":
            self.anonymize_mac.setChecked(True)
            self.anonymize_ip.setChecked(False)
            self.anonymize_devices.setChecked(True)
            self.encrypt_logs.setChecked(True)
            self.clear_logs.setChecked(False)
            self.mask_activity.setChecked(False)
        elif level_lower == "high":
            self.anonymize_mac.setChecked(True)
            self.anonymize_ip.setChecked(True)
            self.anonymize_devices.setChecked(True)
            self.encrypt_logs.setChecked(True)
            self.clear_logs.setChecked(True)
            self.mask_activity.setChecked(True)
        elif level_lower == "maximum":
            self.anonymize_mac.setChecked(True)
            self.anonymize_ip.setChecked(True)
            self.anonymize_devices.setChecked(True)
            self.encrypt_logs.setChecked(True)
            self.clear_logs.setChecked(True)
            self.mask_activity.setChecked(True)
        
        self.privacy_level_changed.emit(level_lower)
        log_info(f"Privacy level changed to: {level_lower}")
        
    def on_feature_toggled(self):
        """Handle feature toggle"""
        # Update privacy manager settings based on checkboxes
        privacy_manager.settings.anonymize_mac_addresses = self.anonymize_mac.isChecked()
        privacy_manager.settings.anonymize_ip_addresses = self.anonymize_ip.isChecked()
        privacy_manager.settings.anonymize_device_names = self.anonymize_devices.isChecked()
        privacy_manager.settings.encrypt_logs = self.encrypt_logs.isChecked()
        privacy_manager.settings.clear_logs_on_exit = self.clear_logs.isChecked()
        privacy_manager.settings.mask_user_activity = self.mask_activity.isChecked()
        
        log_info("Privacy features updated")
        
    def mask_network_activity(self):
        """Trigger network activity masking"""
        try:
            privacy_manager.mask_network_activity()
            QMessageBox.information(self, "Privacy", "Network activity masked successfully!")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to mask network activity: {e}")
            
    def clear_privacy_data(self):
        """Clear all privacy data"""
        try:
            reply = QMessageBox.question(
                self, "Clear Privacy Data", 
                "Are you sure you want to clear all privacy data? This cannot be undone.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                privacy_manager.clear_privacy_data()
                self.update_privacy_report()
                QMessageBox.information(self, "Privacy", "Privacy data cleared successfully!")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to clear privacy data: {e}")
            
    def show_privacy_report(self):
        """Show detailed privacy report"""
        try:
            report = privacy_manager.get_privacy_report()
            
            report_text = f"""
🛡️ PRIVACY REPORT
==================

Session ID: {report['session_id']}
Session Duration: {report['session_duration']}
Privacy Level: {report['privacy_level'].upper()}
Events Logged: {report['events_logged']}

ANONYMIZATION STATUS:
• MAC Addresses: {'✅' if report['anonymization_enabled']['mac_addresses'] else '❌'}
• IP Addresses: {'✅' if report['anonymization_enabled']['ip_addresses'] else '❌'}
• Device Names: {'✅' if report['anonymization_enabled']['device_names'] else '❌'}

PROTECTION STATUS:
• Log Encryption: {'✅' if report['protection_enabled']['log_encryption'] else '❌'}
• Log Clearance: {'✅' if report['protection_enabled']['log_clearance'] else '❌'}
• Activity Masking: {'✅' if report['protection_enabled']['activity_masking'] else '❌'}
            """
            
            msg = QMessageBox()
            msg.setWindowTitle("Privacy Report")
            msg.setText(report_text)
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg.exec()
            
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to generate privacy report: {e}")
            
    def update_privacy_report(self):
        """Update privacy status display"""
        try:
            report = privacy_manager.get_privacy_report()
            
            self.session_label.setText(f"Session ID: {report['session_id']}")
            self.events_label.setText(f"Events Logged: {report['events_logged']}")
            
            # Update status color based on privacy level
            if report['privacy_level'] == 'maximum':
                self.status_label.setText("Privacy Status: MAXIMUM PROTECTION")
                self.status_label.setStyleSheet("color: #FF5722; font-weight: bold;")
            elif report['privacy_level'] == 'high':
                self.status_label.setText("Privacy Status: HIGH PROTECTION")
                self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
            elif report['privacy_level'] == 'medium':
                self.status_label.setText("Privacy Status: MEDIUM PROTECTION")
                self.status_label.setStyleSheet("color: #FF9800; font-weight: bold;")
            else:
                self.status_label.setText("Privacy Status: LOW PROTECTION")
                self.status_label.setStyleSheet("color: #F44336; font-weight: bold;")
                
        except Exception as e:
            log_error(f"Failed to update privacy report: {e}")

class PrivacyTabWidget(QTabWidget):
    """Privacy tab widget for main application"""
    
    def __init__(self):
        super().__init__()
        self.init_ui()
        
    def init_ui(self):
        """Initialize privacy tab UI"""
        self.setWindowTitle("Privacy Protection")
        
        # Settings tab
        self.settings_widget = PrivacySettingsWidget()
        self.addTab(self.settings_widget, "🛡️ Privacy Settings")
        
        # Privacy log viewer
        self.log_widget = PrivacyLogWidget()
        self.addTab(self.log_widget, "📋 Privacy Log")
        
    def get_privacy_manager(self):
        """Get privacy manager instance"""
        return privacy_manager

class PrivacyLogWidget(QWidget):
    """Privacy log viewer widget"""
    
    def __init__(self):
        super().__init__()
        self.init_ui()
        
    def init_ui(self):
        """Initialize privacy log UI"""
        layout = QVBoxLayout()
        
        # Log display
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        
        # Refresh button
        refresh_button = QPushButton("🔄 Refresh Log")
        refresh_button.clicked.connect(self.refresh_log)
        
        layout.addWidget(QLabel("Privacy Event Log:"))
        layout.addWidget(self.log_text)
        layout.addWidget(refresh_button)
        
        self.setLayout(layout)
        self.refresh_log()
        
    def refresh_log(self):
        """Refresh privacy log display"""
        try:
            log_content = ""
            
            for event in privacy_manager.privacy_log:
                timestamp = event.get('timestamp', 'Unknown')
                event_type = event.get('event_type', 'Unknown')
                details = event.get('details', {})
                sensitive = event.get('sensitive', False)
                
                log_content += f"[{timestamp}] {event_type}"
                if sensitive:
                    log_content += " [SENSITIVE]"
                log_content += f"\n{json.dumps(details, indent=2)}\n\n"
            
            if not log_content:
                log_content = "No privacy events logged yet."
                
            self.log_text.setPlainText(log_content)
            
        except Exception as e:
            self.log_text.setPlainText(f"Error loading privacy log: {e}") 