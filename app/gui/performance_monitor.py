#!/usr/bin/env python3
"""
Performance Monitor Dashboard
Real-time monitoring of system resources and application performance
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, 
    QProgressBar, QGroupBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QPushButton, QTextEdit, QSplitter
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QPalette
from typing import Dict, List, Optional
import psutil
import time
import threading
from datetime import datetime

from app.logs.logger import log_info, log_error

class PerformanceMonitor(QWidget):
    """Real-time performance monitoring dashboard"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
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
        
        # Set splitter proportions
        splitter.setSizes([400, 600])
        layout.addWidget(splitter)
        
        # Bottom panel - Performance Logs
        bottom_panel = self.create_performance_logs_panel()
        layout.addWidget(bottom_panel)
        
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
                border: 2px solid #404040;
                border-radius: 5px;
                text-align: center;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4caf50, stop:0.5 #ff9800, stop:1 #f44336);
                border-radius: 3px;
            }
        """)
        cpu_layout.addWidget(self.cpu_usage_bar)
        
        self.cpu_info_label = QLabel("CPU Info: Loading...")
        self.cpu_info_label.setStyleSheet("color: #cccccc; font-size: 10px;")
        cpu_layout.addWidget(self.cpu_info_label)
        
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
                border: 2px solid #404040;
                border-radius: 5px;
                text-align: center;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4caf50, stop:0.7 #ff9800, stop:1 #f44336);
                border-radius: 3px;
            }
        """)
        memory_layout.addWidget(self.memory_usage_bar)
        
        self.memory_info_label = QLabel("Memory Info: Loading...")
        self.memory_info_label.setStyleSheet("color: #cccccc; font-size: 10px;")
        memory_layout.addWidget(self.memory_info_label)
        
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
                border: 2px solid #404040;
                border-radius: 5px;
                text-align: center;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4caf50, stop:0.8 #ff9800, stop:1 #f44336);
                border-radius: 3px;
            }
        """)
        disk_layout.addWidget(self.disk_usage_bar)
        
        self.disk_info_label = QLabel("Disk Info: Loading...")
        self.disk_info_label.setStyleSheet("color: #cccccc; font-size: 10px;")
        disk_layout.addWidget(self.disk_info_label)
        
        disk_group.setLayout(disk_layout)
        layout.addWidget(disk_group)
        
        # Network Usage
        network_group = QGroupBox("🌐 Network Usage")
        network_layout = QGridLayout()
        
        self.network_sent_label = QLabel("Sent: 0 KB/s")
        self.network_sent_label.setStyleSheet("color: #4caf50; font-weight: bold;")
        network_layout.addWidget(self.network_sent_label, 0, 0)
        
        self.network_recv_label = QLabel("Received: 0 KB/s")
        self.network_recv_label.setStyleSheet("color: #2196f3; font-weight: bold;")
        network_layout.addWidget(self.network_recv_label, 0, 1)
        
        self.network_connections_label = QLabel("Connections: 0")
        self.network_connections_label.setStyleSheet("color: #ff9800; font-weight: bold;")
        network_layout.addWidget(self.network_connections_label, 1, 0, 1, 2)
        
        network_group.setLayout(network_layout)
        layout.addWidget(network_group)
        
        widget.setLayout(layout)
        return widget
        
    def create_process_monitor_panel(self) -> QWidget:
        """Create the process monitoring panel"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Process table
        self.process_table = QTableWidget()
        self.process_table.setColumnCount(6)
        self.process_table.setHorizontalHeaderLabels([
            "PID", "Name", "CPU %", "Memory %", "Status", "Threads"
        ])
        
        # Set table properties
        header = self.process_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.process_table.setAlternatingRowColors(True)
        self.process_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        
        layout.addWidget(self.process_table)
        
        # Process control buttons
        button_layout = QHBoxLayout()
        
        self.refresh_processes_btn = QPushButton("🔄 Refresh")
        self.refresh_processes_btn.clicked.connect(self.refresh_processes)
        self.kill_process_btn = QPushButton("💀 Kill Process")
        self.kill_process_btn.clicked.connect(self.kill_selected_process)
        
        button_layout.addWidget(self.refresh_processes_btn)
        button_layout.addWidget(self.kill_process_btn)
        
        layout.addLayout(button_layout)
        
        widget.setLayout(layout)
        return widget
        
    def create_performance_logs_panel(self) -> QWidget:
        """Create the performance logs panel"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Performance logs
        logs_group = QGroupBox("📝 Performance Logs")
        logs_layout = QVBoxLayout()
        
        self.logs_text = QTextEdit()
        self.logs_text.setReadOnly(True)
        self.logs_text.setMaximumHeight(150)
        self.logs_text.setStyleSheet("""
            QTextEdit {
                background-color: #1a1a1a;
                border: 1px solid #404040;
                color: #00ff00;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 10px;
            }
        """)
        logs_layout.addWidget(self.logs_text)
        
        # Log control buttons
        log_button_layout = QHBoxLayout()
        
        self.clear_logs_btn = QPushButton("🗑️ Clear Logs")
        self.clear_logs_btn.clicked.connect(self.clear_logs)
        self.export_logs_btn = QPushButton("📤 Export Logs")
        self.export_logs_btn.clicked.connect(self.export_logs)
        
        log_button_layout.addWidget(self.clear_logs_btn)
        log_button_layout.addWidget(self.export_logs_btn)
        
        logs_layout.addLayout(log_button_layout)
        logs_group.setLayout(logs_layout)
        layout.addWidget(logs_group)
        
        widget.setLayout(layout)
        return widget
        
    def start_monitoring(self):
        """Start the performance monitoring"""
        # Create monitoring timer
        self.monitor_timer = QTimer()
        self.monitor_timer.timeout.connect(self.update_performance_data)
        self.monitor_timer.start(1000)  # Update every second
        
        # Create process refresh timer
        self.process_timer = QTimer()
        self.process_timer.timeout.connect(self.refresh_processes)
        self.process_timer.start(5000)  # Refresh processes every 5 seconds
        
        # Initialize network monitoring
        self.last_network_io = psutil.net_io_counters()
        self.last_network_time = time.time()
        
        # Initial update
        self.update_performance_data()
        self.refresh_processes()
        
    def update_performance_data(self):
        """Update all performance data displays"""
        try:
            # CPU Usage
            cpu_percent = psutil.cpu_percent(interval=0.1)
            self.cpu_usage_bar.setValue(int(cpu_percent))
            
            cpu_info = psutil.cpu_count()
            self.cpu_info_label.setText(f"CPU Cores: {cpu_info} | Usage: {cpu_percent:.1f}%")
            
            # Memory Usage
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            self.memory_usage_bar.setValue(int(memory_percent))
            
            memory_used = memory.used / (1024**3)  # GB
            memory_total = memory.total / (1024**3)  # GB
            self.memory_info_label.setText(f"Used: {memory_used:.1f}GB / {memory_total:.1f}GB ({memory_percent:.1f}%)")
            
            # Disk Usage
            try:
                disk = psutil.disk_usage('/')
                disk_percent = (disk.used / disk.total) * 100
                self.disk_usage_bar.setValue(int(disk_percent))
                
                disk_used = disk.used / (1024**3)  # GB
                disk_total = disk.total / (1024**3)  # GB
                self.disk_info_label.setText(f"Used: {disk_used:.1f}GB / {disk_total:.1f}GB ({disk_percent:.1f}%)")
            except:
                self.disk_info_label.setText("Disk info unavailable")
            
            # Network Usage
            try:
                current_network_io = psutil.net_io_counters()
                current_time = time.time()
                
                time_diff = current_time - self.last_network_time
                if time_diff > 0:
                    bytes_sent = (current_network_io.bytes_sent - self.last_network_io.bytes_sent) / time_diff
                    bytes_recv = (current_network_io.bytes_recv - self.last_network_io.bytes_recv) / time_diff
                    
                    self.network_sent_label.setText(f"Sent: {bytes_sent/1024:.1f} KB/s")
                    self.network_recv_label.setText(f"Received: {bytes_recv/1024:.1f} KB/s")
                
                self.last_network_io = current_network_io
                self.last_network_time = current_time
                
                # Network connections
                connections = len(psutil.net_connections())
                self.network_connections_label.setText(f"Connections: {connections}")
                
            except:
                self.network_sent_label.setText("Sent: N/A")
                self.network_recv_label.setText("Received: N/A")
                self.network_connections_label.setText("Connections: N/A")
            
            # Add to logs
            self.add_log_entry(f"CPU: {cpu_percent:.1f}% | Memory: {memory_percent:.1f}% | Disk: {disk_percent:.1f}%")
            
        except Exception as e:
            log_error(f"Error updating performance data: {e}")
    
    def refresh_processes(self):
        """Refresh the process list"""
        try:
            # Get top processes by CPU usage
            processes = []
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'status', 'num_threads']):
                try:
                    proc_info = proc.info
                    if proc_info['cpu_percent'] > 0:  # Only show processes with CPU usage
                        processes.append(proc_info)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            # Sort by CPU usage
            processes.sort(key=lambda x: x['cpu_percent'], reverse=True)
            
            # Update table
            self.process_table.setRowCount(min(len(processes), 50))  # Show top 50
            
            for row, proc in enumerate(processes[:50]):
                self.process_table.setItem(row, 0, QTableWidgetItem(str(proc['pid'])))
                self.process_table.setItem(row, 1, QTableWidgetItem(proc['name'] or 'Unknown'))
                self.process_table.setItem(row, 2, QTableWidgetItem(f"{proc['cpu_percent']:.1f}"))
                self.process_table.setItem(row, 3, QTableWidgetItem(f"{proc['memory_percent']:.1f}"))
                self.process_table.setItem(row, 4, QTableWidgetItem(proc['status'] or 'Unknown'))
                self.process_table.setItem(row, 5, QTableWidgetItem(str(proc['num_threads'] or 0)))
                
                # Color code based on CPU usage
                if proc['cpu_percent'] > 50:
                    for col in range(6):
                        self.process_table.item(row, col).setBackground(QColor(255, 0, 0, 50))
                elif proc['cpu_percent'] > 20:
                    for col in range(6):
                        self.process_table.item(row, col).setBackground(QColor(255, 165, 0, 50))
                        
        except Exception as e:
            log_error(f"Error refreshing processes: {e}")
    
    def kill_selected_process(self):
        """Kill the selected process"""
        try:
            current_row = self.process_table.currentRow()
            if current_row >= 0:
                pid_item = self.process_table.item(current_row, 0)
                if pid_item:
                    pid = int(pid_item.text())
                    process_name = self.process_table.item(current_row, 1).text()
                    
                    # Confirm before killing
                    from PyQt6.QtWidgets import QMessageBox
                    reply = QMessageBox.question(
                        self, 
                        "Confirm Process Kill", 
                        f"Are you sure you want to kill process '{process_name}' (PID: {pid})?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                    )
                    
                    if reply == QMessageBox.StandardButton.Yes:
                        psutil.Process(pid).terminate()
                        self.add_log_entry(f"Killed process: {process_name} (PID: {pid})")
                        self.refresh_processes()
                        
        except Exception as e:
            log_error(f"Error killing process: {e}")
            self.add_log_entry(f"Error killing process: {str(e)}")
    
    def add_log_entry(self, message: str):
        """Add a log entry to the performance logs"""
        try:
            timestamp = datetime.now().strftime("%H:%M:%S")
            log_entry = f"[{timestamp}] {message}"
            
            self.logs_text.append(log_entry)
            
            # Keep only last 100 entries
            lines = self.logs_text.toPlainText().split('\n')
            if len(lines) > 100:
                self.logs_text.setPlainText('\n'.join(lines[-100:]))
                
        except Exception as e:
            log_error(f"Error adding log entry: {e}")
    
    def clear_logs(self):
        """Clear the performance logs"""
        self.logs_text.clear()
        self.add_log_entry("Logs cleared")
    
    def export_logs(self):
        """Export the performance logs to a file"""
        try:
            from PyQt6.QtWidgets import QFileDialog
            
            file_path, _ = QFileDialog.getSaveFileName(
                self, 
                "Export Performance Logs", 
                f"performance_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                "Text Files (*.txt)"
            )
            
            if file_path:
                with open(file_path, 'w') as f:
                    f.write(self.logs_text.toPlainText())
                
                self.add_log_entry(f"Logs exported to: {file_path}")
                
        except Exception as e:
            log_error(f"Error exporting logs: {e}")
            self.add_log_entry(f"Error exporting logs: {str(e)}")
    
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
                border: 1px solid #404040;
            }
        """)
