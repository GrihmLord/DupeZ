# app/gui/settings_dialog.py

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
                              QWidget, QLabel, QSpinBox, QCheckBox, QComboBox,
                              QPushButton, QGroupBox, QFormLayout, QLineEdit,
                              QTextEdit, QSlider, QProgressBar, QMessageBox,
                              QFileDialog, QColorDialog, QFontDialog)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QColor
from typing import Dict, Any
from app.logs.logger import log_info, log_error
from app.core.state import AppSettings

class SettingsDialog(QDialog):
    """Comprehensive settings dialog for PulseDrop Pro"""
    
    # Signals
    settings_changed = pyqtSignal(dict)  # Emit new settings
    
    def __init__(self, current_settings: AppSettings, parent=None):
        super().__init__(parent)
        self.current_settings = current_settings
        self.new_settings = current_settings
        
        self.setWindowTitle("⚙️ PulseDrop Pro Settings")
        self.setModal(True)
        self.resize(600, 500)
        
        self.init_ui()
        self.load_current_settings()
        # Initialize theme controls
        self.update_theme_info()
    
    def init_ui(self):
        """Initialize the user interface"""
        layout = QVBoxLayout()
        
        # Create tab widget
        self.tab_widget = QTabWidget()
        
        # General Settings Tab
        self.general_tab = self.create_general_tab()
        self.tab_widget.addTab(self.general_tab, "🔧 General")
        
        # Network Settings Tab
        self.network_tab = self.create_network_tab()
        self.tab_widget.addTab(self.network_tab, "🌐 Network")
        
        # Smart Mode Tab
        self.smart_mode_tab = self.create_smart_mode_tab()
        self.tab_widget.addTab(self.smart_mode_tab, "🧠 Smart Mode")
        
        # UI Settings Tab
        self.ui_tab = self.create_ui_tab()
        self.tab_widget.addTab(self.ui_tab, "🎨 Interface")
        
        # Advanced Settings Tab
        self.advanced_tab = self.create_advanced_tab()
        self.tab_widget.addTab(self.advanced_tab, "⚡ Advanced")
        
        # Testing Tab
        self.testing_tab = self.create_testing_tab()
        self.tab_widget.addTab(self.testing_tab, "🧪 Testing")
        
        layout.addWidget(self.tab_widget)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.save_btn = QPushButton("💾 Save Settings")
        self.save_btn.clicked.connect(self.save_settings)
        button_layout.addWidget(self.save_btn)
        
        self.cancel_btn = QPushButton("❌ Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_btn)
        
        self.reset_btn = QPushButton("🔄 Reset to Defaults")
        self.reset_btn.clicked.connect(self.reset_to_defaults)
        button_layout.addWidget(self.reset_btn)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
    
    def create_general_tab(self):
        """Create the general settings tab"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Auto-scan settings
        scan_group = QGroupBox("🔍 Auto-Scan Settings")
        scan_layout = QFormLayout()
        
        self.auto_scan_checkbox = QCheckBox("Enable automatic scanning")
        scan_layout.addRow("Auto-Scan:", self.auto_scan_checkbox)
        
        self.scan_interval_spinbox = QSpinBox()
        self.scan_interval_spinbox.setRange(30, 3600)
        self.scan_interval_spinbox.setSuffix(" seconds")
        scan_layout.addRow("Scan Interval:", self.scan_interval_spinbox)
        
        self.max_devices_spinbox = QSpinBox()
        self.max_devices_spinbox.setRange(10, 500)
        self.max_devices_spinbox.setSuffix(" devices")
        scan_layout.addRow("Max Devices:", self.max_devices_spinbox)
        
        scan_group.setLayout(scan_layout)
        layout.addWidget(scan_group)
        
        # Logging settings
        log_group = QGroupBox("📝 Logging Settings")
        log_layout = QFormLayout()
        
        self.log_level_combo = QComboBox()
        self.log_level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        log_layout.addRow("Log Level:", self.log_level_combo)
        
        self.log_to_file_checkbox = QCheckBox("Save logs to file")
        log_layout.addRow("File Logging:", self.log_to_file_checkbox)
        
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)
        
        layout.addStretch()
        widget.setLayout(layout)
        return widget
    
    def create_network_tab(self):
        """Create the network settings tab"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Network scan settings
        scan_group = QGroupBox("🔍 Network Scanning")
        scan_layout = QFormLayout()
        
        self.ping_timeout_spinbox = QSpinBox()
        self.ping_timeout_spinbox.setRange(1, 10)
        self.ping_timeout_spinbox.setSuffix(" seconds")
        scan_layout.addRow("Ping Timeout:", self.ping_timeout_spinbox)
        
        self.max_threads_spinbox = QSpinBox()
        self.max_threads_spinbox.setRange(5, 50)
        self.max_threads_spinbox.setSuffix(" threads")
        scan_layout.addRow("Max Threads:", self.max_threads_spinbox)
        
        self.quick_scan_checkbox = QCheckBox("Use quick scan mode")
        scan_layout.addRow("Quick Scan:", self.quick_scan_checkbox)
        
        scan_group.setLayout(scan_layout)
        layout.addWidget(scan_group)
        
        # Network interface settings
        interface_group = QGroupBox("🌐 Network Interface")
        interface_layout = QFormLayout()
        
        self.interface_combo = QComboBox()
        self.interface_combo.addItem("Auto-detect")
        # TODO: Populate with actual network interfaces
        interface_layout.addRow("Interface:", self.interface_combo)
        
        self.custom_network_edit = QLineEdit()
        self.custom_network_edit.setPlaceholderText("e.g., 192.168.1.0/24")
        interface_layout.addRow("Custom Network:", self.custom_network_edit)
        
        interface_group.setLayout(interface_layout)
        layout.addWidget(interface_group)
        
        layout.addStretch()
        widget.setLayout(layout)
        return widget
    
    def create_smart_mode_tab(self):
        """Create the smart mode settings tab"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Smart mode general settings
        general_group = QGroupBox("🧠 Smart Mode General")
        general_layout = QFormLayout()
        
        self.smart_mode_checkbox = QCheckBox("Enable smart mode")
        general_layout.addRow("Smart Mode:", self.smart_mode_checkbox)
        
        self.auto_block_checkbox = QCheckBox("Auto-block suspicious devices")
        general_layout.addRow("Auto-Block:", self.auto_block_checkbox)
        
        general_group.setLayout(general_layout)
        layout.addWidget(general_group)
        
        # Threshold settings
        threshold_group = QGroupBox("📊 Threshold Settings")
        threshold_layout = QFormLayout()
        
        self.high_traffic_threshold = QSpinBox()
        self.high_traffic_threshold.setRange(100, 10000)
        self.high_traffic_threshold.setSuffix(" KB/s")
        threshold_layout.addRow("High Traffic Threshold:", self.high_traffic_threshold)
        
        self.connection_limit = QSpinBox()
        self.connection_limit.setRange(10, 1000)
        self.connection_limit.setSuffix(" connections")
        threshold_layout.addRow("Connection Limit:", self.connection_limit)
        
        self.suspicious_activity_threshold = QSpinBox()
        self.suspicious_activity_threshold.setRange(5, 100)
        self.suspicious_activity_threshold.setSuffix(" events/min")
        threshold_layout.addRow("Suspicious Activity:", self.suspicious_activity_threshold)
        
        threshold_group.setLayout(threshold_layout)
        layout.addWidget(threshold_group)
        
        # Blocking settings
        blocking_group = QGroupBox("🚫 Blocking Settings")
        blocking_layout = QFormLayout()
        
        self.block_duration_spinbox = QSpinBox()
        self.block_duration_spinbox.setRange(1, 1440)
        self.block_duration_spinbox.setSuffix(" minutes")
        blocking_layout.addRow("Block Duration:", self.block_duration_spinbox)
        
        self.whitelist_edit = QTextEdit()
        self.whitelist_edit.setMaximumHeight(80)
        self.whitelist_edit.setPlaceholderText("Enter IP addresses to whitelist (one per line)")
        blocking_layout.addRow("Whitelist:", self.whitelist_edit)
        
        blocking_group.setLayout(blocking_layout)
        layout.addWidget(blocking_group)
        
        layout.addStretch()
        widget.setLayout(layout)
        return widget
    
    def create_ui_tab(self):
        """Create the UI settings tab"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Enhanced Theme settings
        theme_group = QGroupBox("🎨 Theme Settings")
        theme_layout = QVBoxLayout()
        
        # Theme selection
        theme_selection_layout = QHBoxLayout()
        theme_selection_layout.addWidget(QLabel("Theme:"))
        
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["dark", "light", "hacker", "rainbow"])
        self.theme_combo.currentTextChanged.connect(self.on_theme_selected)
        theme_selection_layout.addWidget(self.theme_combo)
        
        self.apply_theme_btn = QPushButton("Apply Theme")
        self.apply_theme_btn.clicked.connect(self.apply_selected_theme)
        theme_selection_layout.addWidget(self.apply_theme_btn)
        
        theme_layout.addLayout(theme_selection_layout)
        
        # Rainbow mode controls
        rainbow_group = QGroupBox("🌈 Rainbow Mode")
        rainbow_layout = QVBoxLayout()
        
        # Rainbow speed slider
        speed_layout = QHBoxLayout()
        speed_layout.addWidget(QLabel("Animation Speed:"))
        
        self.rainbow_speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.rainbow_speed_slider.setRange(1, 10)
        self.rainbow_speed_slider.setValue(2)
        self.rainbow_speed_slider.valueChanged.connect(self.on_rainbow_speed_changed)
        speed_layout.addWidget(self.rainbow_speed_slider)
        
        self.speed_label = QLabel("2.0")
        speed_layout.addWidget(self.speed_label)
        
        rainbow_layout.addLayout(speed_layout)
        
        # Rainbow control buttons
        rainbow_buttons_layout = QHBoxLayout()
        
        self.start_rainbow_btn = QPushButton("Start Rainbow")
        self.start_rainbow_btn.clicked.connect(self.start_rainbow_mode)
        rainbow_buttons_layout.addWidget(self.start_rainbow_btn)
        
        self.stop_rainbow_btn = QPushButton("Stop Rainbow")
        self.stop_rainbow_btn.clicked.connect(self.stop_rainbow_mode)
        rainbow_buttons_layout.addWidget(self.stop_rainbow_btn)
        
        rainbow_layout.addLayout(rainbow_buttons_layout)
        
        # Quick theme buttons
        quick_themes_layout = QHBoxLayout()
        quick_themes_layout.addWidget(QLabel("Quick Themes:"))
        
        self.light_theme_btn = QPushButton("Light")
        self.light_theme_btn.clicked.connect(lambda: self.apply_theme("light"))
        quick_themes_layout.addWidget(self.light_theme_btn)
        
        self.dark_theme_btn = QPushButton("Dark")
        self.dark_theme_btn.clicked.connect(lambda: self.apply_theme("dark"))
        quick_themes_layout.addWidget(self.dark_theme_btn)
        
        self.hacker_theme_btn = QPushButton("Hacker")
        self.hacker_theme_btn.clicked.connect(lambda: self.apply_theme("hacker"))
        quick_themes_layout.addWidget(self.hacker_theme_btn)
        
        self.rainbow_theme_btn = QPushButton("Rainbow")
        self.rainbow_theme_btn.clicked.connect(lambda: self.apply_theme("rainbow"))
        quick_themes_layout.addWidget(self.rainbow_theme_btn)
        
        rainbow_layout.addLayout(quick_themes_layout)
        
        # Theme info
        self.theme_info_label = QLabel("Current Theme: Dark")
        self.theme_info_label.setStyleSheet("color: #888888; font-style: italic;")
        rainbow_layout.addWidget(self.theme_info_label)
        
        rainbow_group.setLayout(rainbow_layout)
        theme_layout.addWidget(rainbow_group)
        
        # Add the theme group to the main layout
        theme_group.setLayout(theme_layout)
        layout.addWidget(theme_group)
        
        # Auto-refresh settings
        refresh_group = QGroupBox("🔄 Auto-Refresh Settings")
        refresh_layout = QFormLayout()
        
        self.auto_refresh_checkbox = QCheckBox("Enable auto-refresh")
        refresh_layout.addRow("Auto-Refresh:", self.auto_refresh_checkbox)
        
        self.refresh_interval_spinbox = QSpinBox()
        self.refresh_interval_spinbox.setRange(10, 300)
        self.refresh_interval_spinbox.setSuffix(" seconds")
        refresh_layout.addRow("Refresh Interval:", self.refresh_interval_spinbox)
        
        refresh_group.setLayout(refresh_layout)
        theme_layout.addWidget(refresh_group)
        
        # Display settings
        display_group = QGroupBox("📱 Display Settings")
        display_layout = QFormLayout()
        
        self.show_device_icons_checkbox = QCheckBox("Show device type icons")
        display_layout.addRow("Device Icons:", self.show_device_icons_checkbox)
        
        self.show_status_indicators_checkbox = QCheckBox("Show status indicators")
        display_layout.addRow("Status Indicators:", self.show_status_indicators_checkbox)
        
        self.compact_view_checkbox = QCheckBox("Use compact view")
        display_layout.addRow("Compact View:", self.compact_view_checkbox)
        
        display_group.setLayout(display_layout)
        layout.addWidget(display_group)
        
        # Notifications
        notification_group = QGroupBox("🔔 Notifications")
        notification_layout = QFormLayout()
        
        self.show_notifications_checkbox = QCheckBox("Show desktop notifications")
        notification_layout.addRow("Desktop Notifications:", self.show_notifications_checkbox)
        
        self.sound_alerts_checkbox = QCheckBox("Play sound alerts")
        notification_layout.addRow("Sound Alerts:", self.sound_alerts_checkbox)
        
        notification_group.setLayout(notification_layout)
        layout.addWidget(notification_group)
        
        layout.addStretch()
        widget.setLayout(layout)
        return widget
    
    def create_advanced_tab(self):
        """Create the advanced settings tab"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Performance settings
        performance_group = QGroupBox("⚡ Performance Settings")
        performance_layout = QFormLayout()
        
        self.cache_duration_spinbox = QSpinBox()
        self.cache_duration_spinbox.setRange(30, 600)
        self.cache_duration_spinbox.setSuffix(" seconds")
        performance_layout.addRow("Cache Duration:", self.cache_duration_spinbox)
        
        self.memory_limit_spinbox = QSpinBox()
        self.memory_limit_spinbox.setRange(50, 1000)
        self.memory_limit_spinbox.setSuffix(" MB")
        performance_layout.addRow("Memory Limit:", self.memory_limit_spinbox)
        
        performance_group.setLayout(performance_layout)
        layout.addWidget(performance_group)
        
        # Security settings
        security_group = QGroupBox("🔒 Security Settings")
        security_layout = QFormLayout()
        
        self.require_admin_checkbox = QCheckBox("Require administrator privileges")
        security_layout.addRow("Admin Required:", self.require_admin_checkbox)
        
        self.encrypt_logs_checkbox = QCheckBox("Encrypt log files")
        security_layout.addRow("Encrypt Logs:", self.encrypt_logs_checkbox)
        
        security_group.setLayout(security_layout)
        layout.addWidget(security_group)
        
        # Debug settings
        debug_group = QGroupBox("🐛 Debug Settings")
        debug_layout = QFormLayout()
        
        self.debug_mode_checkbox = QCheckBox("Enable debug mode")
        debug_layout.addRow("Debug Mode:", self.debug_mode_checkbox)
        
        self.verbose_logging_checkbox = QCheckBox("Verbose logging")
        debug_layout.addRow("Verbose Logging:", self.verbose_logging_checkbox)
        
        debug_group.setLayout(debug_layout)
        layout.addWidget(debug_group)
        
        layout.addStretch()
        widget.setLayout(layout)
        return widget
    
    def load_current_settings(self):
        """Load current settings into the UI"""
        try:
            # General settings
            self.auto_scan_checkbox.setChecked(self.current_settings.auto_scan)
            self.scan_interval_spinbox.setValue(self.current_settings.scan_interval)
            self.max_devices_spinbox.setValue(self.current_settings.max_devices)
            self.log_level_combo.setCurrentText(self.current_settings.log_level)
            
            # Smart mode settings
            self.smart_mode_checkbox.setChecked(self.current_settings.smart_mode)
            
            # Network settings
            self.ping_timeout_spinbox.setValue(self.current_settings.ping_timeout)
            self.max_threads_spinbox.setValue(self.current_settings.max_threads)
            self.quick_scan_checkbox.setChecked(self.current_settings.quick_scan)
            self.auto_block_checkbox.setChecked(self.current_settings.auto_block)
            self.high_traffic_threshold.setValue(self.current_settings.high_traffic_threshold)
            self.connection_limit.setValue(self.current_settings.connection_limit)
            self.suspicious_activity_threshold.setValue(self.current_settings.suspicious_activity_threshold)
            self.block_duration_spinbox.setValue(self.current_settings.block_duration)
            
            # UI settings
            self.theme_combo.setCurrentText(self.current_settings.theme)
            # Initialize theme info
            self.update_theme_info()
            self.auto_refresh_checkbox.setChecked(self.current_settings.auto_refresh)
            self.refresh_interval_spinbox.setValue(self.current_settings.refresh_interval)
            self.show_device_icons_checkbox.setChecked(self.current_settings.show_device_icons)
            self.show_status_indicators_checkbox.setChecked(self.current_settings.show_status_indicators)
            self.compact_view_checkbox.setChecked(self.current_settings.compact_view)
            self.show_notifications_checkbox.setChecked(self.current_settings.show_notifications)
            self.sound_alerts_checkbox.setChecked(self.current_settings.sound_alerts)
            
            # Advanced settings
            self.cache_duration_spinbox.setValue(self.current_settings.cache_duration)
            self.memory_limit_spinbox.setValue(self.current_settings.memory_limit)
            self.require_admin_checkbox.setChecked(self.current_settings.require_admin)
            self.encrypt_logs_checkbox.setChecked(self.current_settings.encrypt_logs)
            self.debug_mode_checkbox.setChecked(self.current_settings.debug_mode)
            self.verbose_logging_checkbox.setChecked(self.current_settings.verbose_logging)
            
            # Security settings
            if hasattr(self.current_settings, 'whitelist') and self.current_settings.whitelist:
                self.whitelist_edit.setPlainText('\n'.join(self.current_settings.whitelist))
            
        except Exception as e:
            log_error(f"Error loading settings: {e}")
    
    def save_settings(self):
        """Save the current settings"""
        try:
            # Create new settings object with all settings
            new_settings = AppSettings(
                smart_mode=self.smart_mode_checkbox.isChecked(),
                auto_scan=self.auto_scan_checkbox.isChecked(),
                scan_interval=self.scan_interval_spinbox.value(),
                max_devices=self.max_devices_spinbox.value(),
                log_level=self.log_level_combo.currentText(),
                
                # Network settings
                ping_timeout=self.ping_timeout_spinbox.value(),
                max_threads=self.max_threads_spinbox.value(),
                quick_scan=self.quick_scan_checkbox.isChecked(),
                auto_block=self.auto_block_checkbox.isChecked(),
                high_traffic_threshold=self.high_traffic_threshold.value(),
                connection_limit=self.connection_limit.value(),
                suspicious_activity_threshold=self.suspicious_activity_threshold.value(),
                block_duration=self.block_duration_spinbox.value(),
                
                # UI settings
                theme=self.theme_combo.currentText(),
                auto_refresh=self.auto_refresh_checkbox.isChecked(),
                refresh_interval=self.refresh_interval_spinbox.value(),
                show_device_icons=self.show_device_icons_checkbox.isChecked(),
                show_status_indicators=self.show_status_indicators_checkbox.isChecked(),
                compact_view=self.compact_view_checkbox.isChecked(),
                show_notifications=self.show_notifications_checkbox.isChecked(),
                sound_alerts=self.sound_alerts_checkbox.isChecked(),
                
                # Advanced settings
                cache_duration=self.cache_duration_spinbox.value(),
                memory_limit=self.memory_limit_spinbox.value(),
                require_admin=self.require_admin_checkbox.isChecked(),
                encrypt_logs=self.encrypt_logs_checkbox.isChecked(),
                debug_mode=self.debug_mode_checkbox.isChecked(),
                verbose_logging=self.verbose_logging_checkbox.isChecked(),
                
                # Security settings
                whitelist=self.whitelist_edit.toPlainText().split('\n') if self.whitelist_edit.toPlainText() else []
            )
            
            self.new_settings = new_settings
            
            # Emit settings changed signal for immediate UI updates
            additional_settings = {
                "theme": self.theme_combo.currentText(),
                "auto_refresh": self.auto_refresh_checkbox.isChecked(),
                "refresh_interval": self.refresh_interval_spinbox.value(),
                "show_device_icons": self.show_device_icons_checkbox.isChecked(),
                "show_status_indicators": self.show_status_indicators_checkbox.isChecked(),
                "compact_view": self.compact_view_checkbox.isChecked(),
                "show_notifications": self.show_notifications_checkbox.isChecked(),
                "sound_alerts": self.sound_alerts_checkbox.isChecked()
            }
            self.settings_changed.emit(additional_settings)
            
            log_info("Settings saved successfully")
            QMessageBox.information(self, "Success", "Settings saved successfully!")
            self.accept()
            
        except Exception as e:
            log_error(f"Error saving settings: {e}")
            QMessageBox.critical(self, "Error", f"Failed to save settings: {e}")
    
    def reset_to_defaults(self):
        """Reset all settings to defaults"""
        try:
            reply = QMessageBox.question(
                self, "Reset Settings",
                "Are you sure you want to reset all settings to defaults?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                # Create default settings object
                default_settings = AppSettings()
                
                # Reset to default values
                self.auto_scan_checkbox.setChecked(default_settings.auto_scan)
                self.scan_interval_spinbox.setValue(default_settings.scan_interval)
                self.max_devices_spinbox.setValue(default_settings.max_devices)
                self.log_level_combo.setCurrentText(default_settings.log_level)
                self.smart_mode_checkbox.setChecked(default_settings.smart_mode)
                
                # Reset network settings to defaults
                self.ping_timeout_spinbox.setValue(default_settings.ping_timeout)
                self.max_threads_spinbox.setValue(default_settings.max_threads)
                self.quick_scan_checkbox.setChecked(default_settings.quick_scan)
                self.auto_block_checkbox.setChecked(default_settings.auto_block)
                self.high_traffic_threshold.setValue(default_settings.high_traffic_threshold)
                self.connection_limit.setValue(default_settings.connection_limit)
                self.suspicious_activity_threshold.setValue(default_settings.suspicious_activity_threshold)
                self.block_duration_spinbox.setValue(default_settings.block_duration)
                
                # Reset UI settings to defaults
                self.theme_combo.setCurrentText(default_settings.theme)
                self.auto_refresh_checkbox.setChecked(default_settings.auto_refresh)
                self.refresh_interval_spinbox.setValue(default_settings.refresh_interval)
                self.show_device_icons_checkbox.setChecked(default_settings.show_device_icons)
                self.show_status_indicators_checkbox.setChecked(default_settings.show_status_indicators)
                self.compact_view_checkbox.setChecked(default_settings.compact_view)
                self.show_notifications_checkbox.setChecked(default_settings.show_notifications)
                self.sound_alerts_checkbox.setChecked(default_settings.sound_alerts)
                
                # Reset advanced settings to defaults
                self.cache_duration_spinbox.setValue(default_settings.cache_duration)
                self.memory_limit_spinbox.setValue(default_settings.memory_limit)
                self.require_admin_checkbox.setChecked(default_settings.require_admin)
                self.encrypt_logs_checkbox.setChecked(default_settings.encrypt_logs)
                self.debug_mode_checkbox.setChecked(default_settings.debug_mode)
                self.verbose_logging_checkbox.setChecked(default_settings.verbose_logging)
                
                # Reset security settings
                self.whitelist_edit.clear()
                
                log_info("Settings reset to defaults")
                QMessageBox.information(self, "Success", "Settings reset to defaults!")
                
        except Exception as e:
            log_error(f"Error resetting settings: {e}")
            QMessageBox.critical(self, "Error", f"Failed to reset settings: {e}")
    
    def get_new_settings(self) -> AppSettings:
        """Get the new settings object"""
        return self.new_settings
    
    def create_testing_tab(self):
        """Create the testing tab"""
        testing_widget = QWidget()
        layout = QVBoxLayout()
        
        # Testing section
        testing_group = QGroupBox("🧪 Testing & Debugging")
        testing_layout = QVBoxLayout()
        
        # Testing description
        testing_desc = QLabel("""
        Run comprehensive tests to verify all PulseDrop Pro features are working correctly.
        Tests include network scanning, device health protection, privacy features, and blocking systems.
        """)
        testing_desc.setWordWrap(True)
        testing_layout.addWidget(testing_desc)
        
        # Testing buttons
        testing_buttons_layout = QHBoxLayout()
        
        self.health_test_btn = QPushButton("🏥 Health Test")
        self.health_test_btn.clicked.connect(self.run_health_test)
        testing_buttons_layout.addWidget(self.health_test_btn)
        
        self.network_test_btn = QPushButton("🌐 Network Test")
        self.network_test_btn.clicked.connect(self.run_network_test)
        testing_buttons_layout.addWidget(self.network_test_btn)
        
        self.privacy_test_btn = QPushButton("🔒 Privacy Test")
        self.privacy_test_btn.clicked.connect(self.run_privacy_test)
        testing_buttons_layout.addWidget(self.privacy_test_btn)
        
        testing_layout.addLayout(testing_buttons_layout)
        
        # Comprehensive test button
        self.comprehensive_test_btn = QPushButton("🚀 Comprehensive Test")
        self.comprehensive_test_btn.setStyleSheet("""
            QPushButton {
                background-color: #00ff00;
                color: #000000;
                font-weight: bold;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #00cc00;
            }
        """)
        self.comprehensive_test_btn.clicked.connect(self.run_comprehensive_test)
        testing_layout.addWidget(self.comprehensive_test_btn)
        
        # Debug options
        debug_group = QGroupBox("🐛 Debug Options")
        debug_layout = QVBoxLayout()
        
        self.enable_debug_checkbox = QCheckBox("Enable Debug Logging")
        self.enable_debug_checkbox.setChecked(True)
        debug_layout.addWidget(self.enable_debug_checkbox)
        
        self.verbose_logging_checkbox = QCheckBox("Verbose Logging")
        self.verbose_logging_checkbox.setChecked(False)
        debug_layout.addWidget(self.verbose_logging_checkbox)
        
        self.auto_test_checkbox = QCheckBox("Auto-run tests on startup")
        self.auto_test_checkbox.setChecked(False)
        debug_layout.addWidget(self.auto_test_checkbox)
        
        debug_group.setLayout(debug_layout)
        testing_layout.addWidget(debug_group)
        
        testing_group.setLayout(testing_layout)
        layout.addWidget(testing_group)
        
        testing_widget.setLayout(layout)
        return testing_widget
    
    def run_health_test(self):
        """Run device health test"""
        try:
            from app.gui.testing_dialog import TestingDialog
            dialog = TestingDialog(self)
            dialog.test_combo.setCurrentText("Device Health")
            dialog.run_test("Device Health")
            dialog.exec()
        except Exception as e:
            QMessageBox.critical(self, "Test Error", f"Failed to run health test: {e}")
    
    def run_network_test(self):
        """Run network test"""
        try:
            from app.gui.testing_dialog import TestingDialog
            dialog = TestingDialog(self)
            dialog.test_combo.setCurrentText("Network Scanner")
            dialog.run_test("Network Scanner")
            dialog.exec()
        except Exception as e:
            QMessageBox.critical(self, "Test Error", f"Failed to run network test: {e}")
    
    def run_privacy_test(self):
        """Run privacy test"""
        try:
            from app.gui.testing_dialog import TestingDialog
            dialog = TestingDialog(self)
            dialog.test_combo.setCurrentText("Privacy Protection")
            dialog.run_test("Privacy Protection")
            dialog.exec()
        except Exception as e:
            QMessageBox.critical(self, "Test Error", f"Failed to run privacy test: {e}")
    
    def run_comprehensive_test(self):
        """Run comprehensive test"""
        try:
            from app.gui.testing_dialog import TestingDialog
            dialog = TestingDialog(self)
            dialog.test_combo.setCurrentText("Comprehensive")
            dialog.run_test("Comprehensive")
            dialog.exec()
        except Exception as e:
            QMessageBox.critical(self, "Test Error", f"Failed to run comprehensive test: {e}")
    
    # Theme Management Methods
    def on_theme_selected(self, theme_name: str):
        """Handle theme selection"""
        try:
            log_info(f"Theme selected: {theme_name}")
            self.update_theme_info()
        except Exception as e:
            log_error(f"Error handling theme selection: {e}")
    
    def apply_selected_theme(self):
        """Apply the selected theme"""
        try:
            theme_name = self.theme_combo.currentText()
            self.apply_theme(theme_name)
        except Exception as e:
            log_error(f"Error applying selected theme: {e}")
    
    def apply_theme(self, theme_name: str):
        """Apply a theme"""
        try:
            from app.themes.theme_manager import theme_manager
            success = theme_manager.apply_theme(theme_name)
            if success:
                self.update_theme_info()
                log_info(f"Theme applied: {theme_name}")
            else:
                log_error(f"Failed to apply theme: {theme_name}")
        except Exception as e:
            log_error(f"Error applying theme {theme_name}: {e}")
    
    def on_rainbow_speed_changed(self, value: int):
        """Handle rainbow speed slider change"""
        try:
            speed = value / 10.0  # Convert to float
            self.speed_label.setText(f"{speed:.1f}")
            
            from app.themes.theme_manager import theme_manager
            theme_manager.set_rainbow_speed(speed)
            log_info(f"Rainbow speed changed to: {speed}")
        except Exception as e:
            log_error(f"Error changing rainbow speed: {e}")
    
    def start_rainbow_mode(self):
        """Start rainbow mode"""
        try:
            from app.themes.theme_manager import theme_manager
            theme_manager.start_rainbow_mode()
            self.update_theme_info()
            log_info("Rainbow mode started")
        except Exception as e:
            log_error(f"Error starting rainbow mode: {e}")
    
    def stop_rainbow_mode(self):
        """Stop rainbow mode"""
        try:
            from app.themes.theme_manager import theme_manager
            theme_manager.stop_rainbow_mode()
            self.update_theme_info()
            log_info("Rainbow mode stopped")
        except Exception as e:
            log_error(f"Error stopping rainbow mode: {e}")
    
    def update_theme_info(self):
        """Update theme information display"""
        try:
            from app.themes.theme_manager import theme_manager
            current_theme = theme_manager.get_current_theme()
            rainbow_active = theme_manager.is_rainbow_active()
            rainbow_speed = theme_manager.get_rainbow_speed()
            
            status_text = f"Current Theme: {current_theme.title()}"
            if rainbow_active:
                status_text += f" (Rainbow Active, Speed: {rainbow_speed:.1f})"
            
            self.theme_info_label.setText(status_text)
            
            # Update button states
            self.start_rainbow_btn.setEnabled(not rainbow_active)
            self.stop_rainbow_btn.setEnabled(rainbow_active)
            
        except Exception as e:
            log_error(f"Error updating theme info: {e}") 