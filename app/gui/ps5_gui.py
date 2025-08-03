#!/usr/bin/env python3
"""
PS5 Network Management GUI
Specialized GUI for PS5 network monitoring and control
"""

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QTableWidget, QTableWidgetItem,
                             QGroupBox, QProgressBar, QTextEdit, QMessageBox,
                             QHeaderView, QTabWidget, QFrame, QSplitter)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QIcon, QPalette
import time
from typing import Dict, List, Optional

from app.ps5.ps5_network_tool import ps5_network_tool, PS5Device
from app.logs.logger import log_info, log_error

class PS5NetworkGUI(QWidget):
    """PS5-specific network management GUI"""
    
    # Signals
    ps5_device_blocked = pyqtSignal(str)  # ip
    ps5_device_unblocked = pyqtSignal(str)  # ip
    ps5_scan_completed = pyqtSignal(int)  # device_count
    
    def __init__(self, controller=None):
        super().__init__()
        self.controller = controller
        self.setup_ui()
        self.connect_signals()
        self.start_updates()
        
    def setup_ui(self):
        """Setup the PS5 network management UI"""
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        # Title
        title = QLabel("🎮 PS5 Network Management Tool")
        title.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #0070CC; margin: 10px;")
        layout.addWidget(title)
        
        # Create tab widget
        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)
        
        # Create tabs
        self.tab_widget.addTab(self.create_ps5_devices_tab(), "🎮 PS5 Devices")
        self.tab_widget.addTab(self.create_ps5_services_tab(), "🌐 PS5 Services")
        self.tab_widget.addTab(self.create_ps5_network_tab(), "📊 Network Stats")
        self.tab_widget.addTab(self.create_ps5_control_tab(), "🎛️ PS5 Control")
        
        # Status bar
        self.status_label = QLabel("🎮 PS5 Network Tool Ready")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold; padding: 5px;")
        layout.addWidget(self.status_label)
        
    def create_ps5_devices_tab(self) -> QWidget:
        """Create PS5 devices tab"""
        tab = QWidget()
        layout = QVBoxLayout()
        tab.setLayout(layout)
        
        # Control buttons
        button_layout = QHBoxLayout()
        
        self.scan_ps5_button = QPushButton("🔍 Scan for PS5")
        self.scan_ps5_button.clicked.connect(self.scan_ps5_devices)
        button_layout.addWidget(self.scan_ps5_button)
        
        self.start_monitoring_button = QPushButton("▶️ Start Monitoring")
        self.start_monitoring_button.clicked.connect(self.start_ps5_monitoring)
        button_layout.addWidget(self.start_monitoring_button)
        
        self.stop_monitoring_button = QPushButton("⏹️ Stop Monitoring")
        self.stop_monitoring_button.clicked.connect(self.stop_ps5_monitoring)
        button_layout.addWidget(self.stop_monitoring_button)
        
        layout.addLayout(button_layout)
        
        # PS5 devices table
        self.ps5_table = QTableWidget()
        self.ps5_table.setColumnCount(8)
        self.ps5_table.setHorizontalHeaderLabels([
            "Status", "IP Address", "MAC Address", "Hostname", "Device Type", 
            "Connection Quality", "Services", "Last Seen"
        ])
        self.ps5_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.ps5_table)
        
        # PS5 device actions
        action_layout = QHBoxLayout()
        
        self.block_selected_ps5_button = QPushButton("🚫 Block Selected PS5")
        self.block_selected_ps5_button.clicked.connect(self.block_selected_ps5)
        action_layout.addWidget(self.block_selected_ps5_button)
        
        self.unblock_selected_ps5_button = QPushButton("✅ Unblock Selected PS5")
        self.unblock_selected_ps5_button.clicked.connect(self.unblock_selected_ps5)
        action_layout.addWidget(self.unblock_selected_ps5_button)
        
        self.block_all_ps5_button = QPushButton("🚫 Block All PS5")
        self.block_all_ps5_button.clicked.connect(self.block_all_ps5_devices)
        action_layout.addWidget(self.block_all_ps5_button)
        
        self.unblock_all_ps5_button = QPushButton("✅ Unblock All PS5")
        self.unblock_all_ps5_button.clicked.connect(self.unblock_all_ps5_devices)
        action_layout.addWidget(self.unblock_all_ps5_button)
        
        layout.addLayout(action_layout)
        
        return tab
    
    def create_ps5_services_tab(self) -> QWidget:
        """Create PS5 services tab"""
        tab = QWidget()
        layout = QVBoxLayout()
        tab.setLayout(layout)
        
        # PS5 services info
        services_group = QGroupBox("🎮 PS5 Services")
        services_layout = QVBoxLayout()
        services_group.setLayout(services_layout)
        
        self.services_text = QTextEdit()
        self.services_text.setReadOnly(True)
        self.services_text.setFont(QFont("Consolas", 10))
        services_layout.addWidget(self.services_text)
        
        layout.addWidget(services_group)
        
        # Service control buttons
        service_buttons_layout = QHBoxLayout()
        
        self.refresh_services_button = QPushButton("🔄 Refresh Services")
        self.refresh_services_button.clicked.connect(self.refresh_ps5_services)
        service_buttons_layout.addWidget(self.refresh_services_button)
        
        self.block_psn_button = QPushButton("🚫 Block PSN")
        self.block_psn_button.clicked.connect(self.block_psn_services)
        service_buttons_layout.addWidget(self.block_psn_button)
        
        self.unblock_psn_button = QPushButton("✅ Unblock PSN")
        self.unblock_psn_button.clicked.connect(self.unblock_psn_services)
        service_buttons_layout.addWidget(self.unblock_psn_button)
        
        layout.addLayout(service_buttons_layout)
        
        return tab
    
    def create_ps5_network_tab(self) -> QWidget:
        """Create PS5 network statistics tab"""
        tab = QWidget()
        layout = QVBoxLayout()
        tab.setLayout(layout)
        
        # Network statistics
        stats_group = QGroupBox("📊 PS5 Network Statistics")
        stats_layout = QVBoxLayout()
        stats_group.setLayout(stats_layout)
        
        self.stats_text = QTextEdit()
        self.stats_text.setReadOnly(True)
        self.stats_text.setFont(QFont("Consolas", 10))
        stats_layout.addWidget(self.stats_text)
        
        layout.addWidget(stats_group)
        
        # Bandwidth usage
        bandwidth_group = QGroupBox("🌊 PS5 Bandwidth Usage")
        bandwidth_layout = QVBoxLayout()
        bandwidth_group.setLayout(bandwidth_layout)
        
        self.download_progress = QProgressBar()
        self.download_progress.setFormat("Download: %v KB/s")
        bandwidth_layout.addWidget(self.download_progress)
        
        self.upload_progress = QProgressBar()
        self.upload_progress.setFormat("Upload: %v KB/s")
        bandwidth_layout.addWidget(self.upload_progress)
        
        self.total_progress = QProgressBar()
        self.total_progress.setFormat("Total: %v KB/s")
        bandwidth_layout.addWidget(self.total_progress)
        
        layout.addWidget(bandwidth_group)
        
        return tab
    
    def create_ps5_control_tab(self) -> QWidget:
        """Create PS5 control tab"""
        tab = QWidget()
        layout = QVBoxLayout()
        tab.setLayout(layout)
        
        # PS5-specific controls
        controls_group = QGroupBox("🎛️ PS5 Network Controls")
        controls_layout = QVBoxLayout()
        controls_group.setLayout(controls_layout)
        
        # Connection quality control
        quality_layout = QHBoxLayout()
        quality_layout.addWidget(QLabel("Connection Quality:"))
        self.quality_label = QLabel("Unknown")
        self.quality_label.setStyleSheet("font-weight: bold; color: #0070CC;")
        quality_layout.addWidget(self.quality_label)
        controls_layout.addLayout(quality_layout)
        
        # Latency control
        latency_layout = QHBoxLayout()
        latency_layout.addWidget(QLabel("Latency:"))
        self.latency_label = QLabel("Unknown")
        self.latency_label.setStyleSheet("font-weight: bold; color: #0070CC;")
        latency_layout.addWidget(self.latency_label)
        controls_layout.addLayout(latency_layout)
        
        # PS5-specific blocking options
        blocking_group = QGroupBox("🚫 PS5-Specific Blocking")
        blocking_layout = QVBoxLayout()
        blocking_group.setLayout(blocking_layout)
        
        self.block_gaming_button = QPushButton("🎮 Block Gaming Services")
        self.block_gaming_button.clicked.connect(self.block_gaming_services)
        blocking_layout.addWidget(self.block_gaming_button)
        
        self.block_media_button = QPushButton("📺 Block Media Services")
        self.block_media_button.clicked.connect(self.block_media_services)
        blocking_layout.addWidget(self.block_media_button)
        
        self.block_updates_button = QPushButton("🔄 Block Updates")
        self.block_updates_button.clicked.connect(self.block_update_services)
        blocking_layout.addWidget(self.block_updates_button)
        
        self.block_remote_play_button = QPushButton("📱 Block Remote Play")
        self.block_remote_play_button.clicked.connect(self.block_remote_play)
        blocking_layout.addWidget(self.block_remote_play_button)
        
        controls_layout.addWidget(blocking_group)
        
        # Unblocking options
        unblocking_group = QGroupBox("✅ PS5-Specific Unblocking")
        unblocking_layout = QVBoxLayout()
        unblocking_group.setLayout(unblocking_layout)
        
        self.unblock_gaming_button = QPushButton("🎮 Unblock Gaming Services")
        self.unblock_gaming_button.clicked.connect(self.unblock_gaming_services)
        unblocking_layout.addWidget(self.unblock_gaming_button)
        
        self.unblock_media_button = QPushButton("📺 Unblock Media Services")
        self.unblock_media_button.clicked.connect(self.unblock_media_services)
        unblocking_layout.addWidget(self.unblock_media_button)
        
        self.unblock_updates_button = QPushButton("🔄 Unblock Updates")
        self.unblock_updates_button.clicked.connect(self.unblock_update_services)
        unblocking_layout.addWidget(self.unblock_updates_button)
        
        self.unblock_remote_play_button = QPushButton("📱 Unblock Remote Play")
        self.unblock_remote_play_button.clicked.connect(self.unblock_remote_play)
        unblocking_layout.addWidget(self.unblock_remote_play_button)
        
        controls_layout.addWidget(unblocking_group)
        
        layout.addWidget(controls_group)
        
        return tab
    
    def connect_signals(self):
        """Connect UI signals"""
        try:
            # Connect scan button
            if hasattr(self, 'scan_ps5_button'):
                self.scan_ps5_button.clicked.connect(self.scan_ps5_devices)
            
            # Connect monitoring buttons
            if hasattr(self, 'start_monitoring_button'):
                self.start_monitoring_button.clicked.connect(self.start_ps5_monitoring)
            
            if hasattr(self, 'stop_monitoring_button'):
                self.stop_monitoring_button.clicked.connect(self.stop_ps5_monitoring)
            
            # Connect blocking buttons
            if hasattr(self, 'block_selected_ps5_button'):
                self.block_selected_ps5_button.clicked.connect(self.block_selected_ps5)
            
            if hasattr(self, 'unblock_selected_ps5_button'):
                self.unblock_selected_ps5_button.clicked.connect(self.unblock_selected_ps5)
            
            if hasattr(self, 'block_all_ps5_button'):
                self.block_all_ps5_button.clicked.connect(self.block_all_ps5_devices)
            
            if hasattr(self, 'unblock_all_ps5_button'):
                self.unblock_all_ps5_button.clicked.connect(self.unblock_all_ps5_devices)
            
            # Connect service-specific blocking buttons
            if hasattr(self, 'block_gaming_button'):
                self.block_gaming_button.clicked.connect(self.block_gaming_services)
            
            if hasattr(self, 'block_media_button'):
                self.block_media_button.clicked.connect(self.block_media_services)
            
            if hasattr(self, 'block_updates_button'):
                self.block_updates_button.clicked.connect(self.block_update_services)
            
            if hasattr(self, 'block_remote_play_button'):
                self.block_remote_play_button.clicked.connect(self.block_remote_play)
            
            if hasattr(self, 'block_psn_button'):
                self.block_psn_button.clicked.connect(self.block_psn_services)
            
            # Connect service-specific unblocking buttons
            if hasattr(self, 'unblock_gaming_button'):
                self.unblock_gaming_button.clicked.connect(self.unblock_gaming_services)
            
            if hasattr(self, 'unblock_media_button'):
                self.unblock_media_button.clicked.connect(self.unblock_media_services)
            
            if hasattr(self, 'unblock_updates_button'):
                self.unblock_updates_button.clicked.connect(self.unblock_update_services)
            
            if hasattr(self, 'unblock_remote_play_button'):
                self.unblock_remote_play_button.clicked.connect(self.unblock_remote_play)
            
            if hasattr(self, 'unblock_psn_button'):
                self.unblock_psn_button.clicked.connect(self.unblock_psn_services)
            
            log_info("PS5 GUI signals connected successfully")
            
        except Exception as e:
            log_error(f"Error connecting PS5 GUI signals: {e}")
    
    def start_updates(self):
        """Start periodic updates"""
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_ui)
        self.update_timer.start(2000)  # Update every 2 seconds
    
    def update_ui(self):
        """Update UI elements"""
        self.refresh_ps5_table()
        self.refresh_ps5_services()
        self.refresh_ps5_stats()
    
    def scan_ps5_devices(self):
        """Scan for PS5 devices"""
        try:
            self.status_label.setText("🔍 Scanning for PS5 devices...")
            self.status_label.setStyleSheet("color: #FF9800; font-weight: bold;")
            
            devices = ps5_network_tool.scan_for_ps5_devices()
            
            self.status_label.setText(f"🎮 Found {len(devices)} PS5 devices")
            self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
            
            self.ps5_scan_completed.emit(len(devices))
            
        except Exception as e:
            log_error(f"Error scanning PS5 devices: {e}")
            self.status_label.setText("❌ PS5 scan failed")
            self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
    
    def start_ps5_monitoring(self):
        """Start PS5 monitoring"""
        try:
            ps5_network_tool.start_monitoring()
            self.status_label.setText("🎮 PS5 monitoring started")
            self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        except Exception as e:
            log_error(f"Error starting PS5 monitoring: {e}")
            self.status_label.setText("❌ Failed to start PS5 monitoring")
            self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
    
    def stop_ps5_monitoring(self):
        """Stop PS5 monitoring"""
        try:
            ps5_network_tool.stop_monitoring()
            self.status_label.setText("🎮 PS5 monitoring stopped")
            self.status_label.setStyleSheet("color: #FF9800; font-weight: bold;")
        except Exception as e:
            log_error(f"Error stopping PS5 monitoring: {e}")
            self.status_label.setText("❌ Failed to stop PS5 monitoring")
            self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
    
    def refresh_ps5_table(self):
        """Refresh PS5 devices table"""
        try:
            devices = ps5_network_tool.get_ps5_devices()
            self.ps5_table.setRowCount(len(devices))
            
            for row, device in enumerate(devices):
                # Status
                status_icon = "🟢" if device.is_online else "🔴"
                self.ps5_table.setItem(row, 0, QTableWidgetItem(status_icon))
                
                # IP Address
                self.ps5_table.setItem(row, 1, QTableWidgetItem(device.ip))
                
                # MAC Address
                self.ps5_table.setItem(row, 2, QTableWidgetItem(device.mac))
                
                # Hostname
                self.ps5_table.setItem(row, 3, QTableWidgetItem(device.hostname))
                
                # Device Type
                self.ps5_table.setItem(row, 4, QTableWidgetItem(device.device_type))
                
                # Connection Quality
                self.ps5_table.setItem(row, 5, QTableWidgetItem(device.connection_quality))
                
                # Services
                services_text = ", ".join(device.ps5_services) if device.ps5_services else "None"
                self.ps5_table.setItem(row, 6, QTableWidgetItem(services_text))
                
                # Last Seen
                last_seen = time.strftime("%H:%M:%S", time.localtime(device.last_seen))
                self.ps5_table.setItem(row, 7, QTableWidgetItem(last_seen))
                
        except Exception as e:
            log_error(f"Error refreshing PS5 table: {e}")
    
    def refresh_ps5_services(self):
        """Refresh PS5 services display"""
        try:
            devices = ps5_network_tool.get_online_ps5_devices()
            
            services_text = "🎮 PS5 Services Status:\n"
            services_text += "=" * 40 + "\n\n"
            
            for device in devices:
                services_text += f"📱 {device.ip} ({device.hostname})\n"
                services_text += f"   Type: {device.device_type}\n"
                services_text += f"   Quality: {device.connection_quality}\n"
                services_text += f"   Services: {', '.join(device.ps5_services) if device.ps5_services else 'None'}\n"
                services_text += f"   Bandwidth: {device.bandwidth_usage.get('total', 0):.2f} KB/s\n"
                services_text += "\n"
            
            if not devices:
                services_text += "No PS5 devices currently online\n"
            
            self.services_text.setText(services_text)
            
        except Exception as e:
            log_error(f"Error refreshing PS5 services: {e}")
    
    def refresh_ps5_stats(self):
        """Refresh PS5 network statistics"""
        try:
            stats = ps5_network_tool.get_ps5_network_stats()
            
            stats_text = "📊 PS5 Network Statistics:\n"
            stats_text += "=" * 40 + "\n\n"
            stats_text += f"Total PS5 Devices: {stats.get('total_ps5_devices', 0)}\n"
            stats_text += f"Online PS5 Devices: {stats.get('online_ps5_devices', 0)}\n"
            stats_text += f"Offline PS5 Devices: {stats.get('offline_ps5_devices', 0)}\n"
            stats_text += f"Local IP: {stats.get('local_ip', 'Unknown')}\n"
            stats_text += f"Local MAC: {stats.get('local_mac', 'Unknown')}\n\n"
            
            bandwidth = stats.get('total_bandwidth', {})
            stats_text += f"Total Download: {bandwidth.get('download', 0):.2f} KB/s\n"
            stats_text += f"Total Upload: {bandwidth.get('upload', 0):.2f} KB/s\n"
            stats_text += f"Total Bandwidth: {bandwidth.get('total', 0):.2f} KB/s\n\n"
            
            ps5_ips = stats.get('ps5_ips', [])
            if ps5_ips:
                stats_text += "PS5 IP Addresses:\n"
                for ip in ps5_ips:
                    stats_text += f"  • {ip}\n"
            
            self.stats_text.setText(stats_text)
            
            # Update progress bars
            total_bandwidth = bandwidth.get('total', 0)
            self.total_progress.setValue(min(int(total_bandwidth), 100))
            
            download_bandwidth = bandwidth.get('download', 0)
            self.download_progress.setValue(min(int(download_bandwidth), 100))
            
            upload_bandwidth = bandwidth.get('upload', 0)
            self.upload_progress.setValue(min(int(upload_bandwidth), 100))
            
        except Exception as e:
            log_error(f"Error refreshing PS5 stats: {e}")
    
    def block_selected_ps5(self):
        """Block selected PS5 device"""
        try:
            current_row = self.ps5_table.currentRow()
            if current_row < 0:
                QMessageBox.warning(self, "Warning", "Please select a PS5 device to block")
                return
            
            ip = self.ps5_table.item(current_row, 1).text()
            
            success = ps5_network_tool.block_ps5_device(ip)
            
            if success:
                self.status_label.setText(f"✅ Blocked PS5 device: {ip}")
                self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
                self.ps5_device_blocked.emit(ip)
            else:
                self.status_label.setText(f"❌ Failed to block PS5 device: {ip}")
                self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
                
        except Exception as e:
            log_error(f"Error blocking PS5 device: {e}")
            QMessageBox.critical(self, "Error", f"Failed to block PS5 device: {e}")
    
    def unblock_selected_ps5(self):
        """Unblock selected PS5 device"""
        try:
            current_row = self.ps5_table.currentRow()
            if current_row < 0:
                QMessageBox.warning(self, "Warning", "Please select a PS5 device to unblock")
                return
            
            ip = self.ps5_table.item(current_row, 1).text()
            
            success = ps5_network_tool.unblock_ps5_device(ip)
            
            if success:
                self.status_label.setText(f"✅ Unblocked PS5 device: {ip}")
                self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
                self.ps5_device_unblocked.emit(ip)
            else:
                self.status_label.setText(f"❌ Failed to unblock PS5 device: {ip}")
                self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
                
        except Exception as e:
            log_error(f"Error unblocking PS5 device: {e}")
            QMessageBox.critical(self, "Error", f"Failed to unblock PS5 device: {e}")
    
    def block_all_ps5_devices(self):
        """Block all PS5 devices"""
        try:
            reply = QMessageBox.question(self, "Confirm", 
                                       "Block all PS5 devices?",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            
            if reply == QMessageBox.StandardButton.Yes:
                results = ps5_network_tool.block_all_ps5_devices()
                success_count = sum(1 for success in results.values() if success)
                total_count = len(results)
                
                self.status_label.setText(f"✅ Blocked {success_count}/{total_count} PS5 devices")
                self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
                
        except Exception as e:
            log_error(f"Error blocking all PS5 devices: {e}")
            QMessageBox.critical(self, "Error", f"Failed to block all PS5 devices: {e}")
    
    def unblock_all_ps5_devices(self):
        """Unblock all PS5 devices"""
        try:
            reply = QMessageBox.question(self, "Confirm", 
                                       "Unblock all PS5 devices?",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            
            if reply == QMessageBox.StandardButton.Yes:
                results = ps5_network_tool.unblock_all_ps5_devices()
                success_count = sum(1 for success in results.values() if success)
                total_count = len(results)
                
                self.status_label.setText(f"✅ Unblocked {success_count}/{total_count} PS5 devices")
                self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
                
        except Exception as e:
            log_error(f"Error unblocking all PS5 devices: {e}")
            QMessageBox.critical(self, "Error", f"Failed to unblock all PS5 devices: {e}")
    
    # PS5 service-specific blocking methods
    def block_gaming_services(self):
        """Block PS5 gaming services"""
        try:
            from app.ps5.ps5_network_tool import ps5_network_tool
            success = ps5_network_tool.block_gaming_services()
            
            if success:
                self.status_label.setText("🎮 Gaming services blocked")
                self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
            else:
                self.status_label.setText("❌ Failed to block gaming services")
                self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
                
        except Exception as e:
            log_error(f"Error blocking gaming services: {e}")
            self.status_label.setText(f"❌ Error: {e}")
            self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
    
    def block_media_services(self):
        """Block PS5 media services"""
        try:
            from app.ps5.ps5_network_tool import ps5_network_tool
            success = ps5_network_tool.block_media_services()
            
            if success:
                self.status_label.setText("📺 Media services blocked")
                self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
            else:
                self.status_label.setText("❌ Failed to block media services")
                self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
                
        except Exception as e:
            log_error(f"Error blocking media services: {e}")
            self.status_label.setText(f"❌ Error: {e}")
            self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
    
    def block_update_services(self):
        """Block PS5 update services"""
        try:
            from app.ps5.ps5_network_tool import ps5_network_tool
            success = ps5_network_tool.block_update_services()
            
            if success:
                self.status_label.setText("🔄 Update services blocked")
                self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
            else:
                self.status_label.setText("❌ Failed to block update services")
                self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
                
        except Exception as e:
            log_error(f"Error blocking update services: {e}")
            self.status_label.setText(f"❌ Error: {e}")
            self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
    
    def block_remote_play(self):
        """Block PS5 remote play"""
        try:
            from app.ps5.ps5_network_tool import ps5_network_tool
            success = ps5_network_tool.block_remote_play()
            
            if success:
                self.status_label.setText("📱 Remote play blocked")
                self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
            else:
                self.status_label.setText("❌ Failed to block remote play")
                self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
                
        except Exception as e:
            log_error(f"Error blocking remote play: {e}")
            self.status_label.setText(f"❌ Error: {e}")
            self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
    
    def block_psn_services(self):
        """Block PSN services"""
        try:
            from app.ps5.ps5_network_tool import ps5_network_tool
            success = ps5_network_tool.block_psn_services()
            
            if success:
                self.status_label.setText("🌐 PSN services blocked")
                self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
            else:
                self.status_label.setText("❌ Failed to block PSN services")
                self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
                
        except Exception as e:
            log_error(f"Error blocking PSN services: {e}")
            self.status_label.setText(f"❌ Error: {e}")
            self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
    
    # PS5 service-specific unblocking methods
    def unblock_gaming_services(self):
        """Unblock PS5 gaming services"""
        try:
            from app.ps5.ps5_network_tool import ps5_network_tool
            success = ps5_network_tool.unblock_gaming_services()
            
            if success:
                self.status_label.setText("🎮 Gaming services unblocked")
                self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
            else:
                self.status_label.setText("❌ Failed to unblock gaming services")
                self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
                
        except Exception as e:
            log_error(f"Error unblocking gaming services: {e}")
            self.status_label.setText(f"❌ Error: {e}")
            self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
    
    def unblock_media_services(self):
        """Unblock PS5 media services"""
        try:
            from app.ps5.ps5_network_tool import ps5_network_tool
            success = ps5_network_tool.unblock_media_services()
            
            if success:
                self.status_label.setText("📺 Media services unblocked")
                self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
            else:
                self.status_label.setText("❌ Failed to unblock media services")
                self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
                
        except Exception as e:
            log_error(f"Error unblocking media services: {e}")
            self.status_label.setText(f"❌ Error: {e}")
            self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
    
    def unblock_update_services(self):
        """Unblock PS5 update services"""
        try:
            from app.ps5.ps5_network_tool import ps5_network_tool
            success = ps5_network_tool.unblock_update_services()
            
            if success:
                self.status_label.setText("🔄 Update services unblocked")
                self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
            else:
                self.status_label.setText("❌ Failed to unblock update services")
                self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
                
        except Exception as e:
            log_error(f"Error unblocking update services: {e}")
            self.status_label.setText(f"❌ Error: {e}")
            self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
    
    def unblock_remote_play(self):
        """Unblock PS5 remote play"""
        try:
            from app.ps5.ps5_network_tool import ps5_network_tool
            success = ps5_network_tool.unblock_remote_play()
            
            if success:
                self.status_label.setText("📱 Remote play unblocked")
                self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
            else:
                self.status_label.setText("❌ Failed to unblock remote play")
                self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
                
        except Exception as e:
            log_error(f"Error unblocking remote play: {e}")
            self.status_label.setText(f"❌ Error: {e}")
            self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
    
    def unblock_psn_services(self):
        """Unblock PSN services"""
        try:
            from app.ps5.ps5_network_tool import ps5_network_tool
            success = ps5_network_tool.unblock_psn_services()
            
            if success:
                self.status_label.setText("🌐 PSN services unblocked")
                self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
            else:
                self.status_label.setText("❌ Failed to unblock PSN services")
                self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
                
        except Exception as e:
            log_error(f"Error unblocking PSN services: {e}")
            self.status_label.setText(f"❌ Error: {e}")
            self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
    
    def set_controller(self, controller):
        """Set the controller for this component"""
        self.controller = controller
    
    def cleanup(self):
        """Cleanup resources"""
        try:
            if hasattr(self, 'update_timer'):
                self.update_timer.stop()
            ps5_network_tool.stop_monitoring()
        except Exception as e:
            log_error(f"Error during PS5 GUI cleanup: {e}") 