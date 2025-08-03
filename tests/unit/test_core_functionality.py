#!/usr/bin/env python3
"""
Unit Tests for Core Functionality
Testing core application logic, state management, and controller functionality
"""

import sys
import os
import unittest
from unittest.mock import Mock, patch, MagicMock
import tempfile
import json

# Add the app directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'app'))

from core.state import AppSettings, load_settings, save_settings
from core.controller import AppController
from core.smart_mode import SmartMode
from core.traffic_analyzer import TrafficAnalyzer
from firewall.ps5_blocker import PS5Blocker
from firewall.internet_dropper import InternetDropper
from network.device_scan import DeviceScanner
from network.enhanced_scanner import EnhancedScanner

class TestAppSettings(unittest.TestCase):
    """Test application settings functionality"""
    
    def setUp(self):
        """Set up test environment"""
        self.temp_dir = tempfile.mkdtemp()
        self.settings_file = os.path.join(self.temp_dir, 'test_settings.json')
    
    def tearDown(self):
        """Clean up test environment"""
        import shutil
        shutil.rmtree(self.temp_dir)
    
    def test_default_settings(self):
        """Test default settings creation"""
        settings = AppSettings()
        
        # Test that all required fields are present
        self.assertTrue(hasattr(settings, 'smart_mode'))
        self.assertTrue(hasattr(settings, 'auto_scan'))
        self.assertTrue(hasattr(settings, 'scan_interval'))
        self.assertTrue(hasattr(settings, 'theme'))
        self.assertTrue(hasattr(settings, 'auto_refresh'))
        
        # Test default values
        self.assertTrue(settings.smart_mode)
        self.assertTrue(settings.auto_scan)
        self.assertEqual(settings.scan_interval, 300)
        self.assertEqual(settings.theme, 'dark')
        self.assertTrue(settings.auto_refresh)
    
    def test_settings_serialization(self):
        """Test settings serialization to/from JSON"""
        settings = AppSettings()
        settings.smart_mode = False
        settings.theme = 'light'
        settings.scan_interval = 120
        
        # Test serialization
        settings_dict = settings.to_dict()
        self.assertIsInstance(settings_dict, dict)
        self.assertEqual(settings_dict['smart_mode'], False)
        self.assertEqual(settings_dict['theme'], 'light')
        self.assertEqual(settings_dict['scan_interval'], 120)
        
        # Test deserialization
        new_settings = AppSettings.from_dict(settings_dict)
        self.assertEqual(new_settings.smart_mode, False)
        self.assertEqual(new_settings.theme, 'light')
        self.assertEqual(new_settings.scan_interval, 120)
    
    def test_settings_persistence(self):
        """Test settings save and load functionality"""
        settings = AppSettings()
        settings.theme = 'hacker'
        settings.auto_scan = False
        
        # Save settings
        save_settings(settings, self.settings_file)
        
        # Load settings
        loaded_settings = load_settings(self.settings_file)
        
        # Verify settings were saved and loaded correctly
        self.assertEqual(loaded_settings.theme, 'hacker')
        self.assertEqual(loaded_settings.auto_scan, False)
    
    def test_settings_validation(self):
        """Test settings validation"""
        settings = AppSettings()
        
        # Test valid settings
        settings.scan_interval = 60
        settings.max_threads = 10
        settings.ping_timeout = 5
        
        # These should not raise exceptions
        self.assertIsInstance(settings.scan_interval, int)
        self.assertIsInstance(settings.max_threads, int)
        self.assertIsInstance(settings.ping_timeout, int)

class TestAppController(unittest.TestCase):
    """Test application controller functionality"""
    
    def setUp(self):
        """Set up test environment"""
        self.controller = AppController()
    
    def test_controller_initialization(self):
        """Test controller initialization"""
        self.assertIsNotNone(self.controller)
        self.assertIsNotNone(self.controller.settings)
        self.assertIsInstance(self.controller.settings, AppSettings)
    
    def test_settings_update(self):
        """Test settings update functionality"""
        # Create new settings
        new_settings = AppSettings()
        new_settings.theme = 'light'
        new_settings.auto_scan = False
        
        # Update controller settings
        self.controller.update_settings(new_settings)
        
        # Verify settings were updated
        self.assertEqual(self.controller.settings.theme, 'light')
        self.assertEqual(self.controller.settings.auto_scan, False)
    
    def test_network_operations(self):
        """Test network operations"""
        # Mock network scanner
        with patch('network.device_scan.DeviceScanner') as mock_scanner:
            mock_scanner.return_value.scan_devices.return_value = [
                {'ip': '192.168.1.100', 'mac': '00:11:22:33:44:55'}
            ]
            
            # Test device scanning
            devices = self.controller.scan_network()
            self.assertIsInstance(devices, list)
            self.assertGreater(len(devices), 0)
    
    def test_blocking_operations(self):
        """Test blocking operations"""
        # Mock PS5 blocker
        with patch('firewall.ps5_blocker.PS5Blocker') as mock_blocker:
            mock_blocker.return_value.block_ps5.return_value = True
            
            # Test PS5 blocking
            result = self.controller.block_ps5('192.168.1.100')
            self.assertTrue(result)
    
    def test_internet_drop_operations(self):
        """Test internet drop operations"""
        # Mock internet dropper
        with patch('firewall.internet_dropper.InternetDropper') as mock_dropper:
            mock_dropper.return_value.drop_internet.return_value = True
            mock_dropper.return_value.restore_internet.return_value = True
            
            # Test internet drop
            result = self.controller.drop_internet()
            self.assertTrue(result)
            
            # Test internet restore
            result = self.controller.restore_internet()
            self.assertTrue(result)

class TestSmartMode(unittest.TestCase):
    """Test smart mode functionality"""
    
    def setUp(self):
        """Set up test environment"""
        self.smart_mode = SmartMode()
    
    def test_smart_mode_initialization(self):
        """Test smart mode initialization"""
        self.assertIsNotNone(self.smart_mode)
        self.assertFalse(self.smart_mode.is_active())
    
    def test_smart_mode_activation(self):
        """Test smart mode activation"""
        self.smart_mode.activate()
        self.assertTrue(self.smart_mode.is_active())
        
        self.smart_mode.deactivate()
        self.assertFalse(self.smart_mode.is_active())
    
    def test_smart_mode_rules(self):
        """Test smart mode rule processing"""
        # Test with normal traffic
        normal_device = {'ip': '192.168.1.100', 'traffic': 100}
        result = self.smart_mode.process_device(normal_device)
        self.assertIsInstance(result, dict)
        
        # Test with suspicious traffic
        suspicious_device = {'ip': '192.168.1.101', 'traffic': 10000}
        result = self.smart_mode.process_device(suspicious_device)
        self.assertIsInstance(result, dict)

class TestTrafficAnalyzer(unittest.TestCase):
    """Test traffic analyzer functionality"""
    
    def setUp(self):
        """Set up test environment"""
        self.analyzer = TrafficAnalyzer()
    
    def test_traffic_analyzer_initialization(self):
        """Test traffic analyzer initialization"""
        self.assertIsNotNone(self.analyzer)
    
    def test_traffic_analysis(self):
        """Test traffic analysis functionality"""
        # Test with sample traffic data
        traffic_data = [
            {'ip': '192.168.1.100', 'bytes_sent': 1000, 'bytes_received': 500},
            {'ip': '192.168.1.101', 'bytes_sent': 5000, 'bytes_received': 2000}
        ]
        
        analysis = self.analyzer.analyze_traffic(traffic_data)
        self.assertIsInstance(analysis, dict)
        self.assertIn('total_traffic', analysis)
        self.assertIn('suspicious_devices', analysis)

class TestPS5Blocker(unittest.TestCase):
    """Test PS5 blocker functionality"""
    
    def setUp(self):
        """Set up test environment"""
        self.blocker = PS5Blocker()
    
    def test_ps5_blocker_initialization(self):
        """Test PS5 blocker initialization"""
        self.assertIsNotNone(self.blocker)
        self.assertIsInstance(self.blocker.blocked_ps5s, set)
    
    def test_ps5_detection(self):
        """Test PS5 device detection"""
        # Test Sony MAC addresses
        sony_devices = [
            {'mac': '00:50:c2:11:22:33'},
            {'mac': '00:1f:a7:44:55:66'},
            {'mac': '00:19:c5:77:88:99'}
        ]
        
        for device in sony_devices:
            result = self.blocker._is_ps5_device(device)
            self.assertTrue(result)
        
        # Test non-Sony devices
        non_sony_devices = [
            {'mac': '00:11:22:33:44:55'},
            {'mac': 'aa:bb:cc:dd:ee:ff'}
        ]
        
        for device in non_sony_devices:
            result = self.blocker._is_ps5_device(device)
            self.assertFalse(result)
    
    def test_ps5_blocking(self):
        """Test PS5 blocking functionality"""
        # Mock subprocess calls
        with patch('subprocess.run') as mock_run:
            mock_run.return_value.returncode = 0
            
            # Test blocking
            result = self.blocker.block_ps5('192.168.1.100')
            self.assertTrue(result)
            
            # Test unblocking
            result = self.blocker.unblock_ps5('192.168.1.100')
            self.assertTrue(result)

class TestInternetDropper(unittest.TestCase):
    """Test internet dropper functionality"""
    
    def setUp(self):
        """Set up test environment"""
        self.dropper = InternetDropper()
    
    def test_internet_dropper_initialization(self):
        """Test internet dropper initialization"""
        self.assertIsNotNone(self.dropper)
        self.assertFalse(self.dropper.is_internet_dropped())
    
    def test_internet_drop_restore(self):
        """Test internet drop and restore functionality"""
        # Mock subprocess calls
        with patch('subprocess.run') as mock_run:
            mock_run.return_value.returncode = 0
            
            # Test internet drop
            result = self.dropper.drop_internet()
            self.assertTrue(result)
            self.assertTrue(self.dropper.is_internet_dropped())
            
            # Test internet restore
            result = self.dropper.restore_internet()
            self.assertTrue(result)
            self.assertFalse(self.dropper.is_internet_dropped())

class TestDeviceScanner(unittest.TestCase):
    """Test device scanner functionality"""
    
    def setUp(self):
        """Set up test environment"""
        self.scanner = DeviceScanner()
    
    def test_device_scanner_initialization(self):
        """Test device scanner initialization"""
        self.assertIsNotNone(self.scanner)
    
    def test_interface_discovery(self):
        """Test network interface discovery"""
        # Mock network interfaces
        with patch('socket.gethostbyname') as mock_gethostbyname:
            mock_gethostbyname.return_value = '192.168.1.1'
            
            interfaces = self.scanner.discover_interfaces()
            self.assertIsInstance(interfaces, list)
    
    def test_device_scanning(self):
        """Test device scanning functionality"""
        # Mock ping and ARP operations
        with patch('subprocess.run') as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = b'192.168.1.100'
            
            devices = self.scanner.scan_devices()
            self.assertIsInstance(devices, list)

if __name__ == '__main__':
    unittest.main() 