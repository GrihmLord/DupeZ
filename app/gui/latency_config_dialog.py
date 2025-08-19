"""
Latency Configuration Dialog for DupeZ Application
Clean, organized interface for managing all latency settings
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget, QLabel, 
    QSpinBox, QComboBox, QPushButton, QTableWidget, QTableWidgetItem,
    QGroupBox, QFormLayout, QCheckBox, QTextEdit, QMessageBox,
    QHeaderView, QSplitter, QScrollArea
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QColor

from app.core.latency_manager import latency_manager
from app.logs.logger import log_info, log_error

class LatencyConfigDialog(QDialog):
    """Main latency configuration dialog"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        self.load_current_config()
        
    def setup_ui(self):
        """Setup the user interface"""
        self.setWindowTitle("DupeZ Latency Configuration")
        self.setMinimumSize(900, 700)
        
        # Main layout
        layout = QVBoxLayout()
        
        # Title
        title_label = QLabel("Latency Configuration & Optimization")
        title_label.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)
        
        # Tab widget for different configuration sections
        self.tab_widget = QTabWidget()
        
        # Gaming Latency Tab
        self.gaming_tab = GamingLatencyTab()
        self.tab_widget.addTab(self.gaming_tab, "Gaming Latency")
        
        # Server Configuration Tab
        self.server_tab = ServerConfigTab()
        self.tab_widget.addTab(self.server_tab, "Server Configuration")
        
        # Duping Profiles Tab
        self.duping_tab = DupingProfilesTab()
        self.tab_widget.addTab(self.duping_tab, "Duping Profiles")
        
        # Network Optimization Tab
        self.network_tab = NetworkOptimizationTab()
        self.tab_widget.addTab(self.network_tab, "Network Optimization")
        
        # Performance Monitoring Tab
        self.monitoring_tab = PerformanceMonitoringTab()
        self.tab_widget.addTab(self.monitoring_tab, "Performance Monitoring")
        
        layout.addWidget(self.tab_widget)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.save_button = QPushButton("Save Configuration")
        self.save_button.clicked.connect(self.save_configuration)
        self.save_button.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        
        self.reload_button = QPushButton("Reload")
        self.reload_button.clicked.connect(self.reload_configuration)
        
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        
        button_layout.addWidget(self.save_button)
        button_layout.addWidget(self.reload_button)
        button_layout.addStretch()
        button_layout.addWidget(self.close_button)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
        
    def load_current_config(self):
        """Load current configuration into all tabs"""
        try:
            self.gaming_tab.load_config()
            self.server_tab.load_config()
            self.duping_tab.load_config()
            self.network_tab.load_config()
            self.monitoring_tab.load_config()
            log_info("Latency configuration loaded into dialog")
        except Exception as e:
            log_error(f"Failed to load configuration into dialog: {e}")
    
    def save_configuration(self):
        """Save all configuration changes"""
        try:
            # Collect changes from all tabs
            changes = {}
            changes.update(self.gaming_tab.get_changes())
            changes.update(self.server_tab.get_changes())
            changes.update(self.duping_tab.get_changes())
            changes.update(self.network_tab.get_changes())
            changes.update(self.monitoring_tab.get_changes())
            
            # Apply changes to latency manager
            if changes:
                latency_manager.config.update(changes)
                if latency_manager.save_configuration():
                    QMessageBox.information(self, "Success", "Configuration saved successfully!")
                    log_info("Latency configuration saved")
                else:
                    QMessageBox.warning(self, "Warning", "Failed to save configuration")
            else:
                QMessageBox.information(self, "Info", "No changes to save")
                
        except Exception as e:
            log_error(f"Failed to save configuration: {e}")
            QMessageBox.critical(self, "Error", f"Failed to save configuration: {e}")
    
    def reload_configuration(self):
        """Reload configuration from file"""
        try:
            if latency_manager.reload_configuration():
                self.load_current_config()
                QMessageBox.information(self, "Success", "Configuration reloaded successfully!")
            else:
                QMessageBox.warning(self, "Warning", "Failed to reload configuration")
        except Exception as e:
            log_error(f"Failed to reload configuration: {e}")
            QMessageBox.critical(self, "Error", f"Failed to reload configuration: {e}")


class GamingLatencyTab(QWidget):
    """Gaming latency configuration tab"""
    
    def __init__(self):
        super().__init__()
        self.setup_ui()
        
    def setup_ui(self):
        """Setup the gaming latency UI"""
        layout = QVBoxLayout()
        
        # Description
        desc_label = QLabel("Configure gaming latency tiers for different performance levels")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)
        
        # Latency profiles table
        self.profiles_table = QTableWidget()
        self.profiles_table.setColumnCount(7)
        self.profiles_table.setHorizontalHeaderLabels([
            "Profile", "Target (ms)", "Max (ms)", "Priority", "QoS Level", "Bandwidth (Mbps)", "Description"
        ])
        
        # Set table properties
        header = self.profiles_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        
        layout.addWidget(self.profiles_table)
        
        # Add/Edit buttons
        button_layout = QHBoxLayout()
        
        self.add_profile_button = QPushButton("Add Profile")
        self.add_profile_button.clicked.connect(self.add_profile)
        
        self.edit_profile_button = QPushButton("Edit Profile")
        self.edit_profile_button.clicked.connect(self.edit_profile)
        
        self.delete_profile_button = QPushButton("Delete Profile")
        self.delete_profile_button.clicked.connect(self.delete_profile)
        
        button_layout.addWidget(self.add_profile_button)
        button_layout.addWidget(self.edit_profile_button)
        button_layout.addWidget(self.delete_profile_button)
        button_layout.addStretch()
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
        
    def load_config(self):
        """Load gaming latency configuration"""
        try:
            profiles = latency_manager.get_all_profiles()
            self.profiles_table.setRowCount(len(profiles))
            
            for row, (name, profile) in enumerate(profiles.items()):
                self.profiles_table.setItem(row, 0, QTableWidgetItem(profile.name))
                self.profiles_table.setItem(row, 1, QTableWidgetItem(str(profile.target_ms)))
                self.profiles_table.setItem(row, 2, QTableWidgetItem(str(profile.max_ms)))
                self.profiles_table.setItem(row, 3, QTableWidgetItem(profile.priority))
                self.profiles_table.setItem(row, 4, QTableWidgetItem(profile.qos_level))
                self.profiles_table.setItem(row, 5, QTableWidgetItem(str(profile.bandwidth_reserved)))
                self.profiles_table.setItem(row, 6, QTableWidgetItem(profile.description))
                
        except Exception as e:
            log_error(f"Failed to load gaming latency config: {e}")
    
    def get_changes(self):
        """Get changes from the gaming latency tab"""
        # Implementation for collecting changes
        return {}
    
    def add_profile(self):
        """Add new latency profile"""
        # Implementation for adding profile
        pass
    
    def edit_profile(self):
        """Edit selected latency profile"""
        # Implementation for editing profile
        pass
    
    def delete_profile(self):
        """Delete selected latency profile"""
        # Implementation for deleting profile
        pass


class ServerConfigTab(QWidget):
    """Server configuration tab"""
    
    def __init__(self):
        super().__init__()
        self.setup_ui()
        
    def setup_ui(self):
        """Setup the server configuration UI"""
        layout = QVBoxLayout()
        
        # Description
        desc_label = QLabel("Configure DayZ server latency settings and optimization")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)
        
        # Server configuration table
        self.servers_table = QTableWidget()
        self.servers_table.setColumnCount(8)
        self.servers_table.setHorizontalHeaderLabels([
            "Server", "IP Address", "Ports", "Target (ms)", "Max (ms)", "Priority", "Auto-Optimize", "DDoS Protection"
        ])
        
        # Set table properties
        header = self.servers_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        
        layout.addWidget(self.servers_table)
        
        # Server management buttons
        button_layout = QHBoxLayout()
        
        self.add_server_button = QPushButton("Add Server")
        self.add_server_button.clicked.connect(self.add_server)
        
        self.edit_server_button = QPushButton("Edit Server")
        self.edit_server_button.clicked.connect(self.edit_server)
        
        self.delete_server_button = QPushButton("Delete Server")
        self.delete_server_button.clicked.connect(self.delete_server)
        
        button_layout.addWidget(self.add_server_button)
        button_layout.addWidget(self.edit_server_button)
        button_layout.addWidget(self.delete_server_button)
        button_layout.addStretch()
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
        
    def load_config(self):
        """Load server configuration"""
        try:
            servers = latency_manager.get_all_servers()
            self.servers_table.setRowCount(len(servers))
            
            for row, (name, server) in enumerate(servers.items()):
                self.servers_table.setItem(row, 0, QTableWidgetItem(server.name))
                self.servers_table.setItem(row, 1, QTableWidgetItem(server.ip))
                self.servers_table.setItem(row, 2, QTableWidgetItem(", ".join(map(str, server.ports))))
                self.servers_table.setItem(row, 3, QTableWidgetItem(str(server.target_latency)))
                self.servers_table.setItem(row, 4, QTableWidgetItem(str(server.max_latency)))
                self.servers_table.setItem(row, 5, QTableWidgetItem(server.priority))
                self.servers_table.setItem(row, 6, QTableWidgetItem("Yes" if server.auto_optimize else "No"))
                self.servers_table.setItem(row, 7, QTableWidgetItem("Yes" if server.ddos_protection else "No"))
                
        except Exception as e:
            log_error(f"Failed to load server config: {e}")
    
    def get_changes(self):
        """Get changes from the server config tab"""
        return {}
    
    def add_server(self):
        """Add new server configuration"""
        pass
    
    def edit_server(self):
        """Edit selected server configuration"""
        pass
    
    def delete_server(self):
        """Delete selected server configuration"""
        pass


class DupingProfilesTab(QWidget):
    """Duping profiles configuration tab"""
    
    def __init__(self):
        super().__init__()
        self.setup_ui()
        
    def setup_ui(self):
        """Setup the duping profiles UI"""
        layout = QVBoxLayout()
        
        # Description
        desc_label = QLabel("Configure duping latency profiles for different stealth levels")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)
        
        # Profile selection and configuration
        profile_group = QGroupBox("Duping Profile Configuration")
        profile_layout = QFormLayout()
        
        self.profile_combo = QComboBox()
        self.profile_combo.currentTextChanged.connect(self.on_profile_changed)
        profile_layout.addRow("Profile:", self.profile_combo)
        
        self.latency_variance_spin = QSpinBox()
        self.latency_variance_spin.setRange(1, 100)
        self.latency_variance_spin.setSuffix(" ms")
        profile_layout.addRow("Latency Variance:", self.latency_variance_spin)
        
        self.packet_timing_spin = QSpinBox()
        self.packet_timing_spin.setRange(1, 50)
        self.packet_timing_spin.setSuffix(" ms")
        profile_layout.addRow("Packet Timing:", self.packet_timing_spin)
        
        self.target_latency_spin = QSpinBox()
        self.target_latency_spin.setRange(10, 200)
        self.target_latency_spin.setSuffix(" ms")
        profile_layout.addRow("Target Latency:", self.target_latency_spin)
        
        self.max_latency_spin = QSpinBox()
        self.max_latency_spin.setRange(20, 500)
        self.max_latency_spin.setSuffix(" ms")
        profile_layout.addRow("Max Latency:", self.max_latency_spin)
        
        profile_group.setLayout(profile_layout)
        layout.addWidget(profile_group)
        
        # Profile information
        info_group = QGroupBox("Profile Information")
        info_layout = QVBoxLayout()
        
        self.info_text = QTextEdit()
        self.info_text.setMaximumHeight(100)
        self.info_text.setReadOnly(True)
        info_layout.addWidget(self.info_text)
        
        info_group.setLayout(info_layout)
        layout.addWidget(info_group)
        
        self.setLayout(layout)
        
    def load_config(self):
        """Load duping profiles configuration"""
        try:
            duping_profiles = latency_manager.config.get("duping_latency_profiles", {})
            self.profile_combo.clear()
            self.profile_combo.addItems(duping_profiles.keys())
            
            if duping_profiles:
                self.on_profile_changed(self.profile_combo.currentText())
                
        except Exception as e:
            log_error(f"Failed to load duping profiles: {e}")
    
    def on_profile_changed(self, profile_name: str):
        """Handle profile selection change"""
        try:
            if not profile_name:
                return
                
            profile = latency_manager.get_duping_profile(profile_name)
            if profile:
                self.latency_variance_spin.setValue(profile.get("latency_variance", 10))
                self.packet_timing_spin.setValue(profile.get("packet_timing", 5))
                self.target_latency_spin.setValue(profile.get("target_latency", 30))
                self.max_latency_spin.setValue(profile.get("max_latency", 50))
                
                # Update info text
                info = f"Profile: {profile.get('name', profile_name)}\n"
                info += f"Description: {profile.get('description', '')}\n"
                info += f"Detection Risk: {profile.get('detection_risk', 'medium')}\n"
                info += f"Success Rate: {profile.get('success_rate', 0)}%"
                
                self.info_text.setText(info)
                
        except Exception as e:
            log_error(f"Failed to update profile display: {e}")
    
    def get_changes(self):
        """Get changes from the duping profiles tab"""
        return {}


class NetworkOptimizationTab(QWidget):
    """Network optimization configuration tab"""
    
    def __init__(self):
        super().__init__()
        self.setup_ui()
        
    def setup_ui(self):
        """Setup the network optimization UI"""
        layout = QVBoxLayout()
        
        # Description
        desc_label = QLabel("Configure network optimization and QoS policies")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)
        
        # QoS Policies
        qos_group = QGroupBox("QoS Policies")
        qos_layout = QFormLayout()
        
        self.gaming_latency_spin = QSpinBox()
        self.gaming_latency_spin.setRange(10, 100)
        self.gaming_latency_spin.setSuffix(" ms")
        qos_layout.addRow("Gaming Latency Target:", self.gaming_latency_spin)
        
        self.voice_latency_spin = QSpinBox()
        self.voice_latency_spin.setRange(20, 100)
        self.voice_latency_spin.setSuffix(" ms")
        qos_layout.addRow("Voice Chat Latency Target:", self.voice_latency_spin)
        
        self.streaming_latency_spin = QSpinBox()
        self.streaming_latency_spin.setRange(100, 500)
        self.streaming_latency_spin.setSuffix(" ms")
        qos_layout.addRow("Streaming Latency Target:", self.streaming_latency_spin)
        
        qos_group.setLayout(qos_layout)
        layout.addWidget(qos_group)
        
        # Auto-optimization settings
        auto_group = QGroupBox("Auto-Optimization")
        auto_layout = QFormLayout()
        
        self.auto_optimize_check = QCheckBox("Enable Auto-Optimization")
        auto_layout.addRow(self.auto_optimize_check)
        
        self.check_interval_spin = QSpinBox()
        self.check_interval_spin.setRange(10, 300)
        self.check_interval_spin.setSuffix(" seconds")
        auto_layout.addRow("Check Interval:", self.check_interval_spin)
        
        self.cooldown_spin = QSpinBox()
        self.cooldown_spin.setRange(60, 1800)
        self.cooldown_spin.setSuffix(" seconds")
        auto_layout.addRow("Optimization Cooldown:", self.cooldown_spin)
        
        auto_group.setLayout(auto_layout)
        layout.addWidget(auto_group)
        
        self.setLayout(layout)
        
    def load_config(self):
        """Load network optimization configuration"""
        try:
            network_config = latency_manager.config.get("network_optimization", {})
            qos_policies = network_config.get("qos_policies", {})
            auto_opt = network_config.get("auto_optimization", {})
            
            # Load QoS settings
            if "gaming" in qos_policies:
                self.gaming_latency_spin.setValue(qos_policies["gaming"].get("latency_target", 25))
            if "voice_chat" in qos_policies:
                self.voice_latency_spin.setValue(qos_policies["voice_chat"].get("latency_target", 35))
            if "streaming" in qos_policies:
                self.streaming_latency_spin.setValue(qos_policies["streaming"].get("latency_target", 200))
            
            # Load auto-optimization settings
            self.auto_optimize_check.setChecked(auto_opt.get("enabled", True))
            self.check_interval_spin.setValue(auto_opt.get("check_interval", 30))
            self.cooldown_spin.setValue(auto_opt.get("optimization_cooldown", 300))
            
        except Exception as e:
            log_error(f"Failed to load network optimization config: {e}")
    
    def get_changes(self):
        """Get changes from the network optimization tab"""
        return {}


class PerformanceMonitoringTab(QWidget):
    """Performance monitoring configuration tab"""
    
    def __init__(self):
        super().__init__()
        self.setup_ui()
        
    def setup_ui(self):
        """Setup the performance monitoring UI"""
        layout = QVBoxLayout()
        
        # Description
        desc_label = QLabel("Configure performance monitoring and alert thresholds")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)
        
        # Alert thresholds
        thresholds_group = QGroupBox("Alert Thresholds")
        thresholds_layout = QFormLayout()
        
        self.latency_warning_spin = QSpinBox()
        self.latency_warning_spin.setRange(20, 200)
        self.latency_warning_spin.setSuffix(" ms")
        thresholds_layout.addRow("Latency Warning:", self.latency_warning_spin)
        
        self.latency_critical_spin = QSpinBox()
        self.latency_critical_spin.setRange(50, 500)
        self.latency_critical_spin.setSuffix(" ms")
        thresholds_layout.addRow("Latency Critical:", self.latency_critical_spin)
        
        self.packet_loss_warning_spin = QSpinBox()
        self.packet_loss_warning_spin.setRange(1, 20)
        self.packet_loss_warning_spin.setSuffix("%")
        thresholds_layout.addRow("Packet Loss Warning:", self.packet_loss_warning_spin)
        
        self.packet_loss_critical_spin = QSpinBox()
        self.packet_loss_critical_spin.setRange(2, 50)
        self.packet_loss_critical_spin.setSuffix("%")
        thresholds_layout.addRow("Packet Loss Critical:", self.packet_loss_critical_spin)
        
        thresholds_group.setLayout(thresholds_layout)
        layout.addWidget(thresholds_group)
        
        # Performance summary
        summary_group = QGroupBox("Performance Summary")
        summary_layout = QVBoxLayout()
        
        self.summary_text = QTextEdit()
        self.summary_text.setMaximumHeight(150)
        self.summary_text.setReadOnly(True)
        summary_layout.addWidget(self.summary_text)
        
        # Refresh button
        self.refresh_button = QPushButton("Refresh Summary")
        self.refresh_button.clicked.connect(self.refresh_summary)
        summary_layout.addWidget(self.refresh_button)
        
        summary_group.setLayout(summary_layout)
        layout.addWidget(summary_group)
        
        self.setLayout(layout)
        
    def load_config(self):
        """Load performance monitoring configuration"""
        try:
            monitoring_config = latency_manager.config.get("performance_monitoring", {})
            thresholds = monitoring_config.get("alert_thresholds", {})
            
            self.latency_warning_spin.setValue(thresholds.get("latency_warning", 50))
            self.latency_critical_spin.setValue(thresholds.get("latency_critical", 100))
            self.packet_loss_warning_spin.setValue(thresholds.get("packet_loss_warning", 0.5) * 100)
            self.packet_loss_critical_spin.setValue(thresholds.get("packet_loss_critical", 2.0) * 100)
            
            self.refresh_summary()
            
        except Exception as e:
            log_error(f"Failed to load performance monitoring config: {e}")
    
    def refresh_summary(self):
        """Refresh performance summary"""
        try:
            summary = latency_manager.get_performance_summary()
            
            if "error" in summary:
                self.summary_text.setText(f"Error: {summary['error']}")
                return
            
            summary_text = f"Total Profiles: {summary['total_profiles']}\n"
            summary_text += f"Total Servers: {summary['total_servers']}\n"
            summary_text += f"Optimization Enabled: {'Yes' if summary['optimization_enabled'] else 'No'}\n"
            summary_text += f"Last Optimization: {summary['last_optimization']}\n\n"
            
            summary_text += "Profiles:\n"
            for name, profile in summary['profiles'].items():
                summary_text += f"  {name}: {profile['target_ms']}ms target, {profile['priority']} priority\n"
            
            summary_text += "\nServers:\n"
            for name, server in summary['servers'].items():
                summary_text += f"  {name}: {server['ip']} - {server['target_latency']}ms target\n"
            
            self.summary_text.setText(summary_text)
            
        except Exception as e:
            log_error(f"Failed to refresh summary: {e}")
            self.summary_text.setText(f"Error refreshing summary: {e}")
    
    def get_changes(self):
        """Get changes from the performance monitoring tab"""
        return {}
