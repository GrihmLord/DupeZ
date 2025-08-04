# app/gui/dashboard.py

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QMainWindow, QStatusBar, QDialog, QMessageBox, QTabWidget, QSplitter
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtCore import Qt, QTimer

from app.gui.sidebar import Sidebar
from app.gui.enhanced_device_list import EnhancedDeviceList
from app.gui.graph import PacketGraph
from app.gui.settings_dialog import SettingsDialog
from app.gui.topology_view import NetworkTopologyView
from app.gui.network_manipulator_gui import NetworkManipulatorGUI
from app.gui.dayz_udp_gui import DayZUDPGUI
from app.gui.dayz_firewall_gui import DayZFirewallGUI
from app.gui.dayz_map_gui import DayZMapGUI
from app.gui.dayz_account_tracker import DayZAccountTracker

from app.logs.logger import log_info, log_error
import threading

class DupeZDashboard(QMainWindow):
    """Main application dashboard with enhanced functionality"""
    
    def __init__(self, controller=None):
        super().__init__()
        self.controller = controller
        self.setup_ui()
        self.setup_menu()
        self.setup_status_bar()
        self.connect_signals()
        
        # Start periodic updates
        self.start_updates()
    
    def setup_ui(self):
        """Setup the main user interface with responsive design"""
        self.setWindowTitle("DupeZ - Advanced LagSwitch Tool")
        self.setWindowIcon(QIcon("app/assets/icon.ico"))
        
        # Make window responsive to screen size
        screen = self.screen()
        screen_geometry = screen.availableGeometry()
        
        # Calculate responsive window size (80% of screen size)
        window_width = int(screen_geometry.width() * 0.8)
        window_height = int(screen_geometry.height() * 0.8)
        window_x = (screen_geometry.width() - window_width) // 2
        window_y = (screen_geometry.height() - window_height) // 2
        
        self.setGeometry(window_x, window_y, window_width, window_height)
        
        # Set minimum size to prevent window from becoming too small
        self.setMinimumSize(1200, 700)
        
        # Force window to be visible and active
        self.setWindowState(Qt.WindowState.WindowActive)
        self.raise_()
        self.activateWindow()
        
        # Apply default theme (dark)
        self.apply_default_theme()
        
        # Central widget
        central_widget = QWidget()
        central_widget.setObjectName("main_container")
        self.setCentralWidget(central_widget)
        
        # Main layout with proper spacing
        layout = QHBoxLayout()
        layout.setSpacing(8)  # Add spacing between elements
        layout.setContentsMargins(8, 8, 8, 8)  # Add margins
        
        # Sidebar with responsive width
        self.sidebar = Sidebar(controller=self.controller)
        self.sidebar.setObjectName("sidebar")
        
        # Calculate responsive sidebar width (20-25% of window width)
        sidebar_width = max(250, min(350, int(window_width * 0.22)))
        self.sidebar.setMinimumWidth(sidebar_width)
        self.sidebar.setMaximumWidth(sidebar_width)
        layout.addWidget(self.sidebar)
        
        # Content area with tabs
        self.content_tabs = QTabWidget()
        self.content_tabs.setObjectName("content_tabs")
        self.content_tabs.setTabPosition(QTabWidget.TabPosition.North)
        
        # Enhanced device list tab (main scanner)
        self.enhanced_device_list = EnhancedDeviceList(controller=self.controller)
        self.enhanced_device_list.setObjectName("enhanced_device_panel")
        self.content_tabs.addTab(self.enhanced_device_list, "🔍 Network Scanner")
        
        # Network topology tab
        self.topology_view = NetworkTopologyView(controller=self.controller)
        self.topology_view.setObjectName("topology_panel")
        self.content_tabs.addTab(self.topology_view, "🗺️ Network Topology")
        
        # Graph tab
        self.graph = PacketGraph(controller=self.controller)
        self.graph.setObjectName("graph_panel")
        self.content_tabs.addTab(self.graph, "📊 Traffic Graph")
        
        # Network Manipulator tab
        self.network_manipulator = NetworkManipulatorGUI(controller=self.controller)
        self.content_tabs.addTab(self.network_manipulator, "🎛️ Network Manipulator")
        
        # DayZ UDP Interruption tab
        self.dayz_udp_gui = DayZUDPGUI()
        self.dayz_udp_gui.setObjectName("dayz_udp_panel")
        self.content_tabs.addTab(self.dayz_udp_gui, "🎮 DayZ UDP Control")
        
        # DayZ Firewall Controller tab (DayZPCFW Integration)
        self.dayz_firewall_gui = DayZFirewallGUI()
        self.dayz_firewall_gui.setObjectName("dayz_firewall_panel")
        self.content_tabs.addTab(self.dayz_firewall_gui, "🛡️ DayZ Firewall (DayZPCFW)")
        
        # DayZ Interactive Map tab (iZurvive Integration)
        self.dayz_map_gui = DayZMapGUI()
        self.dayz_map_gui.setObjectName("dayz_map_panel")
        self.content_tabs.addTab(self.dayz_map_gui, "🗺️ DayZ Map (iZurvive)")
        
        # DayZ Account Tracker tab
        self.dayz_account_tracker = DayZAccountTracker(controller=self.controller)
        self.dayz_account_tracker.setObjectName("dayz_account_tracker_panel")
        self.content_tabs.addTab(self.dayz_account_tracker, "👤 DayZ Account Tracker")
        
        layout.addWidget(self.content_tabs)
        central_widget.setLayout(layout)
        
        # Ensure window is shown and visible
        self.show()
        self.raise_()
        self.activateWindow()
    
    def apply_default_theme(self):
        """Apply the default theme to the application"""
        try:
            # Import and use theme manager
            from app.themes.theme_manager import theme_manager
            success = theme_manager.apply_theme("dark")
            if success:
                log_info("Default theme applied successfully")
            else:
                log_error("Failed to apply default theme")
                self.apply_fallback_theme()
        except Exception as e:
            log_error(f"Failed to apply default theme: {e}")
            self.apply_fallback_theme()
    
    def apply_fallback_theme(self):
        """Apply a fallback dark theme"""
        try:
            theme_file = "app/themes/dark.qss"
            with open(theme_file, 'r') as f:
                style = f.read()
            self.setStyleSheet(style)
            log_info("Fallback to dark theme applied")
        except Exception as e2:
            log_error(f"Failed to apply fallback theme: {e2}")
            # Final fallback - basic styling to ensure visibility
            self.setStyleSheet("""
                QMainWindow {
                    background-color: #2b2b2b;
                    color: #ffffff;
                }
                QWidget {
                    background-color: #2b2b2b;
                    color: #ffffff;
                }
                QTabWidget::pane {
                    border: 1px solid #555555;
                    background-color: #2b2b2b;
                }
                QTabBar::tab {
                    background-color: #3b3b3b;
                    color: #ffffff;
                    padding: 8px 16px;
                    margin-right: 2px;
                }
                QTabBar::tab:selected {
                    background-color: #555555;
                }
            """)
            log_info("Basic fallback styling applied")
    
    def setup_menu(self):
        """Setup the application menu bar with lagswitch functionality"""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu('&File')
        
        # Scan action
        scan_action = QAction('&Scan Network', self)
        scan_action.setShortcut('Ctrl+S')
        scan_action.triggered.connect(self.scan_network)
        file_menu.addAction(scan_action)
        
        # Quick scan action
        quick_scan_action = QAction('&Quick Scan', self)
        quick_scan_action.setShortcut('Ctrl+Shift+S')
        quick_scan_action.triggered.connect(self.quick_scan_network)
        file_menu.addAction(quick_scan_action)
        
        # Clear data action
        clear_action = QAction('&Clear Data', self)
        clear_action.setShortcut('Ctrl+C')
        clear_action.triggered.connect(self.clear_data)
        file_menu.addAction(clear_action)
        
        file_menu.addSeparator()
        
        # Export data action
        export_action = QAction('&Export Data', self)
        export_action.setShortcut('Ctrl+E')
        export_action.triggered.connect(self.export_data)
        file_menu.addAction(export_action)
        
        file_menu.addSeparator()
        
        # Exit action
        exit_action = QAction('&Exit', self)
        exit_action.setShortcut('Ctrl+Q')
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Tools menu
        tools_menu = menubar.addMenu('&Tools')
        
        # Smart mode action
        smart_action = QAction('&Smart Mode', self)
        smart_action.setCheckable(True)
        smart_action.triggered.connect(self.toggle_smart_mode)
        tools_menu.addAction(smart_action)
        
        # Mass block action
        mass_block_action = QAction('&Mass Block', self)
        mass_block_action.setShortcut('Ctrl+B')
        mass_block_action.triggered.connect(self.mass_block_devices)
        tools_menu.addAction(mass_block_action)
        
        # Mass unblock action
        mass_unblock_action = QAction('&Mass Unblock', self)
        mass_unblock_action.setShortcut('Ctrl+U')
        mass_unblock_action.triggered.connect(self.mass_unblock_devices)
        tools_menu.addAction(mass_unblock_action)
        
        tools_menu.addSeparator()
        
        # Search devices action
        search_action = QAction('&Search Devices', self)
        search_action.setShortcut('Ctrl+F')
        search_action.triggered.connect(self.search_devices)
        tools_menu.addAction(search_action)
        
        tools_menu.addSeparator()
        
        # Network tools submenu
        network_menu = tools_menu.addMenu('&Network Tools')
        
        # Ping test action
        ping_action = QAction('&Ping Test', self)
        ping_action.triggered.connect(self.ping_test)
        network_menu.addAction(ping_action)
        
        # Port scan action
        port_scan_action = QAction('&Port Scan', self)
        port_scan_action.triggered.connect(self.port_scan)
        network_menu.addAction(port_scan_action)
        
        tools_menu.addSeparator()
        
        # Advanced analysis submenu
        analysis_menu = tools_menu.addMenu('&Advanced Analysis')
        
        # Traffic analysis action
        traffic_analysis_action = QAction('&Traffic Analysis', self)
        traffic_analysis_action.setShortcut('Ctrl+T')
        traffic_analysis_action.triggered.connect(self.show_traffic_analysis)
        analysis_menu.addAction(traffic_analysis_action)
        
        # Network topology action
        topology_action = QAction('&Network Topology', self)
        topology_action.setShortcut('Ctrl+N')
        topology_action.triggered.connect(self.show_network_topology)
        analysis_menu.addAction(topology_action)
        
        # Plugin manager action
        plugin_action = QAction('&Plugin Manager', self)
        plugin_action.setShortcut('Ctrl+P')
        plugin_action.triggered.connect(self.show_plugin_manager)
        analysis_menu.addAction(plugin_action)
        
        # Settings action
        settings_action = QAction('&Settings', self)
        settings_action.setShortcut('Ctrl+,')
        settings_action.triggered.connect(self.open_settings)
        tools_menu.addAction(settings_action)
        
        # View menu
        view_menu = menubar.addMenu('&View')
        
        # Toggle sidebar action
        toggle_sidebar_action = QAction('&Toggle Sidebar', self)
        toggle_sidebar_action.setShortcut('Ctrl+Shift+T')
        toggle_sidebar_action.triggered.connect(self.toggle_sidebar)
        view_menu.addAction(toggle_sidebar_action)
        
        # Toggle graph action
        toggle_graph_action = QAction('&Toggle Graph', self)
        toggle_graph_action.setShortcut('Ctrl+G')
        toggle_graph_action.triggered.connect(self.toggle_graph)
        view_menu.addAction(toggle_graph_action)
        
        # Help menu
        help_menu = menubar.addMenu('&Help')
        
        # Hotkeys help action
        hotkeys_action = QAction('&Hotkeys', self)
        hotkeys_action.setShortcut('F1')
        hotkeys_action.triggered.connect(self.show_hotkeys)
        help_menu.addAction(hotkeys_action)
        
        # About action
        about_action = QAction('&About', self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
    
    def setup_status_bar(self):
        """Setup the status bar"""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        # Status labels
        self.device_status_label = QLabel("Devices: 0")
        self.network_status_label = QLabel("Network: Unknown")
        self.blocking_status_label = QLabel("Blocking: None")
        
        self.status_bar.addWidget(self.device_status_label)
        self.status_bar.addPermanentWidget(self.network_status_label)
        self.status_bar.addPermanentWidget(self.blocking_status_label)
    
    def connect_signals(self):
        """Connect all signals and slots"""
        try:
            # Connect sidebar signals
            if hasattr(self, 'sidebar'):
                self.sidebar.scan_requested.connect(self.scan_network)
                self.sidebar.clear_data_requested.connect(self.clear_data)
                self.sidebar.smart_mode_toggled.connect(self.on_smart_mode_toggled)
                self.sidebar.settings_requested.connect(self.open_settings)
                self.sidebar.search_requested.connect(self.search_devices)
                self.sidebar.quick_scan_requested.connect(self.quick_scan_network)
                self.sidebar.mass_block_requested.connect(self.mass_block_devices)
                self.sidebar.mass_unblock_requested.connect(self.mass_unblock_devices)
            
            # Connect enhanced device list signals
            if hasattr(self, 'enhanced_device_list'):
                self.enhanced_device_list.scan_started.connect(self.on_enhanced_scan_started)
                self.enhanced_device_list.scan_finished.connect(self.on_enhanced_scan_finished)
                self.enhanced_device_list.device_selected.connect(self.on_device_selected)
                self.enhanced_device_list.device_blocked.connect(self.on_device_blocked)
            
            # Connect graph signals
            if hasattr(self, 'graph'):
                self.graph.graph_clicked.connect(self.on_graph_clicked)
            
            # Connect network manipulator signals
            if hasattr(self, 'network_manipulator'):
                self.network_manipulator.rule_created.connect(self.on_network_rule_created)
                self.network_manipulator.rule_removed.connect(self.on_network_rule_removed)
                self.network_manipulator.manipulation_started.connect(self.on_manipulation_started)
                self.network_manipulator.manipulation_stopped.connect(self.on_manipulation_stopped)
            

            
            # Connect tab change signals
            if hasattr(self, 'content_tabs'):
                self.content_tabs.currentChanged.connect(self.on_tab_changed)
            
            log_info("All dashboard signals connected successfully")
            
        except Exception as e:
            log_error(f"Error connecting dashboard signals: {e}")
    
    def on_tab_changed(self, index: int):
        """Handle tab changes"""
        try:
            if index == 1:  # Topology tab
                log_info("Topology tab selected, updating topology view")
                self.update_topology_view()
            elif index == 2:  # Graph tab
                log_info("Graph tab selected")
                if hasattr(self, 'graph'):
                    self.graph.start_updates()
            elif index == 0:  # Scanner tab
                log_info("Scanner tab selected")
        except Exception as e:
            log_error(f"Error handling tab change: {e}")
    
    def start_updates(self):
        """Start periodic UI updates"""
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_status_bar)
        self.update_timer.start(2000)  # Update every 2 seconds (much faster updates)
        
        # Start topology view updates (reduced frequency to prevent loops)
        self.topology_timer = QTimer()
        self.topology_timer.timeout.connect(self.update_topology_view)
        self.topology_timer.start(10000)  # Update topology every 10 seconds (reduced frequency)
        
        # Add loop prevention flag
        self._topology_updating = False
    
    def update_status_bar(self):
        """Update the status bar with current information"""
        if self.controller:
            # Update device count
            devices = self.controller.get_devices()
            self.device_status_label.setText(f"Devices: {len(devices)}")
            
            # Update network info
            network_info = self.controller.get_network_info()
            if network_info:
                network = network_info.get("network", "Unknown")
                self.network_status_label.setText(f"Network: {network}")
            
            # Update blocking status
            if self.controller.is_blocking():
                self.blocking_status_label.setText("Blocking: Active")
                self.blocking_status_label.setStyleSheet("color: #ff4444;")
            else:
                self.blocking_status_label.setText("Blocking: None")
                self.blocking_status_label.setStyleSheet("")
    
    def on_device_selected(self, ip: str):
        """Handle device selection"""
        if self.controller:
            self.controller.select_device(ip)
    
    def on_device_blocked(self, ip: str, blocked: bool):
        """Handle device blocking"""
        status = "blocked" if blocked else "unblocked"
        self.status_bar.showMessage(f"Device {ip} {status}", 3000)
    
    def on_enhanced_scan_started(self):
        """Handle enhanced scan start"""
        log_info("Enhanced network scan started")
        self.status_bar.showMessage("Enhanced network scan in progress...")
    
    def on_enhanced_scan_finished(self, devices: list):
        """Handle enhanced scan completion"""
        log_info(f"Enhanced scan completed with {len(devices)} devices")
        self.status_bar.showMessage(f"Enhanced scan complete! Found {len(devices)} devices")
        
        # Notify controller of scan completion
        if self.controller:
            self.controller._on_scan_complete(devices)
        
        # Update device count in status bar
        self.update_status_bar()
        
        # Update topology view
        self.update_topology_view()
    
    def on_smart_mode_toggled(self):
        """Handle smart mode toggle"""
        if self.controller:
            self.controller.toggle_smart_mode()
    
    def on_graph_clicked(self, data: str):
        """Handle graph interaction"""
        self.status_bar.showMessage("Graph interaction detected", 2000)
    
    def on_network_rule_created(self, rule_id: str, rule_type: str):
        """Handle network rule creation"""
        log_info(f"Network rule created: {rule_id} ({rule_type})")
        self.status_bar.showMessage(f"Network rule created: {rule_type}", 3000)
    
    def on_network_rule_removed(self, rule_id: str):
        """Handle network rule removal"""
        log_info(f"Network rule removed: {rule_id}")
        self.status_bar.showMessage("Network rule removed", 3000)
    
    def on_manipulation_started(self, ip: str, action: str):
        """Handle network manipulation start"""
        log_info(f"Network manipulation started: {action} on {ip}")
        self.status_bar.showMessage(f"Started {action} on {ip}", 3000)
    
    def on_manipulation_stopped(self, ip: str, action: str):
        """Handle network manipulation stop"""
        log_info(f"Network manipulation stopped: {action} on {ip}")
        self.status_bar.showMessage(f"Stopped {action} on {ip}", 3000)
    

    
    def scan_network(self):
        """Scan the network for devices"""
        if self.controller:
            try:
                self.controller.scan_devices()
                self.status_bar.showMessage("Network scan started", 3000)
                # Update topology view after scan
                self.update_topology_view()
            except Exception as e:
                self.status_bar.showMessage(f"Scan failed: {e}", 5000)
    
    def clear_data(self):
        """Clear all data"""
        if self.controller:
            try:
                self.controller.clear_devices()
                self.status_bar.showMessage("Data cleared", 3000)
            except Exception as e:
                self.status_bar.showMessage(f"Clear failed: {e}", 5000)
    
    def toggle_smart_mode(self):
        """Toggle smart mode"""
        if self.controller:
            try:
                self.controller.toggle_smart_mode()
                self.status_bar.showMessage("Smart mode toggled", 3000)
            except Exception as e:
                self.status_bar.showMessage(f"Smart mode toggle failed: {e}", 5000)
    
    def open_settings(self):
        """Open settings dialog"""
        try:
            if self.controller:
                # Reload settings from file to ensure we have the latest
                self.controller.state.load_settings()
                
                current_settings = self.controller.state.settings
                dialog = SettingsDialog(current_settings, self)
                dialog.controller = self.controller  # Pass controller to dialog
                dialog.settings_changed.connect(self.on_settings_changed)
                
                if dialog.exec() == QDialog.DialogCode.Accepted:
                    # Settings were saved
                    new_settings = dialog.get_new_settings()
                    self.controller.update_settings(new_settings)
                    
                    # Force reload settings to ensure consistency
                    self.controller.state.load_settings()
                    
                    # Update UI immediately
                    self._update_ui_from_settings()
                    
                    log_info("Settings updated successfully")
            else:
                QMessageBox.warning(self, "Warning", "Controller not available")
        except Exception as e:
            log_error(f"Error opening settings: {e}")
            QMessageBox.critical(self, "Error", f"Failed to open settings: {e}")
    
    def on_settings_changed(self, additional_settings: dict):
        """Handle settings changes"""
        try:
            # Handle theme changes
            if "theme" in additional_settings:
                theme_name = additional_settings["theme"]
                self.apply_theme(theme_name)
                log_info(f"Theme changed to: {theme_name}")
            
            if self.controller:
                # Apply additional settings to controller
                self.controller.apply_additional_settings(additional_settings)
                log_info("Additional settings applied")
                
                # Reload settings from file to ensure consistency
                self.controller.state.load_settings()
                
                # Update UI based on new settings
                self._update_ui_from_settings()
                
        except Exception as e:
            log_error(f"Error applying additional settings: {e}")
    
    def _update_ui_from_settings(self):
        """Update UI elements based on current settings"""
        try:
            if not self.controller:
                return
                
            settings = self.controller.state.settings
            
            # Update auto-refresh settings
            if hasattr(self, 'update_timer') and self.update_timer:
                if settings.auto_refresh:
                    self.update_timer.start(settings.refresh_interval * 1000)
                else:
                    self.update_timer.stop()
            
            # Update display settings
            if hasattr(self, 'enhanced_device_list'):
                # Update device list display settings
                pass  # Add specific UI updates here
            
            log_info("UI updated from settings")
            
        except Exception as e:
            log_error(f"Error updating UI from settings: {e}")
    
    def apply_theme(self, theme_name: str):
        """Apply a theme to the application"""
        try:
            from app.themes.theme_manager import theme_manager
            success = theme_manager.apply_theme(theme_name)
            if success:
                log_info(f"Theme applied successfully: {theme_name}")
            else:
                log_error(f"Failed to apply theme: {theme_name}")
                self.apply_fallback_theme()
        except Exception as e:
            log_error(f"Error applying theme {theme_name}: {e}")
            self.apply_fallback_theme()
    
    def show_about(self):
        """Show about dialog"""
        from PyQt6.QtWidgets import QMessageBox
        
        about_text = """
        <h3>⚡ DUPEZ ⚡</h3>
        <p><b>Advanced LagSwitch Tool</b></p>
        <p>Version: 2.0.0 - Hacker Edition</p>
        <p>A powerful network lag control and device management tool.</p>
        <p><b>LagSwitch Features:</b></p>
        <ul>
            <li>🎯 Advanced device targeting</li>
            <li>🧠 Smart mode for intelligent blocking</li>
            <li>🚫 Mass blocking capabilities</li>
            <li>⚡ Quick scan and network analysis</li>
            <li>🔒 Security and encryption features</li>
            <li>📊 Real-time traffic monitoring</li>
            <li>🎮 Gaming device detection</li>
            <li>🔍 Port scanning and ping testing</li>
        </ul>
        <p><b>Hotkeys:</b></p>
        <ul>
            <li>Ctrl+S - Scan Network</li>
            <li>Ctrl+Shift+S - Quick Scan</li>
            <li>Ctrl+B - Mass Block</li>
            <li>Ctrl+U - Mass Unblock</li>
            <li>F1 - Show Hotkeys</li>
        </ul>
        <p><i>Advanced network control for power users</i></p>
        """
        
        QMessageBox.about(self, "About DUPEZ", about_text)
    
    def closeEvent(self, event):
        """Handle application close event with improved performance"""
        try:
            log_info("Starting application shutdown...")
            
            # Stop timers first for faster shutdown
            if hasattr(self, 'update_timer'):
                self.update_timer.stop()
                log_info("Stopped update timer")
            
            # Stop enhanced device list updates (if method exists)
            if hasattr(self, 'enhanced_device_list') and hasattr(self.enhanced_device_list, 'stop_auto_updates'):
                self.enhanced_device_list.stop_auto_updates()
                log_info("Stopped enhanced device list updates")
            
            # Stop sidebar updates
            if hasattr(self, 'sidebar'):
                self.sidebar.stop_updates()
                log_info("Stopped sidebar updates")
            
            # Stop graph updates
            if hasattr(self, 'graph'):
                self.graph.stop_updates()
                log_info("Stopped graph updates")
            
            # Stop network manipulator
            if hasattr(self, 'network_manipulator'):
                self.network_manipulator.cleanup()
                log_info("Stopped network manipulator")
            
            # Perform controller shutdown with timeout
            if self.controller:
                try:
                    # Use a thread to prevent blocking
                    shutdown_thread = threading.Thread(target=self.controller.shutdown)
                    shutdown_thread.daemon = True
                    shutdown_thread.start()
                    shutdown_thread.join(timeout=3)  # 3 second timeout
                    log_info("Controller shutdown completed")
                except Exception as e:
                    log_error(f"Error during controller shutdown: {e}")
            
            log_info("Application shutdown complete")
            event.accept()
            
        except Exception as e:
            log_error(f"Error during shutdown: {e}")
            event.accept()  # Always accept to ensure app closes
    
    def set_controller(self, controller):
        """Set the controller for all components"""
        self.controller = controller
        
        if controller:
            # Reload settings to ensure we have the latest
            controller.state.load_settings()
            
            # Apply settings to UI
            self._update_ui_from_settings()
        
        # Update components
        self.sidebar.set_controller(controller)
        self.enhanced_device_list.set_controller(controller)
        self.graph.controller = controller
    
    def get_controller(self):
        """Get the current controller"""
        return self.controller
    
    def refresh_ui(self):
        """Refresh all UI components"""
        if self.controller:
            # Update enhanced device list
            devices = self.controller.get_devices()
            self.enhanced_device_list.update_device_list(devices)
            
            # Update network info
            network_info = self.controller.get_network_info()
            if network_info:
                self.sidebar.set_network_info(network_info)
            
            # Update smart mode status
            smart_status = self.controller.get_smart_mode_status()
            if smart_status:
                self.sidebar.set_smart_mode(smart_status.get("enabled", False))
    
    def get_device_count(self) -> int:
        """Get current device count"""
        if self.controller:
            return len(self.controller.get_devices())
        return 0
    
    def get_selected_device(self):
        """Get currently selected device"""
        if self.controller:
            return self.controller.get_selected_device()
        return None
    
    # New lagswitch functionality methods
    def quick_scan_network(self):
        """Perform a quick network scan"""
        try:
            log_info("Starting quick network scan...")
            if self.controller:
                self.controller.scan_devices(quick=True)
            self.status_bar.showMessage("Quick scan completed", 3000)
        except Exception as e:
            log_error(f"Quick scan failed: {e}")
            self.status_bar.showMessage("Quick scan failed", 3000)
    
    def export_data(self):
        """Export device data to file"""
        try:
            from PyQt6.QtWidgets import QFileDialog
            filename, _ = QFileDialog.getSaveFileName(
                self, "Export Data", "dupez_data.txt", "Text Files (*.txt)"
            )
            if filename and self.controller:
                devices = self.controller.get_devices()
                with open(filename, 'w') as f:
                    f.write("DUPEZ - Device Export\n")
                    f.write("=" * 40 + "\n\n")
                    for device in devices:
                        f.write(f"IP: {device.ip}\n")
                        f.write(f"MAC: {device.mac}\n")
                        f.write(f"Vendor: {device.vendor}\n")
                        f.write(f"Hostname: {device.hostname}\n")
                        f.write(f"Blocked: {device.blocked}\n")
                        f.write("-" * 20 + "\n")
                self.status_bar.showMessage(f"Data exported to {filename}", 3000)
        except Exception as e:
            log_error(f"Export failed: {e}")
            self.status_bar.showMessage("Export failed", 3000)
    
    def mass_block_devices(self):
        """Block all non-local devices"""
        try:
            if self.controller:
                devices = self.controller.get_devices()
                blocked_count = 0
                for device in devices:
                    if not device.local and not device.blocked:
                        self.controller.toggle_lag(device.ip)
                        blocked_count += 1
                self.status_bar.showMessage(f"Mass blocked {blocked_count} devices", 3000)
        except Exception as e:
            log_error(f"Mass block failed: {e}")
            self.status_bar.showMessage("Mass block failed", 3000)
    
    def mass_unblock_devices(self):
        """Unblock all devices"""
        try:
            if self.controller:
                devices = self.controller.get_devices()
                unblocked_count = 0
                for device in devices:
                    if device.blocked:
                        self.controller.toggle_lag(device.ip)
                        unblocked_count += 1
                self.status_bar.showMessage(f"Mass unblocked {unblocked_count} devices", 3000)
        except Exception as e:
            log_error(f"Mass unblock failed: {e}")
            self.status_bar.showMessage("Mass unblock failed", 3000)
    
    def ping_test(self):
        """Perform ping test on selected device"""
        try:
            selected_device = self.get_selected_device()
            if selected_device:
                import subprocess
                result = subprocess.run(
                    ["ping", "-n", "4", selected_device.ip],
                    capture_output=True, text=True
                )
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.information(self, "Ping Test", f"Ping results for {selected_device.ip}:\n\n{result.stdout}")
            else:
                self.status_bar.showMessage("No device selected for ping test", 3000)
        except Exception as e:
            log_error(f"Ping test failed: {e}")
            self.status_bar.showMessage("Ping test failed", 3000)
    
    def port_scan(self):
        """Perform port scan on selected device"""
        try:
            selected_device = self.get_selected_device()
            if selected_device:
                # Simple port scan implementation
                import socket
                common_ports = [21, 22, 23, 25, 53, 80, 110, 143, 443, 993, 995]
                open_ports = []
                
                for port in common_ports:
                    try:
                        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        sock.settimeout(1)
                        result = sock.connect_ex((selected_device.ip, port))
                        if result == 0:
                            open_ports.append(port)
                        sock.close()
                    except:
                        pass
                
                from PyQt6.QtWidgets import QMessageBox
                if open_ports:
                    QMessageBox.information(self, "Port Scan", f"Open ports on {selected_device.ip}:\n{', '.join(map(str, open_ports))}")
                else:
                    QMessageBox.information(self, "Port Scan", f"No common ports open on {selected_device.ip}")
            else:
                self.status_bar.showMessage("No device selected for port scan", 3000)
        except Exception as e:
            log_error(f"Port scan failed: {e}")
            self.status_bar.showMessage("Port scan failed", 3000)
    
    def toggle_sidebar(self):
        """Toggle sidebar visibility"""
        try:
            if self.sidebar.isVisible():
                self.sidebar.hide()
                self.status_bar.showMessage("Sidebar hidden", 2000)
            else:
                self.sidebar.show()
                self.status_bar.showMessage("Sidebar shown", 2000)
        except Exception as e:
            log_error(f"Toggle sidebar failed: {e}")
    
    def toggle_graph(self):
        """Toggle graph visibility"""
        try:
            if self.graph.isVisible():
                self.graph.hide()
                self.status_bar.showMessage("Graph hidden", 2000)
            else:
                self.graph.show()
                self.status_bar.showMessage("Graph shown", 2000)
        except Exception as e:
            log_error(f"Toggle graph failed: {e}")
    
    def search_devices(self):
        """Open search dialog for devices"""
        try:
            from PyQt6.QtWidgets import QInputDialog, QMessageBox
            
            # Get search term from user
            search_term, ok = QInputDialog.getText(
                self, "Search Devices", 
                "Enter search term (IP, hostname, vendor, or MAC):"
            )
            
            if ok and search_term.strip():
                # Get search field from user
                fields = ["All Fields", "IP Address", "Hostname", "Vendor", "MAC Address"]
                field, ok = QInputDialog.getItem(
                    self, "Search Field", 
                    "Select search field:", fields, 0, False
                )
                
                if ok:
                    # Perform search
                    results = self.enhanced_device_list.search_for_device(search_term.strip(), field)
                    
                    if results:
                        QMessageBox.information(
                            self, "Search Results", 
                            f"Found {len(results)} devices matching '{search_term}' in {field}"
                        )
                        # Focus on the search input in enhanced device list
                        self.enhanced_device_list.search_input.setFocus()
                        self.enhanced_device_list.search_input.selectAll()
                    else:
                        QMessageBox.information(
                            self, "Search Results", 
                            f"No devices found matching '{search_term}' in {field}"
                        )
            
            log_info(f"Search dialog opened")
        except Exception as e:
            log_error(f"Error in search dialog: {e}")
            QMessageBox.critical(self, "Error", f"Search failed: {e}")
    
    def show_hotkeys(self):
        """Show hotkeys help dialog"""
        try:
            from PyQt6.QtWidgets import QMessageBox
            hotkeys_text = """
            <h3>DUPEZ - Advanced LagSwitch Tool - Hotkeys</h3>
            <p><b>File Operations:</b></p>
            <ul>
                <li>Ctrl+S - Scan Network</li>
                <li>Ctrl+Shift+S - Quick Scan</li>
                <li>Ctrl+E - Export Data</li>
                <li>Ctrl+Q - Exit</li>
            </ul>
            <p><b>Tools:</b></p>
            <ul>
                <li>Ctrl+B - Mass Block</li>
                <li>Ctrl+U - Mass Unblock</li>
                <li>Ctrl+F - Search Devices</li>
                <li>Ctrl+, - Settings</li>
            </ul>
            <p><b>Advanced Analysis:</b></p>
            <ul>
                <li>Ctrl+T - Traffic Analysis</li>
                <li>Ctrl+N - Network Topology</li>
                <li>Ctrl+P - Plugin Manager</li>
            </ul>
            <p><b>View:</b></p>
            <ul>
                <li>Ctrl+Shift+T - Toggle Sidebar</li>
                <li>Ctrl+G - Toggle Graph</li>
            </ul>
            <p><b>Help:</b></p>
            <ul>
                <li>F1 - This Help</li>
            </ul>
            """
            QMessageBox.information(self, "Hotkeys", hotkeys_text)
        except Exception as e:
            log_error(f"Show hotkeys failed: {e}")
    
    def show_traffic_analysis(self):
        """Show advanced traffic analysis"""
        try:
            from PyQt6.QtWidgets import QMessageBox
            
            # Check if traffic analyzer is available
            if hasattr(self.controller, 'traffic_analyzer'):
                # Switch to traffic analysis view
                self.content_tabs.setCurrentIndex(2)  # Assuming traffic analysis is tab 2
                self.status_bar.showMessage("Traffic analysis view activated", 2000)
                log_info("Traffic analysis view opened")
            else:
                QMessageBox.information(
                    self, "Traffic Analysis", 
                    "Advanced traffic analysis is being initialized. Please wait a moment and try again."
                )
        except Exception as e:
            log_error(f"Show traffic analysis failed: {e}")
            QMessageBox.critical(self, "Error", f"Failed to open traffic analysis: {e}")
    
    def show_network_topology(self):
        """Show network topology view"""
        try:
            # Switch to topology view
            self.content_tabs.setCurrentIndex(1)  # Topology tab
            self.status_bar.showMessage("Network topology view activated", 2000)
            log_info("Network topology view opened")
        except Exception as e:
            log_error(f"Show network topology failed: {e}")
            QMessageBox.critical(self, "Error", f"Failed to open network topology: {e}")
    
    def show_plugin_manager(self):
        """Show plugin manager dialog"""
        try:
            from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QPushButton, QLabel, QTextEdit, QTabWidget, QWidget, QFormLayout, QLineEdit, QComboBox
            
            dialog = QDialog(self)
            dialog.setWindowTitle("🔌 Plugin Manager")
            dialog.setModal(True)
            dialog.resize(600, 400)
            
            layout = QVBoxLayout()
            
            # Create tabs
            tab_widget = QTabWidget()
            
            # Installed plugins tab
            installed_tab = QWidget()
            installed_layout = QVBoxLayout()
            
            # Plugin list
            plugin_list = QListWidget()
            plugin_list.addItem("gaming_control - Gaming device control and management")
            plugin_list.addItem("No other plugins installed")
            installed_layout.addWidget(QLabel("Installed Plugins:"))
            installed_layout.addWidget(plugin_list)
            
            # Plugin controls
            plugin_controls = QHBoxLayout()
            enable_btn = QPushButton("Enable Plugin")
            disable_btn = QPushButton("Disable Plugin")
            reload_btn = QPushButton("Reload Plugin")
            plugin_controls.addWidget(enable_btn)
            plugin_controls.addWidget(disable_btn)
            plugin_controls.addWidget(reload_btn)
            installed_layout.addLayout(plugin_controls)
            
            installed_tab.setLayout(installed_layout)
            tab_widget.addTab(installed_tab, "Installed")
            
            # Create plugin tab
            create_tab = QWidget()
            create_layout = QFormLayout()
            
            plugin_name = QLineEdit()
            plugin_category = QComboBox()
            plugin_category.addItems(["General", "Gaming", "Security", "Monitoring", "Custom"])
            plugin_description = QTextEdit()
            plugin_description.setMaximumHeight(100)
            
            create_layout.addRow("Plugin Name:", plugin_name)
            create_layout.addRow("Category:", plugin_category)
            create_layout.addRow("Description:", plugin_description)
            
            create_btn = QPushButton("Create Plugin Template")
            create_layout.addRow(create_btn)
            
            create_tab.setLayout(create_layout)
            tab_widget.addTab(create_tab, "Create New")
            
            layout.addWidget(tab_widget)
            
            # Buttons
            button_layout = QHBoxLayout()
            close_btn = QPushButton("Close")
            close_btn.clicked.connect(dialog.accept)
            button_layout.addWidget(close_btn)
            
            layout.addLayout(button_layout)
            dialog.setLayout(layout)
            
            # Show dialog
            dialog.exec()
            log_info("Plugin manager dialog opened")
            
        except Exception as e:
            log_error(f"Show plugin manager failed: {e}")
            QMessageBox.critical(self, "Error", f"Failed to open plugin manager: {e}")
    
    def update_topology_view(self):
        """Update the network topology view with current devices"""
        # Loop prevention - don't update if already updating
        if hasattr(self, '_topology_updating') and self._topology_updating:
            log_info("Topology update skipped - already in progress")
            return
            
        try:
            self._topology_updating = True
            
            if hasattr(self, 'topology_view') and self.controller:
                devices = self.controller.get_devices()
                log_info(f"Updating topology view with {len(devices) if devices else 0} devices")
                
                if devices:
                    self.topology_view.update_topology(devices)
                    log_info(f"Topology view updated with {len(devices)} devices")
                else:
                    # No devices found - show placeholder
                    self.topology_view.update_topology([])
                    log_info("Topology view updated with empty device list (showing placeholder)")
                    
                # Force the topology view to refresh (but not recursively)
                if hasattr(self.topology_view, 'refresh_topology'):
                    self.topology_view.refresh_topology()
                
        except Exception as e:
            log_error(f"Update topology view failed: {e}")
            # Try to show placeholder even if there's an error
            try:
                if hasattr(self, 'topology_view'):
                    self.topology_view.update_topology([])
            except Exception as inner_e:
                log_error(f"Failed to show topology placeholder: {inner_e}")
        finally:
            # Always reset the flag
            self._topology_updating = False
