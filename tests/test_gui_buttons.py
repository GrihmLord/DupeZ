import pytest
import sys
import os
from unittest.mock import Mock, patch, MagicMock
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtTest import QTest

# Add the app directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

from gui.device_list import DeviceList
from gui.sidebar import Sidebar
from gui.dashboard import PulseDropDashboard
from core.controller import AppController
from core.state import Device


class TestGUIButtons:
    """Comprehensive test suite for all GUI buttons"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test environment"""
        self.app = QApplication.instance()
        if self.app is None:
            self.app = QApplication([])
        
        # Create mock controller
        self.mock_controller = Mock(spec=AppController)
        
        # Create test devices
        self.test_devices = [
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
        
        yield
        
        # Cleanup
        self.app.quit()
    
    def test_hide_sensitive_data_button(self):
        """Test the hide sensitive data button functionality"""
        device_list = DeviceList(self.mock_controller)
        device_list.update_device_list(self.test_devices)
        
        # Get the hide sensitive button
        hide_btn = device_list.hide_sensitive_btn
        assert hide_btn is not None, "Hide sensitive button should exist"
        
        # Test initial state (not checked)
        assert not hide_btn.isChecked(), "Hide sensitive button should be unchecked initially"
        
        # Click the button
        QTest.mouseClick(hide_btn, Qt.MouseButton.LeftButton)
        
        # Verify button state changed
        assert hide_btn.isChecked(), "Hide sensitive button should be checked after click"
        
        # Verify sensitive data is hidden in device list
        # Skip the header item (index 0) and check actual device items
        for i in range(1, device_list.device_list.count()):
            item = device_list.device_list.item(i)
            item_text = item.text()
            
            # Check that sensitive data is hidden
            assert "***" in item_text, "Sensitive data should be hidden with ***"
            assert "TestDevice" not in item_text, "Hostnames should be hidden"
            assert "00:11:22" not in item_text, "MAC addresses should be hidden"
        
        # Click again to unhide
        QTest.mouseClick(hide_btn, Qt.MouseButton.LeftButton)
        assert not hide_btn.isChecked(), "Hide sensitive button should be unchecked after second click"
    
    def test_encrypt_data_button(self):
        """Test the encrypt data button functionality"""
        device_list = DeviceList(self.mock_controller)
        
        # Get the encrypt data button
        encrypt_btn = device_list.encrypt_data_btn
        assert encrypt_btn is not None, "Encrypt data button should exist"
        
        # Test initial state
        assert not encrypt_btn.isChecked(), "Encrypt data button should be unchecked initially"
        
        # Click the button
        QTest.mouseClick(encrypt_btn, Qt.MouseButton.LeftButton)
        
        # Verify button state changed
        assert encrypt_btn.isChecked(), "Encrypt data button should be checked after click"
        
        # Click again to disable
        QTest.mouseClick(encrypt_btn, Qt.MouseButton.LeftButton)
        assert not encrypt_btn.isChecked(), "Encrypt data button should be unchecked after second click"
    
    def test_select_all_devices_button(self):
        """Test the select all devices button"""
        device_list = DeviceList(self.mock_controller)
        device_list.update_device_list(self.test_devices)
        
        # Get the select all button
        select_all_btn = device_list.select_all_btn
        assert select_all_btn is not None, "Select all button should exist"
        
        # Initially no devices should be selected
        assert len(device_list.device_list.selectedItems()) == 0, "No devices should be selected initially"
        
        # Click the select all button
        QTest.mouseClick(select_all_btn, Qt.MouseButton.LeftButton)
        
        # Verify all devices are selected
        selected_count = len(device_list.device_list.selectedItems())
        total_count = device_list.device_list.count()
        assert selected_count == total_count, f"All {total_count} devices should be selected, got {selected_count}"
    
    def test_block_selected_devices_button(self):
        """Test the block selected devices button"""
        device_list = DeviceList(self.mock_controller)
        device_list.update_device_list(self.test_devices)
        
        # Get the block selected button
        block_btn = device_list.block_selected_btn
        assert block_btn is not None, "Block selected button should exist"
        
        # Select a device first
        device_list.device_list.selectAll()
        
        # Click the block selected button
        QTest.mouseClick(block_btn, Qt.MouseButton.LeftButton)
        
        # Verify controller was called
        self.mock_controller.toggle_lag.assert_called()
    
    def test_scan_network_button(self):
        """Test the scan network button in sidebar"""
        sidebar = Sidebar(self.mock_controller)
        
        # Get the scan button
        scan_btn = sidebar.scan_btn
        assert scan_btn is not None, "Scan button should exist"
        
        # Click the scan button
        QTest.mouseClick(scan_btn, Qt.MouseButton.LeftButton)
        
        # Verify controller was called
        self.mock_controller.scan_devices.assert_called_once()
    
    def test_quick_scan_button(self):
        """Test the quick scan button in sidebar"""
        sidebar = Sidebar(self.mock_controller)
        
        # Get the quick scan button
        quick_scan_btn = sidebar.quick_scan_btn
        assert quick_scan_btn is not None, "Quick scan button should exist"
        
        # Click the quick scan button
        QTest.mouseClick(quick_scan_btn, Qt.MouseButton.LeftButton)
        
        # Verify controller was called
        self.mock_controller.scan_devices.assert_called_once()
    
    def test_smart_mode_button(self):
        """Test the smart mode button in sidebar"""
        sidebar = Sidebar(self.mock_controller)
        
        # Get the smart mode button
        smart_mode_btn = sidebar.smart_mode_btn
        assert smart_mode_btn is not None, "Smart mode button should exist"
        
        # Test initial state
        assert not smart_mode_btn.isChecked(), "Smart mode button should be unchecked initially"
        
        # Click the smart mode button
        QTest.mouseClick(smart_mode_btn, Qt.MouseButton.LeftButton)
        
        # Verify button state changed
        assert smart_mode_btn.isChecked(), "Smart mode button should be checked after click"
        
        # Verify controller was called
        self.mock_controller.toggle_smart_mode.assert_called_once()
        
        # Click again to disable
        QTest.mouseClick(smart_mode_btn, Qt.MouseButton.LeftButton)
        assert not smart_mode_btn.isChecked(), "Smart mode button should be unchecked after second click"
    
    def test_mass_block_button(self):
        """Test the mass block button in sidebar"""
        sidebar = Sidebar(self.mock_controller)
        
        # Get the mass block button
        mass_block_btn = sidebar.mass_block_btn
        assert mass_block_btn is not None, "Mass block button should exist"
        
        # Click the mass block button
        QTest.mouseClick(mass_block_btn, Qt.MouseButton.LeftButton)
        
        # Verify controller was called
        self.mock_controller.mass_block.assert_called_once()
    
    def test_mass_unblock_button(self):
        """Test the mass unblock button in sidebar"""
        sidebar = Sidebar(self.mock_controller)
        
        # Get the mass unblock button
        mass_unblock_btn = sidebar.mass_unblock_btn
        assert mass_unblock_btn is not None, "Mass unblock button should exist"
        
        # Click the mass unblock button
        QTest.mouseClick(mass_unblock_btn, Qt.MouseButton.LeftButton)
        
        # Verify controller was called
        self.mock_controller.mass_unblock.assert_called_once()
    
    def test_search_devices_button(self):
        """Test the search devices button in sidebar"""
        sidebar = Sidebar(self.mock_controller)
        
        # Get the search button
        search_btn = sidebar.search_btn
        assert search_btn is not None, "Search button should exist"
        
        # Click the search button
        QTest.mouseClick(search_btn, Qt.MouseButton.LeftButton)
        
        # Verify controller was called
        self.mock_controller.search_devices.assert_called_once()
    
    def test_clear_data_button(self):
        """Test the clear data button in sidebar"""
        sidebar = Sidebar(self.mock_controller)
        
        # Get the clear button
        clear_btn = sidebar.clear_btn
        assert clear_btn is not None, "Clear button should exist"
        
        # Click the clear button
        QTest.mouseClick(clear_btn, Qt.MouseButton.LeftButton)
        
        # Verify controller was called
        self.mock_controller.clear_data.assert_called_once()
    
    def test_settings_button(self):
        """Test the settings button in sidebar"""
        sidebar = Sidebar(self.mock_controller)
        
        # Get the settings button
        settings_btn = sidebar.settings_btn
        assert settings_btn is not None, "Settings button should exist"
        
        # Mock the signal emission
        with patch.object(sidebar, 'settings_requested') as mock_signal:
            # Click the settings button
            QTest.mouseClick(settings_btn, Qt.MouseButton.LeftButton)
            
            # Verify signal was emitted
            mock_signal.emit.assert_called_once()
    
    def test_device_selection(self):
        """Test device selection in device list"""
        device_list = DeviceList(self.mock_controller)
        device_list.update_device_list(self.test_devices)
        
        # Select first device
        first_item = device_list.device_list.item(0)
        device_list.device_list.setCurrentItem(first_item)
        
        # Verify device is selected
        assert device_list.device_list.currentItem() == first_item, "First device should be selected"
        
        # Verify controller was notified
        self.mock_controller.select_device.assert_called_with("192.168.1.100")
    
    def test_device_blocking_toggle(self):
        """Test device blocking toggle functionality"""
        device_list = DeviceList(self.mock_controller)
        device_list.update_device_list(self.test_devices)
        
        # Select a device
        first_item = device_list.device_list.item(0)
        device_list.device_list.setCurrentItem(first_item)
        
        # Get the block button
        block_btn = device_list.block_btn
        assert block_btn is not None, "Block button should exist"
        
        # Initially button should be disabled
        assert not block_btn.isEnabled(), "Block button should be disabled initially"
        
        # Enable the button (simulate device selection)
        block_btn.setEnabled(True)
        
        # Click the block button
        QTest.mouseClick(block_btn, Qt.MouseButton.LeftButton)
        
        # Verify controller was called
        self.mock_controller.toggle_lag.assert_called_with("192.168.1.100")
    
    def test_search_functionality(self):
        """Test search functionality in device list"""
        device_list = DeviceList(self.mock_controller)
        device_list.update_device_list(self.test_devices)
        
        # Get the search input
        search_input = device_list.search_input
        assert search_input is not None, "Search input should exist"
        
        # Enter search text
        QTest.keyClicks(search_input, "TestDevice1")
        
        # Verify search is applied
        assert search_input.text() == "TestDevice1", "Search text should be entered"
        
        # Test clear search button
        clear_search_btn = device_list.clear_search_btn
        assert clear_search_btn is not None, "Clear search button should exist"
        
        QTest.mouseClick(clear_search_btn, Qt.MouseButton.LeftButton)
        
        # Verify search is cleared
        assert search_input.text() == "", "Search should be cleared"
    
    def test_context_menu(self):
        """Test context menu functionality"""
        device_list = DeviceList(self.mock_controller)
        device_list.update_device_list(self.test_devices)
        
        # Get first device item
        first_item = device_list.device_list.item(0)
        
        # Simulate right-click context menu
        with patch.object(device_list, 'show_context_menu') as mock_menu:
            # Right-click on the item
            QTest.mouseClick(device_list.device_list.viewport(), Qt.MouseButton.RightButton)
            
            # Verify context menu was called
            mock_menu.assert_called()
    
    def test_auto_refresh_toggle(self):
        """Test auto refresh toggle functionality"""
        device_list = DeviceList(self.mock_controller)
        
        # Get the auto refresh button (if it exists)
        auto_refresh_btn = getattr(device_list, 'auto_refresh_btn', None)
        if auto_refresh_btn is not None:
            # Test initial state
            assert not auto_refresh_btn.isChecked(), "Auto refresh should be disabled initially"
            
            # Click the button
            QTest.mouseClick(auto_refresh_btn, Qt.MouseButton.LeftButton)
            
            # Verify button state changed
            assert auto_refresh_btn.isChecked(), "Auto refresh should be enabled after click"
    
    def test_button_accessibility(self):
        """Test that all buttons are accessible and have proper tooltips"""
        device_list = DeviceList(self.mock_controller)
        sidebar = Sidebar(self.mock_controller)
        
        # Test device list buttons
        buttons_to_test = [
            (device_list.hide_sensitive_btn, "Hide sensitive data button"),
            (device_list.encrypt_data_btn, "Encrypt data button"),
            (device_list.select_all_btn, "Select all button"),
            (device_list.block_selected_btn, "Block selected button"),
            (device_list.block_btn, "Block button"),
            (device_list.clear_search_btn, "Clear search button"),
        ]
        
        for button, name in buttons_to_test:
            if button is not None:
                assert button.isVisible(), f"{name} should be visible"
                assert button.isEnabled(), f"{name} should be enabled"
                assert button.toolTip(), f"{name} should have a tooltip"
        
        # Test sidebar buttons
        sidebar_buttons_to_test = [
            (sidebar.smart_mode_btn, "Smart mode button"),
            (sidebar.scan_btn, "Scan button"),
            (sidebar.quick_scan_btn, "Quick scan button"),
            (sidebar.mass_block_btn, "Mass block button"),
            (sidebar.mass_unblock_btn, "Mass unblock button"),
            (sidebar.search_btn, "Search button"),
            (sidebar.clear_btn, "Clear button"),
            (sidebar.settings_btn, "Settings button"),
        ]
        
        for button, name in sidebar_buttons_to_test:
            if button is not None:
                assert button.isVisible(), f"{name} should be visible"
                assert button.isEnabled(), f"{name} should be enabled"
                assert button.toolTip(), f"{name} should have a tooltip"


if __name__ == "__main__":
    pytest.main([__file__, "-v"]) 