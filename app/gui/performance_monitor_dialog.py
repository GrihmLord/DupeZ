#!/usr/bin/env python3
"""
Performance Monitor Dialog
Popup dialog for real-time monitoring of system resources and application performance
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, 
    QProgressBar, QGroupBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QPushButton, QTextEdit, QSplitter, QFrame, QWidget, QCheckBox, QLineEdit
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QPalette
from typing import Dict, List, Optional
import psutil
import time
import threading
from datetime import datetime

from app.logs.logger import log_info, log_error

class PerformanceMonitorDialog(QDialog):
    """Performance monitoring popup dialog"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📊 Performance Monitor")
        self.setModal(False)  # Allow interaction with main window
        self.resize(1000, 700)
        
        # Initialize monitoring
        self.monitoring = False
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_metrics)
        
        self.setup_ui()
        self.start_monitoring()
        
    def setup_ui(self):
        """Setup the performance monitoring UI"""
        layout = QVBoxLayout()
        
        # Title
        title = QLabel("📊 Performance Monitor Dashboard")
        title.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        title.setStyleSheet("color: #ffffff; margin: 10px; text-align: center;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # Create splitter for better layout
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left panel - System Resources
        left_panel = self.create_system_resources_panel()
        splitter.addWidget(left_panel)
        
        # Right panel - Process Monitor
        right_panel = self.create_process_monitor_panel()
        splitter.addWidget(right_panel)
        
        # Center panel - Network Monitor
        center_panel = self.create_network_monitor_panel()
        splitter.addWidget(center_panel)
        
        # Set splitter proportions
        splitter.setSizes([350, 400, 450])
        layout.addWidget(splitter)
        
        # Bottom panel - Performance Logs
        bottom_panel = self.create_performance_logs_panel()
        layout.addWidget(bottom_panel)
        
        # Control buttons
        button_layout = QHBoxLayout()
        
        self.refresh_btn = QPushButton("🔄 Refresh")
        self.refresh_btn.clicked.connect(self.refresh_data)
        button_layout.addWidget(self.refresh_btn)
        
        self.export_btn = QPushButton("📤 Export Data")
        self.export_btn.clicked.connect(self.export_data)
        button_layout.addWidget(self.export_btn)
        
        self.close_btn = QPushButton("❌ Close")
        self.close_btn.clicked.connect(self.close)
        button_layout.addWidget(self.close_btn)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
        self.apply_styling()
        
    def create_system_resources_panel(self) -> QWidget:
        """Create the system resources monitoring panel"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # CPU Usage
        cpu_group = QGroupBox("🖥️ CPU Usage")
        cpu_layout = QVBoxLayout()
        
        self.cpu_usage_bar = QProgressBar()
        self.cpu_usage_bar.setRange(0, 100)
        self.cpu_usage_bar.setFormat("CPU: %p%")
        self.cpu_usage_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #555555;
                border-radius: 5px;
                text-align: center;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4CAF50, stop:0.5 #FF9800, stop:1 #F44336);
                border-radius: 3px;
            }
        """)
        cpu_layout.addWidget(self.cpu_usage_bar)
        
        self.cpu_freq_label = QLabel("Frequency: --")
        self.cpu_cores_label = QLabel("Cores: --")
        cpu_layout.addWidget(self.cpu_freq_label)
        cpu_layout.addWidget(self.cpu_cores_label)
        
        cpu_group.setLayout(cpu_layout)
        layout.addWidget(cpu_group)
        
        # Memory Usage
        memory_group = QGroupBox("💾 Memory Usage")
        memory_layout = QVBoxLayout()
        
        self.memory_usage_bar = QProgressBar()
        self.memory_usage_bar.setRange(0, 100)
        self.memory_usage_bar.setFormat("Memory: %p%")
        self.memory_usage_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #555555;
                border-radius: 5px;
                text-align: center;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #2196F3, stop:0.5 #FF9800, stop:1 #F44336);
                border-radius: 3px;
            }
        """)
        memory_layout.addWidget(self.memory_usage_bar)
        
        self.memory_total_label = QLabel("Total: --")
        self.memory_available_label = QLabel("Available: --")
        self.memory_used_label = QLabel("Used: --")
        memory_layout.addWidget(self.memory_total_label)
        memory_layout.addWidget(self.memory_available_label)
        memory_layout.addWidget(self.memory_used_label)
        
        memory_group.setLayout(memory_layout)
        layout.addWidget(memory_group)
        
        # Disk Usage
        disk_group = QGroupBox("💿 Disk Usage")
        disk_layout = QVBoxLayout()
        
        self.disk_usage_bar = QProgressBar()
        self.disk_usage_bar.setRange(0, 100)
        self.disk_usage_bar.setFormat("Disk: %p%")
        self.disk_usage_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #555555;
                border-radius: 5px;
                text-align: center;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #9C27B0, stop:0.5 #FF9800, stop:1 #F44336);
                border-radius: 3px;
            }
        """)
        disk_layout.addWidget(self.disk_usage_bar)
        
        self.disk_total_label = QLabel("Total: --")
        self.disk_used_label = QLabel("Used: --")
        self.disk_free_label = QLabel("Free: --")
        disk_layout.addWidget(self.disk_total_label)
        disk_layout.addWidget(self.disk_used_label)
        disk_layout.addWidget(self.disk_free_label)
        
        disk_group.setLayout(disk_layout)
        layout.addWidget(disk_group)
        
        # Network Usage
        network_group = QGroupBox("🌐 Network Usage")
        network_layout = QVBoxLayout()
        
        self.network_sent_label = QLabel("Sent: --")
        self.network_recv_label = QLabel("Received: --")
        self.network_connections_label = QLabel("Connections: --")
        network_layout.addWidget(self.network_sent_label)
        network_layout.addWidget(self.network_recv_label)
        network_layout.addWidget(self.network_connections_label)
        
        network_group.setLayout(network_layout)
        layout.addWidget(network_group)
        
        layout.addStretch()
        widget.setLayout(layout)
        return widget
        
    def create_network_monitor_panel(self) -> QWidget:
        """Create the network monitoring panel"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Network Usage
        network_group = QGroupBox("🌐 Network Usage")
        network_layout = QVBoxLayout()
        
        # Network interfaces
        self.network_interfaces_label = QLabel("Interfaces: --")
        network_layout.addWidget(self.network_interfaces_label)
        
        # Network speed and bandwidth
        bandwidth_group = QGroupBox("📊 Bandwidth Monitor")
        bandwidth_layout = QVBoxLayout()
        
        self.network_speed_label = QLabel("Current Speed: --")
        self.network_speed_label.setStyleSheet("color: #00ff00; font-weight: bold;")
        bandwidth_layout.addWidget(self.network_speed_label)
        
        self.bandwidth_usage_bar = QProgressBar()
        self.bandwidth_usage_bar.setRange(0, 100)
        self.bandwidth_usage_bar.setFormat("Bandwidth: %p%")
        self.bandwidth_usage_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #555555;
                border-radius: 5px;
                text-align: center;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #00ff00, stop:0.5 #ffff00, stop:1 #ff0000);
                border-radius: 3px;
            }
        """)
        bandwidth_layout.addWidget(self.bandwidth_usage_bar)
        
        bandwidth_group.setLayout(bandwidth_layout)
        network_layout.addWidget(bandwidth_group)
        
        # Network connections
        self.network_connections_label = QLabel("Active Connections: --")
        network_layout.addWidget(self.network_connections_label)
        
        # Network sent/received
        self.network_sent_label = QLabel("Sent: --")
        self.network_recv_label = QLabel("Received: --")
        network_layout.addWidget(self.network_sent_label)
        network_layout.addWidget(self.network_recv_label)
        
        # Real-time bandwidth monitoring
        bandwidth_monitor_group = QGroupBox("⚡ Real-time Bandwidth")
        bandwidth_monitor_layout = QVBoxLayout()
        
        self.current_upload_speed = QLabel("Upload: -- Mbps")
        self.current_upload_speed.setStyleSheet("color: #00ff00; font-weight: bold;")
        bandwidth_monitor_layout.addWidget(self.current_upload_speed)
        
        self.current_download_speed = QLabel("Download: -- Mbps")
        self.current_download_speed.setStyleSheet("color: #00ccff; font-weight: bold;")
        bandwidth_monitor_layout.addWidget(self.current_download_speed)
        
        self.total_bandwidth_usage = QLabel("Total Usage: -- MB")
        self.total_bandwidth_usage.setStyleSheet("color: #ffff00; font-weight: bold;")
        bandwidth_monitor_layout.addWidget(self.total_bandwidth_usage)
        
        bandwidth_monitor_group.setLayout(bandwidth_monitor_layout)
        network_layout.addWidget(bandwidth_monitor_group)
        
        # Network latency
        self.network_latency_label = QLabel("Latency: --")
        self.network_latency_label.setStyleSheet("color: #00ccff; font-weight: bold;")
        network_layout.addWidget(self.network_latency_label)
        
        # Network device discovery
        device_discovery_group = QGroupBox("🔍 Device Discovery")
        device_layout = QVBoxLayout()
        
        self.device_count_label = QLabel("Discovered Devices: --")
        device_layout.addWidget(self.device_count_label)
        
        # Device details table
        self.device_table = QTableWidget()
        self.device_table.setColumnCount(5)
        self.device_table.setHorizontalHeaderLabels([
            "IP Address", "Hostname", "Status", "Method", "MAC"
        ])
        
        # Set table properties
        header = self.device_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        
        self.device_table.setAlternatingRowColors(True)
        self.device_table.setMaximumHeight(150)
        self.device_table.setStyleSheet("""
            QTableWidget {
                background-color: #1e1e1e;
                alternate-background-color: #2b2b2b;
                gridline-color: #555555;
                color: #ffffff;
                font-size: 10px;
            }
        """)
        device_layout.addWidget(self.device_table)
        
        self.scan_network_btn = QPushButton("🔍 Scan Network")
        self.scan_network_btn.clicked.connect(self.scan_network_devices)
        device_layout.addWidget(self.scan_network_btn)
        
        self.auto_scan_checkbox = QCheckBox("Auto-scan every 30s")
        self.auto_scan_checkbox.setChecked(True)
        self.auto_scan_checkbox.toggled.connect(self.toggle_auto_scan)
        device_layout.addWidget(self.auto_scan_checkbox)
        
        device_discovery_group.setLayout(device_layout)
        network_layout.addWidget(device_discovery_group)
        
        # Network traffic graph placeholder
        traffic_label = QLabel("📈 Network Traffic Graph")
        traffic_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        traffic_label.setStyleSheet("color: #888888; font-style: italic; padding: 20px;")
        network_layout.addWidget(traffic_label)
        
        network_group.setLayout(network_layout)
        layout.addWidget(network_group)
        
        # System Health Monitor
        health_group = QGroupBox("🏥 System Health")
        health_layout = QVBoxLayout()
        
        # Temperature monitoring (if available)
        self.temp_label = QLabel("CPU Temp: --")
        self.temp_label.setStyleSheet("color: #ffaa00; font-weight: bold;")
        health_layout.addWidget(self.temp_label)
        
        # Fan speeds (if available)
        self.fan_label = QLabel("Fan Speed: --")
        self.fan_label.setStyleSheet("color: #00aaff; font-weight: bold;")
        health_layout.addWidget(self.fan_label)
        
        # System uptime
        self.uptime_label = QLabel("Uptime: --")
        self.uptime_label.setStyleSheet("color: #00ffaa; font-weight: bold;")
        health_layout.addWidget(self.uptime_label)
        
        # Battery status (for laptops)
        self.battery_label = QLabel("Battery: --")
        self.battery_label.setStyleSheet("color: #ff00aa; font-weight: bold;")
        health_layout.addWidget(self.battery_label)
        
        health_group.setLayout(health_layout)
        layout.addWidget(health_group)
        
        # System Alerts Panel
        alerts_group = QGroupBox("🚨 System Alerts")
        alerts_layout = QVBoxLayout()
        
        self.alerts_text = QTextEdit()
        self.alerts_text.setReadOnly(True)
        self.alerts_text.setMaximumHeight(100)
        self.alerts_text.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #ffffff;
                border: 1px solid #555555;
                border-radius: 3px;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 10px;
            }
        """)
        alerts_layout.addWidget(self.alerts_text)
        
        # Alert controls
        alert_controls_layout = QHBoxLayout()
        
        self.clear_alerts_btn = QPushButton("Clear Alerts")
        self.clear_alerts_btn.clicked.connect(self.clear_alerts)
        alert_controls_layout.addWidget(self.clear_alerts_btn)
        
        self.alert_settings_btn = QPushButton("Alert Settings")
        self.alert_settings_btn.clicked.connect(self.show_alert_settings)
        alert_controls_layout.addWidget(self.alert_settings_btn)
        
        alerts_layout.addLayout(alert_controls_layout)
        alerts_group.setLayout(alerts_layout)
        layout.addWidget(alerts_group)
        
        # Quick Actions Panel
        actions_group = QGroupBox("⚡ Quick Actions")
        actions_layout = QVBoxLayout()
        
        # System operations
        actions_row1 = QHBoxLayout()
        
        self.refresh_all_btn = QPushButton("🔄 Refresh All")
        self.refresh_all_btn.clicked.connect(self.refresh_all_metrics)
        actions_row1.addWidget(self.refresh_all_btn)
        
        self.export_now_btn = QPushButton("📊 Export Now")
        self.export_now_btn.clicked.connect(self.export_data)
        actions_row1.addWidget(self.export_now_btn)
        
        actions_layout.addLayout(actions_row1)
        
        # Network operations
        actions_row2 = QHBoxLayout()
        
        self.quick_scan_btn = QPushButton("🔍 Quick Scan")
        self.quick_scan_btn.clicked.connect(self.quick_network_scan)
        actions_row2.addWidget(self.quick_scan_btn)
        
        self.network_info_btn = QPushButton("🌐 Network Info")
        self.network_info_btn.clicked.connect(self.show_network_info)
        actions_row2.addWidget(self.network_info_btn)
        
        actions_layout.addLayout(actions_row2)
        
        actions_group.setLayout(actions_layout)
        layout.addWidget(actions_group)
        
        # Disk Usage
        disk_group = QGroupBox("💿 Disk Usage")
        disk_layout = QVBoxLayout()
        
        self.disk_usage_bar = QProgressBar()
        self.disk_usage_bar.setRange(0, 100)
        self.disk_usage_bar.setFormat("Disk: %p%")
        self.disk_usage_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #555555;
                border-radius: 5px;
                text-align: center;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #9C27B0, stop:0.5 #FF9800, stop:1 #F44336);
                border-radius: 3px;
            }
        """)
        disk_layout.addWidget(self.disk_usage_bar)
        
        self.disk_total_label = QLabel("Total: --")
        self.disk_used_label = QLabel("Used: --")
        self.disk_free_label = QLabel("Free: --")
        disk_layout.addWidget(self.disk_total_label)
        disk_layout.addWidget(self.disk_used_label)
        disk_layout.addWidget(self.disk_free_label)
        
        disk_group.setLayout(disk_layout)
        layout.addWidget(disk_group)
        
        layout.addStretch()
        widget.setLayout(layout)
        return widget
        
    def create_process_monitor_panel(self) -> QWidget:
        """Create the process monitoring panel"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Process Table
        process_group = QGroupBox("⚙️ Process Monitor")
        process_layout = QVBoxLayout()
        
        # Process table
        self.process_table = QTableWidget()
        self.process_table.setColumnCount(5)
        self.process_table.setHorizontalHeaderLabels([
            "Process", "CPU %", "Memory %", "Status", "PID"
        ])
        
        # Set table properties
        header = self.process_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        
        self.process_table.setAlternatingRowColors(True)
        self.process_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        
        process_layout.addWidget(self.process_table)
        
        # Process controls
        control_layout = QHBoxLayout()
        
        self.refresh_processes_btn = QPushButton("🔄 Refresh Processes")
        self.refresh_processes_btn.clicked.connect(self.refresh_processes)
        control_layout.addWidget(self.refresh_processes_btn)
        
        self.kill_process_btn = QPushButton("💀 Kill Process")
        self.kill_process_btn.clicked.connect(self.kill_selected_process)
        control_layout.addWidget(self.kill_process_btn)
        
        # Process filtering
        filter_layout = QHBoxLayout()
        
        self.process_filter_label = QLabel("Filter:")
        filter_layout.addWidget(self.process_filter_label)
        
        self.process_filter_input = QLineEdit()
        self.process_filter_input.setPlaceholderText("Enter process name...")
        self.process_filter_input.textChanged.connect(self.filter_processes)
        filter_layout.addWidget(self.process_filter_input)
        
        self.clear_filter_btn = QPushButton("Clear")
        self.clear_filter_btn.clicked.connect(self.clear_process_filter)
        filter_layout.addWidget(self.clear_filter_btn)
        
        process_layout.addLayout(control_layout)
        process_layout.addLayout(filter_layout)
        process_group.setLayout(process_layout)
        layout.addWidget(process_group)
        
        widget.setLayout(layout)
        return widget
        
    def create_performance_logs_panel(self) -> QWidget:
        """Create the performance logs panel"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        logs_group = QGroupBox("📝 Performance Logs")
        logs_layout = QVBoxLayout()
        
        self.logs_text = QTextEdit()
        self.logs_text.setReadOnly(True)
        self.logs_text.setMaximumHeight(150)
        self.logs_text.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #ffffff;
                border: 1px solid #555555;
                border-radius: 3px;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 10px;
            }
        """)
        logs_layout.addWidget(self.logs_text)
        
        logs_group.setLayout(logs_layout)
        layout.addWidget(logs_group)
        
        widget.setLayout(layout)
        return widget
        
    def apply_styling(self):
        """Apply consistent styling to the dialog"""
        self.setStyleSheet("""
            QDialog {
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
            QLabel {
                color: #ffffff;
            }
            QPushButton {
                background-color: #3b3b3b;
                border: 1px solid #555555;
                border-radius: 3px;
                padding: 5px 10px;
                color: #ffffff;
            }
            QPushButton:hover {
                background-color: #4b4b4b;
            }
            QPushButton:pressed {
                background-color: #2b2b2b;
            }
            QTableWidget {
                background-color: #1e1e1e;
                alternate-background-color: #2b2b2b;
                gridline-color: #555555;
                color: #ffffff;
            }
            QTableWidget::item:selected {
                background-color: #4b4b4b;
            }
            QHeaderView::section {
                background-color: #3b3b3b;
                color: #ffffff;
                padding: 5px;
                border: 1px solid #555555;
            }
        """)
        
    def start_monitoring(self):
        """Start the performance monitoring"""
        try:
            self.monitoring = True
            self.update_timer.start(1000)  # Update every second
            self.log_message("Performance monitoring started")
            log_info("Performance monitoring started")
        except Exception as e:
            log_error(f"Error starting performance monitoring: {e}")
            
    def stop_monitoring(self):
        """Stop the performance monitoring"""
        try:
            self.monitoring = False
            self.update_timer.stop()
            self.log_message("Performance monitoring stopped")
            log_info("Performance monitoring stopped")
        except Exception as e:
            log_error(f"Error stopping performance monitoring: {e}")
            
    def update_metrics(self):
        """Update all performance metrics"""
        try:
            self.update_cpu_metrics()
            self.update_memory_metrics()
            self.update_disk_metrics()
            self.update_network_metrics()
            self.update_system_health_metrics()
            self.update_process_table()
            self.update_bandwidth_metrics()
            
            # Log successful update
            from app.logs.logger import log_info
            log_info("Performance metrics updated successfully")
            
        except Exception as e:
            log_error(f"Error updating metrics: {e}")
            # Show error in logs
            self.log_message(f"Error updating metrics: {e}")
    
    def update_system_health_metrics(self):
        """Update system health metrics"""
        try:
            # System uptime
            uptime_seconds = time.time() - psutil.boot_time()
            uptime_days = int(uptime_seconds // 86400)
            uptime_hours = int((uptime_seconds % 86400) // 3600)
            uptime_minutes = int((uptime_seconds % 3600) // 60)
            
            if uptime_days > 0:
                self.uptime_label.setText(f"Uptime: {uptime_days}d {uptime_hours}h {uptime_minutes}m")
            elif uptime_hours > 0:
                self.uptime_label.setText(f"Uptime: {uptime_hours}h {uptime_minutes}m")
            else:
                self.uptime_label.setText(f"Uptime: {uptime_minutes}m")
            
            # Battery status (for laptops)
            try:
                battery = psutil.sensors_battery()
                if battery:
                    if battery.power_plugged:
                        self.battery_label.setText(f"Battery: {battery.percent}% (Plugged)")
                        self.battery_label.setStyleSheet("color: #00ff00; font-weight: bold;")
                    else:
                        self.battery_label.setText(f"Battery: {battery.percent}% ({battery.secsleft//60}m left)")
                        if battery.percent > 20:
                            self.battery_label.setStyleSheet("color: #ffff00; font-weight: bold;")
                        else:
                            self.battery_label.setStyleSheet("color: #ff0000; font-weight: bold;")
                else:
                    self.battery_label.setText("Battery: N/A")
            except:
                self.battery_label.setText("Battery: N/A")
            
            # Temperature monitoring (platform specific)
            try:
                if hasattr(psutil, 'sensors_temperatures'):
                    temps = psutil.sensors_temperatures()
                    if temps:
                        # Get first available temperature sensor
                        for name, entries in temps.items():
                            if entries:
                                temp = entries[0].current
                                self.temp_label.setText(f"CPU Temp: {temp:.1f}°C")
                                
                                # Color code temperature and generate alerts
                                if temp < 60:
                                    self.temp_label.setStyleSheet("color: #00ff00; font-weight: bold;")
                                elif temp < 80:
                                    self.temp_label.setStyleSheet("color: #ffff00; font-weight: bold;")
                                    self.add_alert(f"CPU temperature high: {temp:.1f}°C", "WARNING")
                                else:
                                    self.temp_label.setStyleSheet("color: #ff0000; font-weight: bold;")
                                    self.add_alert(f"CPU temperature critical: {temp:.1f}°C", "CRITICAL")
                                break
                    else:
                        self.temp_label.setText("CPU Temp: N/A")
                else:
                    self.temp_label.setText("CPU Temp: N/A")
            except:
                self.temp_label.setText("CPU Temp: N/A")
            
            # Fan speeds (platform specific)
            try:
                if hasattr(psutil, 'sensors_fans'):
                    fans = psutil.sensors_fans()
                    if fans:
                        # Get first available fan
                        for name, entries in fans.items():
                            if entries:
                                fan_speed = entries[0].current
                                self.fan_label.setText(f"Fan Speed: {fan_speed} RPM")
                                break
                    else:
                        self.fan_label.setText("Fan Speed: N/A")
                else:
                    self.fan_label.setText("Fan Speed: N/A")
            except:
                self.fan_label.setText("Fan Speed: N/A")
                
        except Exception as e:
            log_error(f"Error updating system health metrics: {e}")
    
    def update_bandwidth_metrics(self):
        """Update real-time bandwidth metrics"""
        try:
            # Get current network I/O counters
            net_io = psutil.net_io_counters()
            
            # Calculate bandwidth usage since last update
            if hasattr(self, '_last_net_io'):
                # Calculate time difference
                current_time = time.time()
                time_diff = current_time - self._last_time
                
                if time_diff > 0:
                    # Calculate bytes per second
                    bytes_sent_per_sec = (net_io.bytes_sent - self._last_net_io.bytes_sent) / time_diff
                    bytes_recv_per_sec = (net_io.bytes_recv - self._last_net_io.bytes_recv) / time_diff
                    
                    # Convert to Mbps
                    upload_mbps = (bytes_sent_per_sec * 8) / 1_000_000
                    download_mbps = (bytes_recv_per_sec * 8) / 1_000_000
                    
                    # Update labels
                    self.current_upload_speed.setText(f"Upload: {upload_mbps:.2f} Mbps")
                    self.current_download_speed.setText(f"Download: {download_mbps:.2f} Mbps")
                    
                    # Update bandwidth usage bar
                    total_bandwidth = upload_mbps + download_mbps
                    if total_bandwidth > 0:
                        # Normalize to 0-100 for progress bar
                        bandwidth_percent = min(100, (total_bandwidth / 100) * 100)  # Assume 100 Mbps as 100%
                        self.bandwidth_usage_bar.setValue(int(bandwidth_percent))
                    
                    # Calculate total usage in MB
                    total_sent_mb = net_io.bytes_sent / 1_048_576
                    total_recv_mb = net_io.bytes_recv / 1_048_576
                    total_usage_mb = total_sent_mb + total_recv_mb
                    self.total_bandwidth_usage.setText(f"Total Usage: {total_usage_mb:.1f} MB")
            
            # Store current values for next calculation
            self._last_net_io = net_io
            self._last_time = time.time()
            
        except Exception as e:
            log_error(f"Error updating bandwidth metrics: {e}")
            self.log_message(f"Error updating bandwidth metrics: {e}")
            
    def update_cpu_metrics(self):
        """Update CPU metrics"""
        try:
            cpu_percent = psutil.cpu_percent(interval=0.1)
            self.cpu_usage_bar.setValue(int(cpu_percent))
            
            # Generate alerts for high CPU usage
            if cpu_percent > 95:
                self.add_alert(f"CPU usage critical: {cpu_percent:.1f}%", "CRITICAL")
            elif cpu_percent > 80:
                self.add_alert(f"CPU usage high: {cpu_percent:.1f}%", "WARNING")
            
            cpu_freq = psutil.cpu_freq()
            if cpu_freq:
                self.cpu_freq_label.setText(f"Frequency: {cpu_freq.current:.1f} MHz")
            
            self.cpu_cores_label.setText(f"Cores: {psutil.cpu_count()}")
        except Exception as e:
            log_error(f"Error updating CPU metrics: {e}")
            
    def update_memory_metrics(self):
        """Update memory metrics"""
        try:
            memory = psutil.virtual_memory()
            self.memory_usage_bar.setValue(int(memory.percent))
            
            # Generate alerts for high memory usage
            if memory.percent > 95:
                self.add_alert(f"Memory usage critical: {memory.percent:.1f}%", "CRITICAL")
            elif memory.percent > 85:
                self.add_alert(f"Memory usage high: {memory.percent:.1f}%", "WARNING")
            
            self.memory_total_label.setText(f"Total: {self.format_bytes(memory.total)}")
            self.memory_available_label.setText(f"Available: {self.format_bytes(memory.available)}")
            self.memory_used_label.setText(f"Used: {self.format_bytes(memory.used)}")
        except Exception as e:
            log_error(f"Error updating memory metrics: {e}")
            
    def update_disk_metrics(self):
        """Update disk metrics"""
        try:
            disk = psutil.disk_usage('/')
            disk_percent = (disk.used / disk.total) * 100
            self.disk_usage_bar.setValue(int(disk_percent))
            
            # Generate alerts for high disk usage
            if disk_percent > 95:
                self.add_alert(f"Disk usage critical: {disk_percent:.1f}%", "CRITICAL")
            elif disk_percent > 90:
                self.add_alert(f"Disk usage high: {disk_percent:.1f}%", "WARNING")
            
            self.disk_total_label.setText(f"Total: {self.format_bytes(disk.total)}")
            self.disk_used_label.setText(f"Used: {self.format_bytes(disk.used)}")
            self.disk_free_label.setText(f"Free: {self.format_bytes(disk.free)}")
        except Exception as e:
            log_error(f"Error updating disk metrics: {e}")
            
    def update_network_metrics(self):
        """Update network metrics"""
        try:
            net_io = psutil.net_io_counters()
            self.network_sent_label.setText(f"Sent: {self.format_bytes(net_io.bytes_sent)}")
            self.network_recv_label.setText(f"Received: {self.format_bytes(net_io.bytes_recv)}")
            
            connections = len(psutil.net_connections())
            self.network_connections_label.setText(f"Connections: {connections}")
            
            # Update network interfaces
            interfaces = psutil.net_if_addrs()
            interface_count = len(interfaces)
            self.network_interfaces_label.setText(f"Interfaces: {interface_count}")
            
            # Calculate bandwidth usage
            if hasattr(self, '_last_net_io'):
                bytes_sent_diff = net_io.bytes_sent - self._last_net_io.bytes_sent
                bytes_recv_diff = net_io.bytes_recv - self._last_net_io.bytes_recv
                total_diff = bytes_sent_diff + bytes_recv_diff
                
                # Convert to Mbps
                mbps = (total_diff * 8) / (1024 * 1024)
                self.network_speed_label.setText(f"Current Speed: {mbps:.2f} Mbps")
                
                # Update bandwidth bar (0-100%)
                max_bandwidth = 1000  # Assume 1 Gbps max
                bandwidth_percent = min(100, (mbps / max_bandwidth) * 100)
                self.bandwidth_usage_bar.setValue(int(bandwidth_percent))
                
                # Color code based on usage
                if bandwidth_percent < 50:
                    self.network_speed_label.setStyleSheet("color: #00ff00; font-weight: bold;")
                elif bandwidth_percent < 80:
                    self.network_speed_label.setStyleSheet("color: #ffff00; font-weight: bold;")
                else:
                    self.network_speed_label.setStyleSheet("color: #ff0000; font-weight: bold;")
            
            self._last_net_io = net_io
            
            # Update network latency
            try:
                import socket
                start_time = time.time()
                socket.create_connection(("8.8.8.8", 53), timeout=1)
                latency = (time.time() - start_time) * 1000
                self.network_latency_label.setText(f"Latency: {latency:.1f}ms")
                
                # Color code latency
                if latency < 50:
                    self.network_latency_label.setStyleSheet("color: #00ff00; font-weight: bold;")
                elif latency < 100:
                    self.network_latency_label.setStyleSheet("color: #ffff00; font-weight: bold;")
                else:
                    self.network_latency_label.setStyleSheet("color: #ff0000; font-weight: bold;")
            except:
                self.network_latency_label.setText("Latency: --")
                
        except Exception as e:
            log_error(f"Error updating network metrics: {e}")
            
    def update_process_table(self):
        """Update the process table"""
        try:
            processes = []
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'status']):
                try:
                    info = proc.info
                    if info['cpu_percent'] is not None and info['memory_percent'] is not None:
                        processes.append({
                            'name': info['name'],
                            'cpu': info['cpu_percent'],
                            'memory': info['memory_percent'],
                            'status': info['status'],
                            'pid': info['pid']
                        })
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
            
            # Sort by CPU usage (descending)
            processes.sort(key=lambda x: x['cpu'], reverse=True)
            
            # Update table
            self.process_table.setRowCount(min(len(processes), 50))  # Show top 50 processes
            
            for row, proc in enumerate(processes[:50]):
                self.process_table.setItem(row, 0, QTableWidgetItem(proc['name']))
                self.process_table.setItem(row, 1, QTableWidgetItem(f"{proc['cpu']:.1f}"))
                self.process_table.setItem(row, 2, QTableWidgetItem(f"{proc['memory']:.1f}"))
                self.process_table.setItem(row, 3, QTableWidgetItem(proc['status']))
                self.process_table.setItem(row, 4, QTableWidgetItem(str(proc['pid'])))
                
        except Exception as e:
            log_error(f"Error updating process table: {e}")
            
    def refresh_data(self):
        """Refresh all data immediately"""
        try:
            self.update_metrics()
            self.log_message("Data refreshed manually")
        except Exception as e:
            log_error(f"Error refreshing data: {e}")
            
    def refresh_processes(self):
        """Refresh the process list"""
        try:
            self.update_process_table()
            self.log_message("Process list refreshed")
        except Exception as e:
            log_error(f"Error refreshing processes: {e}")
            
    def kill_selected_process(self):
        """Kill the selected process"""
        try:
            current_row = self.process_table.currentRow()
            if current_row >= 0:
                pid_item = self.process_table.item(current_row, 4)
                if pid_item:
                    pid = int(pid_item.text())
                    proc_name = self.process_table.item(current_row, 0).text()
                    
                    # Confirm before killing
                    from PyQt6.QtWidgets import QMessageBox
                    reply = QMessageBox.question(
                        self, 
                        "Confirm Process Kill", 
                        f"Are you sure you want to kill process '{proc_name}' (PID: {pid})?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                    )
                    
                    if reply == QMessageBox.StandardButton.Yes:
                        psutil.Process(pid).terminate()
                        self.log_message(f"Process {proc_name} (PID: {pid}) terminated")
                        self.update_process_table()
                        
        except Exception as e:
            log_error(f"Error killing process: {e}")
            self.log_message(f"Error killing process: {e}")
    
    def filter_processes(self, filter_text: str):
        """Filter processes based on search text"""
        try:
            if not filter_text:
                # Show all processes
                for row in range(self.process_table.rowCount()):
                    self.process_table.setRowHidden(row, False)
                return
            
            # Hide rows that don't match the filter
            for row in range(self.process_table.rowCount()):
                process_name = self.process_table.item(row, 0).text().lower()
                if filter_text.lower() in process_name:
                    self.process_table.setRowHidden(row, False)
                else:
                    self.process_table.setRowHidden(row, True)
                    
        except Exception as e:
            log_error(f"Error filtering processes: {e}")
            self.log_message(f"Error filtering processes: {e}")
    
    def clear_process_filter(self):
        """Clear the process filter and show all processes"""
        try:
            self.process_filter_input.clear()
            for row in range(self.process_table.rowCount()):
                self.process_table.setRowHidden(row, False)
        except Exception as e:
            log_error(f"Error clearing process filter: {e}")
            self.log_message(f"Error clearing process filter: {e}")
    
    def add_alert(self, message: str, alert_type: str = "INFO"):
        """Add a system alert"""
        try:
            timestamp = datetime.now().strftime("%H:%M:%S")
            alert_text = f"[{timestamp}] {alert_type}: {message}"
            
            # Color code based on alert type
            if alert_type == "WARNING":
                alert_text = f"⚠️ {alert_text}"
            elif alert_type == "ERROR":
                alert_text = f"❌ {alert_text}"
            elif alert_type == "CRITICAL":
                alert_text = f"🚨 {alert_text}"
            
            self.alerts_text.append(alert_text)
            
            # Keep only last 50 alerts
            lines = self.alerts_text.toPlainText().split('\n')
            if len(lines) > 50:
                self.alerts_text.setPlainText('\n'.join(lines[-50:]))
                
        except Exception as e:
            log_error(f"Error adding alert: {e}")
    
    def clear_alerts(self):
        """Clear all system alerts"""
        try:
            self.alerts_text.clear()
        except Exception as e:
            log_error(f"Error clearing alerts: {e}")
    
    def show_alert_settings(self):
        """Show alert configuration dialog"""
        try:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(
                self, 
                "Alert Settings", 
                "Alert thresholds:\n"
                "• CPU > 80%: Warning\n"
                "• CPU > 95%: Critical\n"
                "• Memory > 85%: Warning\n"
                "• Memory > 95%: Critical\n"
                "• Disk > 90%: Warning\n"
                "• Temperature > 80°C: Warning"
            )
        except Exception as e:
            log_error(f"Error showing alert settings: {e}")
    
    def refresh_all_metrics(self):
        """Refresh all performance metrics immediately"""
        try:
            self.log_message("Refreshing all metrics...")
            self.update_metrics()
            self.add_alert("All metrics refreshed", "INFO")
        except Exception as e:
            log_error(f"Error refreshing metrics: {e}")
            self.add_alert(f"Error refreshing metrics: {e}", "ERROR")
    
    def quick_network_scan(self):
        """Perform a quick network scan"""
        try:
            self.log_message("Starting quick network scan...")
            self.scan_network_devices()
        except Exception as e:
            log_error(f"Error starting quick scan: {e}")
            self.add_alert(f"Quick scan error: {e}", "ERROR")
    
    def show_network_info(self):
        """Show detailed network information"""
        try:
            import socket
            import psutil
            
            # Get local network info
            hostname = socket.gethostname()
            local_ip = socket.gethostbyname(hostname)
            
            # Get network interfaces
            interfaces = psutil.net_if_addrs()
            interface_info = []
            
            for interface, addrs in interfaces.items():
                for addr in addrs:
                    if addr.family == socket.AF_INET:  # IPv4
                        interface_info.append(f"{interface}: {addr.address}")
            
            # Get default gateway
            try:
                import subprocess
                if hasattr(subprocess, 'run'):
                    result = subprocess.run(['route', 'print'], capture_output=True, text=True)
                    gateway = "Unknown"
                    for line in result.stdout.split('\n'):
                        if '0.0.0.0' in line and '0.0.0.0' in line.split():
                            parts = line.split()
                            if len(parts) > 2:
                                gateway = parts[2]
                                break
                else:
                    gateway = "Unknown"
            except:
                gateway = "Unknown"
            
            info_text = f"""Network Information:
Hostname: {hostname}
Local IP: {local_ip}
Default Gateway: {gateway}

Network Interfaces:
{chr(10).join(interface_info)}
"""
            
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "Network Information", info_text)
            
        except Exception as e:
            log_error(f"Error showing network info: {e}")
            self.add_alert(f"Error showing network info: {e}", "ERROR")
            
    def export_data(self):
        """Export performance data to file"""
        try:
            from PyQt6.QtWidgets import QFileDialog
            filename, _ = QFileDialog.getSaveFileName(
                self, 
                "Export Performance Data", 
                f"performance_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                "Text Files (*.txt);;CSV Files (*.csv);;JSON Files (*.json)"
            )
            
            if filename:
                file_ext = filename.split('.')[-1].lower() if '.' in filename else 'txt'
                
                if file_ext == 'csv':
                    self._export_csv(filename)
                elif file_ext == 'json':
                    self._export_json(filename)
                else:
                    self._export_txt(filename)
                
                self.log_message(f"Data exported to {filename}")
                
        except Exception as e:
            log_error(f"Error exporting data: {e}")
            self.log_message(f"Error exporting data: {e}")
    
    def _export_txt(self, filename: str):
        """Export data as text file"""
        with open(filename, 'w') as f:
            f.write("DupeZ Performance Monitor Data\n")
            f.write("=" * 40 + "\n")
            f.write(f"Generated: {datetime.now()}\n\n")
            
            # CPU info
            f.write("CPU Information:\n")
            f.write(f"Usage: {self.cpu_usage_bar.value()}%\n")
            f.write(f"Frequency: {self.cpu_freq_label.text()}\n")
            f.write(f"Cores: {self.cpu_cores_label.text()}\n\n")
            
            # Memory info
            f.write("Memory Information:\n")
            f.write(f"Usage: {self.memory_usage_bar.value()}%\n")
            f.write(f"Total: {self.memory_total_label.text()}\n")
            f.write(f"Used: {self.memory_used_label.text()}\n\n")
            
            # Process info
            f.write("Top Processes:\n")
            for row in range(min(self.process_table.rowCount(), 20)):
                name = self.process_table.item(row, 0).text()
                cpu = self.process_table.item(row, 1).text()
                memory = self.process_table.item(row, 2).text()
                f.write(f"{name}: CPU {cpu}%, Memory {memory}%\n")
    
    def _export_csv(self, filename: str):
        """Export data as CSV file"""
        import csv
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # Write header
            writer.writerow(['Metric', 'Value', 'Unit'])
            
            # CPU data
            writer.writerow(['CPU Usage', self.cpu_usage_bar.value(), '%'])
            writer.writerow(['CPU Frequency', self.cpu_freq_label.text().replace('Frequency: ', ''), ''])
            writer.writerow(['CPU Cores', self.cpu_cores_label.text().replace('Cores: ', ''), ''])
            
            # Memory data
            writer.writerow(['Memory Usage', self.memory_usage_bar.value(), '%'])
            writer.writerow(['Memory Total', self.memory_total_label.text().replace('Total: ', ''), ''])
            writer.writerow(['Memory Used', self.memory_used_label.text().replace('Used: ', ''), ''])
            
            # Process data
            writer.writerow([])  # Empty row
            writer.writerow(['Process Name', 'CPU %', 'Memory %', 'PID'])
            for row in range(min(self.process_table.rowCount(), 20)):
                name = self.process_table.item(row, 0).text()
                cpu = self.process_table.item(row, 1).text()
                memory = self.process_table.item(row, 2).text()
                pid = self.process_table.item(row, 4).text() if self.process_table.columnCount() > 4 else ''
                writer.writerow([name, cpu, memory, pid])
    
    def _export_json(self, filename: str):
        """Export data as JSON file"""
        import json
        data = {
            'timestamp': datetime.now().isoformat(),
            'system_info': {
                'cpu': {
                    'usage_percent': self.cpu_usage_bar.value(),
                    'frequency': self.cpu_freq_label.text().replace('Frequency: ', ''),
                    'cores': self.cpu_cores_label.text().replace('Cores: ', '')
                },
                'memory': {
                    'usage_percent': self.memory_usage_bar.value(),
                    'total': self.memory_total_label.text().replace('Total: ', ''),
                    'used': self.memory_used_label.text().replace('Used: ', '')
                }
            },
            'processes': []
        }
        
        # Add process data
        for row in range(min(self.process_table.rowCount(), 20)):
            process = {
                'name': self.process_table.item(row, 0).text(),
                'cpu_percent': self.process_table.item(row, 1).text(),
                'memory_percent': self.process_table.item(row, 2).text(),
                'status': self.process_table.item(row, 3).text() if self.process_table.columnCount() > 3 else '',
                'pid': self.process_table.item(row, 4).text() if self.process_table.columnCount() > 4 else ''
            }
            data['processes'].append(process)
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            
    def log_message(self, message: str):
        """Add a message to the logs"""
        try:
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.logs_text.append(f"[{timestamp}] {message}")
            
            # Keep only last 100 lines
            lines = self.logs_text.toPlainText().split('\n')
            if len(lines) > 100:
                self.logs_text.setPlainText('\n'.join(lines[-100:]))
                
        except Exception as e:
            log_error(f"Error logging message: {e}")
            
    def format_bytes(self, bytes_value: int) -> str:
        """Format bytes into human readable format"""
        try:
            for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
                if bytes_value < 1024.0:
                    return f"{bytes_value:.1f} {unit}"
                bytes_value /= 1024.0
            return f"{bytes_value:.1f} PB"
        except Exception:
            return "0 B"
            
    def scan_network_devices(self):
        """Scan the network for devices"""
        try:
            self.log_message("Starting network device scan...")
            self.scan_network_btn.setEnabled(False)
            self.scan_network_btn.setText("Scanning...")
            
            # Start scan in background thread
            import threading
            scan_thread = threading.Thread(target=self._perform_network_scan)
            scan_thread.daemon = True
            scan_thread.start()
            
        except Exception as e:
            log_error(f"Error starting network scan: {e}")
            self.log_message(f"Error starting network scan: {e}")
            self.scan_network_btn.setEnabled(True)
            self.scan_network_btn.setText("🔍 Scan Network")
    
    def _perform_network_scan(self):
        """Perform the actual network scan using multiple discovery methods"""
        try:
            import socket
            import subprocess
            import platform
            import threading
            import time
            
            discovered_devices = []
            device_lock = threading.Lock()
            
            # Get local network info
            hostname = socket.gethostname()
            local_ip = socket.gethostbyname(hostname)
            network_prefix = '.'.join(local_ip.split('.')[:-1]) + '.'
            
            self.log_message(f"Starting comprehensive network scan: {network_prefix}0/24")
            
            def scan_with_ping(start_ip, end_ip):
                """Scan IP range using ping"""
                for i in range(start_ip, end_ip):
                    ip = f"{network_prefix}{i}"
                    try:
                        # Use ping to check if device is alive
                        if platform.system().lower() == "windows":
                            result = subprocess.run(
                                ["ping", "-n", "1", "-w", "50", ip],
                                capture_output=True, text=True, timeout=0.5
                            )
                        else:
                            result = subprocess.run(
                                ["ping", "-c", "1", "-W", "1", ip],
                                capture_output=True, text=True, timeout=0.5
                            )
                        
                        if result.returncode == 0:
                            # Try to get hostname
                            try:
                                hostname = socket.gethostbyaddr(ip)[0]
                            except:
                                hostname = "Unknown"
                            
                            device_info = {
                                'ip': ip,
                                'hostname': hostname,
                                'status': 'Online',
                                'response_time': 'Fast',
                                'method': 'Ping'
                            }
                            
                            with device_lock:
                                discovered_devices.append(device_info)
                                
                    except Exception:
                        continue
            
            def scan_with_arp():
                """Scan using ARP table (Windows) or arp command (Linux/Mac)"""
                try:
                    if platform.system().lower() == "windows":
                        result = subprocess.run(
                            ["arp", "-a"], 
                            capture_output=True, text=True, timeout=2
                        )
                        if result.returncode == 0:
                            lines = result.stdout.split('\n')
                            for line in lines:
                                if 'dynamic' in line.lower():
                                    parts = line.split()
                                    if len(parts) >= 2:
                                        ip = parts[0]
                                        mac = parts[1] if len(parts) > 1 else "Unknown"
                                        if ip != local_ip and ip.startswith(network_prefix):
                                            device_info = {
                                                'ip': ip,
                                                'hostname': 'Unknown',
                                                'status': 'Online',
                                                'response_time': 'Fast',
                                                'method': 'ARP',
                                                'mac': mac
                                            }
                                            with device_lock:
                                                discovered_devices.append(device_info)
                    else:
                        # Linux/Mac ARP scan
                        result = subprocess.run(
                            ["arp", "-n"], 
                            capture_output=True, text=True, timeout=2
                        )
                        if result.returncode == 0:
                            lines = result.stdout.split('\n')
                            for line in lines:
                                if 'ether' in line.lower():
                                    parts = line.split()
                                    if len(parts) >= 1:
                                        ip = parts[0]
                                        if ip != local_ip and ip.startswith(network_prefix):
                                            device_info = {
                                                'ip': ip,
                                                'hostname': 'Unknown',
                                                'status': 'Online',
                                                'response_time': 'Fast',
                                                'method': 'ARP'
                                            }
                                            with device_lock:
                                                discovered_devices.append(device_info)
                except Exception as e:
                    self.log_message(f"ARP scan error: {e}")
            
            def scan_with_netstat():
                """Scan using netstat to find active connections"""
                try:
                    if platform.system().lower() == "windows":
                        result = subprocess.run(
                            ["netstat", "-n"], 
                            capture_output=True, text=True, timeout=2
                        )
                    else:
                        result = subprocess.run(
                            ["netstat", "-n"], 
                            capture_output=True, text=True, timeout=2
                        )
                    
                    if result.returncode == 0:
                        lines = result.stdout.split('\n')
                        for line in lines:
                            parts = line.split()
                            if len(parts) >= 4:
                                remote_ip = parts[2]
                                if remote_ip != local_ip and remote_ip.startswith(network_prefix):
                                    # Check if we already have this IP
                                    with device_lock:
                                        if not any(d['ip'] == remote_ip for d in discovered_devices):
                                            device_info = {
                                                'ip': remote_ip,
                                                'hostname': 'Unknown',
                                                'status': 'Online',
                                                'response_time': 'Fast',
                                                'method': 'Netstat'
                                            }
                                            discovered_devices.append(device_info)
                except Exception as e:
                    self.log_message(f"Netstat scan error: {e}")
            
            def scan_with_nmap():
                """Scan using nmap if available"""
                try:
                    result = subprocess.run(
                        ["nmap", "-sn", f"{network_prefix}0/24"], 
                        capture_output=True, text=True, timeout=10
                    )
                    if result.returncode == 0:
                        lines = result.stdout.split('\n')
                        for line in lines:
                            if 'Nmap scan report for' in line:
                                parts = line.split()
                                if len(parts) >= 5:
                                    ip = parts[4]
                                    if ip != local_ip and ip.startswith(network_prefix):
                                        device_info = {
                                            'ip': ip,
                                            'hostname': 'Unknown',
                                            'status': 'Online',
                                            'response_time': 'Fast',
                                            'method': 'Nmap'
                                        }
                                        with device_lock:
                                            discovered_devices.append(device_info)
                except Exception:
                    # Nmap not available, skip
                    pass
            
            # Start multiple scanning threads for better coverage
            threads = []
            
            # Ping scan in chunks
            chunk_size = 64
            for start in range(1, 255, chunk_size):
                end = min(start + chunk_size, 255)
                thread = threading.Thread(target=scan_with_ping, args=(start, end))
                thread.daemon = True
                threads.append(thread)
                thread.start()
            
            # ARP scan
            arp_thread = threading.Thread(target=scan_with_arp)
            arp_thread.daemon = True
            threads.append(arp_thread)
            arp_thread.start()
            
            # Netstat scan
            netstat_thread = threading.Thread(target=scan_with_netstat)
            netstat_thread.daemon = True
            threads.append(netstat_thread)
            netstat_thread.start()
            
            # Nmap scan (if available)
            nmap_thread = threading.Thread(target=scan_with_nmap)
            nmap_thread.daemon = True
            threads.append(nmap_thread)
            nmap_thread.start()
            
            # Wait for all threads to complete
            for thread in threads:
                thread.join(timeout=15)  # Max 15 seconds wait
            
            # Store discovered devices for UI update
            self.discovered_devices = discovered_devices
            
            # Update UI in main thread
            from PyQt6.QtCore import QMetaObject, Q_ARG
            QMetaObject.invokeMethod(
                self, 
                "_update_device_count", 
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(int, len(discovered_devices))
            )
            
            self.log_message(f"Network scan completed. Found {len(discovered_devices)} devices.")
            
        except Exception as e:
            log_error(f"Error during network scan: {e}")
            self.log_message(f"Error during network scan: {e}")
        finally:
            # Re-enable scan button
            from PyQt6.QtCore import QMetaObject, Q_ARG
            QMetaObject.invokeMethod(
                self, 
                "_re_enable_scan_button", 
                Qt.ConnectionType.QueuedConnection
            )
    
    def _update_device_count(self, count: int):
        """Update device count display and populate device table (called from main thread)"""
        try:
            self.device_count_label.setText(f"Discovered Devices: {count}")
            
            # Update device table
            if hasattr(self, 'discovered_devices'):
                self.device_table.setRowCount(len(self.discovered_devices))
                
                for row, device in enumerate(self.discovered_devices):
                    # IP Address
                    ip_item = QTableWidgetItem(device.get('ip', '--'))
                    self.device_table.setItem(row, 0, ip_item)
                    
                    # Hostname
                    hostname_item = QTableWidgetItem(device.get('hostname', '--'))
                    self.device_table.setItem(row, 1, hostname_item)
                    
                    # Status
                    status_item = QTableWidgetItem(device.get('status', '--'))
                    self.device_table.setItem(row, 2, status_item)
                    
                    # Discovery Method
                    method_item = QTableWidgetItem(device.get('method', '--'))
                    self.device_table.setItem(row, 3, method_item)
                    
                    # MAC Address
                    mac_item = QTableWidgetItem(device.get('mac', '--'))
                    self.device_table.setItem(row, 4, mac_item)
                    
        except Exception as e:
            log_error(f"Error updating device count: {e}")
    
    def _re_enable_scan_button(self):
        """Re-enable scan button (called from main thread)"""
        try:
            self.scan_network_btn.setEnabled(True)
            self.scan_network_btn.setText("🔍 Scan Network")
        except Exception as e:
            log_error(f"Error re-enabling scan button: {e}")
    
    def toggle_auto_scan(self, enabled: bool):
        """Toggle automatic network scanning"""
        try:
            if enabled:
                self.log_message("Auto-scan enabled - scanning every 30 seconds")
                # Start auto-scan timer
                if not hasattr(self, 'auto_scan_timer'):
                    self.auto_scan_timer = QTimer()
                    self.auto_scan_timer.timeout.connect(self.scan_network_devices)
                self.auto_scan_timer.start(30000)  # 30 seconds
            else:
                self.log_message("Auto-scan disabled")
                if hasattr(self, 'auto_scan_timer'):
                    self.auto_scan_timer.stop()
        except Exception as e:
            log_error(f"Error toggling auto-scan: {e}")
    
    def closeEvent(self, event):
        """Handle dialog close event"""
        try:
            self.stop_monitoring()
            # Stop auto-scan if running
            if hasattr(self, 'auto_scan_timer'):
                self.auto_scan_timer.stop()
            event.accept()
        except Exception as e:
            log_error(f"Error closing performance monitor: {e}")
            event.accept()
