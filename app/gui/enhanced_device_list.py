# app/gui/enhanced_device_list.py

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QListWidget, QListWidgetItem,
                             QProgressBar, QTextEdit, QSplitter, QFrame,
                             QHeaderView, QTableWidget, QTableWidgetItem,
                             QComboBox, QSpinBox, QCheckBox, QGroupBox,
                             QMenu, QGridLayout, QLineEdit, QMessageBox)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QIcon, QAction
import time
import platform
import subprocess
from typing import List, Dict, Optional

from app.network.enhanced_scanner import get_enhanced_scanner, cleanup_enhanced_scanner
from app.logs.logger import log_info, log_error, log_warning
from app.logs.error_tracker import track_error
from app.firewall.clumsy_network_disruptor import clumsy_network_disruptor
from app.firewall.enterprise_network_disruptor import enterprise_network_disruptor
from app.firewall.blocker import is_admin

class EnhancedDeviceList(QWidget):
    """Enhanced device list with Angry IP Scanner-like features"""
    
    # Signals
    device_selected = pyqtSignal(dict)  # Selected device
    device_blocked = pyqtSignal(str, bool)  # IP, blocked status
    scan_started = pyqtSignal()
    scan_finished = pyqtSignal(list)  # All devices
    
    def __init__(self, controller=None):
        super().__init__()
        self.controller = controller
        
        # Initialize scanner with error handling
        try:
            self.scanner = get_enhanced_scanner()
        except Exception as e:
            log_error(f"Failed to initialize scanner: {e}")
            self.scanner = None
        
        # Initialize network disruptors with error handling
        self.clumsy_network_disruptor = None
        self.enterprise_network_disruptor = None
        self._initialize_disruptors()
        
        self.devices = []
        self.disconnect_active = False  # Track disconnect state
        
        # Stability optimization: Enhanced UI update throttling
        self.ui_update_timer = QTimer()
        self.ui_update_timer.setSingleShot(True)
        self.ui_update_timer.timeout.connect(self._perform_batched_ui_update)
        self.device_ui_updates = []
        
        # Stability optimization: Add error handling for UI updates
        self.ui_update_error_count = 0
        self.max_ui_update_errors = 5
        
        # Performance optimization: Reduce logging during operations
        self.operation_in_progress = False
        self.last_log_time = 0
        self.log_throttle_interval = 0.5  # Only log every 0.5 seconds
        
        self.setup_ui()
        self.connect_signals()
        
        # Connect resize event for responsive design
        self.resizeEvent = self.on_resize
        
        # Stability optimization: Reduced UDP status timer frequency
        self.udp_status_timer = QTimer()
        self.udp_status_timer.timeout.connect(self.check_udp_tool_status)
        self.udp_status_timer.start(10000)  # Check every 10 seconds for better stability
    
    def _initialize_disruptors(self):
        """Initialize network disruptors with proper error handling"""
        try:
            # Initialize Clumsy network disruptor
            try:
                from app.firewall.clumsy_network_disruptor import clumsy_network_disruptor
                self.clumsy_network_disruptor = clumsy_network_disruptor
                log_info("Clumsy network disruptor initialized successfully")
            except Exception as e:
                log_error(f"Failed to initialize Clumsy network disruptor: {e}")
                self.clumsy_network_disruptor = None
            
            # Initialize Enterprise network disruptor
            try:
                from app.firewall.enterprise_network_disruptor import enterprise_network_disruptor
                self.enterprise_network_disruptor = enterprise_network_disruptor
                log_info("Enterprise network disruptor initialized successfully")
            except Exception as e:
                log_error(f"Failed to initialize Enterprise network disruptor: {e}")
                self.enterprise_network_disruptor = None
                
        except Exception as e:
            log_error(f"Error initializing network disruptors: {e}")
            self.clumsy_network_disruptor = None
            self.enterprise_network_disruptor = None
    
    def setup_ui(self):
        """Setup a simple, Clumsy-like network scanner UI"""
        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(8, 8, 8, 8)
        self.setLayout(layout)
        
        # Simple title
        title = QLabel("Network Scanner")
        title.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #ffffff; padding: 8px; margin-bottom: 8px;")
        layout.addWidget(title)
        
        # Simple control panel
        control_panel = self.create_simple_control_panel()
        layout.addWidget(control_panel)
        
        # Simple progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #555555;
                border-radius: 3px;
                text-align: center;
                height: 16px;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                border-radius: 2px;
            }
        """)
        layout.addWidget(self.progress_bar)
        
        # Simple device table
        self.device_table = QTableWidget()
        self.setup_simple_device_table()
        layout.addWidget(self.device_table, 1)
        
        # Simple status bar
        self.status_label = QLabel("Ready to scan")
        self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold; padding: 4px;")
        layout.addWidget(self.status_label)
        
        # Apply simple styling
        self.apply_simple_styling()
        
        # Initialize admin status
        try:
            from app.firewall.blocker import is_admin
            if is_admin():
                admin_label = QLabel("👑 Administrator Mode")
                admin_label.setStyleSheet("color: #4CAF50; font-weight: bold; font-size: 10px;")
                layout.addWidget(admin_label)
        except Exception as e:
            log_error(f"Failed to create admin status indicator: {e}")
    
    def create_simple_control_panel(self) -> QWidget:
        """Create a simple control panel like Clumsy"""
        panel = QWidget()
        panel.setStyleSheet("""
            QWidget {
                background-color: #2d2d2d;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 8px;
            }
        """)
        
        layout = QHBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(8, 8, 8, 8)
        panel.setLayout(layout)
        
        # Scan button
        self.scan_button = QPushButton("🔍 Scan Network")
        self.scan_button.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        self.scan_button.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                min-height: 28px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        self.scan_button.clicked.connect(self.start_scan)
        layout.addWidget(self.scan_button)
        
        # Stop button
        self.stop_button = QPushButton("⏹️ Stop")
        self.stop_button.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        self.stop_button.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                min-height: 28px;
            }
            QPushButton:hover {
                background-color: #d32f2f;
            }
        """)
        self.stop_button.clicked.connect(self.stop_scan)
        self.stop_button.setEnabled(False)
        layout.addWidget(self.stop_button)
        
        # Disconnect selected device button
        self.disconnect_button = QPushButton("🔌 Disconnect Selected")
        self.disconnect_button.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        self.disconnect_button.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                min-height: 28px;
            }
            QPushButton:hover {
                background-color: #F57C00;
            }
        """)
        self.disconnect_button.clicked.connect(self.disconnect_selected_device)
        self.disconnect_button.setEnabled(False)
        layout.addWidget(self.disconnect_button)
        
        # Reconnect selected device button
        self.reconnect_button = QPushButton("🔌 Reconnect Selected")
        self.reconnect_button.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        self.reconnect_button.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                min-height: 28px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)
        self.reconnect_button.clicked.connect(self.reconnect_selected_device)
        self.reconnect_button.setEnabled(False)
        layout.addWidget(self.reconnect_button)
        
        # Clear all button
        self.clear_button = QPushButton("🗑️ Clear All")
        self.clear_button.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        self.clear_button.setStyleSheet("""
            QPushButton {
                background-color: #9E9E9E;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                min-height: 28px;
            }
            QPushButton:hover {
                background-color: #757575;
            }
        """)
        self.clear_button.clicked.connect(self.clear_devices)
        layout.addWidget(self.clear_button)
        
        layout.addStretch()
        return panel
    
    def setup_simple_device_table(self):
        """Setup a simple device table like Clumsy"""
        # Set table properties
        self.device_table.setColumnCount(6)
        self.device_table.setHorizontalHeaderLabels([
            "IP Address", "MAC Address", "Hostname", "Vendor", "Status", "Actions"
        ])
        
        # Set table style
        self.device_table.setStyleSheet("""
            QTableWidget {
                background-color: #1e1e1e;
                alternate-background-color: #2d2d2d;
                color: #ffffff;
                gridline-color: #555555;
                border: 1px solid #555555;
                border-radius: 4px;
            }
            QTableWidget::item {
                padding: 4px;
                border: none;
            }
            QTableWidget::item:selected {
                background-color: #4CAF50;
                color: white;
            }
            QHeaderView::section {
                background-color: #34495e;
                color: white;
                padding: 6px;
                border: 1px solid #555555;
                font-weight: bold;
            }
        """)
        
        # Set selection behavior
        self.device_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.device_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.device_table.setAlternatingRowColors(True)
        
        # Connect selection change
        self.device_table.itemSelectionChanged.connect(self.on_device_selection_changed)
        
        # Set column widths
        header = self.device_table.horizontalHeader()
        header.setStretchLastSection(False)
        self.device_table.setColumnWidth(0, 120)  # IP
        self.device_table.setColumnWidth(1, 140)  # MAC
        self.device_table.setColumnWidth(2, 150)  # Hostname
        self.device_table.setColumnWidth(3, 120)  # Vendor
        self.device_table.setColumnWidth(4, 80)   # Status
        self.device_table.setColumnWidth(5, 100)  # Actions
        
        # Make hostname column stretch
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
    
    def on_resize(self, event):
        """Handle resize events for responsive design"""
        super().resizeEvent(event)
        
        # Update table column widths when window is resized
        if hasattr(self, 'device_table') and self.device_table:
            total_width = self.device_table.width()
            if total_width > 0:
                # Recalculate responsive column widths
                column_widths = {
                    0: int(total_width * 0.12),  # IP Address
                    1: int(total_width * 0.15),  # MAC Address
                    2: int(total_width * 0.20),  # Hostname (stretch)
                    3: int(total_width * 0.15),  # Vendor
                    4: int(total_width * 0.12),  # Device Type
                    5: int(total_width * 0.10),  # Interface
                    6: int(total_width * 0.08),  # Open Ports
                    7: int(total_width * 0.08)   # Status
                }
                
                # Apply new column widths
                header = self.device_table.horizontalHeader()
                for col, width in column_widths.items():
                    if col != 2:  # Don't resize stretch column
                        self.device_table.setColumnWidth(col, width)
    
    def create_control_panel(self) -> QWidget:
        """Create the control panel with responsive scan options"""
        panel = QWidget()
        panel.setStyleSheet("""
            QWidget {
                background-color: #2d2d2d;
                border: 2px solid #404040;
                border-radius: 8px;
                padding: 10px;
                margin: 5px;
            }
        """)
        
        # Use QGridLayout for better organization
        layout = QGridLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)
        panel.setLayout(layout)
        
        # Row 1: Main scan controls
        self.scan_button = QPushButton("🔍 Start Enhanced Scan")
        self.scan_button.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        self.scan_button.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: 2px solid #45a049;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
                min-height: 30px;
            }
            QPushButton:hover {
                background-color: #45a049;
                border-color: #3d8b40;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
        """)
        self.scan_button.clicked.connect(self.start_scan)
        layout.addWidget(self.scan_button, 0, 0, 1, 2)
        
        self.stop_button = QPushButton("⏹️ Stop Scan")
        self.stop_button.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        self.stop_button.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border: 2px solid #d32f2f;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
                min-height: 30px;
            }
            QPushButton:hover {
                background-color: #d32f2f;
                border-color: #c62828;
            }
            QPushButton:pressed {
                background-color: #c62828;
            }
        """)
        self.stop_button.clicked.connect(self.stop_scan)
        self.stop_button.setEnabled(False)
        layout.addWidget(self.stop_button, 0, 2, 1, 2)
        
        # Row 2: Scan settings
        thread_label = QLabel("Threads:")
        thread_label.setStyleSheet("color: #ffffff; font-weight: bold;")
        layout.addWidget(thread_label, 1, 0)
        
        self.thread_spinbox = QSpinBox()
        self.thread_spinbox.setRange(5, 64)
        self.thread_spinbox.setValue(24)
        self.thread_spinbox.setToolTip("Number of concurrent scan threads")
        self.thread_spinbox.setStyleSheet("""
            QSpinBox {
                background-color: #3d3d3d;
                color: #ffffff;
                border: 2px solid #404040;
                border-radius: 4px;
                padding: 5px;
                min-height: 25px;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                background-color: #505050;
                border: 1px solid #404040;
                border-radius: 2px;
            }
        """)
        layout.addWidget(self.thread_spinbox, 1, 1)
        
        timeout_label = QLabel("Timeout (ms):")
        timeout_label.setStyleSheet("color: #ffffff; font-weight: bold;")
        layout.addWidget(timeout_label, 1, 2)
        
        self.timeout_spinbox = QSpinBox()
        self.timeout_spinbox.setRange(800, 8000)
        self.timeout_spinbox.setValue(1500)
        self.timeout_spinbox.setSuffix(" ms")
        self.timeout_spinbox.setToolTip("Scan timeout per IP")
        self.timeout_spinbox.setStyleSheet("""
            QSpinBox {
                background-color: #3d3d3d;
                color: #ffffff;
                border: 2px solid #404040;
                border-radius: 4px;
                padding: 5px;
                min-height: 25px;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                background-color: #505050;
                border: 1px solid #404040;
                border-radius: 2px;
            }
        """)
        layout.addWidget(self.timeout_spinbox, 1, 3)
        
        # Row 3: Options and actions
        self.advanced_checkbox = QCheckBox("Advanced Scan")
        self.advanced_checkbox.setToolTip("Use advanced scanning methods")
        self.advanced_checkbox.setChecked(True)
        self.advanced_checkbox.setStyleSheet("""
            QCheckBox {
                color: #ffffff;
                font-weight: bold;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border: 2px solid #404040;
                border-radius: 3px;
                background-color: #3d3d3d;
            }
            QCheckBox::indicator:checked {
                background-color: #4CAF50;
                border-color: #4CAF50;
            }
        """)
        layout.addWidget(self.advanced_checkbox, 2, 0)
        
        self.clear_button = QPushButton("🗑️ Clear")
        self.clear_button.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        self.clear_button.setStyleSheet("""
            QPushButton {
                background-color: #ff9800;
                color: white;
                border: 2px solid #f57c00;
                border-radius: 6px;
                padding: 6px 12px;
                font-weight: bold;
                min-height: 25px;
            }
            QPushButton:hover {
                background-color: #f57c00;
                border-color: #ef6c00;
            }
        """)
        self.clear_button.clicked.connect(self.clear_devices)
        layout.addWidget(self.clear_button, 2, 1)
        
        self.block_button = QPushButton("🚫 Block Selected")
        self.block_button.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        self.block_button.setStyleSheet("""
            QPushButton {
                background-color: #e91e63;
                color: white;
                border: 2px solid #c2185b;
                border-radius: 6px;
                padding: 6px 12px;
                font-weight: bold;
                min-height: 25px;
            }
            QPushButton:hover {
                background-color: #c2185b;
                border-color: #ad1457;
            }
        """)
        self.block_button.clicked.connect(self.block_selected)
        layout.addWidget(self.block_button, 2, 2)
        
        # Global blocking controls
        layout.addWidget(QLabel("|"))
        
        # Global block/unblock all button
        self.global_block_button = QPushButton("🔒 Block All")
        self.global_block_button.setFont(QFont("Arial", 12))
        self.global_block_button.clicked.connect(self.block_all_devices)
        layout.addWidget(self.global_block_button)
        
        self.global_unblock_button = QPushButton("🔓 Unblock All")
        self.global_unblock_button.setFont(QFont("Arial", 12))
        self.global_unblock_button.clicked.connect(self.unblock_all_devices)
        layout.addWidget(self.global_unblock_button)
        
        # Clear all blocks button
        self.clear_blocks_button = QPushButton("🧹 Clear All Blocks")
        self.clear_blocks_button.setFont(QFont("Arial", 12))
        self.clear_blocks_button.clicked.connect(self.clear_all_blocks)
        layout.addWidget(self.clear_blocks_button)
        
        # Internet drop toggle
        layout.addWidget(QLabel("|"))
        
        # Row 3: Internet drop button
        self.internet_drop_button = QPushButton("🔌 Disconnect")
        self.internet_drop_button.setStyleSheet("""
            QPushButton {
                background-color: #d32f2f;
                color: white;
                border: 2px solid #b71c1c;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 12px;
                min-height: 30px;
            }
            QPushButton:hover {
                background-color: #f44336;
                border-color: #d32f2f;
            }
        """)
        self.internet_drop_button.clicked.connect(self.toggle_internet_drop)
        layout.addWidget(self.internet_drop_button, 2, 3)
        
        # Emergency network restoration button
        self.emergency_restore_button = QPushButton("🚨 Emergency Restore")
        self.emergency_restore_button.setStyleSheet("""
            QPushButton {
                background-color: #ff5722;
                color: white;
                border: 2px solid #e64a19;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 11px;
                min-height: 30px;
            }
            QPushButton:hover {
                background-color: #ff7043;
                border-color: #ff5722;
            }
        """)
        self.emergency_restore_button.setToolTip("Emergency network restoration - use if devices are permanently blocked")
        self.emergency_restore_button.clicked.connect(self.emergency_network_restoration)
        layout.addWidget(self.emergency_restore_button, 2, 4)
        
        # Row 4: Search functionality
        layout.addWidget(QLabel("|"))
        
        search_label = QLabel("🔍 Search:")
        search_label.setStyleSheet("color: #ffffff; font-weight: bold;")
        layout.addWidget(search_label, 4, 0)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search devices by IP, hostname, vendor, or MAC...")
        self.search_input.setStyleSheet("""
            QLineEdit {
                background-color: #3d3d3d;
                color: #ffffff;
                border: 2px solid #404040;
                border-radius: 4px;
                padding: 5px;
                min-height: 25px;
                font-size: 10px;
            }
            QLineEdit:focus {
                border-color: #4CAF50;
            }
        """)
        self.search_input.textChanged.connect(self.filter_devices_by_search)
        layout.addWidget(self.search_input, 4, 1, 1, 3)
        
        # Row 5: Disconnect Methods Frame
        disconnect_methods_frame = QFrame()
        disconnect_methods_frame.setFrameStyle(QFrame.Shape.StyledPanel)
        disconnect_methods_frame.setStyleSheet("""
            QFrame {
                background-color: #2a2a2a;
                border: 1px solid #404040;
                border-radius: 5px;
                margin: 5px;
            }
        """)
        
        # Use QGridLayout for better organization of checkboxes
        disconnect_methods_layout = QGridLayout(disconnect_methods_frame)
        disconnect_methods_layout.setContentsMargins(15, 10, 15, 10)
        disconnect_methods_layout.setSpacing(8)
        
        # Disconnect Methods Label
        methods_label = QLabel("🔌 Disconnect Methods:")
        methods_label.setStyleSheet("""
            QLabel {
                color: #ffffff;
                font-weight: bold;
                font-size: 12px;
                padding: 5px;
            }
        """)
        disconnect_methods_layout.addWidget(methods_label, 0, 0, 1, 3)
        
        # Disconnect Method Checkboxes - arranged in 2 rows for better visibility
        self.icmp_spoof_cb = QCheckBox("ICMP Spoof")
        self.dns_spoof_cb = QCheckBox("DNS Spoof") 
        self.ps5_packets_cb = QCheckBox("PS5 Packets")
        self.response_spoof_cb = QCheckBox("Response Spoof")
        self.arp_poison_cb = QCheckBox("ARP Poison")
        self.udp_interrupt_cb = QCheckBox("UDP Interrupt")
        
        # Style checkboxes with better spacing and visibility
        checkbox_style = """
            QCheckBox {
                color: #ffffff;
                font-size: 11px;
                font-weight: bold;
                spacing: 8px;
                padding: 3px;
                min-width: 120px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
            }
            QCheckBox::indicator:unchecked {
                border: 2px solid #666666;
                background-color: #333333;
                border-radius: 3px;
            }
            QCheckBox::indicator:checked {
                border: 2px solid #00ff00;
                background-color: #00ff00;
                border-radius: 3px;
            }
            QCheckBox:hover {
                color: #4CAF50;
            }
        """
        self.icmp_spoof_cb.setStyleSheet(checkbox_style)
        self.dns_spoof_cb.setStyleSheet(checkbox_style)
        self.ps5_packets_cb.setStyleSheet(checkbox_style)
        self.response_spoof_cb.setStyleSheet(checkbox_style)
        self.arp_poison_cb.setStyleSheet(checkbox_style)
        self.udp_interrupt_cb.setStyleSheet(checkbox_style)
        
        # Set default selections for effective DayZ duping
        self.arp_poison_cb.setChecked(True)  # Most effective for duping
        self.icmp_spoof_cb.setChecked(True)  # ICMP spoofing
        self.ps5_packets_cb.setChecked(True)  # PS5 specific packets
        
        # Arrange checkboxes in 2 rows for better visibility
        disconnect_methods_layout.addWidget(self.icmp_spoof_cb, 1, 0)
        disconnect_methods_layout.addWidget(self.dns_spoof_cb, 1, 1)
        disconnect_methods_layout.addWidget(self.ps5_packets_cb, 1, 2)
        disconnect_methods_layout.addWidget(self.response_spoof_cb, 2, 0)
        disconnect_methods_layout.addWidget(self.arp_poison_cb, 2, 1)
        disconnect_methods_layout.addWidget(self.udp_interrupt_cb, 2, 2)
        
        layout.addWidget(disconnect_methods_frame, 5, 0, 1, 4)
        
        return panel
    
    def setup_device_table(self):
        """Setup the device table with responsive columns"""
        # Set up table headers
        headers = [
            "IP Address", "MAC Address", "Hostname", "Vendor", 
            "Device Type", "Interface", "Open Ports", "Status"
        ]
        self.device_table.setColumnCount(len(headers))
        self.device_table.setHorizontalHeaderLabels(headers)
        
        # Set up table properties
        self.device_table.setAlternatingRowColors(True)
        self.device_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.device_table.setSelectionMode(QTableWidget.SelectionMode.MultiSelection)  # Allow multiple selection
        self.device_table.setSortingEnabled(True)
        self.device_table.setWordWrap(True)  # Enable word wrapping
        self.device_table.setShowGrid(True)
        self.device_table.setGridStyle(Qt.PenStyle.SolidLine)
        
        # Set responsive column widths
        header = self.device_table.horizontalHeader()
        header.setStretchLastSection(False)
        
        # Calculate responsive column widths
        total_width = self.device_table.width() if self.device_table.width() > 0 else 1200
        column_widths = {
            0: int(total_width * 0.12),  # IP Address
            1: int(total_width * 0.15),  # MAC Address
            2: int(total_width * 0.20),  # Hostname (stretch)
            3: int(total_width * 0.15),  # Vendor
            4: int(total_width * 0.12),  # Device Type
            5: int(total_width * 0.10),  # Interface
            6: int(total_width * 0.08),  # Open Ports
            7: int(total_width * 0.08)   # Status
        }
        
        # Apply column widths
        for col, width in column_widths.items():
            self.device_table.setColumnWidth(col, width)
            if col == 2:  # Hostname column stretches
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
            else:
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
        
        # Set table styling
        self.device_table.setStyleSheet("""
            QTableWidget {
                background-color: #2d2d2d;
                color: #ffffff;
                gridline-color: #404040;
                border: 2px solid #404040;
                border-radius: 6px;
                font-size: 10pt;
                selection-background-color: #4CAF50;
                selection-color: #ffffff;
            }
            QTableWidget::item {
                padding: 6px;
                border-bottom: 1px solid #404040;
            }
            QTableWidget::item:selected {
                background-color: #4CAF50;
                color: #ffffff;
            }
            QHeaderView::section {
                background-color: #3d3d3d;
                color: #ffffff;
                padding: 8px;
                border: 1px solid #404040;
                font-weight: bold;
                font-size: 11pt;
            }
            QHeaderView::section:hover {
                background-color: #505050;
            }
            QScrollBar:vertical {
                background-color: #2d2d2d;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #404040;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #505050;
            }
        """)
        
        # Connect selection signal
        self.device_table.itemSelectionChanged.connect(self.on_device_selected)
        
        # Connect double-click signal for toggle blocking
        self.device_table.cellDoubleClicked.connect(self.on_cell_double_clicked)
        
        # Connect context menu
        self.device_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.device_table.customContextMenuRequested.connect(self.show_context_menu)
    
    def connect_signals(self):
        """Connect scanner signals to UI updates"""
        try:
            # Check if scanner is still valid
            if hasattr(self, 'scanner') and self.scanner is not None:
                # Don't connect device_found to avoid conflicts with scan_complete
                # self.scanner.device_found.connect(self.add_device_to_table)
                self.scanner.scan_progress.connect(self.update_progress)
                self.scanner.scan_complete.connect(self.on_scan_complete)
                self.scanner.scan_error.connect(self.on_scan_error)
                self.scanner.status_update.connect(self.update_status)
        except Exception as e:
            log_error(f"Failed to connect scanner signals: {e}")
            # Reinitialize scanner if needed
            try:
                self.scanner = get_enhanced_scanner()
                if self.scanner is not None:
                    self.scanner.scan_progress.connect(self.update_progress)
                    self.scanner.scan_complete.connect(self.on_scan_complete)
                    self.scanner.scan_error.connect(self.on_scan_error)
                    self.scanner.status_update.connect(self.update_status)
            except Exception as e2:
                log_error(f"Failed to reinitialize scanner: {e2}")
    
    def start_scan(self):
        """Start the enhanced network scan"""
        try:
            # Clear previous results
            self.device_table.setRowCount(0)
            self.devices = []
            
            # Record scan start time
            import time
            self.scan_start_time = time.time()
            
            # Update scanner settings
            self.scanner.max_threads = self.thread_spinbox.value()
            self.scanner.timeout = self.timeout_spinbox.value() / 1000.0
            
            # Update UI state
            self.scan_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)
            
            # Start scan
            self.scanner.start()
            self.scan_started.emit()
            
            log_info("Enhanced network scan started")
            
        except Exception as e:
            log_error(f"Error starting scan: {e}", 
                      exception=e, category="network_scan", severity="medium",
                      context={"scanner_type": "enhanced", "devices_count": len(self.devices)})
            self.update_status(f"Error starting scan: {e}")
    
    def stop_scan(self):
        """Stop the network scan"""
        try:
            self.scanner.stop_scan()
            self.update_status("Scan stopped by user")
            self.on_scan_complete(self.devices)
            
        except Exception as e:
            log_error(f"Error stopping scan: {e}", 
                      exception=e, category="network_scan", severity="medium",
                      context={"scanner_type": "enhanced", "devices_count": len(self.devices)})
    
    def on_scan_complete(self, devices: List[Dict]):
        """Handle scan completion - batched population for performance"""
        try:
            log_info(f"Scan completed with {len(devices)} devices")

            # Calculate scan duration
            if hasattr(self, 'scan_start_time'):
                import time as _t
                scan_duration = _t.time() - self.scan_start_time
                log_info(f"Scan duration: {scan_duration:.2f} seconds")

            # Batch populate table
            self.device_table.setSortingEnabled(False)
            self.device_table.setRowCount(0)
            self.device_table.setRowCount(len(devices))
            self.devices = devices[:]  # shallow copy

            for row, device in enumerate(devices):
                self.device_table.setItem(row, 0, QTableWidgetItem(device.get('ip', 'Unknown')))
                self.device_table.setItem(row, 1, QTableWidgetItem(device.get('mac', 'Unknown')))
                self.device_table.setItem(row, 2, QTableWidgetItem(device.get('hostname', 'Unknown')))
                self.device_table.setItem(row, 3, QTableWidgetItem(device.get('vendor', 'Unknown')))
                self.device_table.setItem(row, 4, QTableWidgetItem(device.get('device_type', 'Unknown')))
                self.device_table.setItem(row, 5, QTableWidgetItem('Online'))
                self.device_table.setItem(row, 6, QTableWidgetItem('No'))
                self.device_table.setItem(row, 7, QTableWidgetItem('Online'))

            self.device_table.setSortingEnabled(True)

            # Update status and UI state
            self.update_status(f"Scan completed: {len(devices)} devices found")
            self.progress_bar.setVisible(False)
            self.scan_button.setEnabled(True)
            self.stop_button.setEnabled(False)

            # Update statistics
            self.update_statistics()

            # Emit scan finished signal
            self.scan_finished.emit(devices)

        except Exception as e:
            log_error(
                f"Error handling scan completion: {e}",
                exception=e,
                category="network_scan",
                severity="high",
                context={"devices_count": len(devices) if isinstance(devices, list) else 0, "scanner_type": "enhanced"},
            )
            self.update_status(f"Error completing scan: {e}")
    
    def add_device_to_table(self, device: Dict):
        """Add device to table - OPTIMIZED FOR SPEED"""
        try:
            # Get current row count
            row = self.device_table.rowCount()
            self.device_table.insertRow(row)
            
            # Add device data to table
            self.device_table.setItem(row, 0, QTableWidgetItem(device.get('ip', 'Unknown')))
            self.device_table.setItem(row, 1, QTableWidgetItem(device.get('mac', 'Unknown')))
            self.device_table.setItem(row, 2, QTableWidgetItem(device.get('hostname', 'Unknown')))
            self.device_table.setItem(row, 3, QTableWidgetItem(device.get('vendor', 'Unknown')))
            self.device_table.setItem(row, 4, QTableWidgetItem(device.get('device_type', 'Unknown')))
            self.device_table.setItem(row, 5, QTableWidgetItem('Online'))
            self.device_table.setItem(row, 6, QTableWidgetItem('No'))
            self.device_table.setItem(row, 7, QTableWidgetItem('Online'))
            
            # Color code the device
            self.color_code_device(row, device)
            
            # Avoid per-device status updates to reduce UI churn
            
        except Exception as e:
            log_error(f"Error adding device to table: {e}", 
                      exception=e, category="gui", severity="medium",
                      context={"device_ip": device.get('ip', 'Unknown'), "device_type": device.get('device_type', 'Unknown')})
    
    def color_code_device(self, row: int, device: Dict):
        """Color code device based on type"""
        try:
            device_type = device.get('device_type', '').lower()
            is_local = device.get('local', False)
            
            # Set background color based on device type
            if "gaming console" in device_type:
                color = QColor(255, 200, 200)  # Light red for gaming
            elif "network device" in device_type:
                color = QColor(200, 255, 200)  # Light green for network
            elif "mobile device" in device_type:
                color = QColor(200, 200, 255)  # Light blue for mobile
            elif "computer" in device_type:
                color = QColor(255, 255, 200)  # Light yellow for computer
            else:
                color = QColor(240, 240, 240)  # Light gray for unknown
            
            # Special color for local device
            if is_local:
                color = QColor(255, 255, 150)  # Bright yellow for local
            
            # Apply color to all cells in the row
            for col in range(self.device_table.columnCount()):
                item = self.device_table.item(row, col)
                if item:
                    item.setBackground(color)
                    
        except Exception as e:
            log_error(f"Error color coding device: {e}", 
                      exception=e, category="gui", severity="low",
                      context={"device_ip": device.get('ip', 'Unknown'), "device_type": device.get('device_type', 'Unknown'), "row": row})
    
    def update_progress(self, current: int, total: int):
        """Update progress bar"""
        try:
            if total > 0:
                progress = int((current / total) * 100)
                self.progress_bar.setValue(progress)
        except Exception as e:
            log_error(f"Error updating progress: {e}", 
                      exception=e, category="gui", severity="low",
                      context={"current": current, "total": total})
    
    def on_scan_error(self, error_msg: str):
        """Handle scan errors"""
        try:
            self.update_status(f"Scan error: {error_msg}")
            self.on_scan_complete(self.devices)
            
        except Exception as e:
            log_error(f"Error handling scan error: {e}", 
                      exception=e, category="network_scan", severity="medium",
                      context={"error_msg": error_msg})
    
    def update_status(self, message: str):
        """Update status label"""
        try:
            self.status_label.setText(message)
            
            # Color code status messages
            if "error" in message.lower():
                self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
            elif "complete" in message.lower():
                self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
            elif "scanning" in message.lower():
                self.status_label.setStyleSheet("color: #FF9800; font-weight: bold;")
            else:
                self.status_label.setStyleSheet("color: #2196F3; font-weight: bold;")
                
        except Exception as e:
            log_error(f"Error updating status: {e}", 
                      exception=e, category="gui", severity="low",
                      context={"status_message": message})
    
    def clear_cache(self):
        """Clear the device cache to free memory"""
        try:
            # Clear device dictionaries
            self.devices.clear()
            
            # Clear table data
            self.device_table.setRowCount(0)
            
            # Force garbage collection
            import gc
            gc.collect()
            
            # Refresh the table
            self.refresh_table()
            
            print("Device cache cleared and memory freed")
            
        except Exception as e:
            print(f"Error clearing cache: {e}")
    
    def on_device_selected(self):
        """Handle device selection"""
        try:
            current_row = self.device_table.currentRow()
            if current_row >= 0 and current_row < len(self.devices):
                selected_device = self.devices[current_row]
                self.device_selected.emit(selected_device)
                
        except Exception as e:
            log_error(f"Error handling device selection: {e}", 
                      exception=e, category="gui", severity="low",
                      context={"selected_row": self.device_table.currentRow()})
    
    def on_cell_double_clicked(self, row: int, column: int):
        """Handle double-click on table cell to toggle blocking"""
        try:
            if row < len(self.devices):
                device = self.devices[row]
                ip = device.get('ip', '')
                
                # Toggle blocking status
                current_blocked = device.get('blocked', False)
                new_blocked = not current_blocked
                
                # Update device status
                device['blocked'] = new_blocked
                device['status'] = 'Blocked' if new_blocked else 'Online'
                
                # Update table display
                status_item = QTableWidgetItem(device['status'])
                if new_blocked:
                    status_item.setBackground(QColor(255, 100, 100))  # Red for blocked
                    status_item.setForeground(QColor(255, 255, 255))  # White text
                else:
                    status_item.setBackground(QColor(100, 255, 100))  # Green for online
                    status_item.setForeground(QColor(0, 0, 0))  # Black text
                
                self.device_table.setItem(row, 7, status_item) # Changed from 8 to 7
                
                # Actually block/unblock the device
                self.actually_block_device(ip, new_blocked)
                
                # Update status message
                action = "blocked" if new_blocked else "unblocked"
                self.update_status(f"Device {ip} {action}")
                
                # Emit signal
                self.device_blocked.emit(ip, new_blocked)
                
        except Exception as e:
            log_error(f"Error toggling device blocking: {e}")
    
    def show_context_menu(self, position):
        """Show context menu for device actions"""
        try:
            
            # Get the row under the cursor
            row = self.device_table.rowAt(position.y())
            if row < 0 or row >= len(self.devices):
                return
            
            device = self.devices[row]
            ip = device.get('ip', '')
            is_blocked = device.get('blocked', False)
            is_disconnected = device.get('disconnected', False)
            
            # Create context menu
            menu = QMenu(self)
            
            # Individual device disconnect/reconnect action
            if not is_disconnected:
                disconnect_action = QAction("🔌 Disconnect Device", self)
                disconnect_action.triggered.connect(lambda: self.disconnect_individual_device(row))
                menu.addAction(disconnect_action)
            else:
                reconnect_action = QAction("🔌 Reconnect Device", self)
                reconnect_action.triggered.connect(lambda: self.reconnect_individual_device(row))
                menu.addAction(reconnect_action)
            
            # Toggle blocking action
            toggle_action = QAction("Block Device" if not is_blocked else "Unblock Device", self)
            toggle_action.triggered.connect(lambda: self.toggle_device_blocking(row))
            menu.addAction(toggle_action)
            
            # Add separator
            menu.addSeparator()
            
            # Ping device action
            ping_action = QAction("Ping Device", self)
            ping_action.triggered.connect(lambda: self.ping_device(ip))
            menu.addAction(ping_action)
            
            # Port scan action
            scan_action = QAction("Port Scan", self)
            scan_action.triggered.connect(lambda: self.port_scan_device(ip))
            menu.addAction(scan_action)
            
            # Add separator
            menu.addSeparator()
            
            # Copy IP action
            copy_action = QAction("Copy IP Address", self)
            copy_action.triggered.connect(lambda: self.copy_ip_to_clipboard(ip))
            menu.addAction(copy_action)
            
            # Show menu at cursor position
            menu.exec(self.device_table.mapToGlobal(position))
            
        except Exception as e:
            log_error(f"Error showing context menu: {e}", 
                      exception=e, category="gui", severity="low",
                      context={"row": row, "device_ip": ip})
    
    def disconnect_individual_device(self, row: int):
        """Disconnect a specific individual device"""
        try:
            if row < len(self.devices):
                device = self.devices[row]
                ip = device.get('ip', '')
                
                if not ip:
                    self.update_status("❌ No IP address found for device")
                    return
                
                self.update_status(f"🔄 Disconnecting individual device {ip}...")
                
                # Try to disconnect using available disruptors
                success = False
                
                try:
                    if self.clumsy_network_disruptor:
                        if self.clumsy_network_disruptor.disconnect_device_clumsy(ip, ["drop", "lag"]):
                            success = True
                            log_info(f"Device {ip} disconnected using Clumsy")
                except Exception as e:
                    log_error(f"Clumsy disconnect error for {ip}: {e}")
                
                if not success and self.enterprise_network_disruptor:
                    try:
                        if self.enterprise_network_disruptor.disconnect_device_enterprise(ip, ["arp_spoof", "icmp_flood"]):
                            success = True
                            log_info(f"Device {ip} disconnected using Enterprise")
                    except Exception as e:
                        log_error(f"Enterprise disconnect error for {ip}: {e}")
                
                if success:
                    # Update device status
                    device['disconnected'] = True
                    device['status'] = 'Disconnected'
                    
                    # Update table display
                    status_item = QTableWidgetItem(device['status'])
                    status_item.setBackground(QColor(255, 165, 0))  # Orange for disconnected
                    status_item.setForeground(QColor(255, 255, 255))  # White text
                    self.device_table.setItem(row, 7, status_item)
                    
                    self.update_status(f"✅ Device {ip} disconnected successfully")
                    
                    # Emit signal for other components
                    self.device_blocked.emit(ip, True)
                else:
                    self.update_status(f"❌ Failed to disconnect device {ip}")
                    QMessageBox.warning(
                        self,
                        "Disconnect Failed",
                        f"Failed to disconnect device {ip}.\n\nPlease check the application logs for error details."
                    )
                    
        except Exception as e:
            log_error(f"Error disconnecting individual device: {e}", 
                      exception=e, category="firewall", severity="medium",
                      context={"device_ip": ip, "row": row})
            self.update_status(f"❌ Error disconnecting device {ip}")
    
    def reconnect_individual_device(self, row: int):
        """Reconnect a specific individual device"""
        try:
            if row < len(self.devices):
                device = self.devices[row]
                ip = device.get('ip', '')
                
                if not ip:
                    self.update_status("❌ No IP address found for device")
                    return
                
                self.update_status(f"🔄 Reconnecting individual device {ip}...")
                
                # Try to reconnect using available disruptors
                success = False
                
                try:
                    if self.clumsy_network_disruptor:
                        self.clumsy_network_disruptor.reconnect_device_clumsy(ip)
                        success = True
                        log_info(f"Device {ip} reconnected using Clumsy")
                except Exception as e:
                    log_error(f"Clumsy reconnection error for {ip}: {e}")
                
                if not success and self.enterprise_network_disruptor:
                    try:
                        self.enterprise_network_disruptor.reconnect_device_enterprise(ip)
                        success = True
                        log_info(f"Device {ip} reconnected using Enterprise")
                    except Exception as e:
                        log_error(f"Enterprise reconnection error for {ip}: {e}")
                
                if success:
                    # Update device status
                    device['disconnected'] = False
                    device['status'] = 'Online'
                    
                    # Update table display
                    status_item = QTableWidgetItem(device['status'])
                    status_item.setBackground(QColor(100, 255, 100))  # Green for online
                    status_item.setForeground(QColor(0, 0, 0))  # Black text
                    self.device_table.setItem(row, 7, status_item)
                    
                    self.update_status(f"✅ Device {ip} reconnected successfully")
                    
                    # Emit signal for other components
                    self.device_blocked.emit(ip, False)
                else:
                    self.update_status(f"❌ Failed to reconnect device {ip}")
                    QMessageBox.warning(
                        self,
                        "Reconnect Failed",
                        f"Failed to reconnect device {ip}.\n\nPlease check the application logs for error details."
                    )
                    
        except Exception as e:
            log_error(f"Error reconnecting individual device: {e}", 
                      exception=e, category="firewall", severity="medium",
                      context={"device_ip": ip, "row": row})
            self.update_status(f"❌ Error reconnecting device {ip}")
    
    def _update_table_disconnect_status(self):
        """Update the table display to show disconnect status for all devices"""
        try:
            for row, device in enumerate(self.devices):
                if device.get('disconnected', False):
                    status_item = QTableWidgetItem('Disconnected')
                    status_item.setBackground(QColor(255, 165, 0))  # Orange for disconnected
                    status_item.setForeground(QColor(255, 255, 255))  # White text
                    self.device_table.setItem(row, 7, status_item)
        except Exception as e:
            log_error(f"Error updating table disconnect status: {e}")
    
    def toggle_device_blocking(self, row: int):
        """Toggle blocking for a specific device row"""
        try:
            if row < len(self.devices):
                device = self.devices[row]
                ip = device.get('ip', '')
                
                # Toggle blocking status
                current_blocked = device.get('blocked', False)
                new_blocked = not current_blocked
                
                # Update device status
                device['blocked'] = new_blocked
                device['status'] = 'Blocked' if new_blocked else 'Online'
                
                # Update table display
                status_item = QTableWidgetItem(device['status'])
                if new_blocked:
                    status_item.setBackground(QColor(255, 100, 100))  # Red for blocked
                    status_item.setForeground(QColor(255, 255, 255))  # White text
                else:
                    status_item.setBackground(QColor(100, 255, 100))  # Green for online
                    status_item.setForeground(QColor(0, 0, 0))  # Black text
                
                self.device_table.setItem(row, 7, status_item) # Changed from 8 to 7
                
                # Actually block/unblock the device
                self.actually_block_device(ip, new_blocked)
                
                # Update status message
                action = "blocked" if new_blocked else "unblocked"
                self.update_status(f"Device {ip} {action}")
                
                # Emit signal
                self.device_blocked.emit(ip, new_blocked)
                
        except Exception as e:
            log_error(f"Error toggling device blocking: {e}", 
                      exception=e, category="firewall", severity="medium",
                      context={"device_ip": ip, "block_action": block})
    
    def actually_block_device(self, ip: str, block: bool):
        """Actually block/unblock a device using REAL network disruption - OPTIMIZED"""
        try:
            from app.firewall.blocker import is_admin
            
            # Performance optimization: Reduce logging during operations
            if not self._should_log():
                return
            
            log_info(f"🔍 Starting blocking process for {ip} (block={block})")
            
            # Check if running as Administrator
            if not is_admin():
                self.update_status("⚠️ WARNING: Not running as Administrator. Blocking may not work properly.")
                log_info("Blocking feature used without Administrator privileges")
            
            if self.controller:
                # Performance optimization: Batch UI updates
                self._queue_ui_update(f"Processing {ip}...")
                
                # Use the controller's REAL blocking mechanism
                # toggle_lag returns the new blocked state
                new_blocked_state = self.controller.toggle_lag(ip)
                
                # Performance optimization: Only log critical information
                if block != new_blocked_state:
                    log_error(f"Blocking mismatch for {ip}: expected {block}, got {new_blocked_state}")
                
                # Update the device's blocked status in our local list
                for device in self.devices:
                    if device.get('ip') == ip:
                        device['blocked'] = new_blocked_state
                        break
                
                # Performance optimization: Batch status updates
                if block:
                    if new_blocked_state:
                        self._queue_ui_update(f"Successfully blocked {ip}")
                    else:
                        self._queue_ui_update(f"Failed to block {ip} - Try running as Administrator")
                else:
                    if not new_blocked_state:
                        self._queue_ui_update(f"Successfully unblocked {ip}")
                    else:
                        self._queue_ui_update(f"Failed to unblock {ip} - Try running as Administrator")
                
            else:
                # Fallback to direct firewall blocking
                log_error("❌ No controller available, using fallback blocking")
                self.aggressive_block_device(ip, block)
                
            # Performance optimization: Batch UI updates
            self._schedule_ui_update()
            
        except Exception as e:
            log_error(f"❌ Error blocking device {ip}: {e}")
            self._queue_ui_update(f"Error blocking {ip}: {e}")
    
    def _should_log(self) -> bool:
        """Performance optimization: Throttle logging to prevent spam"""
        current_time = time.time()
        if current_time - self.last_log_time > self.log_throttle_interval:
            self.last_log_time = current_time
            return True
        return False
    
    def _queue_ui_update(self, message: str):
        """Performance optimization: Queue UI updates for batching"""
        self.device_ui_updates.append(message)
    
    def _schedule_ui_update(self):
        """Stability optimization: Schedule batched UI update with safety checks"""
        try:
            if not self.ui_update_timer.isActive():
                # Stability optimization: Increased delay for better stability
                self.ui_update_timer.start(150)  # Update every 150ms for better stability
        except Exception as e:
            log_error(f"Error scheduling UI update: {e}")
            # Fallback: try to update immediately
            try:
                self._perform_batched_ui_update()
            except:
                pass
    
    def _perform_batched_ui_update(self):
        """Stability optimization: Perform batched UI updates with error handling"""
        try:
            if self.device_ui_updates:
                # Combine multiple messages into one update
                combined_message = " | ".join(self.device_ui_updates[-3:])  # Show last 3 messages
                self.update_status(combined_message)
                self.device_ui_updates.clear()
                
                # Update blocking status indicator
                self.update_blocking_status()
                
                # Reset error count on successful update
                self.ui_update_error_count = 0
                
        except Exception as e:
            self.ui_update_error_count += 1
            log_error(f"Error in batched UI update (attempt {self.ui_update_error_count}): {e}")
            
            # If too many errors, clear the queue and reset
            if self.ui_update_error_count >= self.max_ui_update_errors:
                log_warning("Too many UI update errors, clearing queue and resetting")
                self.device_ui_updates.clear()
                self.ui_update_error_count = 0
                
                # Try to recover by updating status
                try:
                    self.update_status("UI update recovered after errors")
                except:
                    pass
    
    def update_blocking_status(self):
        """Update the blocking status indicator"""
        try:
            blocked_count = sum(1 for device in self.devices if device.get('blocked', False))
            total_devices = len(self.devices)
            
            if blocked_count > 0:
                self.blocking_status.setText(f"🔒 Blocking: Active ({blocked_count}/{total_devices} devices blocked)")
                self.blocking_status.setStyleSheet("color: #f44336; font-weight: bold;")
            else:
                self.blocking_status.setText("🔒 Blocking: Inactive")
                self.blocking_status.setStyleSheet("color: #FF9800; font-weight: bold;")
                
        except Exception as e:
            log_error(f"Error updating blocking status: {e}", 
                      exception=e, category="gui", severity="low",
                      context={"blocked_count": blocked_count, "total_devices": total_devices})
    
    def block_with_firewall(self, ip: str, block: bool):
        """Block device using Windows Firewall rules"""
        try:
            import subprocess
            import platform
            
            if platform.system().lower() == "windows":
                if block:
                    # Add firewall rule to block IP
                    rule_name = f"DupeZ_Block_{ip.replace('.', '_')}"
                    cmd = [
                        "netsh", "advfirewall", "firewall", "add", "rule",
                        f"name={rule_name}",
                        "dir=out",
                        "action=block",
                        f"remoteip={ip}",
                        "enable=yes"
                    ]
                else:
                    # Remove firewall rule
                    rule_name = f"DupeZ_Block_{ip.replace('.', '_')}"
                    cmd = [
                        "netsh", "advfirewall", "firewall", "delete", "rule",
                        f"name={rule_name}"
                    ]
                
                # Execute command with admin privileges
                result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
                
                if result.returncode != 0:
                    log_error(f"Firewall command failed: {result.stderr}", 
                              category="firewall", severity="high",
                              context={"device_ip": ip, "command": cmd, "return_code": result.returncode})
                    raise Exception(f"Firewall command failed: {result.stderr}")
                
                log_info(f"Firewall rule {'added' if block else 'removed'} for {ip}")
                
                # Also add route blocking for more aggressive blocking
                if block:
                    self.block_with_route(ip, True)
                else:
                    self.block_with_route(ip, False)
                    
            else:
                # For non-Windows systems, use iptables
                if block:
                    cmd = ["iptables", "-A", "OUTPUT", "-d", ip, "-j", "DROP"]
                else:
                    cmd = ["iptables", "-D", "OUTPUT", "-d", ip, "-j", "DROP"]
                
                result = subprocess.run(cmd, capture_output=True, text=True)
                
                if result.returncode != 0:
                    log_error(f"iptables command failed: {result.stderr}", 
                              category="firewall", severity="high",
                              context={"device_ip": ip, "command": cmd, "return_code": result.returncode})
                    raise Exception(f"iptables command failed: {result.stderr}")
                
                log_info(f"iptables rule {'added' if block else 'removed'} for {ip}")
                
        except Exception as e:
            log_error(f"Error with firewall blocking: {e}", 
                      exception=e, category="firewall", severity="high",
                      context={"device_ip": ip, "block_action": block})
            raise
    
    def block_with_route(self, ip: str, block: bool):
        """Block device using route table manipulation"""
        try:
            import subprocess
            import platform
            
            if platform.system().lower() == "windows":
                if block:
                    # Add a blackhole route to the IP
                    cmd = [
                        "route", "add", ip, "mask", "255.255.255.255", "0.0.0.0", "metric", "1"
                    ]
                else:
                    # Remove the blackhole route
                    cmd = [
                        "route", "delete", ip
                    ]
                
                # Execute command with admin privileges
                result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
                
                if result.returncode != 0 and "already exists" not in result.stderr:
                    log_error(f"Route command failed: {result.stderr}")
                    # Don't raise exception for route commands as they might fail for various reasons
                
                log_info(f"Route {'added' if block else 'removed'} for {ip}")
                
        except Exception as e:
            log_error(f"Error with route blocking: {e}", 
                      exception=e, category="firewall", severity="high",
                      context={"device_ip": ip, "block_action": block})
            # Don't raise exception for route blocking as it's secondary
    
    def aggressive_block_device(self, ip: str, block: bool):
        """Aggressive blocking that tries multiple methods"""
        try:
            # Method 1: Firewall rules
            self.block_with_firewall(ip, block)
            
            # Method 2: Route table manipulation
            self.block_with_route(ip, block)
            
            # Method 3: ARP poisoning (for local network)
            if self.is_local_network(ip):
                self.block_with_arp(ip, block)
            
            # Method 4: DNS blocking
            self.block_with_dns(ip, block)
            
            log_info(f"Aggressive blocking {'enabled' if block else 'disabled'} for {ip}")
            
        except Exception as e:
            log_error(f"Error with aggressive blocking: {e}", 
                      exception=e, category="firewall", severity="high",
                      context={"device_ip": ip, "block_action": block, "method": "aggressive"})
            raise
    
    def is_local_network(self, ip: str) -> bool:
        """Check if IP is on local network"""
        try:
            import socket
            
            # Get local IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            
            # Extract network prefix
            local_parts = local_ip.split('.')
            ip_parts = ip.split('.')
            
            # Check if same network (assuming /24)
            return local_parts[:3] == ip_parts[:3]
            
        except:
            return False
    
    def block_with_arp(self, ip: str, block: bool):
        """Block device using ARP poisoning"""
        try:
            import subprocess
            import platform
            
            if platform.system().lower() == "windows":
                if block:
                    # Add static ARP entry pointing to invalid MAC
                    cmd = [
                        "arp", "-s", ip, "00-00-00-00-00-00"
                    ]
                else:
                    # Remove static ARP entry
                    cmd = [
                        "arp", "-d", ip
                    ]
                
                result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
                
                if result.returncode != 0:
                    log_error(f"ARP command failed: {result.stderr}", 
                              category="firewall", severity="medium",
                              context={"device_ip": ip, "command": cmd, "return_code": result.returncode})
                
                log_info(f"ARP entry {'added' if block else 'removed'} for {ip}")
                
        except Exception as e:
            log_error(f"Error with ARP blocking: {e}", 
                      exception=e, category="firewall", severity="medium",
                      context={"device_ip": ip, "block_action": block})
    
    def block_with_dns(self, ip: str, block: bool):
        """Block device using DNS manipulation"""
        try:
            import subprocess
            import platform
            
            if platform.system().lower() == "windows":
                # This would require modifying hosts file or DNS settings
                # For now, just log the attempt
                log_info(f"DNS blocking {'requested' if block else 'removed'} for {ip}")
                
        except Exception as e:
            log_error(f"Error with DNS blocking: {e}", 
                      exception=e, category="firewall", severity="medium",
                      context={"device_ip": ip, "block_action": block})
    
    def ping_device(self, ip: str):
        """Ping a device to check connectivity"""
        try:
            import subprocess
            import platform
            
            if platform.system().lower() == "windows":
                cmd = ["ping", "-n", "4", ip]
            else:
                cmd = ["ping", "-c", "4", ip]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                self.update_status(f"Ping to {ip}: Success")
            else:
                self.update_status(f"Ping to {ip}: Failed")
                
        except Exception as e:
            log_error(f"Error pinging {ip}: {e}", 
                      exception=e, category="network_scan", severity="low",
                      context={"device_ip": ip, "action": "ping"})
            self.update_status(f"Error pinging {ip}: {e}")
    
    def port_scan_device(self, ip: str):
        """Perform a quick port scan on a device"""
        try:
            import socket
            
            common_ports = [21, 22, 23, 25, 53, 80, 110, 143, 443, 993, 995, 8080]
            open_ports = []
            
            for port in common_ports:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(1.0)
                    result = sock.connect_ex((ip, port))
                    sock.close()
                    
                    if result == 0:
                        open_ports.append(port)
                except:
                    continue
            
            if open_ports:
                ports_str = ', '.join(map(str, open_ports))
                self.update_status(f"Port scan {ip}: Open ports: {ports_str}")
            else:
                self.update_status(f"Port scan {ip}: No common ports open")
                
        except Exception as e:
            log_error(f"Error port scanning {ip}: {e}", 
                      exception=e, category="network_scan", severity="low",
                      context={"device_ip": ip, "action": "port_scan"})
            self.update_status(f"Error port scanning {ip}: {e}")
    
    def copy_ip_to_clipboard(self, ip: str):
        """Copy IP address to clipboard"""
        try:
            from PyQt6.QtWidgets import QApplication
            clipboard = QApplication.clipboard()
            clipboard.setText(ip)
            self.update_status(f"IP address {ip} copied to clipboard")
        except Exception as e:
            log_error(f"Error copying IP to clipboard: {e}", 
                      exception=e, category="gui", severity="low",
                      context={"device_ip": ip, "action": "copy_to_clipboard"})
            self.update_status(f"Error copying IP to clipboard: {e}")
    
    def clear_devices(self):
        """Clear all devices from the table"""
        try:
            self.device_table.setRowCount(0)
            self.devices = []
            self.update_status("Device list cleared")
            self.update_statistics()
            
        except Exception as e:
            log_error(f"Error clearing devices: {e}", 
                      exception=e, category="gui", severity="low",
                      context={"devices_count": len(self.devices)})
    
    def export_results(self):
        """Export scan results to a file"""
        try:
            if not self.devices:
                self.update_status("No devices to export")
                return
            
            # Create export filename with timestamp
            import datetime
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"network_scan_results_{timestamp}.csv"
            
            # Export to CSV
            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                import csv
                writer = csv.writer(csvfile)
                
                # Write header
                writer.writerow([
                    'IP Address', 'MAC Address', 'Hostname', 'Vendor', 
                    'Device Type', 'Interface', 'Open Ports', 'Status'
                ])
                
                # Write device data
                for device in self.devices:
                    writer.writerow([
                        device.get('ip', ''),
                        device.get('mac', ''),
                        device.get('hostname', ''),
                        device.get('vendor', ''),
                        device.get('device_type', ''),
                        device.get('interface', ''),
                        device.get('open_ports', ''),
                        device.get('status', '')
                    ])
            
            self.update_status(f"Results exported to {filename}")
            log_info(f"Scan results exported to {filename}")
            
        except Exception as e:
            log_error(f"Failed to export results: {e}", 
                      exception=e, category="data_persistence", severity="medium",
                      context={"devices_count": len(self.devices), "export_format": "csv"})
            self.update_status("Export failed")
    
    def update_statistics(self):
        """Update the statistics display"""
        try:
            # Count devices
            total_devices = len(self.devices)
            self.device_count_label.setText(f"Devices Found: {total_devices}")
            
            # Count PS5 devices
            ps5_devices = sum(1 for device in self.devices if self._is_ps5_device(device))
            self.ps5_count_label.setText(f"PS5 Devices: {ps5_devices}")
            
            # Count blocked devices
            blocked_devices = sum(1 for device in self.devices if device.get('blocked', False))
            self.blocked_count_label.setText(f"Blocked Devices: {blocked_devices}")
            
            # Update scan duration if available
            if hasattr(self, 'scan_start_time'):
                import time
                duration = time.time() - self.scan_start_time
                self.scan_duration_label.setText(f"Last Scan: {duration:.1f}s")
            else:
                self.scan_duration_label.setText("Last Scan: Never")
                
        except Exception as e:
            log_error(f"Failed to update statistics: {e}", 
                      exception=e, category="gui", severity="low",
                      context={"devices_count": len(self.devices)})
    
    def block_selected(self):
        """Block selected devices"""
        try:
            selected_rows = set()
            for item in self.device_table.selectedItems():
                selected_rows.add(item.row())
            
            if not selected_rows:
                self.update_status("No devices selected for blocking")
                return
            
            # Block selected devices
            for row in selected_rows:
                if row < len(self.devices):
                    device = self.devices[row]
                    ip = device.get('ip', '')
                    
                    # Update device status
                    device['blocked'] = True
                    device['status'] = 'Blocked'
                    
                    # Update table
                    status_item = QTableWidgetItem('Blocked')
                    status_item.setBackground(QColor(255, 100, 100))
                    self.device_table.setItem(row, 7, status_item) # Changed from 8 to 7
                    
                    # Emit signal
                    self.device_blocked.emit(ip, True)
            
            self.update_status(f"Blocked {len(selected_rows)} selected device(s)")
            
        except Exception as e:
            log_error(f"Error blocking devices: {e}", 
                      exception=e, category="firewall", severity="medium",
                      context={"selected_devices_count": len(selected_devices)})
    
    def block_all_devices(self):
        """Block all devices in the list"""
        try:
            if not self.devices:
                self.update_status("No devices to block")
                return
            
            # Import PS5 blocker
            from app.firewall.ps5_blocker import ps5_blocker
            
            blocked_count = 0
            ps5_ips = []
            
            for i, device in enumerate(self.devices):
                ip = device.get('ip', '')
                if ip and not device.get('blocked', False):
                    # Check if it's a PS5
                    if self._is_ps5_device(device):
                        ps5_ips.append(ip)
                    
                    # Block this device
                    self.actually_block_device(ip, True)
                    device['blocked'] = True
                    device['status'] = 'Blocked'
                    
                    # Update table display
                    status_item = QTableWidgetItem('Blocked')
                    status_item.setBackground(QColor(255, 100, 100))  # Red
                    status_item.setForeground(QColor(255, 255, 255))  # White text
                    self.device_table.setItem(i, 7, status_item)
                    
                    blocked_count += 1
            
            # Block PS5s specifically
            if ps5_ips:
                ps5_blocker.block_all_ps5s(ps5_ips)
                self.update_status(f"Blocked {blocked_count} devices (including {len(ps5_ips)} PS5s)")
            else:
                self.update_status(f"Blocked {blocked_count} devices")
            
            self.update_blocking_status()
            
        except Exception as e:
            log_error(f"Error blocking all devices: {e}", 
                      exception=e, category="firewall", severity="medium",
                      context={"total_devices_count": len(self.devices)})
            self.update_status(f"Error blocking all devices: {e}")
    
    def _is_ps5_device(self, device: dict) -> bool:
        """Check if device is a PS5"""
        try:
            # Check vendor name
            vendor = device.get('vendor', '').lower()
            if 'sony' in vendor or 'playstation' in vendor or 'ps5' in vendor:
                return True
            
            # Check hostname
            hostname = device.get('hostname', '').lower()
            if 'ps5' in hostname or 'playstation' in hostname:
                return True
            
            # Check MAC address (Sony's OUI)
            mac = device.get('mac', '').lower()
            if mac.startswith(('00:50:c2', '00:1f:a7', '00:19:c5')):
                return True
            
            return False
        except:
            return False
    
    def get_methods_description(self, methods: List[str]) -> str:
        """Get user-friendly description of selected methods"""
        method_descriptions = {
            "icmp_spoof": "ICMP Spoof",
            "dns_spoof": "DNS Spoof", 
            "ps5_packets": "PS5 Packets",
            "response_spoof": "Response Spoof",
            "arp_poison": "ARP Poison",
            "udp_interrupt": "UDP Interrupt"
        }
        
        descriptions = [method_descriptions.get(method, method.replace("_", " ").title()) for method in methods]
        return ", ".join(descriptions)
    
    def get_selected_disconnect_methods(self) -> List[str]:
        """Get the selected disconnect methods for DayZ duping"""
        selected_methods = []
        
        if self.icmp_spoof_cb.isChecked():
            selected_methods.append("icmp_spoof")
        if self.dns_spoof_cb.isChecked():
            selected_methods.append("dns_spoof")
        if self.ps5_packets_cb.isChecked():
            selected_methods.append("ps5_packets")
        if self.response_spoof_cb.isChecked():
            selected_methods.append("response_spoof")
        if self.arp_poison_cb.isChecked():
            selected_methods.append("arp_poison")
        if self.udp_interrupt_cb.isChecked():
            selected_methods.append("udp_interrupt")
            
        return selected_methods
    
    def get_udp_status(self) -> Dict:
        """Get UDP tool status for integration"""
        try:
            from app.firewall.udp_port_interrupter import udp_port_interrupter
            return udp_port_interrupter.get_status()
        except Exception as e:
            log_error(f"Error getting UDP status: {e}", 
                      exception=e, category="udp_flood", severity="low",
                      context={"component": "udp_status_check"})
            return {"is_running": False}
    
    def update_udp_status_display(self):
        """Update the status display to show UDP tool status"""
        try:
            udp_status = self.get_udp_status()
            if udp_status.get("is_running", False):
                self.update_status("🎮 UDP Tool: ACTIVE - Working with disconnect mode")
            else:
                self.update_status("🎮 UDP Tool: INACTIVE")
        except Exception as e:
            log_error(f"Error updating UDP status display: {e}", 
                      exception=e, category="gui", severity="low",
                      context={"udp_status": udp_status})
    
    def check_udp_tool_status(self):
        """Check if UDP tool is active and update button text"""
        try:
            udp_status = self.get_udp_status()
            if udp_status.get("is_running", False):
                # Update button to show UDP is active
                if hasattr(self, 'internet_drop_button'):
                    self.internet_drop_button.setText("🔌 Reconnect (UDP Active)")
            else:
                # Update button to normal state
                if hasattr(self, 'internet_drop_button'):
                    self.internet_drop_button.setText("🔌 Disconnect")
        except Exception as e:
            track_error(f"Error checking UDP tool status: {e}", 
                      exception=e, category="udp_flood", severity="low",
                      context={"component": "udp_tool_status_check"})
    
    def toggle_internet_drop(self):
        """Toggle internet drop for all devices with comprehensive cleanup - OPTIMIZED"""
        try:
            # Check for administrator privileges
            if not is_admin():
                QMessageBox.critical(
                    self, 
                    "Administrator Privileges Required",
                    "Network disruption requires Administrator privileges.\n\n"
                    "Right-click DupeZ.exe and select 'Run as Administrator'"
                )
                return
            
            # Performance optimization: Prevent multiple simultaneous operations
            if self.operation_in_progress:
                log_warning("Operation already in progress, skipping")
                return
            
            self.operation_in_progress = True
            
            # Initialize disruptors with better error handling
            clumsy_available = False
            enterprise_available = False
            
            try:
                if clumsy_network_disruptor.initialize():
                    clumsy_available = True
                    log_info("Clumsy network disruptor initialized successfully")
                else:
                    log_warning("Clumsy network disruptor initialization failed")
            except Exception as e:
                log_error(f"Clumsy initialization error: {e}")
            
            try:
                if enterprise_network_disruptor.initialize():
                    enterprise_available = True
                    log_info("Enterprise network disruptor initialized successfully")
                else:
                    log_warning("Enterprise network disruptor initialization failed")
            except Exception as e:
                log_error(f"Enterprise initialization error: {e}")
            
            # Check if at least one disruptor is available
            if not clumsy_available and not enterprise_available:
                QMessageBox.critical(
                    self,
                    "Network Disruptor Initialization Failed",
                    "Both Clumsy and Enterprise disruptors failed to initialize.\n\n"
                    "Common causes:\n"
                    "• Missing WinDivert files (WinDivert.dll, WinDivert64.sys)\n"
                    "• Missing clumsy.exe in app/firewall directory\n"
                    "• Insufficient Administrator privileges\n\n"
                    "Please check the application logs for detailed error information."
                )
                self.operation_in_progress = False
                return
            
            if not self.disconnect_active:
                # Start disconnect mode - TEMPORARY, not permanent
                self.disconnect_active = True
                self.internet_drop_button.setText("🔌 Reconnect All")
                self.internet_drop_button.setStyleSheet("background-color: #f44336; color: white;")
                
                # Update status
                self.update_status("🔄 Disconnecting ALL devices (TEMPORARY)...")
                
                # Disconnect each device with performance optimization
                success_count = 0
                total_devices = len(self.devices)
                
                for device in self.devices:
                    try:
                        device_ip = device.get('ip', '')
                        if device_ip:
                            # Performance optimization: Batch status updates
                            self._queue_ui_update(f"Disconnecting {device_ip}...")
                            
                            # Try Clumsy first, then Enterprise as fallback
                            if self.clumsy_network_disruptor and self.clumsy_network_disruptor.disconnect_device_clumsy(device_ip, ["drop", "lag"]):
                                success_count += 1
                                # Update device status to disconnected
                                device['disconnected'] = True
                                device['status'] = 'Disconnected'
                                # Performance optimization: Reduce logging
                                if self._should_log():
                                    log_info(f"Device {device_ip} disconnected using Clumsy")
                            elif self.enterprise_network_disruptor and self.enterprise_network_disruptor.disconnect_device_enterprise(device_ip, ["arp_spoof", "icmp_flood"]):
                                success_count += 1
                                # Update device status to disconnected
                                device['disconnected'] = True
                                device['status'] = 'Disconnected'
                                if self._should_log():
                                    log_info(f"Device {device_ip} disconnected using Enterprise")
                            else:
                                log_warning(f"Failed to disconnect device {device_ip}")
                            
                            # Small delay to prevent overwhelming the system
                            time.sleep(0.05)  # Reduced from 0.1 to 0.05
                            
                    except Exception as e:
                        log_error(f"Error disconnecting device {device.get('ip', 'Unknown')}: {e}")
                
                # Update table display for all devices
                self._update_table_disconnect_status()
                
                # Schedule UI update
                self._schedule_ui_update()
                
                # Final status update
                if success_count == total_devices:
                    self.update_status(f"✅ All {success_count} devices disconnected (TEMPORARY)")
                    QMessageBox.information(
                        self,
                        "Disconnect All Mode Active",
                        f"Successfully disconnected {success_count} out of {total_devices} devices.\n\n"
                        "⚠️ IMPORTANT: This is TEMPORARY and will be restored when you reconnect.\n"
                        "All devices are now in disconnect mode.\n\n"
                        "💡 Tip: Use right-click on individual devices to disconnect/reconnect specific devices."
                    )
                elif success_count > 0:
                    self.update_status(f"⚠️ {success_count}/{total_devices} devices disconnected (TEMPORARY)")
                    QMessageBox.information(
                        self,
                        "Partial Disconnect Success",
                        f"Disconnected {success_count} out of {total_devices} devices.\n\n"
                        "⚠️ IMPORTANT: This is TEMPORARY and will be restored when you reconnect.\n"
                        "Some devices may still be connected. Check the logs for details.\n\n"
                        "💡 Tip: Use right-click on individual devices to disconnect/reconnect specific devices."
                    )
                else:
                    self.update_status("❌ Failed to disconnect any devices")
                    QMessageBox.warning(
                        self,
                        "Disconnect Failed",
                        "Failed to disconnect any devices.\n\n"
                        "Please check the application logs for error details."
                    )
                    # Reset disconnect state since it failed
                    self.disconnect_active = False
                    self.internet_drop_button.setText("🔌 Disconnect All")
                    self.internet_drop_button.setStyleSheet("background-color: #4caf50; color: white;")
                
            else:
                # Reconnect mode - CRITICAL: Ensure complete cleanup for TEMPORARY disruption
                self.update_status("🔄 Reconnecting devices and restoring network...")
                
                # First, clear all disruptions from both disruptors
                self._clear_all_disruptions_comprehensive()
                
                # Then reconnect each device individually
                success_count = 0
                total_devices = len(self.devices)
                
                for device in self.devices:
                    try:
                        device_ip = device.get('ip', '')
                        if device_ip:
                            # Performance optimization: Batch status updates
                            self._queue_ui_update(f"Reconnecting {device_ip}...")
                            
                            # Force reconnection through both disruptors
                            reconnected = False
                            
                            try:
                                if self.clumsy_network_disruptor:
                                    self.clumsy_network_disruptor.reconnect_device_clumsy(device_ip)
                                    reconnected = True
                                    if self._should_log():
                                        log_info(f"Device {device_ip} reconnected using Clumsy")
                            except Exception as e:
                                log_error(f"Clumsy reconnection error for {device_ip}: {e}")
                            
                            try:
                                if self.enterprise_network_disruptor:
                                    self.enterprise_network_disruptor.reconnect_device_enterprise(device_ip)
                                    reconnected = True
                                    if self._should_log():
                                        log_info(f"Device {device_ip} reconnected using Enterprise")
                            except Exception as e:
                                log_error(f"Enterprise reconnection error for {device_ip}: {e}")
                            
                            if reconnected:
                                success_count += 1
                            
                            # Small delay
                            time.sleep(0.05)  # Reduced from 0.1 to 0.05
                            
                    except Exception as e:
                        log_error(f"Error reconnecting device {device.get('ip', 'Unknown')}: {e}")
                
                # Final comprehensive cleanup
                self._final_network_restoration()
                
                # Reset disconnect state
                self.disconnect_active = False
                self.internet_drop_button.setText("🔌 Disconnect All")
                self.internet_drop_button.setStyleSheet("background-color: #4caf50; color: white;")
                
                # Schedule UI update
                self._schedule_ui_update()
                
                # Final status update
                if success_count == total_devices:
                    self.update_status(f"✅ All {success_count} devices reconnected successfully")
                    QMessageBox.information(
                        self,
                        "Reconnect Complete",
                        f"Successfully reconnected {success_count} out of {total_devices} devices.\n\n"
                        "✅ All devices are now back online and network has been restored.\n"
                        "The temporary disruption has been completely removed."
                    )
                elif success_count > 0:
                    self.update_status(f"⚠️ {success_count}/{total_devices} devices reconnected")
                    QMessageBox.information(
                        self,
                        "Partial Reconnect Success",
                        f"Reconnected {success_count} out of {total_devices} devices.\n\n"
                        "⚠️ Some devices may still be disconnected. Check the logs for details.\n"
                        "Use the Emergency Restore button if needed."
                    )
                else:
                    self.update_status("❌ Failed to reconnect any devices")
                    QMessageBox.warning(
                        self,
                        "Reconnect Failed",
                        "Failed to reconnect any devices.\n\n"
                        "⚠️ CRITICAL: Your network may be permanently blocked.\n"
                        "Please use the Emergency Restore button or restart your computer."
                    )
            
            # Reset operation flag
            self.operation_in_progress = False
                
        except Exception as e:
            log_error(f"Error in toggle_internet_drop: {e}")
            track_error("toggle_internet_drop", str(e))
            
            # Reset operation flag
            self.operation_in_progress = False
            
            # Reset disconnect state on error
            self.disconnect_active = False
            self.internet_drop_button.setText("🔌 Disconnect All")
            self.internet_drop_button.setStyleSheet("background-color: #4caf50; color: white;")
            
            self.update_status("❌ Error occurred during disconnect/reconnect")
            QMessageBox.critical(
                self,
                "Error",
                f"An error occurred: {str(e)}\n\nPlease check the application logs for details."
            )
    
    def _clear_all_disruptions_comprehensive(self):
        """Comprehensive cleanup of all network disruptions"""
        try:
            log_info("Starting comprehensive network disruption cleanup...")
            
            # Clear all Clumsy disruptions
            try:
                if self.clumsy_network_disruptor:
                    self.clumsy_network_disruptor.clear_all_disruptions_clumsy()
                    log_info("Cleared all Clumsy disruptions")
            except Exception as e:
                log_error(f"Error clearing Clumsy disruptions: {e}")
            
            # Clear all Enterprise disruptions
            try:
                if self.enterprise_network_disruptor:
                    self.enterprise_network_disruptor.clear_all_disruptions_enterprise()
                    log_info("Cleared all Enterprise disruptions")
            except Exception as e:
                log_error(f"Error clearing Enterprise disruptions: {e}")
            
            # Clear any remaining firewall rules
            self._clear_remaining_firewall_rules()
            
            # Clear any remaining network configurations
            self._clear_remaining_network_configs()
            
            log_info("Comprehensive disruption cleanup completed")
            
        except Exception as e:
            log_error(f"Error in comprehensive cleanup: {e}")
    
    def _clear_remaining_firewall_rules(self):
        """Clear any remaining firewall rules that might have been created"""
        try:
            log_info("Clearing remaining firewall rules...")
            
            # Clear Windows Firewall rules
            if platform.system() == "Windows":
                # Clear any rules that might have been created
                clear_commands = [
                    'netsh advfirewall firewall delete rule name="DupeZ_*"',
                    'netsh advfirewall firewall delete rule name="Enterprise_*"',
                    'netsh advfirewall firewall delete rule name="Clumsy_*"'
                ]
                
                for cmd in clear_commands:
                    try:
                        subprocess.run(cmd, shell=True, capture_output=True, timeout=10)
                    except:
                        pass
                
                log_info("Cleared remaining firewall rules")
                
        except Exception as e:
            log_error(f"Error clearing firewall rules: {e}")
    
    def _clear_remaining_network_configs(self):
        """Clear any remaining network configurations"""
        try:
            log_info("Clearing remaining network configurations...")
            
            if platform.system() == "Windows":
                # Clear any static routes that might have been added
                try:
                    # Get current routes and remove any suspicious ones
                    result = subprocess.run('route print', shell=True, capture_output=True, text=True, timeout=10)
                    if result.returncode == 0:
                        lines = result.stdout.split('\n')
                        for line in lines:
                            if '0.0.0.0' in line and ('192.168.' in line or '10.' in line):
                                # This might be a problematic route, try to remove it
                                parts = line.split()
                                if len(parts) >= 4:
                                    target = parts[0]
                                    try:
                                        subprocess.run(f'route delete {target}', shell=True, capture_output=True, timeout=5)
                                    except:
                                        pass
                except:
                    pass
                
                # Clear any ARP cache entries
                try:
                    subprocess.run('arp -d', shell=True, capture_output=True, timeout=5)
                except:
                    pass
                
                log_info("Cleared remaining network configurations")
                
        except Exception as e:
            log_error(f"Error clearing network configurations: {e}")
    
    def _final_network_restoration(self):
        """Final network restoration steps"""
        try:
            log_info("Performing final network restoration...")
            
            # Flush DNS cache
            try:
                if platform.system() == "Windows":
                    subprocess.run('ipconfig /flushdns', shell=True, capture_output=True, timeout=10)
                    log_info("DNS cache flushed")
            except:
                pass
            
            # Reset network adapters if needed
            try:
                if platform.system() == "Windows":
                    # Reset TCP/IP stack
                    subprocess.run('netsh int ip reset', shell=True, capture_output=True, timeout=10)
                    subprocess.run('netsh winsock reset', shell=True, capture_output=True, timeout=10)
                    log_info("Network stack reset completed")
            except:
                pass
            
            log_info("Final network restoration completed")
            
        except Exception as e:
            log_error(f"Error in final network restoration: {e}")
    
    def emergency_network_restoration(self):
        """Emergency network restoration for permanently blocked devices"""
        try:
            # Show confirmation dialog
            reply = QMessageBox.question(
                self,
                "Emergency Network Restoration",
                "This will perform a COMPLETE network restoration including:\n\n"
                "• Stop all network disruptions\n"
                "• Clear all firewall rules\n"
                "• Reset network configurations\n"
                "• Flush DNS and ARP caches\n"
                "• Reset TCP/IP stack\n\n"
                "This may take several minutes and require a restart.\n\n"
                "Continue with emergency restoration?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply != QMessageBox.StandardButton.Yes:
                return
            
            self.update_status("🚨 Starting emergency network restoration...")
            
            # Step 1: Stop all disruptions
            self.update_status("🔄 Step 1/6: Stopping all network disruptions...")
            self._clear_all_disruptions_comprehensive()
            
            # Step 2: Clear all firewall rules
            self.update_status("🔄 Step 2/6: Clearing all firewall rules...")
            self._emergency_firewall_cleanup()
            
            # Step 3: Clear network configurations
            self.update_status("🔄 Step 3/6: Clearing network configurations...")
            self._emergency_network_cleanup()
            
            # Step 4: Reset network stack
            self.update_status("🔄 Step 4/6: Resetting network stack...")
            self._emergency_network_stack_reset()
            
            # Step 5: Flush all caches
            self.update_status("🔄 Step 5/6: Flushing network caches...")
            self._emergency_cache_flush()
            
            # Step 6: Final cleanup
            self.update_status("🔄 Step 6/6: Final cleanup...")
            self._emergency_final_cleanup()
            
            # Reset disconnect state
            self.disconnect_active = False
            self.internet_drop_button.setText("🔌 Disconnect All")
            self.internet_drop_button.setStyleSheet("background-color: #4caf50; color: white;")
            
            self.update_status("✅ Emergency network restoration completed!")
            
            QMessageBox.information(
                self,
                "Emergency Restoration Complete",
                "Emergency network restoration has been completed!\n\n"
                "Your network should now be fully restored.\n\n"
                "If you still experience issues, please restart your computer."
            )
            
        except Exception as e:
            log_error(f"Error in emergency network restoration: {e}")
            track_error("emergency_network_restoration", str(e))
            
            self.update_status("❌ Emergency restoration failed - check logs")
            QMessageBox.critical(
                self,
                "Emergency Restoration Failed",
                f"Emergency network restoration failed: {str(e)}\n\n"
                "Please check the application logs for details."
            )
    
    def _emergency_firewall_cleanup(self):
        """Emergency firewall cleanup"""
        try:
            if platform.system() == "Windows":
                # Clear all possible firewall rules
                clear_commands = [
                    'netsh advfirewall firewall delete rule name="DupeZ_*"',
                    'netsh advfirewall firewall delete rule name="Enterprise_*"',
                    'netsh advfirewall firewall delete rule name="Clumsy_*"',
                    'netsh advfirewall firewall delete rule name="Block_*"',
                    'netsh advfirewall firewall delete rule name="Drop_*"',
                    'netsh advfirewall firewall delete rule name="Lag_*"'
                ]
                
                for cmd in clear_commands:
                    try:
                        subprocess.run(cmd, shell=True, capture_output=True, timeout=10)
                    except:
                        pass
                
                log_info("Emergency firewall cleanup completed")
                
        except Exception as e:
            log_error(f"Error in emergency firewall cleanup: {e}")
    
    def _emergency_network_cleanup(self):
        """Emergency network configuration cleanup"""
        try:
            if platform.system() == "Windows":
                # Clear all static routes
                try:
                    result = subprocess.run('route print', shell=True, capture_output=True, text=True, timeout=10)
                    if result.returncode == 0:
                        lines = result.stdout.split('\n')
                        for line in lines:
                            if any(ip in line for ip in ['192.168.', '10.', '172.']):
                                parts = line.split()
                                if len(parts) >= 4:
                                    target = parts[0]
                                    try:
                                        subprocess.run(f'route delete {target}', shell=True, capture_output=True, timeout=5)
                                    except:
                                        pass
                except:
                    pass
                
                # Clear ARP cache
                try:
                    subprocess.run('arp -d', shell=True, capture_output=True, timeout=5)
                except:
                    pass
                
                # Clear IP configuration
                try:
                    subprocess.run('ipconfig /release', shell=True, capture_output=True, timeout=10)
                    subprocess.run('ipconfig /renew', shell=True, capture_output=True, timeout=10)
                except:
                    pass
                
                log_info("Emergency network cleanup completed")
                
        except Exception as e:
            log_error(f"Error in emergency network cleanup: {e}")
    
    def _emergency_network_stack_reset(self):
        """Emergency network stack reset"""
        try:
            if platform.system() == "Windows":
                # Reset TCP/IP stack
                subprocess.run('netsh int ip reset', shell=True, capture_output=True, timeout=15)
                subprocess.run('netsh winsock reset', shell=True, capture_output=True, timeout=15)
                
                # Reset network adapters
                subprocess.run('netsh int ip set dns "Local Area Connection" dhcp', shell=True, capture_output=True, timeout=10)
                subprocess.run('netsh int ip set wins "Local Area Connection" dhcp', shell=True, capture_output=True, timeout=10)
                
                log_info("Emergency network stack reset completed")
                
        except Exception as e:
            log_error(f"Error in emergency network stack reset: {e}")
    
    def _emergency_cache_flush(self):
        """Emergency cache flush"""
        try:
            if platform.system() == "Windows":
                # Flush DNS cache
                subprocess.run('ipconfig /flushdns', shell=True, capture_output=True, timeout=10)
                
                # Flush NetBIOS cache
                subprocess.run('nbtstat -R', shell=True, capture_output=True, timeout=10)
                subprocess.run('nbtstat -RR', shell=True, capture_output=True, timeout=10)
                
                # Flush ARP cache
                subprocess.run('arp -d', shell=True, capture_output=True, timeout=5)
                
                log_info("Emergency cache flush completed")
                
        except Exception as e:
            log_error(f"Error in emergency cache flush: {e}")
    
    def _emergency_final_cleanup(self):
        """Emergency final cleanup"""
        try:
            # Restart network services
            if platform.system() == "Windows":
                services = ['Dnscache', 'Dhcp', 'Netman']
                for service in services:
                    try:
                        subprocess.run(f'net stop {service}', shell=True, capture_output=True, timeout=10)
                        subprocess.run(f'net start {service}', shell=True, capture_output=True, timeout=10)
                    except:
                        pass
                
                log_info("Emergency final cleanup completed")
                
        except Exception as e:
            log_error(f"Error in emergency final cleanup: {e}")
    
    def unblock_all_devices(self):
        """Unblock all devices in the list"""
        try:
            if not self.devices:
                self.update_status("No devices to unblock")
                return
            
            # Import PS5 blocker
            from app.firewall.ps5_blocker import ps5_blocker
            
            unblocked_count = 0
            ps5_ips = []
            
            for i, device in enumerate(self.devices):
                ip = device.get('ip', '')
                if ip and device.get('blocked', False):
                    # Check if it's a PS5
                    if self._is_ps5_device(device):
                        ps5_ips.append(ip)
                    
                    # Unblock this device
                    self.actually_block_device(ip, False)
                    device['blocked'] = False
                    device['status'] = 'Online'
                    
                    # Update table display
                    status_item = QTableWidgetItem('Online')
                    status_item.setBackground(QColor(100, 255, 100))  # Green
                    status_item.setForeground(QColor(0, 0, 0))  # Black text
                    self.device_table.setItem(i, 7, status_item)
                    
                    unblocked_count += 1
            
            # Unblock PS5s specifically
            if ps5_ips:
                ps5_blocker.unblock_all_ps5s(ps5_ips)
                self.update_status(f"Unblocked {unblocked_count} devices (including {len(ps5_ips)} PS5s)")
            else:
                self.update_status(f"Unblocked {unblocked_count} devices")
            
            self.update_blocking_status()
            
        except Exception as e:
            track_error(f"Error unblocking all devices: {e}", 
                      exception=e, category="firewall", severity="medium",
                      context={"total_devices_count": len(self.devices)})
            self.update_status(f"Error unblocking all devices: {e}")
    
    def clear_all_blocks(self):
        """Clear all blocks and restore network"""
        try:
            from app.firewall.blocker import clear_all_blocks
            from app.firewall.ps5_blocker import ps5_blocker
            
            # Clear all blocks using the blocker module
            success = clear_all_blocks()
            
            # Clear PS5 blocks specifically
            ps5_success = ps5_blocker.clear_all_ps5_blocks()
            
            if success and ps5_success:
                # Update all devices to unblocked status
                for i, device in enumerate(self.devices):
                    device['blocked'] = False
                    device['status'] = 'Online'
                    
                    # Update table display
                    status_item = QTableWidgetItem('Online')
                    status_item.setBackground(QColor(100, 255, 100))  # Green
                    status_item.setForeground(QColor(0, 0, 0))  # Black text
                    self.device_table.setItem(i, 7, status_item)
                
                self.update_status("All blocks cleared successfully (including PS5s)")
                self.update_blocking_status()
            else:
                self.update_status("Failed to clear all blocks")
                
        except Exception as e:
            log_error(f"Error clearing all blocks: {e}", 
                      exception=e, category="firewall", severity="medium",
                      context={"total_devices_count": len(self.devices)})
            self.update_status(f"Error clearing blocks: {e}")
    
    def get_selected_devices(self) -> List[Dict]:
        """Get selected devices from the table"""
        selected_devices = []
        
        try:
            # Get selected rows
            selected_rows = set()
            for item in self.device_table.selectedItems():
                selected_rows.add(item.row())
            
            # Get device data for selected rows
            for row in selected_rows:
                if row < len(self.devices):
                    device = self.devices[row].copy()
                    selected_devices.append(device)
            
            # If no devices selected, use all devices
            if not selected_devices and self.devices:
                selected_devices = self.devices.copy()
                
        except Exception as e:
            log_error(f"Error getting selected devices: {e}", 
                      exception=e, category="gui", severity="low",
                      context={"total_devices_count": len(self.devices)})
            
        return selected_devices
    
    def get_device_count(self) -> int:
        """Get total number of devices"""
        return len(self.devices)
    
    def apply_styling(self):
        """Apply modern styling to the widget"""
        self.setStyleSheet("""
            QWidget {
                background-color: #2d2d2d;
                color: #ffffff;
            }
            QPushButton {
                background-color: #3d3d3d;
                border: 2px solid #4a4a4a;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
                color: #ffffff;
            }
            QPushButton:hover {
                background-color: #4d4d4d;
                border-color: #5a5a5a;
            }
            QPushButton:pressed {
                background-color: #2d2d2d;
                border-color: #3a3a3a;
            }
            QPushButton:disabled {
                background-color: #1a1a1a;
                border-color: #333333;
                color: #666666;
            }
            QTableWidget {
                background-color: #1e1e1e;
                border: 2px solid #4a4a4a;
                border-radius: 6px;
                alternate-background-color: #252525;
                gridline-color: #3a3a3a;
            }
            QTableWidget::item {
                padding: 6px;
                border-bottom: 1px solid #3a3a3a;
            }
            QTableWidget::item:selected {
                background-color: #4CAF50;
                color: #ffffff;
            }
            QHeaderView::section {
                background-color: #3d3d3d;
                color: #ffffff;
                padding: 8px;
                border: 1px solid #4a4a4a;
                font-weight: bold;
            }
            QProgressBar {
                border: 1px solid #555555;
                background-color: #1e1e1e;
                text-align: center;
                border-radius: 4px;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                border-radius: 4px;
            }
            QSpinBox {
                background-color: #3d3d3d;
                border: 1px solid #4a4a4a;
                border-radius: 4px;
                padding: 4px;
                color: #ffffff;
            }
            QCheckBox {
                color: #ffffff;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border: 2px solid #4a4a4a;
                border-radius: 3px;
                background-color: #2d2d2d;
            }
            QCheckBox::indicator:checked {
                background-color: #4CAF50;
                border-color: #4CAF50;
            }
        """)
    
    def search_for_device(self, search_term: str, search_field: str = "All Fields") -> List[Dict]:
        """Search for devices by various criteria"""
        try:
            if not self.devices:
                log_info("No devices to search")
                return []
            
            search_term = search_term.lower().strip()
            results = []
            
            for device in self.devices:
                match_found = False
                
                if search_field == "All Fields":
                    # Search in all fields
                    for field in ['ip', 'hostname', 'vendor', 'mac', 'device_type']:
                        if search_term in str(device.get(field, '')).lower():
                            match_found = True
                            break
                else:
                    # Search in specific field
                    field_map = {
                        "IP Address": "ip",
                        "Hostname": "hostname", 
                        "Vendor": "vendor",
                        "MAC Address": "mac"
                    }
                    
                    field_name = field_map.get(search_field, "ip")
                    if search_term in str(device.get(field_name, '')).lower():
                        match_found = True
                
                if match_found:
                    results.append(device)
            
            log_info(f"Search for '{search_term}' in '{search_field}' found {len(results)} devices")
            return results
            
        except Exception as e:
            log_error(f"Error searching for devices: {e}", 
                      exception=e, category="gui", severity="low",
                      context={"search_term": search_term, "search_field": search_field})
            return []
    
    def filter_devices_by_search(self, search_term: str):
        """Filter the device table by search term"""
        try:
            if not search_term.strip():
                # Show all devices if search is empty
                for row in range(self.device_table.rowCount()):
                    self.device_table.setRowHidden(row, False)
                return
            
            search_term = search_term.lower().strip()
            
            for row in range(self.device_table.rowCount()):
                if row >= len(self.devices):
                    continue
                    
                device = self.devices[row]
                match_found = False
                
                # Search in all device fields
                for field in ['ip', 'hostname', 'vendor', 'mac', 'device_type']:
                    if search_term in str(device.get(field, '')).lower():
                        match_found = True
                        break
                
                # Show/hide row based on match
                self.device_table.setRowHidden(row, not match_found)
            
            log_info(f"Filtered devices by search term: '{search_term}'")
            
        except Exception as e:
            log_error(f"Error filtering devices: {e}", 
                      exception=e, category="gui", severity="low",
                      context={"search_term": search_term, "devices_count": len(self.devices)})
    
    def add_search_input(self):
        """Add search input field to the control panel"""
        try:
            # Create search input
            self.search_input = QLineEdit()
            self.search_input.setPlaceholderText("🔍 Search devices...")
            self.search_input.setStyleSheet("""
                QLineEdit {
                    background-color: #3d3d3d;
                    color: #ffffff;
                    border: 2px solid #404040;
                    border-radius: 4px;
                    padding: 5px;
                    min-height: 25px;
                    font-size: 10px;
                }
                QLineEdit:focus {
                    border-color: #4CAF50;
                }
            """)
            
            # Connect search input to filter function
            self.search_input.textChanged.connect(self.filter_devices_by_search)
            
            # Add search input to control panel
            search_layout = QHBoxLayout()
            search_layout.addWidget(QLabel("Search:"))
            search_layout.addWidget(self.search_input)
            
            # Add to the control panel layout
            if hasattr(self, 'control_panel'):
                self.control_panel.layout().addLayout(search_layout)
            
        except Exception as e:
            log_error(f"Error adding search input: {e}", 
                      exception=e, category="gui", severity="low",
                      context={"component": "search_input"})
    
    def cleanup(self):
        """Cleanup method to ensure temporary blocks are removed"""
        try:
            log_info("EnhancedDeviceList cleanup started")
            
            # Clear any pending UI updates
            if self.ui_update_timer.isActive():
                self.ui_update_timer.stop()
            
            # Clear UDP status timer
            if self.udp_status_timer.isActive():
                self.udp_status_timer.stop()
            
            # If disconnect mode is active, force cleanup
            if self.disconnect_active:
                log_info("Disconnect mode active during cleanup, forcing reconnection...")
                try:
                    # Force cleanup of all disruptions
                    self._clear_all_disruptions_comprehensive()
                    self._final_network_restoration()
                    
                    # Reset disconnect state
                    self.disconnect_active = False
                    if hasattr(self, 'internet_drop_button'):
                        self.internet_drop_button.setText("🔌 Disconnect All")
                        self.internet_drop_button.setStyleSheet("background-color: #4caf50; color: white;")
                    
                    log_info("Forced cleanup completed during disconnect mode")
                except Exception as e:
                    log_error(f"Error during forced cleanup: {e}")
            
            # Clear any remaining firewall rules
            try:
                self._clear_remaining_firewall_rules()
            except Exception as e:
                log_error(f"Error clearing firewall rules during cleanup: {e}")
            
            # Clear any remaining network configurations
            try:
                self._clear_remaining_network_configs()
            except Exception as e:
                log_error(f"Error clearing network configs during cleanup: {e}")
            
            log_info("EnhancedDeviceList cleanup completed")
            
        except Exception as e:
            log_error(f"Error in EnhancedDeviceList cleanup: {e}")
    
    def closeEvent(self, event):
        """Handle close event to ensure cleanup"""
        try:
            self.cleanup()
            event.accept()
        except Exception as e:
            log_error(f"Error in closeEvent: {e}")
            event.accept()
    
    def apply_simple_styling(self):
        """Apply simple styling to the widget"""
        self.setStyleSheet("""
            QWidget {
                background-color: #1e1e1e;
                color: #ffffff;
                font-family: Arial, sans-serif;
            }
        """)
    
    def on_device_selection_changed(self):
        """Handle device selection change to enable/disable action buttons"""
        selected_rows = self.device_table.selectionModel().selectedRows()
        has_selection = len(selected_rows) > 0
        
        # Enable/disable action buttons based on selection
        self.disconnect_button.setEnabled(has_selection)
        self.reconnect_button.setEnabled(has_selection)
        
        if has_selection:
            row = selected_rows[0].row()
            if row < len(self.devices):
                device = self.devices[row]
                is_disconnected = device.get('disconnected', False)
                
                # Update button states based on device status
                if is_disconnected:
                    self.disconnect_button.setEnabled(False)
                    self.reconnect_button.setEnabled(True)
                else:
                    self.disconnect_button.setEnabled(True)
                    self.reconnect_button.setEnabled(False)
    
    def disconnect_selected_device(self):
        """Disconnect only the selected device (not all devices)"""
        try:
            selected_rows = self.device_table.selectionModel().selectedRows()
            if not selected_rows:
                self.update_status("❌ No device selected")
                return
            
            row = selected_rows[0].row()
            if row >= len(self.devices):
                self.update_status("❌ Invalid device selection")
                return
            
            device = self.devices[row]
            ip = device.get('ip', '')
            
            if not ip:
                self.update_status("❌ No IP address found for selected device")
                return
            
            # Check if device is already disconnected
            if device.get('disconnected', False):
                self.update_status(f"⚠️ Device {ip} is already disconnected")
                return
            
            self.update_status(f"🔄 Disconnecting device {ip}...")
            
            # Try to disconnect using available disruptors
            success = False
            
            try:
                if self.clumsy_network_disruptor:
                    if self.clumsy_network_disruptor.disconnect_device_clumsy(ip, ["drop", "lag"]):
                        success = True
                        log_info(f"Device {ip} disconnected using Clumsy")
            except Exception as e:
                log_error(f"Clumsy disconnect error for {ip}: {e}")
            
            if not success and self.enterprise_network_disruptor:
                try:
                    if self.enterprise_network_disruptor.disconnect_device_enterprise(ip, ["arp_spoof", "icmp_flood"]):
                        success = True
                        log_info(f"Device {ip} disconnected using Enterprise")
                except Exception as e:
                    log_error(f"Enterprise disconnect error for {ip}: {e}")
            
            if success:
                # Update device status
                device['disconnected'] = True
                device['status'] = 'Disconnected'
                
                # Update table display
                self.update_device_row(row)
                
                # Update button states
                self.on_device_selection_changed()
                
                self.update_status(f"✅ Device {ip} disconnected successfully")
            else:
                self.update_status(f"❌ Failed to disconnect device {ip}")
                
        except Exception as e:
            log_error(f"Error disconnecting selected device: {e}")
            self.update_status(f"❌ Error: {str(e)}")
    
    def reconnect_selected_device(self):
        """Reconnect only the selected device (not all devices)"""
        try:
            selected_rows = self.device_table.selectionModel().selectedRows()
            if not selected_rows:
                self.update_status("❌ No device selected")
                return
            
            row = selected_rows[0].row()
            if row >= len(self.devices):
                self.update_status("❌ Invalid device selection")
                return
            
            device = self.devices[row]
            ip = device.get('ip', '')
            
            if not ip:
                self.update_status("❌ No IP address found for selected device")
                return
            
            # Check if device is already connected
            if not device.get('disconnected', False):
                self.update_status(f"⚠️ Device {ip} is already connected")
                return
            
            self.update_status(f"🔄 Reconnecting device {ip}...")
            
            # Try to reconnect using available disruptors
            success = False
            
            try:
                if self.clumsy_network_disruptor:
                    self.clumsy_network_disruptor.reconnect_device_clumsy(ip)
                    success = True
                    log_info(f"Device {ip} reconnected using Clumsy")
            except Exception as e:
                log_error(f"Clumsy reconnection error for {ip}: {e}")
            
            if not success and self.enterprise_network_disruptor:
                try:
                    self.enterprise_network_disruptor.reconnect_device_enterprise(ip)
                    success = True
                    log_info(f"Device {ip} reconnected using Enterprise")
                except Exception as e:
                    log_error(f"Enterprise reconnection error for {ip}: {e}")
            
            if success:
                # Update device status
                device['disconnected'] = False
                device['status'] = 'Online'
                
                # Update table display
                self.update_device_row(row)
                
                # Update button states
                self.on_device_selection_changed()
                
                self.update_status(f"✅ Device {ip} reconnected successfully")
            else:
                self.update_status(f"❌ Failed to reconnect device {ip}")
                
        except Exception as e:
            log_error(f"Error reconnecting selected device: {e}")
            self.update_status(f"❌ Error: {str(e)}")
    
    def update_device_row(self, row):
        """Update a specific row in the device table"""
        try:
            if row >= len(self.devices) or row < 0:
                return
            
            device = self.devices[row]
            
            # Update status column
            status_item = QTableWidgetItem(device.get('status', 'Unknown'))
            if device.get('disconnected', False):
                status_item.setBackground(QColor('#FF9800'))  # Orange for disconnected
                status_item.setText('Disconnected')
            elif device.get('blocked', False):
                status_item.setBackground(QColor('#f44336'))  # Red for blocked
                status_item.setText('Blocked')
            else:
                status_item.setBackground(QColor('#4CAF50'))  # Green for online
                status_item.setText('Online')
            
            self.device_table.setItem(row, 4, status_item)
            
            # Update actions column
            actions_item = QTableWidgetItem()
            if device.get('disconnected', False):
                actions_item.setText("🔌 Reconnect")
                actions_item.setBackground(QColor('#2196F3'))
            else:
                actions_item.setText("🔌 Disconnect")
                actions_item.setBackground(QColor('#FF9800'))
            
            self.device_table.setItem(row, 5, actions_item)
            
        except Exception as e:
            log_error(f"Error updating device row {row}: {e}")
    
    def add_device_to_table(self, device, row):
        """Add a device to the simplified table"""
        try:
            # IP Address
            ip_item = QTableWidgetItem(device.get('ip', ''))
            self.device_table.setItem(row, 0, ip_item)
            
            # MAC Address
            mac_item = QTableWidgetItem(device.get('mac', ''))
            self.device_table.setItem(row, 1, mac_item)
            
            # Hostname
            hostname_item = QTableWidgetItem(device.get('hostname', ''))
            self.device_table.setItem(row, 2, hostname_item)
            
            # Vendor
            vendor_item = QTableWidgetItem(device.get('vendor', ''))
            self.device_table.setItem(row, 3, vendor_item)
            
            # Status
            status_item = QTableWidgetItem(device.get('status', 'Online'))
            if device.get('disconnected', False):
                status_item.setBackground(QColor('#FF9800'))
                status_item.setText('Disconnected')
            elif device.get('blocked', False):
                status_item.setBackground(QColor('#f44336'))
                status_item.setText('Blocked')
            else:
                status_item.setBackground(QColor('#4CAF50'))
                status_item.setText('Online')
            
            self.device_table.setItem(row, 4, status_item)
            
            # Actions
            actions_item = QTableWidgetItem()
            if device.get('disconnected', False):
                actions_item.setText("🔌 Reconnect")
                actions_item.setBackground(QColor('#2196F3'))
            else:
                actions_item.setText("🔌 Disconnect")
                actions_item.setBackground(QColor('#FF9800'))
            
            self.device_table.setItem(row, 5, actions_item)
            
        except Exception as e:
            log_error(f"Error adding device to table: {e}")
    
    def clear_devices(self):
        """Clear all devices from the table"""
        try:
            self.devices.clear()
            self.device_table.setRowCount(0)
            self.update_status("🗑️ All devices cleared")
            
            # Disable action buttons
            self.disconnect_button.setEnabled(False)
            self.reconnect_button.setEnabled(False)
            
        except Exception as e:
            log_error(f"Error clearing devices: {e}")
            self.update_status(f"❌ Error clearing devices: {str(e)}")
    
    def update_status(self, message):
        """Update the status label with a simple message"""
        try:
            self.status_label.setText(message)
            self.status_label.repaint()
        except Exception as e:
            log_error(f"Error updating status: {e}")
    
    def start_scan(self):
        """Start a network scan"""
        try:
            if not self.scanner:
                self.update_status("❌ Scanner not initialized")
                return
            
            self.scan_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)
            
            self.update_status("🔍 Starting network scan...")
            
            # Start scan in background thread (simplified)
            self.scan_network()
            
        except Exception as e:
            log_error(f"Error starting scan: {e}")
            self.update_status(f"❌ Error starting scan: {str(e)}")
            self.scan_button.setEnabled(True)
            self.stop_button.setEnabled(False)
    
    def stop_scan(self):
        """Stop the current scan"""
        try:
            if self.scanner:
                self.scanner.stop_scan()
            
            self.scan_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.progress_bar.setVisible(False)
            
            self.update_status("⏹️ Scan stopped")
            
        except Exception as e:
            log_error(f"Error stopping scan: {e}")
    
    def scan_network(self):
        """Perform the actual network scan"""
        try:
            # Simple scan implementation
            self.update_status("🔍 Scanning network...")
            
            # Simulate scan progress
            for i in range(101):
                self.progress_bar.setValue(i)
                QTimer.singleShot(50, lambda: None)  # Simple delay
            
            # Add some sample devices for testing
            sample_devices = [
                {'ip': '192.168.1.1', 'mac': 'AA:BB:CC:DD:EE:FF', 'hostname': 'Router', 'vendor': 'TP-Link', 'status': 'Online', 'disconnected': False, 'blocked': False},
                {'ip': '192.168.1.100', 'mac': '11:22:33:44:55:66', 'hostname': 'PC-Desktop', 'vendor': 'Dell', 'status': 'Online', 'disconnected': False, 'blocked': False},
                {'ip': '192.168.1.101', 'mac': 'AA:11:BB:22:CC:33', 'hostname': 'PS5-Console', 'vendor': 'Sony', 'status': 'Online', 'disconnected': False, 'blocked': False},
            ]
            
            self.devices = sample_devices
            self.device_table.setRowCount(len(self.devices))
            
            for i, device in enumerate(self.devices):
                self.add_device_to_table(device, i)
            
            self.scan_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.progress_bar.setVisible(False)
            
            self.update_status(f"✅ Scan complete - {len(self.devices)} devices found")
            
        except Exception as e:
            log_error(f"Error during scan: {e}")
            self.update_status(f"❌ Scan error: {str(e)}")
            self.scan_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.progress_bar.setVisible(False)
    
    def closeEvent(self, event):
        """Stability optimization: Clean up resources on close"""
        try:
            # Stop all timers
            if hasattr(self, 'udp_status_timer'):
                self.udp_status_timer.stop()
            
            if hasattr(self, 'ui_update_timer'):
                self.ui_update_timer.stop()
            
            # Clear caches and data
            if hasattr(self, 'device_ui_updates'):
                self.device_ui_updates.clear()
            
            # Clear device table
            if hasattr(self, 'device_table'):
                self.device_table.clearContents()
                self.device_table.setRowCount(0)
            
            # Clear devices list
            if hasattr(self, 'devices'):
                self.devices.clear()
            
            log_info("Enhanced device list cleanup completed")
            
        except Exception as e:
            log_error(f"Error during enhanced device list cleanup: {e}")
        
        # Always accept the close event
        event.accept()
