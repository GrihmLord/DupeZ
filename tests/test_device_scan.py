#!/usr/bin/env python3
"""
Device Scanning Tests for PulseDrop Pro
Tests network device detection and scanning functionality
"""

import unittest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.network.enhanced_scanner import EnhancedNetworkScanner
from app.network.device_scan import DeviceScanner
from app.logs.logger import log_info, log_error

class TestDeviceScan(unittest.TestCase):
    """Test device scanning functionality"""
    
    def setUp(self):
        """Setup test environment"""
        self.scanner = EnhancedNetworkScanner(max_threads=10, timeout=2)
        self.device_scanner = DeviceScanner()
    
    def test_scanner_initialization(self):
        """Test scanner initializes correctly"""
        self.assertIsNotNone(self.scanner)
        self.assertIsNotNone(self.device_scanner)
        self.assertEqual(self.scanner.max_threads, 10)
        self.assertEqual(self.scanner.timeout, 2)
    
    def test_arp_table_scan(self):
        """Test ARP table scanning"""
        try:
            devices = self.scanner._scan_arp_table()
            self.assertIsInstance(devices, list)
            log_info(f"ARP table scan found {len(devices)} devices")
            
            # Check device structure
            if devices:
                device = devices[0]
                required_keys = ['ip', 'mac', 'hostname', 'vendor', 'device_type', 'is_ps5']
                for key in required_keys:
                    self.assertIn(key, device)
        except Exception as e:
            log_error(f"ARP table scan test failed: {e}", exception=e)
            self.fail(f"ARP table scan failed: {e}")
    
    def test_network_scan(self):
        """Test full network scanning"""
        try:
            devices = self.scanner.scan_network("192.168.1.0/24", quick_scan=True)
            self.assertIsInstance(devices, list)
            log_info(f"Network scan found {len(devices)} devices")
            
            # Should find some devices
            self.assertGreater(len(devices), 0)
        except Exception as e:
            log_error(f"Network scan test failed: {e}", exception=e)
            self.fail(f"Network scan failed: {e}")
    
    def test_ps5_detection(self):
        """Test PS5 device detection"""
        try:
            # Create test device info
            test_device = {
                'ip': '192.168.1.141',
                'mac': 'b4-0a-d8-b9-bd-b0',
                'hostname': 'PS5-B9BDB0.attlocal.net',
                'vendor': 'Sony Interactive Entertainment',
                'device_type': 'Unknown',
                'is_ps5': False
            }
            
            # Test PS5 detection
            is_ps5 = self.scanner._is_ps5_device(test_device)
            self.assertTrue(is_ps5)
            log_info("PS5 detection test passed")
        except Exception as e:
            log_error(f"PS5 detection test failed: {e}", exception=e)
            self.fail(f"PS5 detection failed: {e}")
    
    def test_device_type_detection(self):
        """Test device type determination"""
        try:
            # Test PS5 device
            ps5_device = {
                'ip': '192.168.1.141',
                'mac': 'b4-0a-d8-b9-bd-b0',
                'hostname': 'PS5-B9BDB0.attlocal.net',
                'vendor': 'Sony Interactive Entertainment',
                'is_ps5': True
            }
            
            device_type = self.scanner._determine_device_type(ps5_device)
            self.assertEqual(device_type, "PlayStation 5")
            
            # Test router device
            router_device = {
                'ip': '192.168.1.1',
                'mac': '00:11:22:33:44:55',
                'hostname': 'router.local',
                'vendor': 'Unknown',
                'is_ps5': False
            }
            
            router_type = self.scanner._determine_device_type(router_device)
            self.assertEqual(router_type, "Router/Gateway")
            
            log_info("Device type detection test passed")
        except Exception as e:
            log_error(f"Device type detection test failed: {e}", exception=e)
            self.fail(f"Device type detection failed: {e}")
    
    def test_vendor_detection(self):
        """Test vendor information detection"""
        try:
            # Test Sony MAC
            sony_mac = "b4-0a-d8-b9-bd-b0"
            vendor = self.scanner._get_vendor_info(sony_mac)
            self.assertEqual(vendor, "Sony Interactive Entertainment")
            
            # Test unknown MAC
            unknown_mac = "00:11:22:33:44:55"
            unknown_vendor = self.scanner._get_vendor_info(unknown_mac)
            self.assertEqual(unknown_vendor, "Unknown")
            
            log_info("Vendor detection test passed")
        except Exception as e:
            log_error(f"Vendor detection test failed: {e}", exception=e)
            self.fail(f"Vendor detection failed: {e}")
    
    def test_ping_host(self):
        """Test ping functionality"""
        try:
            # Test localhost
            result = self.scanner._ping_host("127.0.0.1")
            self.assertTrue(result)
            
            # Test invalid IP
            invalid_result = self.scanner._ping_host("999.999.999.999")
            self.assertFalse(invalid_result)
            
            log_info("Ping test passed")
        except Exception as e:
            log_error(f"Ping test failed: {e}", exception=e)
            self.fail(f"Ping test failed: {e}")
    
    def test_port_scan(self):
        """Test port scanning functionality"""
        try:
            # Test localhost
            result = self.scanner._quick_port_scan("127.0.0.1")
            # Should find some open ports on localhost
            self.assertTrue(result)
            
            log_info("Port scan test passed")
        except Exception as e:
            log_error(f"Port scan test failed: {e}", exception=e)
            self.fail(f"Port scan test failed: {e}")
    
    def test_dns_resolution(self):
        """Test DNS resolution functionality"""
        try:
            # Test localhost
            result = self.scanner._check_dns_resolution("127.0.0.1")
            # localhost should resolve
            self.assertTrue(result)
            
            log_info("DNS resolution test passed")
        except Exception as e:
            log_error(f"DNS resolution test failed: {e}", exception=e)
            self.fail(f"DNS resolution test failed: {e}")
    
    def test_scan_statistics(self):
        """Test scan statistics functionality"""
        try:
            stats = self.scanner.get_scan_stats()
            required_keys = ['total_devices', 'ps5_devices', 'local_devices', 'last_scan_time', 'scan_in_progress']
            
            for key in required_keys:
                self.assertIn(key, stats)
            
            log_info("Scan statistics test passed")
        except Exception as e:
            log_error(f"Scan statistics test failed: {e}", exception=e)
            self.fail(f"Scan statistics test failed: {e}")
    
    def test_device_by_ip(self):
        """Test getting device by IP"""
        try:
            # First scan to populate results
            self.scanner.scan_network("192.168.1.0/24", quick_scan=True)
            
            # Test getting device by IP
            device = self.scanner.get_device_by_ip("192.168.1.1")
            # Should find router
            if device:
                self.assertEqual(device['ip'], "192.168.1.1")
            
            log_info("Device by IP test passed")
        except Exception as e:
            log_error(f"Device by IP test failed: {e}", exception=e)
            self.fail(f"Device by IP test failed: {e}")

if __name__ == "__main__":
    unittest.main()
