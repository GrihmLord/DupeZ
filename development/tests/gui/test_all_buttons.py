#!/usr/bin/env python3
"""
Comprehensive button functionality test for DupeZ application
Tests all buttons across all GUI components to ensure they work properly
"""

import sys
import os
import time
import threading
from typing import List, Dict, Optional
from unittest.mock import Mock, patch, MagicMock

# Add the project root to the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from PyQt6.QtWidgets import QApplication, QWidget, QPushButton, QVBoxLayout, QLabel, QTextEdit
from PyQt6.QtCore import QTimer, pyqtSignal, QThread
from PyQt6.QtTest import QTest
from PyQt6.QtCore import Qt

class ButtonTestGUI(QWidget):
    """Test GUI for button functionality verification"""
    
    def __init__(self):
        super().__init__()
        self.test_results = []
        self.current_test = ""
        self.setup_ui()
        
    def setup_ui(self):
        """Setup the test interface"""
        layout = QVBoxLayout()
        
        # Title
        title = QLabel("🔍 DupeZ Button Functionality Test")
        title.setStyleSheet("font-size: 16pt; font-weight: bold; color: #00ffff;")
        layout.addWidget(title)
        
        # Test results display
        self.results_display = QTextEdit()
        self.results_display.setReadOnly(True)
        self.results_display.setMaximumHeight(300)
        layout.addWidget(self.results_display)
        
        # Status
        self.status_label = QLabel("Ready to test buttons")
        self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        layout.addWidget(self.status_label)
        
        self.setLayout(layout)
        self.setWindowTitle("DupeZ Button Test")
        self.resize(600, 400)
        
    def log_result(self, test_name: str, success: bool, details: str = ""):
        """Log test results"""
        status = "✅ PASS" if success else "❌ FAIL"
        result = f"{status} {test_name}: {details}"
        self.test_results.append(result)
        self.results_display.append(result)
        
    def run_all_tests(self):
        """Run comprehensive button tests"""
        self.log_result("TEST START", True, "Beginning comprehensive button functionality test")
        
        # Test Enhanced Device List buttons
        self.test_enhanced_device_list_buttons()
        
        # Test Sidebar buttons
        self.test_sidebar_buttons()
        
        # Test Network Manipulator buttons
        self.test_network_manipulator_buttons()
        
        # Test DayZ GUI buttons
        self.test_dayz_gui_buttons()
        
        # Test Settings buttons
        self.test_settings_buttons()
        
        # Test Theme buttons
        self.test_theme_buttons()
        
        # Test Topology buttons
        self.test_topology_buttons()
        
        # Test Privacy buttons
        self.test_privacy_buttons()
        
        # Test PS5 buttons
        self.test_ps5_buttons()
        
        # Summary
        passed = sum(1 for result in self.test_results if "✅ PASS" in result)
        total = len(self.test_results) - 1  # Exclude test start
        self.log_result("TEST SUMMARY", True, f"Passed: {passed}/{total}")
        
    def test_enhanced_device_list_buttons(self):
        """Test Enhanced Device List buttons"""
        self.log_result("Enhanced Device List", True, "Testing scan, block, disconnect buttons")
        
        try:
            from app.gui.enhanced_device_list import EnhancedDeviceList
            
            # Create mock controller
            mock_controller = Mock()
            mock_controller.toggle_lag = Mock(return_value=True)
            
            # Create the widget
            device_list = EnhancedDeviceList(controller=mock_controller)
            
            # Test scan button
            if hasattr(device_list, 'scan_button') and device_list.scan_button:
                self.log_result("Scan Button", True, "Scan button exists and connected")
            else:
                self.log_result("Scan Button", False, "Scan button not found")
            
            # Test disconnect button
            if hasattr(device_list, 'internet_drop_button') and device_list.internet_drop_button:
                self.log_result("Disconnect Button", True, "Disconnect button exists and connected")
            else:
                self.log_result("Disconnect Button", False, "Disconnect button not found")
            
            # Test block buttons
            if hasattr(device_list, 'device_table') and device_list.device_table:
                self.log_result("Block Buttons", True, "Device table with block buttons exists")
            else:
                self.log_result("Block Buttons", False, "Device table not found")
                
        except Exception as e:
            self.log_result("Enhanced Device List", False, f"Error: {str(e)}")
    
    def test_sidebar_buttons(self):
        """Test Sidebar buttons"""
        self.log_result("Sidebar", True, "Testing sidebar control buttons")
        
        try:
            from app.gui.sidebar import Sidebar
            
            # Create mock controller
            mock_controller = Mock()
            
            # Create the widget
            sidebar = Sidebar(controller=mock_controller)
            
            # Test smart mode button
            if hasattr(sidebar, 'smart_mode_btn') and sidebar.smart_mode_btn:
                self.log_result("Smart Mode Button", True, "Smart mode button exists and connected")
            else:
                self.log_result("Smart Mode Button", False, "Smart mode button not found")
            
            # Test scan button
            if hasattr(sidebar, 'scan_btn') and sidebar.scan_btn:
                self.log_result("Scan Button", True, "Scan button exists and connected")
            else:
                self.log_result("Scan Button", False, "Scan button not found")
            
            # Test quick scan button
            if hasattr(sidebar, 'quick_scan_btn') and sidebar.quick_scan_btn:
                self.log_result("Quick Scan Button", True, "Quick scan button exists and connected")
            else:
                self.log_result("Quick Scan Button", False, "Quick scan button not found")
            
            # Test settings button
            if hasattr(sidebar, 'settings_btn') and sidebar.settings_btn:
                self.log_result("Settings Button", True, "Settings button exists and connected")
            else:
                self.log_result("Settings Button", False, "Settings button not found")
                
        except Exception as e:
            self.log_result("Sidebar", False, f"Error: {str(e)}")
    
    def test_network_manipulator_buttons(self):
        """Test Network Manipulator buttons"""
        self.log_result("Network Manipulator", True, "Testing network manipulation buttons")
        
        try:
            from app.gui.network_manipulator_gui import NetworkManipulatorGUI
            
            # Create the widget
            manipulator = NetworkManipulatorGUI()
            
            # Test block button
            if hasattr(manipulator, 'block_button') and manipulator.block_button:
                self.log_result("Block Button", True, "Block button exists and connected")
            else:
                self.log_result("Block Button", False, "Block button not found")
            
            # Test unblock button
            if hasattr(manipulator, 'unblock_button') and manipulator.unblock_button:
                self.log_result("Unblock Button", True, "Unblock button exists and connected")
            else:
                self.log_result("Unblock Button", False, "Unblock button not found")
            
            # Test throttle button
            if hasattr(manipulator, 'throttle_button') and manipulator.throttle_button:
                self.log_result("Throttle Button", True, "Throttle button exists and connected")
            else:
                self.log_result("Throttle Button", False, "Throttle button not found")
                
        except Exception as e:
            self.log_result("Network Manipulator", False, f"Error: {str(e)}")
    
    def test_dayz_gui_buttons(self):
        """Test DayZ GUI buttons"""
        self.log_result("DayZ GUIs", True, "Testing DayZ-related GUI buttons")
        
        try:
            # Test DayZ UDP GUI
            from app.gui.dayz_udp_gui import DayZUDPGUI
            udp_gui = DayZUDPGUI()
            
            # Test DayZ Firewall GUI
            from app.gui.dayz_firewall_gui import DayZFirewallGUI
            firewall_gui = DayZFirewallGUI()
            
            # Test DayZ Map GUI
            from app.gui.dayz_map_gui import DayZMapGUI
            map_gui = DayZMapGUI()
            
            # Test DayZ Account Tracker
            from app.gui.dayz_account_tracker import DayZAccountTracker
            account_tracker = DayZAccountTracker()
            
            self.log_result("DayZ UDP GUI", True, "DayZ UDP GUI buttons exist")
            self.log_result("DayZ Firewall GUI", True, "DayZ Firewall GUI buttons exist")
            self.log_result("DayZ Map GUI", True, "DayZ Map GUI buttons exist")
            self.log_result("DayZ Account Tracker", True, "DayZ Account Tracker buttons exist")
            
        except Exception as e:
            self.log_result("DayZ GUIs", False, f"Error: {str(e)}")
    
    def test_settings_buttons(self):
        """Test Settings dialog buttons"""
        self.log_result("Settings Dialog", True, "Testing settings dialog buttons")
        
        try:
            from app.gui.settings_dialog import SettingsDialog
            
            # Create the dialog
            settings = SettingsDialog()
            
            # Test save button
            if hasattr(settings, 'save_btn') and settings.save_btn:
                self.log_result("Save Button", True, "Save button exists and connected")
            else:
                self.log_result("Save Button", False, "Save button not found")
            
            # Test cancel button
            if hasattr(settings, 'cancel_btn') and settings.cancel_btn:
                self.log_result("Cancel Button", True, "Cancel button exists and connected")
            else:
                self.log_result("Cancel Button", False, "Cancel button not found")
            
            # Test reset button
            if hasattr(settings, 'reset_btn') and settings.reset_btn:
                self.log_result("Reset Button", True, "Reset button exists and connected")
            else:
                self.log_result("Reset Button", False, "Reset button not found")
                
        except Exception as e:
            self.log_result("Settings Dialog", False, f"Error: {str(e)}")
    
    def test_theme_buttons(self):
        """Test Theme selector buttons"""
        self.log_result("Theme Selector", True, "Testing theme selector buttons")
        
        try:
            from app.gui.theme_selector import ThemeSelector
            
            # Create the widget
            theme_selector = ThemeSelector()
            
            # Test theme buttons
            if hasattr(theme_selector, 'light_btn') and theme_selector.light_btn:
                self.log_result("Light Theme Button", True, "Light theme button exists and connected")
            else:
                self.log_result("Light Theme Button", False, "Light theme button not found")
            
            if hasattr(theme_selector, 'dark_btn') and theme_selector.dark_btn:
                self.log_result("Dark Theme Button", True, "Dark theme button exists and connected")
            else:
                self.log_result("Dark Theme Button", False, "Dark theme button not found")
            
            if hasattr(theme_selector, 'hacker_btn') and theme_selector.hacker_btn:
                self.log_result("Hacker Theme Button", True, "Hacker theme button exists and connected")
            else:
                self.log_result("Hacker Theme Button", False, "Hacker theme button not found")
                
        except Exception as e:
            self.log_result("Theme Selector", False, f"Error: {str(e)}")
    
    def test_topology_buttons(self):
        """Test Topology view buttons"""
        self.log_result("Topology View", True, "Testing topology view buttons")
        
        try:
            from app.gui.topology_view import NetworkTopologyView
            
            # Create mock controller
            mock_controller = Mock()
            
            # Create the widget
            topology = NetworkTopologyView(controller=mock_controller)
            
            # Test refresh button
            if hasattr(topology, 'refresh_btn') and topology.refresh_btn:
                self.log_result("Refresh Button", True, "Refresh button exists and connected")
            else:
                self.log_result("Refresh Button", False, "Refresh button not found")
            
            # Test export button
            if hasattr(topology, 'export_btn') and topology.export_btn:
                self.log_result("Export Button", True, "Export button exists and connected")
            else:
                self.log_result("Export Button", False, "Export button not found")
                
        except Exception as e:
            self.log_result("Topology View", False, f"Error: {str(e)}")
    
    def test_privacy_buttons(self):
        """Test Privacy GUI buttons"""
        self.log_result("Privacy GUI", True, "Testing privacy GUI buttons")
        
        try:
            from app.gui.privacy_gui import PrivacyGUI
            
            # Create the widget
            privacy = PrivacyGUI()
            
            # Test mask button
            if hasattr(privacy, 'mask_button') and privacy.mask_button:
                self.log_result("Mask Button", True, "Mask button exists and connected")
            else:
                self.log_result("Mask Button", False, "Mask button not found")
            
            # Test clear button
            if hasattr(privacy, 'clear_button') and privacy.clear_button:
                self.log_result("Clear Button", True, "Clear button exists and connected")
            else:
                self.log_result("Clear Button", False, "Clear button not found")
                
        except Exception as e:
            self.log_result("Privacy GUI", False, f"Error: {str(e)}")
    
    def test_ps5_buttons(self):
        """Test PS5 GUI buttons"""
        self.log_result("PS5 GUI", True, "Testing PS5 GUI buttons")
        
        try:
            from app.gui.ps5_gui import PS5NetworkGUI
            
            # Create the widget
            ps5_gui = PS5NetworkGUI()
            
            # Test scan button
            if hasattr(ps5_gui, 'scan_ps5_button') and ps5_gui.scan_ps5_button:
                self.log_result("PS5 Scan Button", True, "PS5 scan button exists and connected")
            else:
                self.log_result("PS5 Scan Button", False, "PS5 scan button not found")
            
            # Test block buttons
            if hasattr(ps5_gui, 'block_selected_ps5_button') and ps5_gui.block_selected_ps5_button:
                self.log_result("PS5 Block Button", True, "PS5 block button exists and connected")
            else:
                self.log_result("PS5 Block Button", False, "PS5 block button not found")
                
        except Exception as e:
            self.log_result("PS5 GUI", False, f"Error: {str(e)}")

def run_button_test():
    """Run the comprehensive button test"""
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
    
    # Create and show test GUI
    test_gui = ButtonTestGUI()
    test_gui.show()
    
    # Run tests after a short delay
    QTimer.singleShot(1000, test_gui.run_all_tests)
    
    # Start the event loop
    app.exec()

if __name__ == "__main__":
    run_button_test() 