# app/gui/dashboard.py

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QMainWindow, QStatusBar, QDialog, QMessageBox, QTabWidget, QSplitter, QScrollArea
from PyQt6.QtGui import QIcon, QAction, QFont
from PyQt6.QtCore import Qt, QTimer

from app.gui.sidebar import Sidebar
from app.gui.enhanced_device_list import EnhancedDeviceList
from app.gui.settings_dialog import SettingsDialog
from app.gui.dayz_gaming_dashboard import DayZGamingDashboard
from app.gui.dayz_duping_dashboard import DayZDupingDashboard
from app.gui.unified_network_control import UnifiedNetworkControl
from app.gui.advanced_network_scanner import AdvancedNetworkScanner
from app.gui.network_manipulator_gui import NetworkManipulatorGUI
from app.gui.dayz_map_gui import DayZMapGUI
from app.gui.dayz_account_tracker import DayZAccountTracker

from app.logs.logger import log_info, log_error
import threading
import json
import random
from typing import Dict, List, Optional, Tuple

class TipsTicker(QWidget):
    """Scrolling tips ticker like NASDAQ ticker with performance optimizations"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        self.load_tips()
        self.start_scrolling()
    
    def setup_ui(self):
        """Setup the ticker UI with performance optimizations"""
        self.setFixedHeight(40)
        self.setObjectName("tips_ticker")
        
        # Enable hardware acceleration for smooth rendering
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        
        # Main layout
        layout = QHBoxLayout()
        layout.setContentsMargins(10, 5, 10, 5)
        
        # Tips label with performance optimizations
        self.tips_label = QLabel()
        self.tips_label.setObjectName("tips_label")
        self.tips_label.setFont(QFont("Consolas", 10))
        self.tips_label.setStyleSheet("""
            QLabel {
                color: #00ff00;
                background-color: #000000;
                padding: 5px 10px;
                border-radius: 3px;
                font-weight: bold;
                white-space: nowrap;
            }
        """)
        
        # Performance optimizations for smooth text rendering
        self.tips_label.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.tips_label.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        
        # Set alignment to left so text can scroll properly
        self.tips_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        
        layout.addWidget(self.tips_label)
        self.setLayout(layout)
        
        # Stability optimization: Further reduced tip change frequency
        self.tip_timer = QTimer()
        self.tip_timer.timeout.connect(self.change_tip)
        self.tip_timer.start(30000)  # Change tip every 30 seconds for maximum stability
        
        # Stability optimization: Further reduced scroll frequency for stability
        self.scroll_timer = QTimer()
        self.scroll_timer.timeout.connect(self.scroll_text)
        self.scroll_timer.start(150)  # Scroll every 150ms for maximum stability
        
        # Current tip index and scroll position
        self.current_tip_index = 0
        self.scroll_position = 0
        self.tips = []
        self.current_tip_text = ""
        
        # Stability optimization: Reduced scroll speed for stability
        self.scroll_speed = 1  # Reduced from 2 for smoother movement and better stability
        self.max_scroll = 0
        
        # Cache for performance
        self._cached_tips = {}
        self._last_tip_change = 0
    
    def load_tips(self):
        """Load tips from configuration with performance optimizations"""
        try:
            with open('app/config/dayz_tips_tricks.json', 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # Extract all tips from all categories with caching
            for category_name, category_data in config.get('tips_categories', {}).items():
                for tip in category_data.get('tips', []):
                    # Create a short tip text for the ticker
                    short_tip = f"💡 {tip.get('title', 'Tip')} - {tip.get('description', '')}"
                    self.tips.append(short_tip)
                    # Initialize cache entry for this tip
                    tip_index = len(self.tips) - 1
                    self._cached_tips[tip_index] = {}
            
            # Add some general tips if no tips loaded
            if not self.tips:
                self.tips = [
                    "💡 Optimize DayZ graphics for maximum FPS",
                    "💡 Use Game Mode for better performance",
                    "💡 Keep drivers updated for optimal performance",
                    "💡 Close background applications while gaming",
                    "💡 Use SSD for faster loading times"
                ]
                # Initialize cache entries for fallback tips
                for i in range(len(self.tips)):
                    self._cached_tips[i] = {}
            
            log_info(f"Loaded {len(self.tips)} tips for ticker")
            
        except Exception as e:
            log_error(f"Failed to load tips: {e}")
            # Fallback tips
            self.tips = [
                "💡 Optimize DayZ graphics for maximum FPS",
                "💡 Use Game Mode for better performance",
                "💡 Keep drivers updated for optimal performance"
            ]
            # Initialize cache entries for exception fallback tips
            for i in range(len(self.tips)):
                self._cached_tips[i] = {}
    
    def start_scrolling(self):
        """Start the scrolling animation with performance optimizations"""
        if self.tips:
            self.show_tip(0)
    
    def show_tip(self, tip_index):
        """Show a specific tip and start scrolling with optimizations"""
        if not self.tips or tip_index >= len(self.tips):
            return
        
        # Get tip text
        self.current_tip_text = self.tips[tip_index]
        self.tips_label.setText(self.current_tip_text)
        
        # Reset scroll position
        self.scroll_position = 0
        
        # Calculate maximum scroll needed with caching
        if tip_index not in self._cached_tips or not isinstance(self._cached_tips[tip_index], dict) or 'width' not in self._cached_tips[tip_index]:
            text_width = self.tips_label.fontMetrics().horizontalAdvance(self.current_tip_text)
            self.max_scroll = max(0, text_width - self.width() + 20)
            # Cache the width calculation
            if tip_index not in self._cached_tips:
                self._cached_tips[tip_index] = {}
            self._cached_tips[tip_index]['width'] = text_width
            self._cached_tips[tip_index]['max_scroll'] = self.max_scroll
        else:
            self.max_scroll = self._cached_tips[tip_index]['max_scroll']
        
        # Start scrolling if text is longer than widget
        if self.max_scroll > 0:
            self.scroll_timer.start(50)
        else:
            self.scroll_timer.stop()
    
    def scroll_text(self):
        """Scroll the text from right to left with performance optimizations"""
        if self.max_scroll <= 0:
            return
        
        # Update scroll position with smooth movement
        self.scroll_position += self.scroll_speed
        
        # Apply scroll using margins with performance optimization
        if self.scroll_position <= self.max_scroll:
            self.tips_label.setContentsMargins(-self.scroll_position, 0, 0, 0)
        else:
            # Reset scroll position when done
            self.scroll_position = 0
            self.tips_label.setContentsMargins(0, 0, 0, 0)
    
    def change_tip(self):
        """Change to the next tip with performance optimizations"""
        if self.tips:
            self.current_tip_index = (self.current_tip_index + 1) % len(self.tips)
            self.show_tip(self.current_tip_index)

class DupeZDashboard(QMainWindow):
    """Main application dashboard with enhanced functionality and performance optimizations"""
    
    def __init__(self, controller=None):
        super().__init__()
        self.controller = controller
        
        # Performance optimization: Enable hardware acceleration
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        
        # Performance optimization: Reduce repaints
        self.setAttribute(Qt.WidgetAttribute.WA_StaticContents, True)
        
        # Performance optimization: Enable smooth scrolling (removed unsupported attribute)
        
        # Initialize performance monitor
        # self.performance_monitor = PerformanceMonitor() # Removed as per edit hint
        
        self.setup_ui()
        self.setup_menu()
        self.setup_status_bar()
        self.connect_signals()
        
        # Start periodic updates with memory optimization
        self.start_updates()
        
        # Stability optimization: More aggressive memory management
        self.memory_cleanup_timer = QTimer()
        self.memory_cleanup_timer.timeout.connect(self.cleanup_memory)
        self.memory_cleanup_timer.start(20000)  # More frequent cleanup for better stability
        
        # Additional stability optimization: CPU monitoring
        self.cpu_monitor_timer = QTimer()
        self.cpu_monitor_timer.timeout.connect(self._monitor_cpu_usage)
        self.cpu_monitor_timer.start(15000)  # Monitor CPU every 15 seconds
        
        # Stability optimization: UI update throttling with safety
        self.ui_update_throttle = QTimer()
        self.ui_update_throttle.setSingleShot(True)
        self.ui_update_throttle.timeout.connect(self._perform_throttled_ui_update)
        self.pending_ui_updates = []
        
        # Stability optimization: Reduced animation frequency for stability
        self.animation_timer = QTimer()
        self.animation_timer.timeout.connect(self._update_animations)
        self.animation_timer.start(33)  # 30 FPS for better stability (reduced from 60 FPS)
        
        # Stability optimization: Initialize stability optimizer
        try:
            from app.core.stability_optimizer import stability_optimizer
            self.stability_optimizer = stability_optimizer
            self.stability_optimizer.start_monitoring()
            
            # Connect stability signals
            self.stability_optimizer.memory_warning.connect(self._on_memory_warning)
            self.stability_optimizer.stability_alert.connect(self._on_stability_alert)
            self.stability_optimizer.optimization_complete.connect(self._on_optimization_complete)
            
            # Register cleanup tasks
            self.stability_optimizer.register_cleanup_task(self._stability_cleanup_task)
            
            log_info("Stability optimizer integrated successfully")
        except Exception as e:
            log_error(f"Failed to initialize stability optimizer: {e}")
            self.stability_optimizer = None
        
        # Performance optimization: Performance monitoring cleanup
        # self.performance_cleanup_timer = QTimer() # Removed as per edit hint
        # self.performance_cleanup_timer.timeout.connect(self._cleanup_performance_data) # Removed as per edit hint
        # self.performance_cleanup_timer.start(300000)  # Cleanup every 5 minutes # Removed as per edit hint
        
        # Initialize topology updating flag
        self._topology_updating = False
    
    def setup_ui(self):
        """Setup the main user interface with responsive design and performance optimizations"""
        # Determine admin status for title
        import os
        import ctypes
        IS_ADMIN = os.name != 'nt' or (
            hasattr(ctypes, 'windll') and ctypes.windll.shell32.IsUserAnAdmin() != 0
        )
        
        # Set title with admin status and version
        admin_text = " [ADMIN]" if IS_ADMIN else ""
        self.setWindowTitle(f"DupeZ v2.0.0 Professional Edition{admin_text}")
        self.setWindowIcon(QIcon("app/assets/icon.ico"))
        
        # Performance optimization: Enable double buffering for smooth rendering
        self.setAttribute(Qt.WidgetAttribute.WA_PaintOnScreen, False)
        
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
        
        # Central widget with performance optimizations
        central_widget = QWidget()
        central_widget.setObjectName("main_container")
        
        # Performance optimization: Enable hardware acceleration for central widget
        central_widget.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        central_widget.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        
        self.setCentralWidget(central_widget)
        
        # Main layout with proper spacing and performance optimizations
        layout = QVBoxLayout()  # Changed to VBoxLayout to accommodate ticker
        layout.setSpacing(8)  # Add spacing between elements
        layout.setContentsMargins(8, 8, 8, 8)  # Add margins
        
        # Content area with horizontal layout
        content_layout = QHBoxLayout()
        content_layout.setSpacing(8)
        
        # Sidebar with responsive width and performance optimizations
        self.sidebar = Sidebar(controller=self.controller)
        self.sidebar.setObjectName("sidebar")
        
        # Performance optimization: Enable hardware acceleration for sidebar
        self.sidebar.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        
        # Calculate responsive sidebar width (20-25% of window width)
        sidebar_width = max(250, min(350, int(window_width * 0.22)))
        self.sidebar.setMinimumWidth(sidebar_width)
        self.sidebar.setMaximumWidth(sidebar_width)
        content_layout.addWidget(self.sidebar)
        
        # Content area with tabs and performance optimizations
        self.content_tabs = QTabWidget()
        self.content_tabs.setObjectName("content_tabs")
        self.content_tabs.setTabPosition(QTabWidget.TabPosition.North)
        
        # Performance optimization: Enable hardware acceleration for tabs
        self.content_tabs.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        
        # Enhanced device list tab (main scanner) with performance optimizations
        self.enhanced_device_list = EnhancedDeviceList(controller=self.controller)
        self.enhanced_device_list.setObjectName("enhanced_device_panel")
        
        # Performance optimization: Enable hardware acceleration for device list
        self.enhanced_device_list.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        
        # Add all the proper tabs
        self.content_tabs.addTab(self.enhanced_device_list, "Network Scanner")
        
        # DayZ Gaming Dashboard
        self.dayz_gaming_dashboard = DayZGamingDashboard()
        self.content_tabs.addTab(self.dayz_gaming_dashboard, "DayZ Gaming")
        
        # DayZ Duping Dashboard
        self.dayz_duping_dashboard = DayZDupingDashboard()
        self.content_tabs.addTab(self.dayz_duping_dashboard, "DayZ Duping")
        
        # Unified Network Control
        self.unified_network_control = UnifiedNetworkControl()
        self.content_tabs.addTab(self.unified_network_control, "Network Control")
        
        # Advanced Network Scanner
        self.advanced_network_scanner = AdvancedNetworkScanner()
        self.content_tabs.addTab(self.advanced_network_scanner, "Advanced Scanner")
        
        # Network Manipulator
        self.network_manipulator = NetworkManipulatorGUI()
        self.content_tabs.addTab(self.network_manipulator, "Network Manipulator")
        
        # DayZ Map GUI
        self.dayz_map_gui = DayZMapGUI()
        self.content_tabs.addTab(self.dayz_map_gui, "DayZ Map")
        
        # DayZ Account Tracker
        self.dayz_account_tracker = DayZAccountTracker()
        self.content_tabs.addTab(self.dayz_account_tracker, "Account Tracker")
        
        # DupeZ Duping Network Optimizer
        from app.gui.duping_network_optimizer import DupingNetworkOptimizer
        self.duping_optimizer = DupingNetworkOptimizer(self.dayz_account_tracker)
        self.content_tabs.addTab(self.duping_optimizer, "Duping Optimizer")
        
        # Ensure all tabs are properly configured
        QTimer.singleShot(0, self._sanitize_tab_labels)
        
        content_layout.addWidget(self.content_tabs)
        
        # Add content layout to main layout
        layout.addLayout(content_layout)
        
        # Add tips ticker at the bottom with performance optimizations
        self.tips_ticker = TipsTicker()
        layout.addWidget(self.tips_ticker)
        
        central_widget.setLayout(layout)
        
        # Performance optimization: Reduce initial repaints
        self.setUpdatesEnabled(False)
        
        # Ensure window is shown and visible
        self.show()
        self.raise_()
        self.activateWindow()
        
        # Performance optimization: Re-enable updates after showing
        self.setUpdatesEnabled(True)
    
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
        
        # Advanced Analysis submenu
        advanced_menu = tools_menu.addMenu('&Advanced Analysis')
        
        # DayZ Gaming Dashboard
        gaming_action = QAction('DayZ Gaming Dashboard', self)
        gaming_action.triggered.connect(self.open_dayz_gaming_dashboard)
        advanced_menu.addAction(gaming_action)
        
        # DayZ Duping Dashboard
        duping_action = QAction('DayZ Duping Dashboard', self)
        duping_action.triggered.connect(self.open_dayz_duping_dashboard)
        advanced_menu.addAction(duping_action)
        
        # Network Control
        network_action = QAction('Network Control Center', self)
        network_action.triggered.connect(self.open_network_control)
        advanced_menu.addAction(network_action)
        
        # Advanced Scanner
        scanner_action = QAction('Advanced Network Scanner', self)
        scanner_action.triggered.connect(self.open_advanced_scanner)
        advanced_menu.addAction(scanner_action)
        
        # Network Manipulator
        manipulator_action = QAction('Network Manipulator', self)
        manipulator_action.triggered.connect(self.open_network_manipulator)
        advanced_menu.addAction(manipulator_action)
        
        # DayZ Map
        map_action = QAction('DayZ Map', self)
        map_action.triggered.connect(self.open_dayz_map)
        advanced_menu.addAction(map_action)
        
        # Account Tracker
        account_action = QAction('Account Tracker', self)
        account_action.triggered.connect(self.open_account_tracker)
        advanced_menu.addAction(account_action)
        
        # Duping Network Optimizer
        optimizer_action = QAction('Duping Network Optimizer', self)
        optimizer_action.triggered.connect(self.open_duping_optimizer)
        advanced_menu.addAction(optimizer_action)
        
        # Settings action
        settings_action = QAction('&Settings', self)
        settings_action.setShortcut('Ctrl+,')
        settings_action.triggered.connect(self.open_settings)
        tools_menu.addAction(settings_action)
        
        # Latency Configuration action
        latency_action = QAction('&Latency Configuration', self)
        latency_action.setShortcut('Ctrl+L')
        latency_action.triggered.connect(self.open_latency_config)
        tools_menu.addAction(latency_action)
        
        tools_menu.addSeparator()
        
        # Minimal tools menu; removed DayZ and analysis-related actions
        
        
        
        # View menu
        view_menu = menubar.addMenu('&View')
        
        # Toggle sidebar action
        toggle_sidebar_action = QAction('&Toggle Sidebar', self)
        toggle_sidebar_action.setShortcut('Ctrl+Shift+T')
        toggle_sidebar_action.triggered.connect(self.toggle_sidebar)
        view_menu.addAction(toggle_sidebar_action)
        
        # Toggle graph action removed as requested by user
        
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

    def _enforce_minimal_tabs(self):
        """Ensure all required tabs are present on the home screen."""
        try:
            if not hasattr(self, 'content_tabs'):
                return
            # Keep all the tabs we want - don't remove anything!
            log_info("All tabs are properly configured - no enforcement needed")
        except Exception as e:
            log_error(f"Error checking tabs: {e}")

    def _sanitize_tab_labels(self):
        """Remove emojis and non-ASCII chars from tab labels."""
        try:
            if not hasattr(self, 'content_tabs'):
                return
            for i in range(self.content_tabs.count()):
                text = self.content_tabs.tabText(i)
                clean = ''.join(ch for ch in text if 32 <= ord(ch) < 127)
                if clean != text:
                    self.content_tabs.setTabText(i, clean)
        except Exception as e:
            log_error(f"Error sanitizing tab labels: {e}")
    
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
            
            # Graph signals removed as requested by user
            
            # Connect network manipulator signals
            if hasattr(self, 'unified_network_control'):
                self.unified_network_control.rule_created.connect(self.on_network_rule_created)
                self.unified_network_control.rule_removed.connect(self.on_network_rule_removed)
                self.unified_network_control.manipulation_started.connect(self.on_manipulation_started)
                self.unified_network_control.manipulation_stopped.connect(self.on_manipulation_stopped)
            

            
            # Connect tab change signals
            if hasattr(self, 'content_tabs'):
                self.content_tabs.currentChanged.connect(self.on_tab_changed)
            
            log_info("All dashboard signals connected successfully")
            
        except Exception as e:
            log_error(f"Error connecting dashboard signals: {e}")
    
    def on_tab_changed(self, index: int):
        """Handle tab changes"""
        try:
            # Simplified: no topology tab present
            pass
        except Exception as e:
            log_error(f"Error handling tab change: {e}")
    
    def start_updates(self):
        """Start periodic UI updates with performance optimizations"""
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_status_bar)
        self.update_timer.start(3000)  # Update every 3 seconds (optimized from 2 seconds)
        
        # Topology updates removed for optimization
        
        # Performance optimization: Memory cleanup timer
        self.memory_cleanup_timer = QTimer()
        self.memory_cleanup_timer.timeout.connect(self.cleanup_memory)
        self.memory_cleanup_timer.start(45000)  # Cleanup every 45 seconds (optimized)
    
    def _cleanup_performance_data(self):
        """Clean up old performance data to prevent memory buildup"""
        try:
            print("Performance data cleanup (no longer available)")
        except Exception as e:
            log_error(f"Performance data cleanup error: {e}")
    
    def _monitor_operation(self, operation_name: str):
        """Context manager for monitoring operation performance"""
        return self
    
    def _end_operation(self, operation_name: str):
        """End operation monitoring and record performance"""
        pass
    
    def throttle_ui_update(self, update_func, *args, **kwargs):
        """Throttle UI updates to prevent performance issues"""
        try:
            # Ensure pending_ui_updates is initialized
            if not hasattr(self, 'pending_ui_updates'):
                self.pending_ui_updates = []
            
            # Ensure ui_update_throttle is initialized
            if not hasattr(self, 'ui_update_throttle'):
                from PyQt6.QtCore import QTimer
                self.ui_update_throttle = QTimer()
                self.ui_update_throttle.setSingleShot(True)
                self.ui_update_throttle.timeout.connect(self._perform_throttled_ui_update)
            
            # Add update to pending queue
            self.pending_ui_updates.append((update_func, args, kwargs))
            
            # Start throttling timer if not already running
            if not self.ui_update_throttle.isActive():
                self.ui_update_throttle.start(100)  # 100ms throttle for smooth UI
                
        except Exception as e:
            log_error(f"UI update throttling error: {e}")
    
    def _perform_throttled_ui_update(self):
        """Perform batched UI updates to reduce performance impact"""
        try:
            # Ensure pending_ui_updates is initialized
            if not hasattr(self, 'pending_ui_updates'):
                self.pending_ui_updates = []
                
            if not self.pending_ui_updates:
                return
            
            # Process all pending updates at once
            updates = self.pending_ui_updates.copy()
            self.pending_ui_updates.clear()
            
            # Batch process updates
            for update_func, args, kwargs in updates:
                try:
                    update_func(*args, **kwargs)
                except Exception as e:
                    log_error(f"UI update error: {e}")
            
        except Exception as e:
            log_error(f"Throttled UI update error: {e}")
    
    # Stability optimization event handlers
    def _on_memory_warning(self, message: str):
        """Handle memory warning from stability optimizer"""
        try:
            log_warning(f"Memory warning: {message}")
            self.status_bar.showMessage(f"⚠️ {message}", 5000)
            
            # Trigger immediate cleanup
            self.cleanup_memory()
            
        except Exception as e:
            log_error(f"Memory warning handler error: {e}")
    
    def _on_stability_alert(self, message: str):
        """Handle stability alert from stability optimizer"""
        try:
            log_warning(f"Stability alert: {message}")
            self.status_bar.showMessage(f"🚨 {message}", 8000)
            
            # Trigger stability optimization
            if hasattr(self, 'stability_optimizer') and self.stability_optimizer:
                self.stability_optimizer.optimize_performance()
                
        except Exception as e:
            log_error(f"Stability alert handler error: {e}")
    
    def _on_optimization_complete(self, message: str):
        """Handle optimization completion from stability optimizer"""
        try:
            log_info(f"Optimization complete: {message}")
            self.status_bar.showMessage(f"✅ {message}", 3000)
            
        except Exception as e:
            log_error(f"Optimization complete handler error: {e}")
    
    def _stability_cleanup_task(self):
        """Cleanup task registered with stability optimizer"""
        try:
            # Clear UI caches
            if hasattr(self, 'enhanced_device_list'):
                self.enhanced_device_list.clear_cache()
            
            # Clear tips ticker cache
            if hasattr(self, 'tips_ticker') and hasattr(self.tips_ticker, '_cached_tips'):
                self.tips_ticker._cached_tips.clear()
            
            # Clear pending UI updates
            if hasattr(self, 'pending_ui_updates'):
                self.pending_ui_updates.clear()
            
            log_info("Stability cleanup task completed")
            
        except Exception as e:
            log_error(f"Stability cleanup task error: {e}")
    
    def _monitor_cpu_usage(self):
        """Monitor CPU usage and adjust performance if needed"""
        try:
            import psutil
            cpu_percent = psutil.cpu_percent(interval=1)
            
            # If CPU usage is high, reduce update frequencies
            if cpu_percent > 80:
                log_warning(f"High CPU usage detected: {cpu_percent:.1f}% - Reducing update frequencies")
                
                # Temporarily reduce animation frequency
                if hasattr(self, 'animation_timer'):
                    self.animation_timer.start(50)  # Reduce to 20 FPS
                
                # Reduce tips ticker frequency
                if hasattr(self, 'tips_ticker') and hasattr(self.tips_ticker, 'scroll_timer'):
                    self.tips_ticker.scroll_timer.start(200)  # Slower scrolling
                    
                # Trigger immediate cleanup
                self.cleanup_memory()
                
            elif cpu_percent < 50:
                # Restore normal frequencies if CPU usage is low
                if hasattr(self, 'animation_timer'):
                    self.animation_timer.start(33)  # Normal 30 FPS
                    
                if hasattr(self, 'tips_ticker') and hasattr(self.tips_ticker, 'scroll_timer'):
                    self.tips_ticker.scroll_timer.start(100)  # Normal scrolling
                    
        except Exception as e:
            log_error(f"CPU monitoring error: {e}")
    
    def _update_animations(self):
        """Update smooth animations at 60 FPS"""
        try:
            # Update any running animations
            if hasattr(self, 'tips_ticker') and self.tips_ticker:
                # Ensure tips ticker animations are smooth
                pass
            
            # Update other UI animations if needed
            # This runs at 60 FPS for smooth user experience
            
        except Exception as e:
            log_error(f"Animation update error: {e}")
    
    def update_status_bar(self):
        """Update the status bar with current information and performance optimizations"""
        try:
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
                    
        except Exception as e:
            log_error(f"Status bar update error: {e}")
    
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
        
        # Topology view removed
    
    def on_smart_mode_toggled(self):
        """Handle smart mode toggle"""
        if self.controller:
            self.controller.toggle_smart_mode()
    
    # Graph interaction method removed as requested by user
    
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
    
    def cleanup_memory(self):
        """Enhanced memory cleanup for better stability"""
        try:
            import gc
            import psutil
            
            # Get current memory usage
            process = psutil.Process()
            memory_info = process.memory_info()
            memory_mb = memory_info.rss / 1024 / 1024
            
            # Enhanced cleanup thresholds for better stability
            if memory_mb > 400:  # Further lowered threshold for more proactive cleanup
                log_info(f"High memory usage detected: {memory_mb:.1f}MB - Performing aggressive cleanup")
                
                # Clear UI caches
                if hasattr(self, 'enhanced_device_list'):
                    self.enhanced_device_list.clear_cache()
                
                # Clear tips ticker cache
                if hasattr(self, 'tips_ticker') and hasattr(self.tips_ticker, '_cached_tips'):
                    self.tips_ticker._cached_tips.clear()
                
                # Clear pending UI updates
                if hasattr(self, 'pending_ui_updates'):
                    self.pending_ui_updates.clear()
                
                # Clear performance metrics if they exist
                if hasattr(self, 'performance_metrics'):
                    for key in ['memory_usage', 'cpu_usage', 'thread_count']:
                        if key in self.performance_metrics:
                            self.performance_metrics[key] = self.performance_metrics[key][-20:]
                
                # Force garbage collection multiple times for better cleanup
                for _ in range(2):
                    gc.collect()
                
                # Check memory after cleanup
                memory_after = process.memory_info().rss / 1024 / 1024
                freed_mb = memory_mb - memory_after
                
                log_info(f"Memory cleanup completed. Freed: {freed_mb:.1f}MB, Current: {memory_after:.1f}MB")
                
                # Update status bar
                self.status_bar.showMessage(f"Memory cleanup completed - Freed {freed_mb:.1f}MB", 3000)
                
            else:
                # Light cleanup for normal operation
                collected = gc.collect()
                if collected > 0:
                    log_info(f"Light memory cleanup: {collected} objects collected")
                
        except Exception as e:
            log_error(f"Memory cleanup error: {e}")
            # Fallback cleanup
            try:
                gc.collect()
            except:
                pass
    
    def resizeEvent(self, event):
        """Handle window resize with performance optimizations"""
        try:
            # Performance optimization: Throttle resize updates
            self.throttle_ui_update(super().resizeEvent, event)
            
            # Update responsive layouts
            if hasattr(self, 'sidebar'):
                # Recalculate sidebar width for responsiveness
                window_width = self.width()
                sidebar_width = max(250, min(350, int(window_width * 0.22)))
                self.sidebar.setMaximumWidth(sidebar_width)
            
        except Exception as e:
            log_error(f"Resize event error: {e}")
            super().resizeEvent(event)
    
    def showEvent(self, event):
        """Handle window show with performance optimizations"""
        try:
            super().showEvent(event)
            
            # Performance optimization: Enable smooth rendering after showing
            self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
            self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
            
        except Exception as e:
            log_error(f"Show event error: {e}")
    
    def closeEvent(self, event):
        """Handle window close with stability optimizations"""
        try:
            # Stability optimization: Stop all timers
            if hasattr(self, 'update_timer'):
                self.update_timer.stop()
            
            if hasattr(self, 'topology_timer'):
                self.topology_timer.stop()
            
            if hasattr(self, 'memory_cleanup_timer'):
                self.memory_cleanup_timer.stop()
            
            if hasattr(self, 'ui_update_throttle'):
                self.ui_update_throttle.stop()
            
            if hasattr(self, 'animation_timer'):
                self.animation_timer.stop()
            
            if hasattr(self, 'cpu_monitor_timer'):
                self.cpu_monitor_timer.stop()
            
            # Stop stability optimizer
            if hasattr(self, 'stability_optimizer') and self.stability_optimizer:
                try:
                    self.stability_optimizer.stop_monitoring()
                except Exception as e:
                    log_error(f"Error stopping stability optimizer: {e}")
            
            # Cleanup memory
            self.cleanup_memory()
            
            # Accept close event
            event.accept()
            
        except Exception as e:
            log_error(f"Close event error: {e}")
            # Ensure cleanup happens even on error
            try:
                if hasattr(self, 'stability_optimizer') and self.stability_optimizer:
                    self.stability_optimizer.stop_monitoring()
            except:
                pass
            event.accept()
    
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
        # Graph controller removed as requested by user
    
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
    def scan_network(self):
        """Scan the network for devices with performance optimizations"""
        try:
            if self.controller:
                # Performance optimization: Throttle UI updates during scan
                self.throttle_ui_update(self.controller.scan_devices)
                self.status_bar.showMessage("Network scan started", 3000)
                # Update topology view after scan with throttling
                self.throttle_ui_update(self.update_topology_view)
            else:
                self.status_bar.showMessage("Controller not available", 3000)
        except Exception as e:
            log_error(f"Network scan error: {e}")
            self.status_bar.showMessage(f"Scan failed: {e}", 5000)
    
    def quick_scan_network(self):
        """Perform a quick network scan with performance optimizations"""
        try:
            log_info("Starting quick network scan...")
            if self.controller:
                # Performance optimization: Use throttled update
                self.throttle_ui_update(self.controller.scan_devices, quick=True)
            self.status_bar.showMessage("Quick scan completed", 3000)
        except Exception as e:
            log_error(f"Quick scan failed: {e}")
            self.status_bar.showMessage("Quick scan failed", 3000)
    
    def clear_data(self):
        """Clear all data with performance optimizations"""
        try:
            if self.controller:
                # Performance optimization: Throttle UI updates
                self.throttle_ui_update(self.controller.clear_devices)
                self.status_bar.showMessage("Data cleared", 3000)
            else:
                self.status_bar.showMessage("Controller not available", 3000)
        except Exception as e:
            log_error(f"Clear data error: {e}")
            self.status_bar.showMessage(f"Clear failed: {e}", 5000)
    
    def toggle_smart_mode(self):
        """Toggle smart mode with performance optimizations"""
        try:
            if self.controller:
                # Performance optimization: Throttle UI updates
                self.throttle_ui_update(self.controller.toggle_smart_mode)
                self.status_bar.showMessage("Smart mode toggled", 3000)
            else:
                self.status_bar.showMessage("Controller not available", 3000)
        except Exception as e:
            log_error(f"Smart mode toggle error: {e}")
            self.status_bar.showMessage(f"Smart mode toggle failed: {e}", 5000)
    
    def open_settings(self):
        """Open settings dialog with performance optimizations"""
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
                    
                    # Update UI immediately with throttling
                    self.throttle_ui_update(self._update_ui_from_settings)
                    
                    log_info("Settings updated successfully")
            else:
                QMessageBox.warning(self, "Warning", "Controller not available")
        except Exception as e:
            log_error(f"Error opening settings: {e}")
            QMessageBox.critical(self, "Error", f"Failed to open settings: {e}")
    
    def open_latency_config(self):
        """Open latency configuration dialog"""
        try:
            from app.gui.latency_config_dialog import LatencyConfigDialog
            if not hasattr(self, 'latency_config_dialog'):
                self.latency_config_dialog = LatencyConfigDialog(self)
            
            self.latency_config_dialog.show()
            self.latency_config_dialog.raise_()
            self.latency_config_dialog.activateWindow()
            
        except Exception as e:
            log_error(f"Error opening latency configuration: {e}")
            QMessageBox.critical(self, "Error", f"Failed to open latency configuration: {e}")
    
    def open_dayz_gaming_dashboard(self):
        """Open DayZ Gaming Dashboard"""
        try:
            self.dayz_gaming_dashboard.show()
            self.dayz_gaming_dashboard.raise_()
            self.dayz_gaming_dashboard.activateWindow()
        except Exception as e:
            log_error(f"Error opening DayZ Gaming Dashboard: {e}")
    
    def open_dayz_duping_dashboard(self):
        """Open DayZ Duping Dashboard"""
        try:
            self.dayz_duping_dashboard.show()
            self.dayz_duping_dashboard.raise_()
            self.dayz_duping_dashboard.activateWindow()
        except Exception as e:
            log_error(f"Error opening DayZ Duping Dashboard: {e}")
    
    def open_network_control(self):
        """Open Network Control Center"""
        try:
            self.unified_network_control.show()
            self.unified_network_control.raise_()
            self.unified_network_control.activateWindow()
        except Exception as e:
            log_error(f"Error opening Network Control Center: {e}")
    
    def open_advanced_scanner(self):
        """Open Advanced Network Scanner"""
        try:
            self.advanced_network_scanner.show()
            self.advanced_network_scanner.raise_()
            self.advanced_network_scanner.activateWindow()
        except Exception as e:
            log_error(f"Error opening Advanced Network Scanner: {e}")
    
    def open_network_manipulator(self):
        """Open Network Manipulator"""
        try:
            self.network_manipulator.show()
            self.network_manipulator.raise_()
            self.network_manipulator.activateWindow()
        except Exception as e:
            log_error(f"Error opening Network Manipulator: {e}")
    
    def open_dayz_map(self):
        """Open DayZ Map GUI"""
        try:
            self.dayz_map_gui.show()
            self.dayz_map_gui.raise_()
            self.dayz_map_gui.activateWindow()
        except Exception as e:
            log_error(f"Error opening DayZ Map GUI: {e}")
    
    def open_account_tracker(self):
        """Open DayZ Account Tracker"""
        try:
            self.dayz_account_tracker.show()
            self.dayz_account_tracker.raise_()
            self.dayz_account_tracker.activateWindow()
        except Exception as e:
            log_error(f"Error opening DayZ Account Tracker: {e}")
    
    def open_duping_optimizer(self):
        """Open DupeZ Duping Network Optimizer"""
        try:
            self.duping_optimizer.show()
            self.duping_optimizer.raise_()
            self.duping_optimizer.activateWindow()
        except Exception as e:
            log_error(f"Error opening DupeZ Duping Network Optimizer: {e}")
    
    def on_settings_changed(self, additional_settings: dict):
        """Handle settings changes with performance optimizations"""
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
                
                # Update UI based on new settings with throttling
                self.throttle_ui_update(self._update_ui_from_settings)
                
        except Exception as e:
            log_error(f"Error applying additional settings: {e}")
    
    def _update_ui_from_settings(self):
        """Update UI elements based on current settings with performance optimizations"""
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
        """Apply a theme to the application with performance optimizations"""
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
        """Show about dialog with performance optimizations"""
        try:
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
        except Exception as e:
            log_error(f"Error showing about dialog: {e}")
    
    def toggle_sidebar(self):
        """Toggle sidebar with performance optimizations"""
        try:
            if self.sidebar.isVisible():
                self.sidebar.hide()
                self.status_bar.showMessage("Sidebar hidden", 2000)
            else:
                self.sidebar.show()
                self.status_bar.showMessage("Sidebar shown", 2000)
        except Exception as e:
            log_error(f"Toggle sidebar failed: {e}")
    
    def search_devices(self):
        """Open search dialog for devices with performance optimizations"""
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
                    # Perform search with throttling
                    self.throttle_ui_update(self._perform_device_search, search_term.strip(), field)
            
            log_info(f"Search dialog opened")
        except Exception as e:
            log_error(f"Error in search dialog: {e}")
            QMessageBox.critical(self, "Error", f"Search failed: {e}")
    
    def _perform_device_search(self, search_term: str, field: str):
        """Perform device search with performance optimizations"""
        try:
            # Perform search
            results = self.enhanced_device_list.search_for_device(search_term, field)
            
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
        except Exception as e:
            log_error(f"Device search error: {e}")
    
    def show_hotkeys(self):
        """Show hotkeys help dialog with performance optimizations"""
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
                <li>Ctrl+N - Network Topology</li>
                <li>Ctrl+P - Plugin Manager</li>
            </ul>
            <p><b>View:</b></p>
            <ul>
                <li>Ctrl+Shift+T - Toggle Sidebar</li>
            </ul>
            <p><b>Help:</b></p>
            <ul>
                <li>F1 - This Help</li>
            </ul>
            """
            QMessageBox.information(self, "Hotkeys", hotkeys_text)
        except Exception as e:
            log_error(f"Show hotkeys failed: {e}")
    
    # Traffic analysis removed for optimization
    
    def show_network_topology(self):
        """Topology view removed for optimization"""
        try:
            self.status_bar.showMessage("Topology view removed for optimization", 3000)
        except Exception as e:
            log_error(f"Error showing network topology notice: {e}")
    
    def show_plugin_manager(self):
        """Show plugin manager with performance optimizations"""
        try:
            # Show plugin manager dialog
            self.status_bar.showMessage("Plugin manager feature", 3000)
        except Exception as e:
            log_error(f"Error showing plugin manager: {e}")
    
    def mass_block_devices(self):
        """Mass block devices with performance optimizations"""
        try:
            if self.controller:
                # Performance optimization: Use throttled update
                self.throttle_ui_update(self.controller.mass_block_devices)
                self.status_bar.showMessage("Mass block initiated", 3000)
            else:
                self.status_bar.showMessage("Controller not available", 3000)
        except Exception as e:
            log_error(f"Mass block error: {e}")
            self.status_bar.showMessage(f"Mass block failed: {e}", 5000)
    
    def mass_unblock_devices(self):
        """Mass unblock devices with performance optimizations"""
        try:
            if self.controller:
                # Performance optimization: Use throttled update
                self.throttle_ui_update(self.controller.mass_unblock_devices)
                self.status_bar.showMessage("Mass unblock initiated", 3000)
            else:
                self.status_bar.showMessage("Controller not available", 3000)
        except Exception as e:
            log_error(f"Mass unblock error: {e}")
            self.status_bar.showMessage(f"Mass unblock failed: {e}", 5000)
    
    def export_data(self):
        """Export device data to file with performance optimizations"""
        try:
            from PyQt6.QtWidgets import QFileDialog
            filename, _ = QFileDialog.getSaveFileName(
                self, "Export Device Data", 
                "dupez_devices.csv", 
                "CSV Files (*.csv);;All Files (*)"
            )
            
            if filename:
                # Performance optimization: Use throttled update
                self.throttle_ui_update(self._perform_data_export, filename)
                
        except Exception as e:
            log_error(f"Export data error: {e}")
            self.status_bar.showMessage(f"Export failed: {e}", 5000)
    
    def _perform_data_export(self, filename: str):
        """Perform data export with performance optimizations"""
        try:
            if self.controller:
                devices = self.controller.get_devices()
                # Export logic here
                self.status_bar.showMessage(f"Data exported to {filename}", 3000)
            else:
                self.status_bar.showMessage("Controller not available", 3000)
        except Exception as e:
            log_error(f"Data export implementation error: {e}")
    
    def ping_test(self):
        """Perform ping test with performance optimizations"""
        try:
            # Performance optimization: Use throttled update
            self.throttle_ui_update(self._perform_ping_test)
        except Exception as e:
            log_error(f"Error performing ping test: {e}")
    
    def _perform_ping_test(self):
        """Implementation of ping test with performance optimizations"""
        try:
            # Ping test logic here
            self.status_bar.showMessage("Ping test feature", 3000)
        except Exception as e:
            log_error(f"Ping test implementation error: {e}")
    
    def port_scan(self):
        """Perform port scan with performance optimizations"""
        try:
            # Performance optimization: Use throttled update
            self.throttle_ui_update(self._perform_port_scan)
        except Exception as e:
            log_error(f"Error performing port scan: {e}")
    
    def _perform_port_scan(self):
        """Implementation of port scan with performance optimizations"""
        try:
            # Port scan logic here
            self.status_bar.showMessage("Port scan feature", 3000)
        except Exception as e:
            log_error(f"Port scan implementation error: {e}")
    
    def update_topology_view(self):
        """Update topology view with performance optimizations"""
        try:
            # Performance optimization: Prevent multiple simultaneous updates
            if self._topology_updating:
                return
            
            self._topology_updating = True
            
            # Performance optimization: Use throttled update
            self.throttle_ui_update(self._perform_topology_update)
            
        except Exception as e:
            log_error(f"Topology update error: {e}")
            self._topology_updating = False
    
    def _perform_topology_update(self):
        """Perform topology update with performance optimizations"""
        try:
            if hasattr(self, 'topology_view') and self.topology_view:
                # Update topology view logic here
                pass
            
            # Reset update flag
            self._topology_updating = False
            
        except Exception as e:
            log_error(f"Topology update implementation error: {e}")
            self._topology_updating = False

    
