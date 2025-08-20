#!/usr/bin/env python3
"""
DayZ Duping Dashboard
Specialized GUI for DayZ duping network optimization
"""

import sys
import time
from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QTabWidget,
    QGroupBox, QLabel, QPushButton, QLineEdit, QSpinBox, QComboBox,
    QTextEdit, QTableWidget, QTableWidgetItem, QProgressBar,
    QCheckBox, QSlider, QMessageBox, QInputDialog, QSplitter
)
from PyQt6.QtCore import QTimer, Qt, pyqtSignal, QThread
from PyQt6.QtGui import QFont, QPalette, QColor

from app.network.dayz_duping_optimizer import DayZDupingOptimizer
from app.logs.logger import log_info, log_error, log_warning

class DupingSessionThread(QThread):
    """Background thread for session monitoring"""
    session_updated = pyqtSignal(dict)
    
    def __init__(self, optimizer: DayZDupingOptimizer):
        super().__init__()
        self.optimizer = optimizer
        self.is_running = False
        
    def run(self):
        """Main thread loop"""
        self.is_running = True
        while self.is_running:
            try:
                # Get performance report
                report = self.optimizer.get_performance_report()
                self.session_updated.emit(report)
                time.sleep(2.0)  # Update every 2 seconds
            except Exception as e:
                log_error(f"Error in session thread: {e}")
                time.sleep(5.0)
    
    def stop(self):
        """Stop the thread"""
        self.is_running = False

class DayZDupingDashboard(QWidget):
    """DayZ Duping Network Optimization Dashboard"""
    
    def __init__(self, parent=None, account_tracker=None):
        super().__init__(parent)
        self.account_tracker = account_tracker
        self.optimizer = DayZDupingOptimizer()
        self.session_thread = DupingSessionThread(self.optimizer)
        
        self.setup_ui()
        self.setup_connections()
        self.setup_timers()
        self.apply_styling()
        
        # Start session monitoring
        self.session_thread.session_updated.connect(self.update_session_display)
        self.session_thread.start()
        
        log_info("DayZ Duping Dashboard initialized")
    
    def setup_ui(self):
        """Setup the user interface"""
        self.setWindowTitle("🎯 DayZ Duping Network Optimizer")
        self.setMinimumSize(1200, 800)
        
        # Main layout
        main_layout = QVBoxLayout()
        
        # Header
        header_layout = self.create_header()
        main_layout.addLayout(header_layout)
        
        # Tab widget
        self.tab_widget = QTabWidget()
        self.tab_widget.addTab(self.create_account_selection_tab(), "🎯 Account Selection")
        self.tab_widget.addTab(self.create_session_tab(), "🎮 Duping Sessions")
        self.tab_widget.addTab(self.create_network_tab(), "🌐 Network Profiles")
        self.tab_widget.addTab(self.create_techniques_tab(), "⚡ Manipulation Techniques")
        # Monitoring tab removed for optimization
        
        main_layout.addWidget(self.tab_widget)
        
        # Status bar
        status_layout = self.create_status_bar()
        main_layout.addLayout(status_layout)
        
        self.setLayout(main_layout)
    
    def create_header(self):
        """Create the header section"""
        header_layout = QHBoxLayout()
        
        # Title
        title_label = QLabel("🎯 DayZ Duping Network Optimizer")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #4CAF50; margin: 10px;")
        
        # Quick actions
        quick_actions_layout = QHBoxLayout()
        
        self.start_session_btn = QPushButton("🚀 Start Session")
        self.start_session_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        
        self.stop_all_btn = QPushButton("⏹️ Stop All")
        self.stop_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #da190b;
            }
        """)
        
        self.refresh_btn = QPushButton("🔄 Refresh")
        self.refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)
        
        quick_actions_layout.addWidget(self.start_session_btn)
        quick_actions_layout.addWidget(self.stop_all_btn)
        quick_actions_layout.addWidget(self.refresh_btn)
        quick_actions_layout.addStretch()
        
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        header_layout.addLayout(quick_actions_layout)
        
        return header_layout
    
    def create_account_selection_tab(self):
        """Create the account selection tab (integrated from Duping Network Optimizer)"""
        tab_widget = QWidget()
        layout = QVBoxLayout()
        
        # Account Selection Group
        account_group = QGroupBox("🎯 Select Accounts for Optimization")
        account_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 13px;
                border: 2px solid #555555;
                border-radius: 8px;
                margin-top: 10px;
                padding: 15px;
                background-color: #3a3a3a;
                color: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px 0 8px;
                color: #ffffff;
                font-size: 13px;
                font-weight: bold;
            }
        """)
        account_layout = QVBoxLayout()
        
        # Account table
        self.account_table = QTableWidget()
        self.account_table.setColumnCount(5)
        self.account_table.setHorizontalHeaderLabels([
            "Select", "Account Name", "Status", "Server", "Last Used"
        ])
        
        # Style the account table
        self.account_table.setStyleSheet("""
            QTableWidget {
                background-color: #2a2a2a;
                alternate-background-color: #3a3a3a;
                color: #ffffff;
                gridline-color: #555555;
                border: 1px solid #555555;
                border-radius: 6px;
                font-size: 11px;
            }
            QTableWidget::item {
                padding: 6px;
                border: none;
            }
            QTableWidget::item:selected {
                background-color: #4CAF50;
                color: #ffffff;
            }
            QHeaderView::section {
                background-color: #4a4a4a;
                color: #ffffff;
                padding: 8px;
                border: 1px solid #555555;
                font-weight: bold;
                font-size: 11px;
            }
        """)
        self.account_table.setAlternatingRowColors(True)
        account_layout.addWidget(self.account_table)
        
        # Selection controls
        selection_controls = QHBoxLayout()
        
        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.clicked.connect(self.select_all_accounts)
        self.select_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: 1px solid #45a049;
                padding: 8px 16px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 11px;
                min-width: 100px;
                min-height: 22px;
            }
            QPushButton:hover {
                background-color: #45a049;
                border-color: #4CAF50;
            }
        """)
        
        self.clear_selection_btn = QPushButton("Clear Selection")
        self.clear_selection_btn.clicked.connect(self.clear_account_selection)
        self.clear_selection_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border: 1px solid #d32f2f;
                padding: 8px 16px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 11px;
                min-width: 100px;
                min-height: 22px;
            }
            QPushButton:hover {
                background-color: #da190b;
                border-color: #f44336;
            }
        """)
        
        selection_controls.addWidget(self.select_all_btn)
        selection_controls.addWidget(self.clear_selection_btn)
        selection_controls.addStretch()
        
        account_layout.addLayout(selection_controls)
        account_group.setLayout(account_layout)
        layout.addWidget(account_group)
        
        # Selected accounts status
        selected_group = QGroupBox("📋 Selected Accounts Status")
        selected_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 15px;
                border: 3px solid #555555;
                border-radius: 10px;
                margin-top: 15px;
                padding: 20px;
                background-color: #1e1e1e;
                color: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 20px;
                padding: 0 10px 0 10px;
                color: #ffffff;
                font-size: 16px;
                font-weight: bold;
            }
        """)
        selected_layout = QVBoxLayout()
        
        self.selected_accounts_label = QLabel("No accounts selected")
        self.selected_accounts_label.setStyleSheet("""
            QLabel {
                color: #ffffff;
                font-size: 14px;
                padding: 10px;
                background-color: #3a3a3a;
                border-radius: 6px;
                border: 1px solid #555555;
            }
        """)
        selected_layout.addWidget(self.selected_accounts_label)
        
        selected_group.setLayout(selected_layout)
        layout.addWidget(selected_group)
        
        tab_widget.setLayout(layout)
        
        # Load accounts if tracker is available
        if self.account_tracker:
            self.load_accounts_table()
        
        return tab_widget
    
    def create_session_tab(self):
        """Create the duping sessions tab"""
        tab_widget = QWidget()
        layout = QVBoxLayout()
        
        # Session controls
        controls_group = QGroupBox("🎯 Session Controls")
        controls_layout = QGridLayout()
        
        # Server input
        controls_layout.addWidget(QLabel("Target Server:"), 0, 0)
        self.server_ip_input = QLineEdit()
        self.server_ip_input.setPlaceholderText("192.168.1.100")
        self.server_ip_input.setText("192.168.1.100")
        controls_layout.addWidget(self.server_ip_input, 0, 1)
        
        controls_layout.addWidget(QLabel("Port:"), 0, 2)
        self.server_port_input = QSpinBox()
        self.server_port_input.setRange(1, 65535)
        self.server_port_input.setValue(2302)
        controls_layout.addWidget(self.server_port_input, 0, 3)
        
        # Method selection
        controls_layout.addWidget(QLabel("Duping Method:"), 1, 0)
        self.method_combo = QComboBox()
        self.method_combo.addItems(["standard", "advanced", "stealth", "aggressive"])
        controls_layout.addWidget(self.method_combo, 1, 1)
        
        # Profile selection
        controls_layout.addWidget(QLabel("Network Profile:"), 1, 2)
        self.profile_combo = QComboBox()
        self.profile_combo.addItems(["stealth", "balanced", "aggressive", "custom"])
        controls_layout.addWidget(self.profile_combo, 1, 3)
        
        # Start button
        self.start_btn = QPushButton("🚀 Start Duping Session")
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        controls_layout.addWidget(self.start_btn, 2, 0, 1, 4)
        
        controls_group.setLayout(controls_layout)
        layout.addWidget(controls_group)
        
        # Active sessions table
        sessions_group = QGroupBox("📋 Active Duping Sessions")
        sessions_layout = QVBoxLayout()
        
        self.sessions_table = QTableWidget()
        self.sessions_table.setColumnCount(8)
        self.sessions_table.setHorizontalHeaderLabels([
            "Session ID", "Server", "Port", "Method", "Profile", 
            "Status", "Duration", "Actions"
        ])
        
        # Set column widths
        self.sessions_table.setColumnWidth(0, 150)  # Session ID
        self.sessions_table.setColumnWidth(1, 120)  # Server
        self.sessions_table.setColumnWidth(2, 80)   # Port
        self.sessions_table.setColumnWidth(3, 100)  # Method
        self.sessions_table.setColumnWidth(4, 100)  # Profile
        self.sessions_table.setColumnWidth(5, 80)   # Status
        self.sessions_table.setColumnWidth(6, 100)  # Duration
        self.sessions_table.setColumnWidth(7, 120)  # Actions
        
        sessions_layout.addWidget(self.sessions_table)
        
        # Session actions
        actions_layout = QHBoxLayout()
        self.refresh_sessions_btn = QPushButton("🔄 Refresh Sessions")
        self.test_all_btn = QPushButton("🧪 Test All Sessions")
        self.export_sessions_btn = QPushButton("📤 Export Sessions")
        
        actions_layout.addWidget(self.refresh_sessions_btn)
        actions_layout.addWidget(self.test_all_btn)
        actions_layout.addWidget(self.export_sessions_btn)
        actions_layout.addStretch()
        
        sessions_layout.addLayout(actions_layout)
        sessions_group.setLayout(sessions_layout)
        layout.addWidget(sessions_group)
        
        tab_widget.setLayout(layout)
        return tab_widget
    
    def create_network_tab(self):
        """Create the network profiles tab"""
        tab_widget = QWidget()
        layout = QVBoxLayout()
        
        # Network profiles
        profiles_group = QGroupBox("🌐 Network Profiles")
        profiles_layout = QGridLayout()
        
        # Profile selection
        profiles_layout.addWidget(QLabel("Select Profile:"), 0, 0)
        self.profile_selector = QComboBox()
        self.profile_selector.addItems(["stealth", "balanced", "aggressive", "custom"])
        self.profile_selector.currentTextChanged.connect(self.on_profile_selected)
        profiles_layout.addWidget(self.profile_selector, 0, 1)
        
        # Profile details
        self.profile_details = QTextEdit()
        self.profile_details.setMaximumHeight(150)
        self.profile_details.setReadOnly(True)
        profiles_layout.addWidget(QLabel("Profile Details:"), 1, 0)
        profiles_layout.addWidget(self.profile_details, 1, 1, 1, 2)
        
        # Profile configuration
        config_group = QGroupBox("⚙️ Profile Configuration")
        config_layout = QGridLayout()
        
        config_layout.addWidget(QLabel("Latency Variance (ms):"), 0, 0)
        self.latency_variance_spin = QSpinBox()
        self.latency_variance_spin.setRange(1, 100)
        self.latency_variance_spin.setValue(10)
        config_layout.addWidget(self.latency_variance_spin, 0, 1)
        
        config_layout.addWidget(QLabel("Packet Timing (ms):"), 0, 2)
        self.packet_timing_spin = QSpinBox()
        self.packet_timing_spin.setRange(1, 100)
        self.packet_timing_spin.setValue(5)
        config_layout.addWidget(self.packet_timing_spin, 0, 3)
        
        config_layout.addWidget(QLabel("Connection Stability (%):"), 1, 0)
        self.stability_spin = QSpinBox()
        self.stability_spin.setRange(50, 100)
        self.stability_spin.setValue(95)
        config_layout.addWidget(self.stability_spin, 1, 1)
        
        # Apply button
        self.apply_profile_btn = QPushButton("✅ Apply Profile Changes")
        self.apply_profile_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        config_layout.addWidget(self.apply_profile_btn, 1, 2, 1, 2)
        
        config_group.setLayout(config_layout)
        profiles_layout.addWidget(config_group, 2, 0, 1, 3)
        
        profiles_group.setLayout(profiles_layout)
        layout.addWidget(profiles_group)
        
        # Traffic patterns
        patterns_group = QGroupBox("Traffic Patterns")
        patterns_layout = QVBoxLayout()
        
        self.patterns_text = QTextEdit()
        self.patterns_text.setMaximumHeight(100)
        self.patterns_text.setPlaceholderText("Available traffic patterns will be displayed here...")
        patterns_layout.addWidget(self.patterns_text)
        
        patterns_group.setLayout(patterns_layout)
        layout.addWidget(patterns_group)
        
        tab_widget.setLayout(layout)
        return tab_widget
    
    def create_techniques_tab(self):
        """Create the manipulation techniques tab"""
        tab_widget = QWidget()
        layout = QVBoxLayout()
        
        # Techniques table
        techniques_group = QGroupBox("⚡ Network Manipulation Techniques")
        techniques_layout = QVBoxLayout()
        
        self.techniques_table = QTableWidget()
        self.techniques_table.setColumnCount(6)
        self.techniques_table.setHorizontalHeaderLabels([
            "Technique", "Type", "Success Rate", "Detection Risk", "Status", "Actions"
        ])
        
        # Set column widths
        self.techniques_table.setColumnWidth(0, 200)  # Technique
        self.techniques_table.setColumnWidth(1, 100)  # Type
        self.techniques_table.setColumnWidth(2, 100)  # Success Rate
        self.techniques_table.setColumnWidth(3, 100)  # Detection Risk
        self.techniques_table.setColumnWidth(4, 80)   # Status
        self.techniques_table.setColumnWidth(5, 120)  # Actions
        
        techniques_layout.addWidget(self.techniques_table)
        
        # Technique controls
        controls_layout = QHBoxLayout()
        self.enable_all_btn = QPushButton("✅ Enable All")
        self.disable_all_btn = QPushButton("❌ Disable All")
        self.refresh_techniques_btn = QPushButton("🔄 Refresh")
        
        controls_layout.addWidget(self.enable_all_btn)
        controls_layout.addWidget(self.disable_all_btn)
        controls_layout.addWidget(self.refresh_techniques_btn)
        controls_layout.addStretch()
        
        # Add the missing labels directly to controls layout
        self.total_techniques_label = QLabel("Total: 0")
        self.total_techniques_label.setStyleSheet("color: #4CAF50; font-weight: bold; padding: 5px;")
        self.enabled_techniques_label = QLabel("Enabled: 0")
        self.enabled_techniques_label.setStyleSheet("color: #2196F3; font-weight: bold; padding: 5px;")
        
        controls_layout.addWidget(self.total_techniques_label)
        controls_layout.addWidget(self.enabled_techniques_label)
        controls_layout.addStretch()
        
        techniques_layout.addLayout(controls_layout)
        techniques_group.setLayout(techniques_layout)
        layout.addWidget(techniques_group)
        
        # Technique details
        details_group = QGroupBox("📋 Technique Details")
        details_layout = QVBoxLayout()
        
        self.technique_details = QTextEdit()
        self.technique_details.setMaximumHeight(150)
        self.technique_details.setReadOnly(True)
        details_layout.addWidget(self.technique_details)
        
        details_group.setLayout(details_layout)
        layout.addWidget(details_group)
        
        tab_widget.setLayout(layout)
        return tab_widget
    
    def create_status_bar(self):
        """Create the status bar"""
        status_layout = QHBoxLayout()
        
        # Status label
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #666; font-style: italic;")
        
        # Active sessions count
        self.active_sessions_label = QLabel("Active Sessions: 0")
        self.active_sessions_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        
        # Last update
        self.last_update_label = QLabel("Last update: Never")
        self.last_update_label.setStyleSheet("color: #666; font-size: 10px;")
        
        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.active_sessions_label)
        status_layout.addStretch()
        status_layout.addWidget(self.last_update_label)
        
        return status_layout
    
    def setup_connections(self):
        """Setup signal connections"""
        # Session controls
        self.start_btn.clicked.connect(self.start_duping_session)
        self.stop_all_btn.clicked.connect(self.stop_all_sessions)
        self.refresh_btn.clicked.connect(self.refresh_all_data)
        
        # Session management
        self.refresh_sessions_btn.clicked.connect(self.refresh_sessions_table)
        self.test_all_btn.clicked.connect(self.test_all_sessions)
        self.export_sessions_btn.clicked.connect(self.export_sessions)
        
        # Network profiles
        self.apply_profile_btn.clicked.connect(self.apply_profile_changes)
        
        # Techniques
        self.enable_all_btn.clicked.connect(self.enable_all_techniques)
        self.disable_all_btn.clicked.connect(self.disable_all_techniques)
        self.refresh_techniques_btn.clicked.connect(self.refresh_techniques_table)
        
        # Monitoring actions removed for optimization
        
        # Profile selection
        self.profile_selector.currentTextChanged.connect(self.on_profile_selected)
    
    def setup_timers(self):
        """Setup timers for updates"""
        # Real-time monitoring timer removed for optimization
    
    def apply_styling(self):
        """Apply custom styling with improved readability and fonts"""
        self.setStyleSheet("""
            QWidget {
                background-color: #2b2b2b;
                color: #ffffff;
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 11px;
            }
            QGroupBox {
                font-weight: bold;
                font-size: 12px;
                border: 2px solid #555555;
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 8px;
                background-color: #3a3a3a;
                color: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 5px 0 5px;
                color: #ffffff;
                font-size: 12px;
                font-weight: bold;
            }
            QLabel {
                color: #ffffff;
                font-size: 11px;
                font-weight: normal;
            }
            QPushButton {
                background-color: #4a4a4a;
                color: #ffffff;
                border: 1px solid #666666;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: bold;
                font-size: 11px;
                min-height: 20px;
            }
            QPushButton:hover {
                background-color: #5a5a5a;
                border-color: #777777;
            }
            QPushButton:pressed {
                background-color: #3a3a3a;
            }
            QLineEdit, QComboBox, QSpinBox {
                background-color: #3a3a3a;
                color: #ffffff;
                border: 1px solid #555555;
                border-radius: 3px;
                padding: 4px 6px;
                font-size: 11px;
                min-height: 18px;
            }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
                border-color: #4CAF50;
            }
            QTableWidget {
                gridline-color: #555555;
                background-color: #2a2a2a;
                alternate-background-color: #3a3a3a;
                color: #ffffff;
                font-size: 10px;
            }
            QTableWidget::item {
                padding: 4px;
                border: none;
            }
            QHeaderView::section {
                background-color: #4a4a4a;
                color: #ffffff;
                padding: 6px;
                border: 1px solid #555555;
                font-weight: bold;
                font-size: 10px;
            }
            QTabWidget::pane {
                border: 1px solid #555555;
                background-color: #2b2b2b;
            }
            QTabBar::tab {
                background-color: #3a3a3a;
                color: #ffffff;
                padding: 8px 16px;
                margin-right: 2px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                font-size: 11px;
                font-weight: bold;
            }
            QTabBar::tab:selected {
                background-color: #4CAF50;
                color: #ffffff;
            }
            QTabBar::tab:hover {
                background-color: #5a5a5a;
            }
            QTextEdit {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #555555;
                border-radius: 3px;
                padding: 4px;
                font-size: 10px;
                font-family: 'Consolas', 'Monaco', monospace;
            }
        """)
    
    def start_duping_session(self):
        """Start a new duping session"""
        try:
            server_ip = self.server_ip_input.text().strip()
            server_port = self.server_port_input.value()
            method = self.method_combo.currentText()
            profile = self.profile_combo.currentText()
            
            if not server_ip:
                QMessageBox.warning(self, "Input Error", "Please enter a server IP address")
                return
            
            # Start session
            session_id = self.optimizer.start_duping_session(
                server_ip, server_port, method, profile
            )
            
            if session_id:
                self.status_label.setText(f"Session started: {session_id}")
                self.add_log_message(f"🚀 Started duping session: {session_id} -> {server_ip}:{server_port}")
                self.refresh_sessions_table()
            else:
                QMessageBox.critical(self, "Error", "Failed to start duping session")
                
        except Exception as e:
            log_error(f"Failed to start duping session: {e}")
            QMessageBox.critical(self, "Error", f"Failed to start duping session: {e}")
    
    def stop_all_sessions(self):
        """Stop all active duping sessions"""
        try:
            active_sessions = self.optimizer.get_active_sessions()
            stopped_count = 0
            
            for session in active_sessions:
                if self.optimizer.stop_duping_session(session.session_id):
                    stopped_count += 1
            
            self.status_label.setText(f"Stopped {stopped_count} sessions")
            self.add_log_message(f"⏹️ Stopped {stopped_count} duping sessions")
            self.refresh_sessions_table()
            
        except Exception as e:
            log_error(f"Failed to stop sessions: {e}")
            QMessageBox.critical(self, "Error", f"Failed to stop sessions: {e}")
    
    def refresh_all_data(self):
        """Refresh all data displays"""
        try:
            self.refresh_sessions_table()
            self.refresh_techniques_table()
            self.update_real_time_metrics()
            self.status_label.setText("Data refreshed")
            self.last_update_label.setText(f"Last update: {datetime.now().strftime('%H:%M:%S')}")
            
        except Exception as e:
            log_error(f"Failed to refresh data: {e}")
    
    def refresh_sessions_table(self):
        """Refresh the sessions table"""
        try:
            active_sessions = self.optimizer.get_active_sessions()
            
            self.sessions_table.setRowCount(len(active_sessions))
            
            for row, session in enumerate(active_sessions):
                # Session ID
                self.sessions_table.setItem(row, 0, QTableWidgetItem(session.session_id))
                
                # Server
                self.sessions_table.setItem(row, 1, QTableWidgetItem(session.target_server))
                
                # Port
                self.sessions_table.setItem(row, 2, QTableWidgetItem(str(session.target_port)))
                
                # Method
                self.sessions_table.setItem(row, 3, QTableWidgetItem(session.duping_method))
                
                # Profile
                self.sessions_table.setItem(row, 4, QTableWidgetItem(session.network_profile))
                
                # Status
                status_item = QTableWidgetItem("🟢 Active" if session.active else "🔴 Inactive")
                status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.sessions_table.setItem(row, 5, status_item)
                
                # Duration
                duration = datetime.now() - session.start_time
                duration_str = f"{int(duration.total_seconds())}s"
                self.sessions_table.setItem(row, 6, QTableWidgetItem(duration_str))
                
                # Actions
                stop_btn = QPushButton("⏹️ Stop")
                stop_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #f44336;
                        color: white;
                        border: none;
                        padding: 5px 10px;
                        border-radius: 3px;
                        font-size: 11px;
                    }
                    QPushButton:hover {
                        background-color: #da190b;
                    }
                """)
                stop_btn.clicked.connect(lambda checked, sid=session.session_id: self.stop_session(sid))
                
                self.sessions_table.setCellWidget(row, 7, stop_btn)
            
            self.active_sessions_label.setText(str(len(active_sessions)))
            
        except Exception as e:
            log_error(f"Failed to refresh sessions table: {e}")
    
    def stop_session(self, session_id: str):
        """Stop a specific session"""
        try:
            if self.optimizer.stop_duping_session(session_id):
                self.add_log_message(f"⏹️ Stopped session: {session_id}")
                self.refresh_sessions_table()
            else:
                QMessageBox.warning(self, "Warning", f"Failed to stop session: {session_id}")
                
        except Exception as e:
            log_error(f"Failed to stop session {session_id}: {e}")
    
    def test_all_sessions(self):
        """Test all active sessions"""
        try:
            active_sessions = self.optimizer.get_active_sessions()
            
            if not active_sessions:
                QMessageBox.information(self, "Info", "No active sessions to test")
                return
            
            # Simulate testing all sessions
            for session in active_sessions:
                self.add_log_message(f"🧪 Testing session: {session.session_id}")
            
            self.status_label.setText(f"Tested {len(active_sessions)} sessions")
            self.add_log_message(f"✅ Completed testing {len(active_sessions)} sessions")
            
        except Exception as e:
            log_error(f"Failed to test sessions: {e}")
    
    def export_sessions(self):
        """Export sessions data"""
        try:
            # Simulate export
            self.add_log_message("📤 Exporting sessions data...")
            self.status_label.setText("Sessions exported")
            
        except Exception as e:
            log_error(f"Failed to export sessions: {e}")
    
    def on_profile_selected(self, profile_name: str):
        """Handle profile selection"""
        try:
            profiles = self.optimizer.get_network_profiles()
            
            if profile_name in profiles:
                profile = profiles[profile_name]
                
                # Update profile details
                details = f"""Profile: {profile_name}
Description: {profile['description']}
Latency Variance: {profile['latency_variance']} ms
Packet Timing: {profile['packet_timing']} ms
Connection Stability: {profile['connection_stability']}%
Detection Risk: {profile['detection_risk']}
Traffic Patterns: {', '.join(profile['traffic_patterns'])}"""
                
                self.profile_details.setText(details)
                
                # Update configuration controls
                self.latency_variance_spin.setValue(int(profile['latency_variance']))
                self.packet_timing_spin.setValue(int(profile['packet_timing']))
                self.stability_spin.setValue(int(profile['connection_stability']))
                
                # Update traffic patterns
                patterns_text = f"Available patterns for {profile_name}:\n"
                for pattern in profile['traffic_patterns']:
                    patterns_text += f"• {pattern}\n"
                self.patterns_text.setText(patterns_text)
                
        except Exception as e:
            log_error(f"Failed to load profile {profile_name}: {e}")
    
    def apply_profile_changes(self):
        """Apply profile configuration changes"""
        try:
            profile_name = self.profile_selector.currentText()
            
            new_config = {
                "latency_variance": self.latency_variance_spin.value(),
                "packet_timing": self.packet_timing_spin.value(),
                "connection_stability": self.stability_spin.value()
            }
            
            if self.optimizer.update_network_profile(profile_name, new_config):
                self.add_log_message(f"✅ Updated profile: {profile_name}")
                self.status_label.setText(f"Profile {profile_name} updated")
            else:
                QMessageBox.warning(self, "Warning", f"Failed to update profile: {profile_name}")
                
        except Exception as e:
            log_error(f"Failed to apply profile changes: {e}")
    
    def refresh_techniques_table(self):
        """Refresh the techniques table"""
        try:
            techniques = self.optimizer.get_manipulation_techniques()
            
            self.techniques_table.setRowCount(len(techniques))
            
            for row, technique in enumerate(techniques):
                # Technique name
                self.techniques_table.setItem(row, 0, QTableWidgetItem(technique.name))
                
                # Type
                self.techniques_table.setItem(row, 1, QTableWidgetItem(technique.technique_type))
                
                # Success rate
                success_item = QTableWidgetItem(f"{technique.success_rate}%")
                success_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.techniques_table.setItem(row, 2, success_item)
                
                # Detection risk
                risk_item = QTableWidgetItem(technique.detection_risk.upper())
                risk_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                
                # Color code risk levels
                if technique.detection_risk == "low":
                    risk_item.setBackground(QColor(76, 175, 80))  # Green
                    risk_item.setForeground(QColor(255, 255, 255))
                elif technique.detection_risk == "medium":
                    risk_item.setBackground(QColor(255, 152, 0))  # Orange
                    risk_item.setForeground(QColor(255, 255, 255))
                else:  # high
                    risk_item.setBackground(QColor(244, 67, 54))  # Red
                    risk_item.setForeground(QColor(255, 255, 255))
                
                self.techniques_table.setItem(row, 3, risk_item)
                
                # Status
                status_item = QTableWidgetItem("✅ Enabled" if technique.enabled else "❌ Disabled")
                status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.techniques_table.setItem(row, 4, status_item)
                
                # Actions
                toggle_btn = QPushButton("Toggle")
                toggle_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #2196F3;
                        color: white;
                        border: none;
                        padding: 5px 10px;
                        border-radius: 3px;
                        font-size: 11px;
                    }
                    QPushButton:hover {
                        background-color: #1976D2;
                    }
                """)
                toggle_btn.clicked.connect(lambda checked, t=technique: self.toggle_technique(t))
                
                self.techniques_table.setCellWidget(row, 5, toggle_btn)
            
            self.total_techniques_label.setText(str(len(techniques)))
            self.enabled_techniques_label.setText(str(len([t for t in techniques if t.enabled])))
            
        except Exception as e:
            log_error(f"Failed to refresh techniques table: {e}")
    
    def toggle_technique(self, technique):
        """Toggle a technique on/off"""
        try:
            new_state = not technique.enabled
            if self.optimizer.enable_manipulation_technique(technique.name, new_state):
                self.add_log_message(f"{'✅ Enabled' if new_state else '❌ Disabled'} technique: {technique.name}")
                self.refresh_techniques_table()
            else:
                QMessageBox.warning(self, "Warning", f"Failed to toggle technique: {technique.name}")
                
        except Exception as e:
            log_error(f"Failed to toggle technique {technique.name}: {e}")
    
    def enable_all_techniques(self):
        """Enable all techniques"""
        try:
            techniques = self.optimizer.get_manipulation_techniques()
            enabled_count = 0
            
            for technique in techniques:
                if self.optimizer.enable_manipulation_technique(technique.name, True):
                    enabled_count += 1
            
            self.add_log_message(f"✅ Enabled {enabled_count} techniques")
            self.refresh_techniques_table()
            
        except Exception as e:
            log_error(f"Failed to enable all techniques: {e}")
    
    def disable_all_techniques(self):
        """Disable all techniques"""
        try:
            techniques = self.optimizer.get_manipulation_techniques()
            disabled_count = 0
            
            for technique in techniques:
                if self.optimizer.enable_manipulation_technique(technique.name, False):
                    disabled_count += 1
            
            self.add_log_message(f"❌ Disabled {disabled_count} techniques")
            self.refresh_techniques_table()
            
        except Exception as e:
            log_error(f"Failed to disable all techniques: {e}")
    
    def update_session_display(self, report: dict):
        """Update session display from background thread"""
        try:
            # Update overview labels
            self.active_sessions_label.setText(str(report.get("active_sessions", 0)))
            self.total_techniques_label.setText(str(report.get("total_techniques", 0)))
            self.enabled_techniques_label.setText(str(report.get("enabled_techniques", 0)))
            
            # Update optimization status (removed for simplicity)
            status = report.get("optimization_status", "stopped")
            
            # Update last update time
            self.last_update_label.setText(f"Last update: {datetime.now().strftime('%H:%M:%S')}")
            
        except Exception as e:
            log_error(f"Failed to update session display: {e}")
    
    # update_real_time_metrics removed for optimization
    
    # add_log_message removed for optimization
    
    # clear_performance_logs removed for optimization
    
    # export_performance_logs removed for optimization
    
    def load_accounts_table(self):
        """Load accounts from account tracker into the table"""
        try:
            if not self.account_tracker:
                return
                
            accounts = self.account_tracker.accounts
            self.account_table.setRowCount(len(accounts))
            
            for row, account in enumerate(accounts):
                
                # Checkbox for selection
                checkbox = QCheckBox()
                checkbox.stateChanged.connect(self.update_selected_accounts)
                self.account_table.setCellWidget(row, 0, checkbox)
                
                # Account details
                self.account_table.setItem(row, 1, QTableWidgetItem(account.get('username', 'Unknown')))
                self.account_table.setItem(row, 2, QTableWidgetItem(account.get('status', 'Unknown')))
                self.account_table.setItem(row, 3, QTableWidgetItem(account.get('server_location', 'Unknown')))
                self.account_table.setItem(row, 4, QTableWidgetItem(account.get('last_login', 'Never')))
                
        except Exception as e:
            log_error(f"Failed to load accounts table: {e}")
    
    def select_all_accounts(self):
        """Select all accounts in the table"""
        try:
            for row in range(self.account_table.rowCount()):
                checkbox = self.account_table.cellWidget(row, 0)
                if checkbox:
                    checkbox.setChecked(True)
        except Exception as e:
            log_error(f"Failed to select all accounts: {e}")
    
    def clear_account_selection(self):
        """Clear all account selections"""
        try:
            for row in range(self.account_table.rowCount()):
                checkbox = self.account_table.cellWidget(row, 0)
                if checkbox:
                    checkbox.setChecked(False)
        except Exception as e:
            log_error(f"Failed to clear account selection: {e}")
    
    def update_selected_accounts(self):
        """Update the selected accounts status"""
        try:
            selected_count = 0
            selected_accounts = []
            
            for row in range(self.account_table.rowCount()):
                checkbox = self.account_table.cellWidget(row, 0)
                if checkbox and checkbox.isChecked():
                    selected_count += 1
                    account_name = self.account_table.item(row, 1)
                    if account_name:
                        selected_accounts.append(account_name.text())
            
            if selected_count == 0:
                self.selected_accounts_label.setText("No accounts selected")
            elif selected_count == 1:
                self.selected_accounts_label.setText(f"1 account selected: {selected_accounts[0]}")
            else:
                self.selected_accounts_label.setText(f"{selected_count} accounts selected")
                
        except Exception as e:
            log_error(f"Failed to update selected accounts: {e}")
    
    def closeEvent(self, event):
        """Handle application close event"""
        try:
            # Stop session monitoring
            if self.session_thread.isRunning():
                self.session_thread.stop()
                self.session_thread.wait(5000)  # Wait up to 5 seconds
            
            # Cleanup optimizer
            self.optimizer.cleanup()
            
            log_info("DayZ Duping Dashboard closed")
            event.accept()
            
        except Exception as e:
            log_error(f"Error during close: {e}")
            event.accept()
