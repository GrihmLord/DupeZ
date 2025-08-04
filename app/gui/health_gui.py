#!/usr/bin/env python3
"""
Device Health GUI for DupeZ
Provides interface for monitoring and protecting device health
"""

import sys
import os
from typing import Dict, Optional
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, 
    QPushButton, QGroupBox, QTextEdit, QProgressBar,
    QTableWidget, QTableWidgetItem, QTabWidget, QMessageBox,
    QHeaderView, QFrame
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QPalette, QColor

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.health.device_health_monitor import health_monitor
from app.health.device_protection import device_protection
from app.logs.logger import log_info, log_error

class DeviceHealthWidget(QWidget):
    """Device health monitoring widget"""
    
    health_updated = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.update_health_display()
        
        # Timer for periodic health updates
        self.health_timer = QTimer()
        self.health_timer.timeout.connect(self.update_health_display)
        self.health_timer.start(10000)  # Update every 10 seconds
        
    def init_ui(self):
        """Initialize the device health UI"""
        layout = QVBoxLayout()
        
        # Health Status Overview
        status_group = QGroupBox("🏥 Device Health Overview")
        status_layout = QVBoxLayout()
        
        self.total_devices_label = QLabel("Total Devices: 0")
        self.healthy_devices_label = QLabel("Healthy: 0")
        self.degraded_devices_label = QLabel("Degraded: 0")
        self.poor_devices_label = QLabel("Poor: 0")
        self.disconnected_devices_label = QLabel("Disconnected: 0")
        
        # Set colors for status labels
        self.healthy_devices_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        self.degraded_devices_label.setStyleSheet("color: #FF9800; font-weight: bold;")
        self.poor_devices_label.setStyleSheet("color: #F44336; font-weight: bold;")
        self.disconnected_devices_label.setStyleSheet("color: #9E9E9E; font-weight: bold;")
        
        status_layout.addWidget(self.total_devices_label)
        status_layout.addWidget(self.healthy_devices_label)
        status_layout.addWidget(self.degraded_devices_label)
        status_layout.addWidget(self.poor_devices_label)
        status_layout.addWidget(self.disconnected_devices_label)
        status_group.setLayout(status_layout)
        
        # Protection Controls
        protection_group = QGroupBox("🛡️ Device Protection")
        protection_layout = QVBoxLayout()
        
        self.protection_checkbox = QCheckBox("Enable Device Protection")
        self.protection_checkbox.setChecked(True)
        self.protection_checkbox.toggled.connect(self.on_protection_toggled)
        
        self.monitoring_checkbox = QCheckBox("Enable Health Monitoring")
        self.monitoring_checkbox.setChecked(True)
        self.monitoring_checkbox.toggled.connect(self.on_monitoring_toggled)
        
        protection_layout.addWidget(self.protection_checkbox)
        protection_layout.addWidget(self.monitoring_checkbox)
        protection_group.setLayout(protection_layout)
        
        # Health Actions
        actions_group = QGroupBox("⚡ Health Actions")
        actions_layout = QHBoxLayout()
        
        self.refresh_button = QPushButton("🔄 Refresh Health")
        self.refresh_button.clicked.connect(self.refresh_all_health)
        
        self.add_device_button = QPushButton("➕ Add Device")
        self.add_device_button.clicked.connect(self.add_device_dialog)
        
        self.report_button = QPushButton("📊 Health Report")
        self.report_button.clicked.connect(self.show_health_report)
        
        actions_layout.addWidget(self.refresh_button)
        actions_layout.addWidget(self.add_device_button)
        actions_layout.addWidget(self.report_button)
        actions_group.setLayout(actions_layout)
        
        # Device Health Table
        table_group = QGroupBox("📋 Device Health Details")
        table_layout = QVBoxLayout()
        
        self.health_table = QTableWidget()
        self.health_table.setColumnCount(7)
        self.health_table.setHorizontalHeaderLabels([
            "IP Address", "Health Score", "Status", "Latency", "Packet Loss", "Errors", "Actions"
        ])
        
        # Set table properties
        header = self.health_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        
        table_layout.addWidget(self.health_table)
        table_group.setLayout(table_layout)
        
        # Add all groups to main layout
        layout.addWidget(status_group)
        layout.addWidget(protection_group)
        layout.addWidget(actions_group)
        layout.addWidget(table_group)
        
        self.setLayout(layout)
        
    def on_protection_toggled(self, enabled: bool):
        """Handle protection mode toggle"""
        if enabled:
            device_protection.enable_protection()
        else:
            device_protection.disable_protection()
        
        log_info(f"Device protection {'enabled' if enabled else 'disabled'}")
        
    def on_monitoring_toggled(self, enabled: bool):
        """Handle monitoring mode toggle"""
        if enabled:
            device_protection.start_health_monitoring()
        else:
            device_protection.stop_health_monitoring()
        
        log_info(f"Health monitoring {'started' if enabled else 'stopped'}")
        
    def refresh_all_health(self):
        """Refresh health for all devices"""
        try:
            devices = health_monitor.get_all_devices_health()
            for device in devices:
                health_monitor.check_device_health(device.ip_address)
            
            self.update_health_display()
            QMessageBox.information(self, "Health Refresh", "Device health refreshed successfully!")
            
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to refresh health: {e}")
    
    def add_device_dialog(self):
        """Show dialog to add device for monitoring"""
        try:
            from PyQt6.QtWidgets import QInputDialog
            
            ip_address, ok = QInputDialog.getText(
                self, "Add Device", "Enter IP address to monitor:"
            )
            
            if ok and ip_address:
                if health_monitor.add_device(ip_address):
                    self.update_health_display()
                    QMessageBox.information(self, "Success", f"Device {ip_address} added to monitoring!")
                else:
                    QMessageBox.warning(self, "Error", f"Failed to add device {ip_address}")
                    
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to add device: {e}")
    
    def show_health_report(self):
        """Show detailed health report"""
        try:
            report = device_protection.get_protection_status()
            
            report_text = f"""
🏥 DEVICE HEALTH REPORT
========================

PROTECTION STATUS:
• Protection Enabled: {'✅' if report['protection_enabled'] else '❌'}
• Monitoring Active: {'✅' if report['health_monitoring_active'] else '❌'}

DEVICE STATISTICS:
• Total Devices: {report['total_monitored_devices']}
• Healthy Devices: {report['healthy_devices']}
• Degraded Devices: {report['degraded_devices']}
• Poor Devices: {report['poor_devices']}
• Disconnected Devices: {report['disconnected_devices']}

OPERATION STATISTICS:
• Safe Operations: {report['safe_operations_count']}
• Blocked Operations: {report['blocked_operations_count']}
• Average Health Score: {report['average_health_score']:.1f}%

HEALTH THRESHOLDS:
• Min Health Score: {report['health_thresholds']['min_health_score']}%
• Max Latency: {report['health_thresholds']['max_latency']}ms
• Max Packet Loss: {report['health_thresholds']['max_packet_loss']}%
• Max Error Count: {report['health_thresholds']['max_error_count']}
            """
            
            msg = QMessageBox()
            msg.setWindowTitle("Device Health Report")
            msg.setText(report_text)
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg.exec()
            
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to generate health report: {e}")
    
    def update_health_display(self):
        """Update health display"""
        try:
            # Update overview
            report = device_protection.get_protection_status()
            
            self.total_devices_label.setText(f"Total Devices: {report['total_monitored_devices']}")
            self.healthy_devices_label.setText(f"Healthy: {report['healthy_devices']}")
            self.degraded_devices_label.setText(f"Degraded: {report['degraded_devices']}")
            self.poor_devices_label.setText(f"Poor: {report['poor_devices']}")
            self.disconnected_devices_label.setText(f"Disconnected: {report['disconnected_devices']}")
            
            # Update table
            devices = health_monitor.get_all_devices_health()
            self.health_table.setRowCount(len(devices))
            
            for row, device in enumerate(devices):
                # IP Address
                ip_item = QTableWidgetItem(device.ip_address)
                ip_item.setFlags(ip_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.health_table.setItem(row, 0, ip_item)
                
                # Health Score
                score_item = QTableWidgetItem(f"{device.health_score:.1f}%")
                score_item.setFlags(score_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if device.health_score >= 80:
                    score_item.setBackground(QColor(76, 175, 80, 100))  # Green
                elif device.health_score >= 60:
                    score_item.setBackground(QColor(255, 152, 0, 100))  # Orange
                else:
                    score_item.setBackground(QColor(244, 67, 54, 100))  # Red
                self.health_table.setItem(row, 1, score_item)
                
                # Status
                status_item = QTableWidgetItem(device.connectivity_status.title())
                status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.health_table.setItem(row, 2, status_item)
                
                # Latency
                latency_item = QTableWidgetItem(f"{device.ping_latency:.1f}ms")
                latency_item.setFlags(latency_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.health_table.setItem(row, 3, latency_item)
                
                # Packet Loss
                loss_item = QTableWidgetItem(f"{device.packet_loss:.1f}%")
                loss_item.setFlags(loss_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.health_table.setItem(row, 4, loss_item)
                
                # Errors
                errors_item = QTableWidgetItem(str(device.error_count))
                errors_item.setFlags(errors_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.health_table.setItem(row, 5, errors_item)
                
                # Actions
                actions_widget = QWidget()
                actions_layout = QHBoxLayout()
                
                check_button = QPushButton("Check")
                check_button.clicked.connect(lambda checked, ip=device.ip_address: self.check_device_health(ip))
                
                details_button = QPushButton("Details")
                details_button.clicked.connect(lambda checked, ip=device.ip_address: self.show_device_details(ip))
                
                actions_layout.addWidget(check_button)
                actions_layout.addWidget(details_button)
                actions_layout.setContentsMargins(0, 0, 0, 0)
                actions_widget.setLayout(actions_layout)
                
                self.health_table.setCellWidget(row, 6, actions_widget)
                
        except Exception as e:
            log_error(f"Failed to update health display: {e}")
    
    def check_device_health(self, ip_address: str):
        """Check health of specific device"""
        try:
            device_health = health_monitor.check_device_health(ip_address)
            if device_health:
                QMessageBox.information(self, "Health Check", 
                    f"Device {ip_address} health score: {device_health.health_score:.1f}%")
            else:
                QMessageBox.warning(self, "Health Check", f"Could not check health for {ip_address}")
                
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to check device health: {e}")
    
    def show_device_details(self, ip_address: str):
        """Show detailed information for specific device"""
        try:
            device_info = device_protection.get_device_protection_info(ip_address)
            
            if 'error' in device_info:
                QMessageBox.warning(self, "Error", device_info['error'])
                return
            
            details_text = f"""
📋 DEVICE DETAILS: {ip_address}
===============================

HEALTH STATUS:
• Health Score: {device_info['health_score']:.1f}%
• Connectivity Status: {device_info['connectivity_status'].title()}
• Safe for Operations: {'✅' if device_info['safe_for_operations'] else '❌'}

NETWORK METRICS:
• Ping Latency: {device_info['ping_latency']:.1f}ms
• Packet Loss: {device_info['packet_loss']:.1f}%
• Error Count: {device_info['error_count']}
• Last Seen: {device_info['last_seen']}

WARNINGS:
{chr(10).join(f"• {warning}" for warning in device_info['warnings']) if device_info['warnings'] else "• No warnings"}

RECOMMENDATIONS:
{chr(10).join(f"• {rec}" for rec in device_info['recommendations']) if device_info['recommendations'] else "• No recommendations"}
            """
            
            msg = QMessageBox()
            msg.setWindowTitle(f"Device Details - {ip_address}")
            msg.setText(details_text)
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg.exec()
            
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to show device details: {e}")

class HealthTabWidget(QTabWidget):
    """Health tab widget for main application"""
    
    def __init__(self):
        super().__init__()
        self.init_ui()
        
    def init_ui(self):
        """Initialize health tab UI"""
        self.setWindowTitle("Device Health Monitoring")
        
        # Health monitoring tab
        self.health_widget = DeviceHealthWidget()
        self.addTab(self.health_widget, "🏥 Device Health")
        
        # Health log viewer
        self.log_widget = HealthLogWidget()
        self.addTab(self.log_widget, "📋 Health Log")
        
    def get_health_monitor(self):
        """Get health monitor instance"""
        return health_monitor
    
    def get_device_protection(self):
        """Get device protection instance"""
        return device_protection

class HealthLogWidget(QWidget):
    """Health log viewer widget"""
    
    def __init__(self):
        super().__init__()
        self.init_ui()
        
    def init_ui(self):
        """Initialize health log UI"""
        layout = QVBoxLayout()
        
        # Log display
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        
        # Refresh button
        refresh_button = QPushButton("🔄 Refresh Log")
        refresh_button.clicked.connect(self.refresh_log)
        
        layout.addWidget(QLabel("Device Health Log:"))
        layout.addWidget(self.log_text)
        layout.addWidget(refresh_button)
        
        self.setLayout(layout)
        self.refresh_log()
        
    def refresh_log(self):
        """Refresh health log display"""
        try:
            log_content = ""
            
            # Get health history for all devices
            for ip_address, history in health_monitor.health_history.items():
                log_content += f"\n=== Device: {ip_address} ===\n"
                
                for entry in history[-10:]:  # Show last 10 entries
                    timestamp = entry.get('timestamp', 'Unknown')
                    health_score = entry.get('health_score', 0)
                    status = entry.get('connectivity_status', 'Unknown')
                    latency = entry.get('ping_latency', 0)
                    packet_loss = entry.get('packet_loss', 0)
                    
                    log_content += f"[{timestamp}] Score: {health_score:.1f}% | Status: {status} | Latency: {latency:.1f}ms | Loss: {packet_loss:.1f}%\n"
                
                log_content += "\n"
            
            if not log_content:
                log_content = "No health history available."
                
            self.log_text.setPlainText(log_content)
            
        except Exception as e:
            self.log_text.setPlainText(f"Error loading health log: {e}") 
