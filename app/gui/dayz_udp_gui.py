#!/usr/bin/env python3
"""
DayZ UDP Interruption GUI
Advanced GUI for managing DayZ server configurations and UDP interruption settings
Based on Laganator's functionality
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, 
    QPushButton, QSpinBox, QCheckBox, QComboBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QFrame, QGroupBox, QLineEdit,
    QMessageBox, QInputDialog, QProgressBar, QTextEdit
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor
from typing import List, Dict, Optional
from app.firewall.udp_port_interrupter import udp_port_interrupter, DayZServer
from app.logs.logger import log_info, log_error
import time

class DayZUDPGUI(QWidget):
    """Advanced GUI for DayZ UDP interruption management"""
    
    # Signals
    udp_interruption_started = pyqtSignal()
    udp_interruption_stopped = pyqtSignal()
    server_added = pyqtSignal(str)
    server_removed = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.udp_interrupter = udp_port_interrupter
        self.setup_ui()
        self.connect_signals()
        self.refresh_servers()
        
    def setup_ui(self):
        """Setup the main UI"""
        layout = QVBoxLayout()
        
        # Title
        title = QLabel("🎮 DayZ UDP Interruption Control")
        title.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        title.setStyleSheet("color: #ffffff; margin: 10px;")
        layout.addWidget(title)
        
        # Main control panel
        control_panel = self.create_control_panel()
        layout.addWidget(control_panel)
        
        # Server management panel
        server_panel = self.create_server_panel()
        layout.addWidget(server_panel)
        
        # Status panel
        status_panel = self.create_status_panel()
        layout.addWidget(status_panel)
        
        self.setLayout(layout)
        self.apply_styling()
        
    def create_control_panel(self) -> QWidget:
        """Create the main control panel"""
        panel = QGroupBox("🎯 UDP Interruption Control")
        layout = QGridLayout()
        
        # Drop Rate Control
        drop_rate_label = QLabel("Drop Rate (%):")
        self.drop_rate_spinbox = QSpinBox()
        self.drop_rate_spinbox.setRange(0, 100)
        self.drop_rate_spinbox.setValue(90)
        self.drop_rate_spinbox.setToolTip("90% = lag without disconnection, 100% = force disconnection")
        
        layout.addWidget(drop_rate_label, 0, 0)
        layout.addWidget(self.drop_rate_spinbox, 0, 1)
        
        # Timer Control
        timer_label = QLabel("Timer (seconds):")
        self.timer_spinbox = QSpinBox()
        self.timer_spinbox.setRange(0, 3600)
        self.timer_spinbox.setValue(0)
        self.timer_spinbox.setToolTip("0 = no timer, manual stop only")
        
        layout.addWidget(timer_label, 1, 0)
        layout.addWidget(self.timer_spinbox, 1, 1)
        
        # Traffic Control
        self.local_traffic_cb = QCheckBox("Affect Local Traffic")
        self.local_traffic_cb.setChecked(True)
        self.shared_traffic_cb = QCheckBox("Affect Shared Devices")
        self.shared_traffic_cb.setChecked(True)
        
        layout.addWidget(self.local_traffic_cb, 2, 0)
        layout.addWidget(self.shared_traffic_cb, 2, 1)
        
        # Server Selection
        server_label = QLabel("Target Server:")
        self.server_combo = QComboBox()
        self.server_combo.addItem("ALL Servers (0)", "all")
        self.refresh_server_combo()
        
        layout.addWidget(server_label, 3, 0)
        layout.addWidget(self.server_combo, 3, 1)
        
        # Control Buttons
        button_layout = QHBoxLayout()
        
        self.start_button = QPushButton("🚀 Start UDP Interruption")
        self.start_button.setStyleSheet("""
            QPushButton {
                background-color: #4caf50;
                color: white;
                border: 2px solid #388e3c;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 12px;
                min-height: 30px;
            }
            QPushButton:hover {
                background-color: #66bb6a;
                border-color: #4caf50;
            }
            QPushButton:pressed {
                background-color: #388e3c;
            }
        """)
        
        self.stop_button = QPushButton("🛑 Stop UDP Interruption")
        self.stop_button.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border: 2px solid #d32f2f;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 12px;
                min-height: 30px;
            }
            QPushButton:hover {
                background-color: #ef5350;
                border-color: #f44336;
            }
            QPushButton:pressed {
                background-color: #d32f2f;
            }
        """)
        
        button_layout.addWidget(self.start_button)
        button_layout.addWidget(self.stop_button)
        
        layout.addLayout(button_layout, 4, 0, 1, 2)
        
        panel.setLayout(layout)
        return panel
        
    def create_server_panel(self) -> QWidget:
        """Create the server management panel"""
        panel = QGroupBox("🌐 DayZ Server Management")
        layout = QVBoxLayout()
        
        # Server table
        self.server_table = QTableWidget()
        self.server_table.setColumnCount(5)
        self.server_table.setHorizontalHeaderLabels([
            "Server Name", "IP Address", "Port", "Drop Rate", "Local"
        ])
        
        # Set table properties
        header = self.server_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.server_table.setAlternatingRowColors(True)
        self.server_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        
        layout.addWidget(self.server_table)
        
        # Server management buttons
        button_layout = QHBoxLayout()
        
        self.add_server_btn = QPushButton("➕ Add Server")
        self.remove_server_btn = QPushButton("➖ Remove Server")
        self.edit_server_btn = QPushButton("✏️ Edit Server")
        self.auto_scan_btn = QPushButton("🔍 Auto-Scan DayZ Servers")
        
        button_layout.addWidget(self.add_server_btn)
        button_layout.addWidget(self.remove_server_btn)
        button_layout.addWidget(self.edit_server_btn)
        button_layout.addWidget(self.auto_scan_btn)
        
        layout.addLayout(button_layout)
        
        panel.setLayout(layout)
        return panel
        
    def create_status_panel(self) -> QWidget:
        """Create the status panel"""
        panel = QGroupBox("📊 Status Information")
        layout = QVBoxLayout()
        
        # Status labels
        self.status_label = QLabel("Status: Ready")
        self.status_label.setStyleSheet("color: #4caf50; font-weight: bold;")
        
        self.active_targets_label = QLabel("Active Targets: None")
        self.timer_label = QLabel("Timer: Not Active")
        self.drop_rate_label = QLabel("Current Drop Rate: 90%")
        
        layout.addWidget(self.status_label)
        layout.addWidget(self.active_targets_label)
        layout.addWidget(self.timer_label)
        layout.addWidget(self.drop_rate_label)
        
        # Progress bar for timer
        self.timer_progress = QProgressBar()
        self.timer_progress.setVisible(False)
        layout.addWidget(self.timer_progress)
        
        panel.setLayout(layout)
        return panel
        
    def connect_signals(self):
        """Connect all signals"""
        try:
            # Control signals
            self.start_button.clicked.connect(self.start_udp_interruption)
            self.stop_button.clicked.connect(self.stop_udp_interruption)
            
            # Server management signals
            self.add_server_btn.clicked.connect(self.add_server_dialog)
            self.remove_server_btn.clicked.connect(self.remove_server)
            self.edit_server_btn.clicked.connect(self.edit_server)
            self.auto_scan_btn.clicked.connect(self.auto_scan_servers)
            
            # Settings signals
            self.drop_rate_spinbox.valueChanged.connect(self.update_drop_rate)
            self.timer_spinbox.valueChanged.connect(self.update_timer)
            self.local_traffic_cb.toggled.connect(self.update_traffic_settings)
            self.shared_traffic_cb.toggled.connect(self.update_traffic_settings)
            
            # Update timer
            self.update_timer = QTimer()
            self.update_timer.timeout.connect(self.update_status)
            self.update_timer.start(2000)  # Update every 2 seconds to reduce memory usage
            
        except Exception as e:
            log_error(f"Failed to connect signals: {e}")
    
    def auto_scan_servers(self):
        """Automatically scan for DayZ servers on the network"""
        try:
            self.auto_scan_btn.setEnabled(False)
            self.auto_scan_btn.setText("🔍 Scanning...")
            
            # Show progress dialog
            progress = QMessageBox(self)
            progress.setIcon(QMessageBox.Icon.Information)
            progress.setWindowTitle("DayZ Server Scan")
            progress.setText("Scanning network for DayZ servers...\nThis may take a few minutes.")
            progress.setStandardButtons(QMessageBox.StandardButton.NoButton)
            progress.show()
            
            # Run scan in background
            import threading
            def scan_thread():
                try:
                    added_count = self.udp_interrupter.auto_detect_and_add_servers()
                    
                    # Update UI on main thread
                    self.auto_scan_btn.setText(f"🔍 Auto-Scan ({added_count} found)")
                    self.refresh_servers()
                    self.refresh_server_combo()
                    
                    progress.accept()
                    
                    if added_count > 0:
                        QMessageBox.information(self, "Scan Complete", 
                                              f"Found and added {added_count} DayZ servers!")
                    else:
                        QMessageBox.information(self, "Scan Complete", 
                                              "No new DayZ servers found on the network.")
                        
                except Exception as e:
                    log_error(f"Auto-scan failed: {e}")
                    progress.accept()
                    QMessageBox.critical(self, "Scan Failed", f"Failed to scan for DayZ servers: {e}")
                finally:
                    self.auto_scan_btn.setEnabled(True)
                    self.auto_scan_btn.setText("🔍 Auto-Scan DayZ Servers")
            
            scan_thread = threading.Thread(target=scan_thread, daemon=True)
            scan_thread.start()
            
        except Exception as e:
            log_error(f"Failed to start auto-scan: {e}")
            self.auto_scan_btn.setEnabled(True)
            self.auto_scan_btn.setText("🔍 Auto-Scan DayZ Servers")
            QMessageBox.critical(self, "Error", f"Failed to start auto-scan: {e}")
    
    def start_udp_interruption(self):
        """Start UDP interruption with current settings"""
        try:
            # Check admin privileges first
            if not self.udp_interrupter.is_admin():
                QMessageBox.critical(
                    self, "Administrator Required", 
                    "⚠️ UDP interruption requires Administrator privileges.\n\n"
                    "Please run the application as Administrator to use this feature."
                )
                return
            
            # Get target server
            server_data = self.server_combo.currentData()
            target_ips = []
            
            if server_data == "all":
                # Target all servers
                servers = self.udp_interrupter.get_servers()
                for server in servers:
                    target_ips.append(server.ip)
            else:
                # Target specific server
                target_ips = [server_data]
            
            if not target_ips:
                QMessageBox.warning(self, "No Targets", "Please add servers or select 'ALL Servers'")
                return
            
            # Get settings
            drop_rate = self.drop_rate_spinbox.value()
            timer_duration = self.timer_spinbox.value()
            
            # Start UDP interruption
            success = self.udp_interrupter.start_udp_interruption(
                target_ips=target_ips,
                drop_rate=drop_rate,
                duration=timer_duration
            )
            
            if success:
                self.update_status()
                self.udp_interruption_started.emit()  # Emit signal
                log_info(f"[SUCCESS] UDP interruption started on {len(target_ips)} targets")
                QMessageBox.information(
                    self, "UDP Interruption Started",
                    f"✅ UDP interruption started successfully!\n\n"
                    f"Targets: {len(target_ips)} servers\n"
                    f"Drop Rate: {drop_rate}%\n"
                    f"Duration: {timer_duration}s (0 = manual stop)\n\n"
                    f"Firewall rules have been created to block UDP traffic."
                )
            else:
                QMessageBox.critical(self, "Error", "Failed to start UDP interruption")
                log_error("Failed to start UDP interruption")
                
        except Exception as e:
            log_error(f"Error starting UDP interruption: {e}")
            QMessageBox.critical(self, "Error", f"Failed to start UDP interruption: {e}")
    
    def stop_udp_interruption(self):
        """Stop UDP interruption"""
        try:
            success = self.udp_interrupter.stop_udp_interruption()
            
            if success:
                self.update_status()
                self.udp_interruption_stopped.emit()  # Emit signal
                log_info("[SUCCESS] UDP interruption stopped")
                QMessageBox.information(
                    self, "UDP Interruption Stopped",
                    "✅ UDP interruption stopped successfully!\n\n"
                    "Firewall rules have been removed."
                )
            else:
                QMessageBox.warning(self, "Warning", "Failed to stop UDP interruption")
                log_error("Failed to stop UDP interruption")
                
        except Exception as e:
            log_error(f"Error stopping UDP interruption: {e}")
            QMessageBox.critical(self, "Error", f"Failed to stop UDP interruption: {e}")
    
    def add_server_dialog(self):
        """Show dialog to add a new server"""
        try:
            name, ok = QInputDialog.getText(self, "Add DayZ Server", "Server Name:")
            if not ok or not name:
                return
                
            ip, ok = QInputDialog.getText(self, "Add DayZ Server", "IP Address:")
            if not ok or not ip:
                return
                
            port, ok = QInputDialog.getInt(self, "Add DayZ Server", "Port:", 2302, 1, 65535)
            if not ok:
                return
                
            drop_rate, ok = QInputDialog.getInt(self, "Add DayZ Server", "Drop Rate (%):", 90, 0, 100)
            if not ok:
                return
            
            # Add server
            success = self.udp_interrupter.add_server(name, ip, port, drop_rate)
            
            if success:
                self.refresh_servers()
                self.refresh_server_combo()
                self.server_added.emit(name)
                QMessageBox.information(self, "Success", f"Added server: {name}")
            else:
                QMessageBox.warning(self, "Error", "Failed to add server")
                
        except Exception as e:
            log_error(f"Failed to add server: {e}")
            QMessageBox.critical(self, "Error", f"Failed to add server: {e}")
    
    def remove_server(self):
        """Remove selected server"""
        try:
            current_row = self.server_table.currentRow()
            if current_row < 0:
                QMessageBox.warning(self, "Warning", "Please select a server to remove")
                return
                
            server_name = self.server_table.item(current_row, 0).text()
            
            reply = QMessageBox.question(
                self, "Confirm Removal", 
                f"Are you sure you want to remove server '{server_name}'?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                success = self.udp_interrupter.remove_server(server_name)
                
                if success:
                    self.refresh_servers()
                    self.refresh_server_combo()
                    self.server_removed.emit(server_name)
                    QMessageBox.information(self, "Success", f"Removed server: {server_name}")
                else:
                    QMessageBox.warning(self, "Error", "Failed to remove server")
                    
        except Exception as e:
            log_error(f"Failed to remove server: {e}")
            QMessageBox.critical(self, "Error", f"Failed to remove server: {e}")
    
    def edit_server(self):
        """Edit selected server"""
        try:
            current_row = self.server_table.currentRow()
            if current_row < 0:
                QMessageBox.warning(self, "Warning", "Please select a server to edit")
                return
                
            # Get current server data
            name = self.server_table.item(current_row, 0).text()
            ip = self.server_table.item(current_row, 1).text()
            port = int(self.server_table.item(current_row, 2).text())
            drop_rate = int(self.server_table.item(current_row, 3).text())
            
            # Show edit dialog
            new_name, ok = QInputDialog.getText(self, "Edit DayZ Server", "Server Name:", text=name)
            if not ok:
                return
                
            new_ip, ok = QInputDialog.getText(self, "Edit DayZ Server", "IP Address:", text=ip)
            if not ok:
                return
                
            new_port, ok = QInputDialog.getInt(self, "Edit DayZ Server", "Port:", port, 1, 65535)
            if not ok:
                return
                
            new_drop_rate, ok = QInputDialog.getInt(self, "Edit DayZ Server", "Drop Rate (%):", drop_rate, 0, 100)
            if not ok:
                return
            
            # Remove old server and add new one
            self.udp_interrupter.remove_server(name)
            success = self.udp_interrupter.add_server(new_name, new_ip, new_port, new_drop_rate)
            
            if success:
                self.refresh_servers()
                self.refresh_server_combo()
                QMessageBox.information(self, "Success", f"Updated server: {new_name}")
            else:
                QMessageBox.warning(self, "Error", "Failed to update server")
                
        except Exception as e:
            log_error(f"Failed to edit server: {e}")
            QMessageBox.critical(self, "Error", f"Failed to edit server: {e}")
    
    def refresh_servers(self):
        """Refresh the server table"""
        try:
            servers = self.udp_interrupter.get_servers()
            self.server_table.setRowCount(len(servers))
            
            for row, server in enumerate(servers):
                self.server_table.setItem(row, 0, QTableWidgetItem(server.name))
                self.server_table.setItem(row, 1, QTableWidgetItem(server.ip))
                self.server_table.setItem(row, 2, QTableWidgetItem(str(server.port)))
                self.server_table.setItem(row, 3, QTableWidgetItem(f"{server.drop_rate}%"))
                self.server_table.setItem(row, 4, QTableWidgetItem("Yes" if server.local else "No"))
                
        except Exception as e:
            log_error(f"Failed to refresh servers: {e}")
    
    def refresh_server_combo(self):
        """Refresh the server combo box"""
        try:
            self.server_combo.clear()
            self.server_combo.addItem("ALL Servers (0)", "all")
            
            servers = self.udp_interrupter.get_servers()
            for server in servers:
                self.server_combo.addItem(f"{server.name} ({server.ip}:{server.port})", server.ip)
                
        except Exception as e:
            log_error(f"Failed to refresh server combo: {e}")
    
    def update_drop_rate(self, value: int):
        """Update drop rate setting"""
        try:
            self.udp_interrupter.set_drop_rate(value)
            self.drop_rate_label.setText(f"Current Drop Rate: {value}%")
        except Exception as e:
            log_error(f"Failed to update drop rate: {e}")
    
    def update_timer(self, value: int):
        """Update timer setting"""
        try:
            self.udp_interrupter.set_timer_duration(value)
        except Exception as e:
            log_error(f"Failed to update timer: {e}")
    
    def update_traffic_settings(self):
        """Update traffic settings"""
        try:
            self.udp_interrupter.local_traffic = self.local_traffic_cb.isChecked()
            self.udp_interrupter.shared_traffic = self.shared_traffic_cb.isChecked()
        except Exception as e:
            log_error(f"Failed to update traffic settings: {e}")
    
    def update_status(self):
        """Update the status display"""
        try:
            status = self.udp_interrupter.get_status()
            
            if status.get("is_running", False):
                self.status_label.setText("Status: ACTIVE")
                self.status_label.setStyleSheet("color: #ff4444; font-weight: bold;")
                
                targets = status.get("active_targets", [])
                if targets:
                    self.active_targets_label.setText(f"Active Targets: {len(targets)} servers")
                else:
                    self.active_targets_label.setText("Active Targets: None")
                    
                drop_rate = status.get("drop_rate", 0)
                self.drop_rate_label.setText(f"Current Drop Rate: {drop_rate}%")
                
                if status.get("timer_active", False):
                    remaining = status.get("timer_duration", 0) - int(time.time() % 60)
                    self.timer_label.setText(f"Timer: {remaining}s remaining")
                    self.timer_progress.setVisible(True)
                    self.timer_progress.setValue(remaining)
                else:
                    self.timer_label.setText("Timer: Not Active")
                    self.timer_progress.setVisible(False)
                    
                # Show admin status
                if status.get("is_admin", False):
                    self.status_label.setText("Status: ACTIVE (Admin)")
                else:
                    self.status_label.setText("Status: ACTIVE (Limited)")
                    
            else:
                self.status_label.setText("Status: Ready")
                self.status_label.setStyleSheet("color: #4caf50; font-weight: bold;")
                self.active_targets_label.setText("Active Targets: None")
                self.timer_label.setText("Timer: Not Active")
                self.timer_progress.setVisible(False)
                
                # Show admin requirement
                if not status.get("is_admin", False):
                    self.status_label.setText("Status: Ready (Admin Required)")
                    self.status_label.setStyleSheet("color: #ff9800; font-weight: bold;")
                    
        except Exception as e:
            log_error(f"Error updating status: {e}")
            self.status_label.setText("Status: Error")
            self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
    
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
            QSpinBox {
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
            QComboBox {
                background-color: #2a2a2a;
                border: 1px solid #404040;
                border-radius: 3px;
                padding: 5px;
                color: #ffffff;
                min-height: 20px;
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
        """) 