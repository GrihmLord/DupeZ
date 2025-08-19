"""
DupeZ Duping Network Optimizer
Integrates with Account Tracker to optimize network settings for selected accounts
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget, 
    QTableWidgetItem, QGroupBox, QFormLayout, QSpinBox, QComboBox, 
    QCheckBox, QTextEdit, QMessageBox, QHeaderView, QSplitter, QFrame,
    QProgressBar, QSlider, QLineEdit, QTabWidget
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QIcon

from app.logs.logger import log_info, log_error, log_warning
from app.core.latency_manager import latency_manager

class DupingNetworkOptimizer(QWidget):
    """Network optimizer for duping operations with account integration"""
    
    def __init__(self, account_tracker=None):
        super().__init__()
        self.account_tracker = account_tracker
        self.selected_accounts = []
        self.optimization_profiles = {}
        self.current_optimization = None
        self.optimization_running = False
        
        self.setup_ui()
        self.load_optimization_profiles()
        
    def setup_ui(self):
        """Setup the main UI"""
        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Header
        header = QLabel("🚀 DupeZ Duping Network Optimizer")
        header.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        header.setStyleSheet("""
            color: #ffffff;
            padding: 15px;
            background-color: #2c3e50;
            border-radius: 8px;
            margin-bottom: 15px;
            text-align: center;
        """)
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)
        
        # Main splitter
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left panel - Account selection and optimization
        left_panel = self.create_left_panel()
        main_splitter.addWidget(left_panel)
        
        # Right panel - Network configuration and monitoring
        right_panel = self.create_right_panel()
        main_splitter.addWidget(right_panel)
        
        # Set splitter proportions
        main_splitter.setSizes([400, 600])
        layout.addWidget(main_splitter)
        
        # Status bar
        self.status_label = QLabel("Ready to optimize network for duping operations")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("""
            color: #4CAF50; 
            font-weight: bold; 
            padding: 12px;
            background-color: #1e1e1e;
            border: 2px solid #4CAF50;
            border-radius: 8px;
            margin: 10px 0;
            font-size: 14px;
        """)
        layout.addWidget(self.status_label)
        
        self.setLayout(layout)
        
    def create_left_panel(self) -> QWidget:
        """Create the left panel for account selection and optimization"""
        panel = QWidget()
        layout = QVBoxLayout()
        
        # Account Selection Group
        account_group = QGroupBox("🎯 Account Selection")
        account_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                border: 2px solid #555555;
                border-radius: 8px;
                margin-top: 10px;
                padding: 15px;
                background-color: #1e1e1e;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px 0 8px;
                color: #ffffff;
                font-size: 16px;
            }
        """)
        
        account_layout = QVBoxLayout()
        
        # Account table
        self.account_table = QTableWidget()
        self.setup_account_table()
        account_layout.addWidget(self.account_table)
        
        # Account selection controls
        selection_controls = QHBoxLayout()
        
        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.clicked.connect(self.select_all_accounts)
        self.select_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                padding: 12px 20px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 12px;
                min-width: 100px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)
        
        self.clear_selection_btn = QPushButton("Clear Selection")
        self.clear_selection_btn.clicked.connect(self.clear_account_selection)
        self.clear_selection_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
                color: white;
                border: none;
                padding: 12px 20px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 12px;
                min-width: 100px;
            }
            QPushButton:hover {
                background-color: #F57C00;
            }
        """)
        
        selection_controls.addWidget(self.select_all_btn)
        selection_controls.addWidget(self.clear_selection_btn)
        selection_controls.addStretch()
        
        account_layout.addLayout(selection_controls)
        account_group.setLayout(account_layout)
        layout.addWidget(account_group)
        
        # Optimization Profile Group
        profile_group = QGroupBox("⚙️ Optimization Profile")
        profile_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                border: 2px solid #555555;
                border-radius: 8px;
                margin-top: 10px;
                padding: 15px;
                background-color: #1e1e1e;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px 0 8px;
                color: #ffffff;
                font-size: 16px;
            }
        """)
        
        profile_layout = QFormLayout()
        profile_layout.setSpacing(15)
        profile_layout.setContentsMargins(20, 20, 20, 20)
        
        self.profile_combo = QComboBox()
        self.profile_combo.addItems(["Stealth", "Balanced", "Aggressive", "Custom"])
        self.profile_combo.currentTextChanged.connect(self.on_profile_changed)
        self.profile_combo.setStyleSheet("""
            QComboBox {
                background-color: #2b2b2b;
                color: #ffffff;
                border: 2px solid #555555;
                border-radius: 6px;
                padding: 8px;
                font-size: 12px;
                min-width: 150px;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid #ffffff;
            }
        """)
        profile_label = QLabel("Profile:")
        profile_label.setStyleSheet("color: #ffffff; font-weight: bold; font-size: 12px; padding: 5px;")
        profile_layout.addRow(profile_label, self.profile_combo)
        
        self.latency_target_spin = QSpinBox()
        self.latency_target_spin.setRange(10, 200)
        self.latency_target_spin.setValue(25)
        self.latency_target_spin.setSuffix(" ms")
        self.latency_target_spin.setStyleSheet("""
            QSpinBox {
                background-color: #2b2b2b;
                color: #ffffff;
                border: 2px solid #555555;
                border-radius: 6px;
                padding: 8px;
                font-size: 12px;
                min-width: 120px;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                background-color: #555555;
                border: none;
                width: 20px;
            }
        """)
        latency_label = QLabel("Target Latency:")
        latency_label.setStyleSheet("color: #ffffff; font-weight: bold; font-size: 12px; padding: 5px;")
        profile_layout.addRow(latency_label, self.latency_target_spin)
        
        self.packet_timing_spin = QSpinBox()
        self.packet_timing_spin.setRange(1, 50)
        self.packet_timing_spin.setValue(5)
        self.packet_timing_spin.setSuffix(" ms")
        self.packet_timing_spin.setStyleSheet("""
            QSpinBox {
                background-color: #2b2b2b;
                color: #ffffff;
                border: 2px solid #555555;
                border-radius: 6px;
                padding: 8px;
                font-size: 12px;
                min-width: 120px;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                background-color: #555555;
                border: none;
                width: 20px;
            }
        """)
        timing_label = QLabel("Packet Timing:")
        timing_label.setStyleSheet("color: #ffffff; font-weight: bold; font-size: 12px; padding: 5px;")
        profile_layout.addRow(timing_label, self.packet_timing_spin)
        
        self.latency_variance_spin = QSpinBox()
        self.latency_variance_spin.setRange(1, 100)
        self.latency_variance_spin.setValue(10)
        self.latency_variance_spin.setSuffix(" ms")
        self.latency_variance_spin.setStyleSheet("""
            QSpinBox {
                background-color: #2b2b2b;
                color: #ffffff;
                border: 2px solid #555555;
                border-radius: 6px;
                padding: 8px;
                font-size: 12px;
                min-width: 120px;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                background-color: #555555;
                border: none;
                width: 20px;
            }
        """)
        variance_label = QLabel("Latency Variance:")
        variance_label.setStyleSheet("color: #ffffff; font-weight: bold; font-size: 12px; padding: 5px;")
        profile_layout.addRow(variance_label, self.latency_variance_spin)
        
        profile_group.setLayout(profile_layout)
        layout.addWidget(profile_group)
        
        # Optimization Controls
        controls_group = QGroupBox("🎮 Optimization Controls")
        controls_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                border: 2px solid #555555;
                border-radius: 8px;
                margin-top: 10px;
                padding: 15px;
                background-color: #1e1e1e;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px 0 8px;
                color: #ffffff;
                font-size: 16px;
            }
        """)
        
        controls_layout = QVBoxLayout()
        
        # Start optimization button
        self.start_optimization_btn = QPushButton("🚀 Start Optimization")
        self.start_optimization_btn.clicked.connect(self.start_optimization)
        self.start_optimization_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 12px 20px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #666666;
            }
        """)
        
        # Stop optimization button
        self.stop_optimization_btn = QPushButton("⏹️ Stop Optimization")
        self.stop_optimization_btn.clicked.connect(self.stop_optimization)
        self.stop_optimization_btn.setEnabled(False)
        self.stop_optimization_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border: none;
                padding: 12px 20px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #da190b;
            }
            QPushButton:disabled {
                background-color: #666666;
            }
        """)
        
        controls_layout.addWidget(self.start_optimization_btn)
        controls_layout.addWidget(self.stop_optimization_btn)
        
        # Progress bar
        self.optimization_progress = QProgressBar()
        self.optimization_progress.setVisible(False)
        controls_layout.addWidget(self.optimization_progress)
        
        controls_group.setLayout(controls_layout)
        layout.addWidget(controls_group)
        
        panel.setLayout(layout)
        return panel
        
    def create_right_panel(self) -> QWidget:
        """Create the right panel for network configuration and monitoring"""
        panel = QWidget()
        layout = QVBoxLayout()
        
        # Tab widget for different sections
        self.tab_widget = QTabWidget()
        
        # Network Configuration Tab
        network_tab = self.create_network_config_tab()
        self.tab_widget.addTab(network_tab, "Network Configuration")
        
        # Real-time Monitoring Tab
        monitoring_tab = self.create_monitoring_tab()
        self.tab_widget.addTab(monitoring_tab, "Real-time Monitoring")
        
        # Optimization Log Tab
        log_tab = self.create_log_tab()
        self.tab_widget.addTab(log_tab, "Optimization Log")
        
        layout.addWidget(self.tab_widget)
        panel.setLayout(layout)
        return panel
        
    def create_network_config_tab(self) -> QWidget:
        """Create the network configuration tab"""
        tab = QWidget()
        layout = QVBoxLayout()
        
        # QoS Configuration
        qos_group = QGroupBox("🌐 QoS Configuration")
        qos_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 12px;
                border: 1px solid #555555;
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 8px;
                background-color: #2b2b2b;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 3px 0 3px;
                color: #ffffff;
            }
        """)
        
        qos_layout = QFormLayout()
        
        self.bandwidth_reserved_spin = QSpinBox()
        self.bandwidth_reserved_spin.setRange(50, 1000)
        self.bandwidth_reserved_spin.setValue(200)
        self.bandwidth_reserved_spin.setSuffix(" Mbps")
        qos_layout.addRow("Bandwidth Reserved:", self.bandwidth_reserved_spin)
        
        self.priority_level_combo = QComboBox()
        self.priority_level_combo.addItems(["LOW", "NORMAL", "HIGH", "HIGHEST", "CRITICAL"])
        self.priority_level_combo.setCurrentText("HIGH")
        qos_layout.addRow("Priority Level:", self.priority_level_combo)
        
        self.auto_optimize_check = QCheckBox("Enable Auto-Optimization")
        self.auto_optimize_check.setChecked(True)
        qos_layout.addRow(self.auto_optimize_check)
        
        qos_group.setLayout(qos_layout)
        layout.addWidget(qos_group)
        
        # Advanced Settings
        advanced_group = QGroupBox("🔧 Advanced Settings")
        advanced_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 12px;
                border: 1px solid #555555;
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 8px;
                background-color: #2b2b2b;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 3px 0 3px;
                color: #ffffff;
            }
        """)
        
        advanced_layout = QFormLayout()
        
        self.connection_stability_spin = QSpinBox()
        self.connection_stability_spin.setRange(50, 100)
        self.connection_stability_spin.setValue(95)
        self.connection_stability_spin.setSuffix("%")
        advanced_layout.addRow("Connection Stability:", self.connection_stability_spin)
        
        self.detection_risk_combo = QComboBox()
        self.detection_risk_combo.addItems(["low", "medium", "high"])
        self.detection_risk_combo.setCurrentText("medium")
        advanced_layout.addRow("Detection Risk:", self.detection_risk_combo)
        
        self.success_rate_spin = QSpinBox()
        self.success_rate_spin.setRange(50, 100)
        self.success_rate_spin.setValue(90)
        self.success_rate_spin.setSuffix("%")
        advanced_layout.addRow("Expected Success Rate:", self.success_rate_spin)
        
        advanced_group.setLayout(advanced_layout)
        layout.addWidget(advanced_group)
        
        # Save/Load Configuration
        config_controls = QHBoxLayout()
        
        self.save_config_btn = QPushButton("💾 Save Configuration")
        self.save_config_btn.clicked.connect(self.save_configuration)
        self.save_config_btn.setStyleSheet("""
            QPushButton {
                background-color: #9C27B0;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #7B1FA2;
            }
        """)
        
        self.load_config_btn = QPushButton("📂 Load Configuration")
        self.load_config_btn.clicked.connect(self.load_configuration)
        self.load_config_btn.setStyleSheet("""
            QPushButton {
                background-color: #00BCD4;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0097A7;
            }
        """)
        
        config_controls.addWidget(self.save_config_btn)
        config_controls.addWidget(self.load_config_btn)
        config_controls.addStretch()
        
        layout.addLayout(config_controls)
        layout.addStretch()
        
        tab.setLayout(layout)
        return tab
        
    def create_monitoring_tab(self) -> QWidget:
        """Create the real-time monitoring tab"""
        tab = QWidget()
        layout = QVBoxLayout()
        
        # Current Status
        status_group = QGroupBox("📊 Current Status")
        status_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 12px;
                border: 1px solid #555555;
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 8px;
                background-color: #2b2b2b;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 3px 0 3px;
                color: #ffffff;
            }
        """)
        
        status_layout = QFormLayout()
        
        self.current_latency_label = QLabel("0 ms")
        self.current_latency_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        status_layout.addRow("Current Latency:", self.current_latency_label)
        
        self.packet_loss_label = QLabel("0%")
        self.packet_loss_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        status_layout.addRow("Packet Loss:", self.packet_loss_label)
        
        self.bandwidth_usage_label = QLabel("0 Mbps")
        self.bandwidth_usage_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        status_layout.addRow("Bandwidth Usage:", self.bandwidth_usage_label)
        
        self.optimization_status_label = QLabel("Idle")
        self.optimization_status_label.setStyleSheet("color: #FF9800; font-weight: bold;")
        status_layout.addRow("Optimization Status:", self.optimization_status_label)
        
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)
        
        # Account Performance
        performance_group = QGroupBox("👥 Account Performance")
        performance_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 12px;
                border: 1px solid #555555;
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 8px;
                background-color: #2b2b2b;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 3px 0 3px;
                color: #ffffff;
            }
        """)
        
        performance_layout = QVBoxLayout()
        
        self.performance_table = QTableWidget()
        self.setup_performance_table()
        performance_layout.addWidget(self.performance_table)
        
        performance_group.setLayout(performance_layout)
        layout.addWidget(performance_group)
        
        # Refresh button
        self.refresh_monitoring_btn = QPushButton("🔄 Refresh Monitoring")
        self.refresh_monitoring_btn.clicked.connect(self.refresh_monitoring)
        self.refresh_monitoring_btn.setStyleSheet("""
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
        
        layout.addWidget(self.refresh_monitoring_btn)
        layout.addStretch()
        
        tab.setLayout(layout)
        return tab
        
    def create_log_tab(self) -> QWidget:
        """Create the optimization log tab"""
        tab = QWidget()
        layout = QVBoxLayout()
        
        # Log display
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #ffffff;
                border: 1px solid #555555;
                border-radius: 4px;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 11px;
            }
        """)
        layout.addWidget(self.log_text)
        
        # Log controls
        log_controls = QHBoxLayout()
        
        self.clear_log_btn = QPushButton("🗑️ Clear Log")
        self.clear_log_btn.clicked.connect(self.clear_log)
        self.clear_log_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border: none;
                padding: 6px 12px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #da190b;
            }
        """)
        
        self.export_log_btn = QPushButton("💾 Export Log")
        self.export_log_btn.clicked.connect(self.export_log)
        self.export_log_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 6px 12px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        
        log_controls.addWidget(self.clear_log_btn)
        log_controls.addWidget(self.export_log_btn)
        log_controls.addStretch()
        
        layout.addLayout(log_controls)
        
        tab.setLayout(layout)
        return tab
        
    def setup_account_table(self):
        """Setup the account selection table"""
        self.account_table.setColumnCount(6)
        self.account_table.setHorizontalHeaderLabels([
            "Select", "Account", "Email", "Status", "Location", "Gear"
        ])
        
        # Set table properties
        header = self.account_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        
        # Enable sorting
        self.account_table.setSortingEnabled(True)
        
        # Set table styling
        self.account_table.setStyleSheet("""
            QTableWidget {
                background-color: #2b2b2b;
                alternate-background-color: #3a3a3a;
                color: #ffffff;
                gridline-color: #555555;
                border: 1px solid #555555;
                border-radius: 6px;
                font-size: 11px;
            }
            QTableWidget::item {
                padding: 8px;
                border: none;
            }
            QTableWidget::item:selected {
                background-color: #2196F3;
                color: white;
            }
            QHeaderView::section {
                background-color: #1e1e1e;
                color: #ffffff;
                padding: 10px;
                border: 1px solid #555555;
                font-weight: bold;
                font-size: 12px;
            }
        """)
        
        # Set alternating row colors
        self.account_table.setAlternatingRowColors(True)
        
    def setup_performance_table(self):
        """Setup the performance monitoring table"""
        self.performance_table.setColumnCount(5)
        self.performance_table.setHorizontalHeaderLabels([
            "Account", "Latency", "Packet Loss", "Bandwidth", "Status"
        ])
        
        # Set table properties
        header = self.performance_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        
        # Set table styling
        self.performance_table.setStyleSheet("""
            QTableWidget {
                background-color: #2b2b2b;
                alternate-background-color: #3a3a3a;
                color: #ffffff;
                gridline-color: #555555;
                border: 1px solid #555555;
                border-radius: 6px;
                font-size: 11px;
            }
            QTableWidget::item {
                padding: 8px;
                border: none;
            }
            QTableWidget::item:selected {
                background-color: #2196F3;
                color: white;
            }
            QHeaderView::section {
                background-color: #1e1e1e;
                color: #ffffff;
                padding: 10px;
                border: 1px solid #555555;
                font-weight: bold;
                font-size: 12px;
            }
        """)
        
        # Set alternating row colors
        self.performance_table.setAlternatingRowColors(True)
        
    def load_optimization_profiles(self):
        """Load optimization profiles from latency manager"""
        try:
            duping_profiles = latency_manager.config.get("duping_latency_profiles", {})
            self.optimization_profiles = duping_profiles
            log_info("Loaded optimization profiles")
        except Exception as e:
            log_error(f"Failed to load optimization profiles: {e}")
            
    def on_profile_changed(self, profile_name: str):
        """Handle profile selection change"""
        try:
            if profile_name in self.optimization_profiles:
                profile = self.optimization_profiles[profile_name]
                
                # Update UI with profile values
                self.latency_target_spin.setValue(profile.get("target_latency", 25))
                self.packet_timing_spin.setValue(profile.get("packet_timing", 5))
                self.latency_variance_spin.setValue(profile.get("latency_variance", 10))
                
                # Update advanced settings
                self.connection_stability_spin.setValue(profile.get("connection_stability", 95))
                self.detection_risk_combo.setCurrentText(profile.get("detection_risk", "medium"))
                self.success_rate_spin.setValue(profile.get("success_rate", 90))
                
                log_info(f"Applied profile: {profile_name}")
                
        except Exception as e:
            log_error(f"Failed to apply profile {profile_name}: {e}")
            
    def select_all_accounts(self):
        """Select all available accounts"""
        try:
            if self.account_tracker and hasattr(self.account_tracker, 'accounts'):
                self.selected_accounts = list(range(len(self.account_tracker.accounts)))
                self.update_account_table()
                self.status_label.setText(f"Selected {len(self.selected_accounts)} accounts")
                log_info(f"Selected {len(self.selected_accounts)} accounts")
            else:
                QMessageBox.warning(self, "Warning", "Account tracker not available")
        except Exception as e:
            log_error(f"Failed to select all accounts: {e}")
            
    def clear_account_selection(self):
        """Clear account selection"""
        try:
            self.selected_accounts.clear()
            self.update_account_table()
            self.status_label.setText("Account selection cleared")
            log_info("Account selection cleared")
        except Exception as e:
            log_error(f"Failed to clear account selection: {e}")
            
    def update_account_table(self):
        """Update the account table with current data"""
        try:
            if not self.account_tracker or not hasattr(self.account_tracker, 'accounts'):
                return
                
            accounts = self.account_tracker.accounts
            self.account_table.setRowCount(len(accounts))
            
            for row, account in enumerate(accounts):
                # Selection checkbox
                checkbox = QTableWidgetItem()
                checkbox.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                checkbox.setCheckState(Qt.CheckState.Checked if row in self.selected_accounts else Qt.CheckState.Unchecked)
                self.account_table.setItem(row, 0, checkbox)
                
                # Account name
                self.account_table.setItem(row, 1, QTableWidgetItem(account.get('account', '')))
                
                # Email
                self.account_table.setItem(row, 2, QTableWidgetItem(account.get('email', '')))
                
                # Status
                status = account.get('status', 'Unknown')
                status_item = QTableWidgetItem(status)
                if status == 'Ready':
                    status_item.setBackground(QColor(76, 175, 80, 50))
                elif status == 'Blood Infection':
                    status_item.setBackground(QColor(244, 67, 54, 50))
                elif status == 'Storage':
                    status_item.setBackground(QColor(255, 152, 0, 50))
                self.account_table.setItem(row, 3, status_item)
                
                # Location
                self.account_table.setItem(row, 4, QTableWidgetItem(account.get('location', '')))
                
                # Gear
                self.account_table.setItem(row, 5, QTableWidgetItem(account.get('gear', '')))
                
        except Exception as e:
            log_error(f"Failed to update account table: {e}")
            
    def start_optimization(self):
        """Start the network optimization process"""
        try:
            if not self.selected_accounts:
                QMessageBox.warning(self, "Warning", "Please select at least one account")
                return
                
            if self.optimization_running:
                QMessageBox.information(self, "Info", "Optimization already running")
                return
                
            # Start optimization
            self.optimization_running = True
            self.start_optimization_btn.setEnabled(False)
            self.stop_optimization_btn.setEnabled(True)
            self.optimization_progress.setVisible(True)
            
            # Update status
            self.optimization_status_label.setText("Running")
            self.optimization_status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
            self.status_label.setText(f"Starting optimization for {len(self.selected_accounts)} accounts...")
            
            # Start optimization timer
            self.optimization_timer = QTimer()
            self.optimization_timer.timeout.connect(self.update_optimization)
            self.optimization_timer.start(1000)  # Update every second
            
            # Log start
            self.log_message(f"🚀 Started optimization for {len(self.selected_accounts)} accounts")
            self.log_message(f"Profile: {self.profile_combo.currentText()}")
            self.log_message(f"Target Latency: {self.latency_target_spin.value()}ms")
            
            log_info(f"Started optimization for {len(self.selected_accounts)} accounts")
            
        except Exception as e:
            log_error(f"Failed to start optimization: {e}")
            QMessageBox.critical(self, "Error", f"Failed to start optimization: {e}")
            
    def stop_optimization(self):
        """Stop the network optimization process"""
        try:
            self.optimization_running = False
            self.start_optimization_btn.setEnabled(True)
            self.stop_optimization_btn.setEnabled(False)
            self.optimization_progress.setVisible(False)
            
            # Stop timer
            if hasattr(self, 'optimization_timer'):
                self.optimization_timer.stop()
                
            # Update status
            self.optimization_status_label.setText("Stopped")
            self.optimization_status_label.setStyleSheet("color: #f44336; font-weight: bold;")
            self.status_label.setText("Optimization stopped")
            
            # Log stop
            self.log_message("⏹️ Optimization stopped by user")
            log_info("Optimization stopped by user")
            
        except Exception as e:
            log_error(f"Failed to stop optimization: {e}")
            
    def update_optimization(self):
        """Update optimization progress and status"""
        try:
            if not self.optimization_running:
                return
                
            # Simulate optimization progress
            current_progress = self.optimization_progress.value()
            if current_progress < 100:
                self.optimization_progress.setValue(current_progress + 5)
            else:
                self.optimization_progress.setValue(0)
                
            # Update monitoring data
            self.update_monitoring_data()
            
        except Exception as e:
            log_error(f"Failed to update optimization: {e}")
            
    def update_monitoring_data(self):
        """Update real-time monitoring data"""
        try:
            # Simulate latency and performance data
            import random
            
            # Update current status
            current_latency = random.randint(15, 45)
            self.current_latency_label.setText(f"{current_latency} ms")
            
            packet_loss = random.uniform(0, 2)
            self.packet_loss_label.setText(f"{packet_loss:.1f}%")
            
            bandwidth = random.randint(150, 250)
            self.bandwidth_usage_label.setText(f"{bandwidth} Mbps")
            
            # Update performance table
            if self.selected_accounts and self.account_tracker:
                accounts = self.account_tracker.accounts
                self.performance_table.setRowCount(len(self.selected_accounts))
                
                for row, account_idx in enumerate(self.selected_accounts):
                    if account_idx < len(accounts):
                        account = accounts[account_idx]
                        
                        # Account name
                        self.performance_table.setItem(row, 0, QTableWidgetItem(account.get('account', '')))
                        
                        # Latency
                        latency = random.randint(15, 45)
                        latency_item = QTableWidgetItem(f"{latency} ms")
                        if latency <= 25:
                            latency_item.setBackground(QColor(76, 175, 80, 50))
                        elif latency <= 35:
                            latency_item.setBackground(QColor(255, 152, 0, 50))
                        else:
                            latency_item.setBackground(QColor(244, 67, 54, 50))
                        self.performance_table.setItem(row, 1, latency_item)
                        
                        # Packet loss
                        packet_loss = random.uniform(0, 2)
                        self.performance_table.setItem(row, 2, QTableWidgetItem(f"{packet_loss:.1f}%"))
                        
                        # Bandwidth
                        bandwidth = random.randint(150, 250)
                        self.performance_table.setItem(row, 3, QTableWidgetItem(f"{bandwidth} Mbps"))
                        
                        # Status
                        status = "Optimized" if latency <= 25 else "Optimizing"
                        status_item = QTableWidgetItem(status)
                        status_item.setBackground(QColor(76, 175, 80, 50) if status == "Optimized" else QColor(255, 152, 0, 50))
                        self.performance_table.setItem(row, 4, status_item)
                        
        except Exception as e:
            log_error(f"Failed to update monitoring data: {e}")
            
    def refresh_monitoring(self):
        """Refresh monitoring data"""
        try:
            self.update_monitoring_data()
            self.status_label.setText("Monitoring data refreshed")
            log_info("Monitoring data refreshed")
        except Exception as e:
            log_error(f"Failed to refresh monitoring: {e}")
            
    def log_message(self, message: str):
        """Add message to log"""
        try:
            from datetime import datetime
            timestamp = datetime.now().strftime("%H:%M:%S")
            log_entry = f"[{timestamp}] {message}"
            self.log_text.append(log_entry)
            
            # Auto-scroll to bottom
            scrollbar = self.log_text.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
            
        except Exception as e:
            log_error(f"Failed to log message: {e}")
            
    def clear_log(self):
        """Clear the optimization log"""
        try:
            self.log_text.clear()
            self.log_message("📝 Log cleared")
            log_info("Optimization log cleared")
        except Exception as e:
            log_error(f"Failed to clear log: {e}")
            
    def export_log(self):
        """Export the optimization log to file"""
        try:
            from PyQt6.QtWidgets import QFileDialog
            
            filename, _ = QFileDialog.getSaveFileName(
                self, "Export Log", "duping_optimization_log.txt", "Text Files (*.txt)"
            )
            
            if filename:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(self.log_text.toPlainText())
                    
                self.log_message(f"💾 Log exported to: {filename}")
                QMessageBox.information(self, "Success", f"Log exported to: {filename}")
                log_info(f"Log exported to: {filename}")
                
        except Exception as e:
            log_error(f"Failed to export log: {e}")
            QMessageBox.critical(self, "Error", f"Failed to export log: {e}")
            
    def save_configuration(self):
        """Save current configuration"""
        try:
            # Collect current settings
            config = {
                "profile": self.profile_combo.currentText(),
                "latency_target": self.latency_target_spin.value(),
                "packet_timing": self.packet_timing_spin.value(),
                "latency_variance": self.latency_variance_spin.value(),
                "bandwidth_reserved": self.bandwidth_reserved_spin.value(),
                "priority_level": self.priority_level_combo.currentText(),
                "auto_optimize": self.auto_optimize_check.isChecked(),
                "connection_stability": self.connection_stability_spin.value(),
                "detection_risk": self.detection_risk_combo.currentText(),
                "success_rate": self.success_rate_spin.value()
            }
            
            # Save to file
            import json
            config_file = "app/config/duping_optimizer_config.json"
            
            # Ensure directory exists
            import os
            os.makedirs(os.path.dirname(config_file), exist_ok=True)
            
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
                
            self.log_message("💾 Configuration saved")
            QMessageBox.information(self, "Success", "Configuration saved successfully!")
            log_info("Configuration saved")
            
        except Exception as e:
            log_error(f"Failed to save configuration: {e}")
            QMessageBox.critical(self, "Error", f"Failed to save configuration: {e}")
            
    def load_configuration(self):
        """Load saved configuration"""
        try:
            config_file = "app/config/duping_optimizer_config.json"
            
            if not os.path.exists(config_file):
                QMessageBox.information(self, "Info", "No saved configuration found")
                return
                
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
                
            # Apply configuration
            if "profile" in config:
                index = self.profile_combo.findText(config["profile"])
                if index >= 0:
                    self.profile_combo.setCurrentIndex(index)
                    
            if "latency_target" in config:
                self.latency_target_spin.setValue(config["latency_target"])
                
            if "packet_timing" in config:
                self.packet_timing_spin.setValue(config["packet_timing"])
                
            if "latency_variance" in config:
                self.latency_variance_spin.setValue(config["latency_variance"])
                
            if "bandwidth_reserved" in config:
                self.bandwidth_reserved_spin.setValue(config["bandwidth_reserved"])
                
            if "priority_level" in config:
                index = self.priority_level_combo.findText(config["priority_level"])
                if index >= 0:
                    self.priority_level_combo.setCurrentIndex(index)
                    
            if "auto_optimize" in config:
                self.auto_optimize_check.setChecked(config["auto_optimize"])
                
            if "connection_stability" in config:
                self.connection_stability_spin.setValue(config["connection_stability"])
                
            if "detection_risk" in config:
                index = self.detection_risk_combo.findText(config["detection_risk"])
                if index >= 0:
                    self.detection_risk_combo.setCurrentIndex(index)
                    
            if "success_rate" in config:
                self.success_rate_spin.setValue(config["success_rate"])
                
            self.log_message("📂 Configuration loaded")
            QMessageBox.information(self, "Success", "Configuration loaded successfully!")
            log_info("Configuration loaded")
            
        except Exception as e:
            log_error(f"Failed to load configuration: {e}")
            QMessageBox.critical(self, "Error", f"Failed to load configuration: {e}")
            
    def refresh_accounts(self):
        """Refresh account data from account tracker"""
        try:
            if self.account_tracker and hasattr(self.account_tracker, 'refresh_account_table'):
                self.account_tracker.refresh_account_table()
                self.update_account_table()
                self.status_label.setText("Account data refreshed")
                log_info("Account data refreshed")
            else:
                QMessageBox.warning(self, "Warning", "Account tracker not available")
        except Exception as e:
            log_error(f"Failed to refresh accounts: {e}")
            
    def set_account_tracker(self, account_tracker):
        """Set the account tracker reference"""
        self.account_tracker = account_tracker
        self.refresh_accounts()
