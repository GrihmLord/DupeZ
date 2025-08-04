#!/usr/bin/env python3
"""
GUI Automation Tests for DupeZ
"""

import sys
import os
import time
import unittest
from unittest.mock import Mock, patch
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtTest import QTest

# Add the app directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'app'))

from gui.dashboard import DupeZDashboard
from gui.enhanced_device_list import EnhancedDeviceList
from gui.settings_dialog import SettingsDialog
from gui.sidebar import Sidebar
from gui.device_list import DeviceList
from core.controller import AppController
from core.state import AppSettings, Device

class TestGUIAutomation(unittest.TestCase):
    """Comprehensive GUI automation tests"""
    
    @classmethod
    def setUpClass(cls):
        """Set up the test environment"""
        cls.app = QApplication.instance()
        if cls.app is None:
            cls.app = QApplication(sys.argv)
        
        # Create mock controller
        cls.mock_controller = Mock(spec=AppController)
        cls.mock_controller.settings = AppSettings()
        
        # Create test devices
        cls.test_devices = [
            Device(
                ip="192.168.1.100",
                mac="00:11:22:33:44:55",
                hostname="TestDevice1",
                vendor="Test Vendor",
                local=False,
                blocked=False,
                last_seen="2024-01-01 12:00:00",
                traffic=1024
            ),
            Device(
                ip="192.168.1.101",
                mac="00:11:22:33:44:56",
                hostname="TestDevice2",
                vendor="Gaming Console",
                local=False,
                blocked=True,
                last_seen="2024-01-01 12:01:00",
                traffic=2048
            )
        ]
        
    def setUp(self):
        """Set up each test"""
        self.dashboard = None
        self.device_list = None
        self.settings_dialog = None
        
    def tearDown(self):
        """Clean up after each test"""
        if self.dashboard:
            self.dashboard.close()
        if self.device_list:
            self.device_list.close()
        if self.settings_dialog:
            self.settings_dialog.close()
    
    def test_dashboard_initialization(self):
        """Test dashboard initialization and basic UI elements"""
        self.dashboard = DupeZDashboard()
        self.dashboard.set_controller(self.mock_controller)
        
        # Test that main window loads
        self.assertIsNotNone(self.dashboard)
        self.assertTrue(self.dashboard.isVisible())
        
        # Test that sidebar is present
        self.assertIsNotNone(self.dashboard.sidebar)
        
        # Test that content tabs are present
        self.assertIsNotNone(self.dashboard.content_tabs)
        
        # Test that status bar is present
        self.assertIsNotNone(self.dashboard.statusBar())
    
    def test_device_list_scan_functionality(self):
        """Test device scanning functionality in the GUI"""
        self.device_list = EnhancedDeviceList()
        
        # Test scan button exists
        scan_button = self.device_list.findChild(QWidget, "scan_button")
        self.assertIsNotNone(scan_button)
        
        # Test scan button is clickable
        self.assertTrue(scan_button.isEnabled())
        
        # Test scan button click
        QTest.mouseClick(scan_button, Qt.MouseButton.LeftButton)
        
        # Wait for scan to start
        time.sleep(0.1)
        
        # Test that scan status is updated
        status_label = self.device_list.findChild(QWidget, "status_label")
        if status_label:
            self.assertIn("scan", status_label.text().lower())
    
    def test_settings_dialog_functionality(self):
        """Test settings dialog functionality"""
        self.settings_dialog = SettingsDialog()
        
        # Test that dialog loads
        self.assertIsNotNone(self.settings_dialog)
        
        # Test that dialog is visible
        self.assertTrue(self.settings_dialog.isVisible())
        
        # Test that dialog has settings controls
        # (Add more specific tests based on actual dialog structure)
    
    def test_sidebar_navigation(self):
        """Test sidebar navigation functionality"""
        sidebar = Sidebar(self.mock_controller)
        
        # Test that sidebar loads
        self.assertIsNotNone(sidebar)
        
        # Test that navigation buttons exist
        # (Add more specific tests based on actual sidebar structure)
    
    def test_device_blocking_functionality(self):
        """Test device blocking functionality in the GUI"""
        self.device_list = DeviceList(self.mock_controller)
        self.device_list.update_device_list(self.test_devices)
        
        # Test that device list loads with test devices
        self.assertGreater(self.device_list.device_list.count(), 0)
        
        # Test device selection
        if self.device_list.device_list.count() > 0:
            self.device_list.device_list.setCurrentRow(0)
            selected_items = self.device_list.device_list.selectedItems()
            self.assertEqual(len(selected_items), 1)
    
    def test_internet_drop_functionality(self):
        """Test internet drop functionality in the GUI"""
        self.dashboard = DupeZDashboard()
        self.dashboard.set_controller(self.mock_controller)
        
        # Test that dashboard loads
        self.assertIsNotNone(self.dashboard)
        
        # Test that internet drop controls exist
        # (Add more specific tests based on actual dashboard structure)
    
    def test_responsive_design(self):
        """Test that GUI elements are responsive"""
        self.dashboard = DupeZDashboard()
        
        # Test window resizing
        original_size = self.dashboard.size()
        self.dashboard.resize(800, 600)
        new_size = self.dashboard.size()
        
        self.assertNotEqual(original_size, new_size)
    
    def test_theme_switching(self):
        """Test theme switching functionality"""
        self.dashboard = DupeZDashboard()
        
        # Test that theme switching works
        # (Add more specific tests based on actual theme implementation)
    
    def test_error_handling(self):
        """Test GUI error handling"""
        # Test that GUI handles errors gracefully
        # (Add more specific tests based on actual error handling)
    
    def test_performance(self):
        """Test GUI performance"""
        start_time = time.time()
        
        self.dashboard = DupeZDashboard()
        self.dashboard.set_controller(self.mock_controller)
        
        load_time = time.time() - start_time
        
        # Test that dashboard loads within reasonable time
        self.assertLess(load_time, 5.0, "Dashboard should load within 5 seconds")
    
    def test_accessibility(self):
        """Test GUI accessibility features"""
        self.dashboard = DupeZDashboard()
        
        # Test that all interactive elements are accessible
        # (Add more specific tests based on actual accessibility features)
    
    def test_memory_management(self):
        """Test GUI memory management"""
        # Test that GUI properly cleans up resources
        # (Add more specific tests based on actual memory management)
    
    # Additional button-specific tests from test_gui_buttons.py
    def test_hide_sensitive_data_button(self):
        """Test the hide sensitive data button functionality"""
        self.device_list = DeviceList(self.mock_controller)
        self.device_list.update_device_list(self.test_devices)
        
        # Get the hide sensitive button
        hide_btn = self.device_list.hide_sensitive_btn
        self.assertIsNotNone(hide_btn, "Hide sensitive button should exist")
        
        # Test initial state (not checked)
        self.assertFalse(hide_btn.isChecked(), "Hide sensitive button should be unchecked initially")
        
        # Click the button
        QTest.mouseClick(hide_btn, Qt.MouseButton.LeftButton)
        
        # Verify button state changed
        self.assertTrue(hide_btn.isChecked(), "Hide sensitive button should be checked after click")
        
        # Click again to unhide
        QTest.mouseClick(hide_btn, Qt.MouseButton.LeftButton)
        self.assertFalse(hide_btn.isChecked(), "Hide sensitive button should be unchecked after second click")
    
    def test_encrypt_data_button(self):
        """Test the encrypt data button functionality"""
        self.device_list = DeviceList(self.mock_controller)
        
        # Get the encrypt data button
        encrypt_btn = self.device_list.encrypt_data_btn
        self.assertIsNotNone(encrypt_btn, "Encrypt data button should exist")
        
        # Test initial state
        self.assertFalse(encrypt_btn.isChecked(), "Encrypt data button should be unchecked initially")
        
        # Click the button
        QTest.mouseClick(encrypt_btn, Qt.MouseButton.LeftButton)
        
        # Verify button state changed
        self.assertTrue(encrypt_btn.isChecked(), "Encrypt data button should be checked after click")
        
        # Click again to disable
        QTest.mouseClick(encrypt_btn, Qt.MouseButton.LeftButton)
        self.assertFalse(encrypt_btn.isChecked(), "Encrypt data button should be unchecked after second click")
    
    def test_select_all_devices_button(self):
        """Test the select all devices button"""
        self.device_list = DeviceList(self.mock_controller)
        self.device_list.update_device_list(self.test_devices)
        
        # Get the select all button
        select_all_btn = self.device_list.select_all_btn
        self.assertIsNotNone(select_all_btn, "Select all button should exist")
        
        # Initially no devices should be selected
        self.assertEqual(len(self.device_list.device_list.selectedItems()), 0, "No devices should be selected initially")
        
        # Click the select all button
        QTest.mouseClick(select_all_btn, Qt.MouseButton.LeftButton)
        
        # Verify all devices are selected
        selected_count = len(self.device_list.device_list.selectedItems())
        total_count = self.device_list.device_list.count()
        self.assertEqual(selected_count, total_count, f"All {total_count} devices should be selected, got {selected_count}")
    
    def test_scan_network_button(self):
        """Test the scan network button in sidebar"""
        sidebar = Sidebar(self.mock_controller)
        
        # Get the scan button
        scan_btn = sidebar.scan_btn
        self.assertIsNotNone(scan_btn, "Scan button should exist")
        
        # Click the scan button
        QTest.mouseClick(scan_btn, Qt.MouseButton.LeftButton)
        
        # Verify controller was called
        self.mock_controller.scan_devices.assert_called_once()
    
    def test_quick_scan_button(self):
        """Test the quick scan button in sidebar"""
        sidebar = Sidebar(self.mock_controller)
        
        # Get the quick scan button
        quick_scan_btn = sidebar.quick_scan_btn
        self.assertIsNotNone(quick_scan_btn, "Quick scan button should exist")
        
        # Click the quick scan button
        QTest.mouseClick(quick_scan_btn, Qt.MouseButton.LeftButton)
        
        # Verify controller was called
        self.mock_controller.scan_devices.assert_called_once()
    
    def test_smart_mode_button(self):
        """Test the smart mode button in sidebar"""
        sidebar = Sidebar(self.mock_controller)
        
        # Get the smart mode button
        smart_mode_btn = sidebar.smart_mode_btn
        self.assertIsNotNone(smart_mode_btn, "Smart mode button should exist")
        
        # Test initial state
        self.assertFalse(smart_mode_btn.isChecked(), "Smart mode button should be unchecked initially")
        
        # Click the smart mode button
        QTest.mouseClick(smart_mode_btn, Qt.MouseButton.LeftButton)
        
        # Verify button state changed
        self.assertTrue(smart_mode_btn.isChecked(), "Smart mode button should be checked after click")
        
        # Verify controller was called
        self.mock_controller.toggle_smart_mode.assert_called_once()

class TestGUIIntegration(unittest.TestCase):
    """Test GUI integration with other components"""
    
    @classmethod
    def setUpClass(cls):
        """Set up the test environment"""
        cls.app = QApplication.instance()
        if cls.app is None:
            cls.app = QApplication(sys.argv)
        
        # Create mock controller
        cls.mock_controller = Mock(spec=AppController)
        cls.mock_controller.settings = AppSettings()
    
    def test_gui_controller_integration(self):
        """Test that GUI properly integrates with controller"""
        dashboard = DupeZDashboard()
        dashboard.set_controller(self.mock_controller)
        
        # Test that controller is properly set
        self.assertEqual(dashboard.controller, self.mock_controller)
        
        # Test that GUI can call controller methods
        # (Add more specific tests based on actual integration)
    
    def test_settings_persistence(self):
        """Test that GUI settings are properly persisted"""
        # Test that settings are saved and loaded correctly
        # (Add more specific tests based on actual settings persistence)

if __name__ == '__main__':
    unittest.main() 