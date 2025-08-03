#!/usr/bin/env python3
"""
Network Functionality Tests
Testing network scanning, device detection, and network operations
"""

import sys
import os
import unittest
from unittest.mock import Mock, patch, MagicMock
import socket
import subprocess

# Add the app directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'app'))

from network.device_scan import DeviceScanner
from network.enhanced_scanner import EnhancedScanner
from network.mdns_discovery import MDNSDiscovery
from network.network_manipulator import NetworkManipulator
from firewall.ps5_blocker import PS5Blocker
from firewall.internet_dropper import InternetDropper
from firewall.blocker import NetworkBlocker

class TestDeviceScanner(unittest.TestCase):
    """Test device scanner functionality"""
    
    def setUp(self):
        """Set up test environment"""
        self.scanner = DeviceScanner()
    
    def test_scanner_initialization(self):
        """Test scanner initialization"""
        self.assertIsNotNone(self.scanner)
        self.assertIsInstance(self.scanner.interfaces, list)
    
    def test_interface_discovery(self):
        """Test network interface discovery"""
        # Mock socket operations
        with patch('socket.socket') as mock_socket:
            mock_socket.return_value.getsockname.return_value = ('192.168.1.100', 0)
            
            interfaces = self.scanner.discover_interfaces()
            self.assertIsInstance(interfaces, list)
    
    def test_device_scanning(self):
        """Test device scanning functionality"""
        # Mock subprocess calls for ping
        with patch('subprocess.run') as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = b'192.168.1.100'
            
            # Mock ARP table
            mock_run.return_value.stdout = b'192.168.1.100 00:11:22:33:44:55 dynamic'
            
            devices = self.scanner.scan_devices()
            self.assertIsInstance(devices, list)
    
    def test_device_validation(self):
        """Test device data validation"""
        # Test valid device data
        valid_device = {
            'ip': '192.168.1.100',
            'mac': '00:11:22:33:44:55',
            'hostname': 'TestDevice',
            'vendor': 'Test Vendor',
            'device_type': 'Computer',
            'interface': 'WiFi',
            'open_ports': '80,443',
            'status': 'Online',
            'blocked': False
        }
        
        result = self.scanner.validate_device(valid_device)
        self.assertTrue(result)
        
        # Test invalid device data
        invalid_device = {
            'ip': 'invalid_ip',
            'mac': 'invalid_mac',
            'hostname': '',
            'vendor': '',
            'device_type': '',
            'interface': '',
            'open_ports': '',
            'status': '',
            'blocked': None
        }
        
        result = self.scanner.validate_device(invalid_device)
        self.assertFalse(result)
    
    def test_network_range_generation(self):
        """Test network range generation"""
        # Test with common network ranges
        test_cases = [
            ('192.168.1.1', '192.168.1.254'),
            ('10.0.0.1', '10.0.0.254'),
            ('172.16.0.1', '172.16.0.254')
        ]
        
        for start_ip, end_ip in test_cases:
            range_ips = self.scanner.generate_ip_range(start_ip, end_ip)
            self.assertIsInstance(range_ips, list)
            self.assertGreater(len(range_ips), 0)

class TestEnhancedScanner(unittest.TestCase):
    """Test enhanced scanner functionality"""
    
    def setUp(self):
        """Set up test environment"""
        self.scanner = EnhancedScanner()
    
    def test_enhanced_scanner_initialization(self):
        """Test enhanced scanner initialization"""
        self.assertIsNotNone(self.scanner)
        self.assertIsInstance(self.scanner.scan_methods, list)
    
    def test_multiple_scan_methods(self):
        """Test multiple scanning methods"""
        # Mock different scan methods
        with patch('subprocess.run') as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = b'192.168.1.100'
            
            # Test ping scan
            devices = self.scanner.ping_scan(['192.168.1.100'])
            self.assertIsInstance(devices, list)
            
            # Test ARP scan
            devices = self.scanner.arp_scan(['192.168.1.100'])
            self.assertIsInstance(devices, list)
            
            # Test TCP connect scan
            devices = self.scanner.tcp_connect_scan(['192.168.1.100'])
            self.assertIsInstance(devices, list)
    
    def test_scan_method_selection(self):
        """Test scan method selection based on network conditions"""
        # Test automatic method selection
        methods = self.scanner.select_scan_methods()
        self.assertIsInstance(methods, list)
        self.assertGreater(len(methods), 0)
    
    def test_parallel_scanning(self):
        """Test parallel scanning functionality"""
        # Mock threading and subprocess
        with patch('threading.Thread') as mock_thread:
            with patch('subprocess.run') as mock_run:
                mock_run.return_value.returncode = 0
                mock_run.return_value.stdout = b'192.168.1.100'
                
                devices = self.scanner.parallel_scan(['192.168.1.100'])
                self.assertIsInstance(devices, list)

class TestMDNSDiscovery(unittest.TestCase):
    """Test mDNS discovery functionality"""
    
    def setUp(self):
        """Set up test environment"""
        self.discovery = MDNSDiscovery()
    
    def test_mdns_discovery_initialization(self):
        """Test mDNS discovery initialization"""
        self.assertIsNotNone(self.discovery)
    
    def test_service_discovery(self):
        """Test service discovery functionality"""
        # Mock mDNS queries
        with patch('socket.socket') as mock_socket:
            mock_socket.return_value.recv.return_value = b'mock_mdns_response'
            
            services = self.discovery.discover_services()
            self.assertIsInstance(services, list)
    
    def test_device_identification(self):
        """Test device identification via mDNS"""
        # Mock device responses
        mock_responses = [
            b'PS5-Device.local',
            b'iPhone.local',
            b'Laptop.local'
        ]
        
        with patch('socket.socket') as mock_socket:
            mock_socket.return_value.recv.side_effect = mock_responses
            
            devices = self.discovery.identify_devices()
            self.assertIsInstance(devices, list)

class TestNetworkManipulator(unittest.TestCase):
    """Test network manipulator functionality"""
    
    def setUp(self):
        """Set up test environment"""
        self.manipulator = NetworkManipulator()
    
    def test_network_manipulator_initialization(self):
        """Test network manipulator initialization"""
        self.assertIsNotNone(self.manipulator)
    
    def test_traffic_analysis(self):
        """Test traffic analysis functionality"""
        # Mock network traffic data
        traffic_data = [
            {'ip': '192.168.1.100', 'bytes_sent': 1000, 'bytes_received': 500},
            {'ip': '192.168.1.101', 'bytes_sent': 5000, 'bytes_received': 2000}
        ]
        
        analysis = self.manipulator.analyze_traffic(traffic_data)
        self.assertIsInstance(analysis, dict)
        self.assertIn('total_traffic', analysis)
        self.assertIn('suspicious_devices', analysis)
    
    def test_bandwidth_control(self):
        """Test bandwidth control functionality"""
        # Mock bandwidth control operations
        with patch('subprocess.run') as mock_run:
            mock_run.return_value.returncode = 0
            
            # Test bandwidth limiting
            result = self.manipulator.limit_bandwidth('192.168.1.100', 1000)
            self.assertTrue(result)
            
            # Test bandwidth restoration
            result = self.manipulator.restore_bandwidth('192.168.1.100')
            self.assertTrue(result)

class TestPS5Blocker(unittest.TestCase):
    """Test PS5 blocker functionality"""
    
    def setUp(self):
        """Set up test environment"""
        self.blocker = PS5Blocker()
    
    def test_ps5_detection_methods(self):
        """Test PS5 detection methods"""
        # Test MAC address detection
        sony_macs = [
            '00:50:c2:11:22:33',
            '00:1f:a7:44:55:66',
            '00:19:c5:77:88:99'
        ]
        
        for mac in sony_macs:
            device = {'mac': mac}
            result = self.blocker._is_ps5_device(device)
            self.assertTrue(result)
        
        # Test hostname detection
        ps5_hostnames = [
            'PS5-Device',
            'PlayStation5',
            'PS5-123456'
        ]
        
        for hostname in ps5_hostnames:
            device = {'hostname': hostname}
            result = self.blocker._is_ps5_device(device)
            self.assertTrue(result)
    
    def test_blocking_methods(self):
        """Test PS5 blocking methods"""
        # Mock subprocess calls
        with patch('subprocess.run') as mock_run:
            mock_run.return_value.returncode = 0
            
            # Test firewall blocking
            result = self.blocker._add_firewall_block('192.168.1.100')
            self.assertTrue(result)
            
            # Test hosts file blocking
            result = self.blocker._add_to_hosts('192.168.1.100')
            self.assertTrue(result)
            
            # Test route table blocking
            result = self.blocker._add_route_block('192.168.1.100')
            self.assertTrue(result)
    
    def test_unblocking_methods(self):
        """Test PS5 unblocking methods"""
        # Mock subprocess calls
        with patch('subprocess.run') as mock_run:
            mock_run.return_value.returncode = 0
            
            # Test firewall unblocking
            result = self.blocker._remove_firewall_block('192.168.1.100')
            self.assertTrue(result)
            
            # Test hosts file unblocking
            result = self.blocker._remove_from_hosts('192.168.1.100')
            self.assertTrue(result)
            
            # Test route table unblocking
            result = self.blocker._remove_route_block('192.168.1.100')
            self.assertTrue(result)

class TestInternetDropper(unittest.TestCase):
    """Test internet dropper functionality"""
    
    def setUp(self):
        """Set up test environment"""
        self.dropper = InternetDropper()
    
    def test_internet_drop_methods(self):
        """Test internet drop methods"""
        # Mock subprocess calls
        with patch('subprocess.run') as mock_run:
            mock_run.return_value.returncode = 0
            
            # Test outbound traffic blocking
            result = self.dropper._block_outbound_traffic()
            self.assertTrue(result)
            
            # Test DNS server blocking
            result = self.dropper._block_dns_servers()
            self.assertTrue(result)
            
            # Test internet port blocking
            result = self.dropper._block_internet_ports()
            self.assertTrue(result)
            
            # Test blackhole route addition
            result = self.dropper._add_blackhole_route()
            self.assertTrue(result)
    
    def test_internet_restore_methods(self):
        """Test internet restore methods"""
        # Mock subprocess calls
        with patch('subprocess.run') as mock_run:
            mock_run.return_value.returncode = 0
            
            # Test blackhole route removal
            result = self.dropper._remove_blackhole_route()
            self.assertTrue(result)
            
            # Test internet block removal
            result = self.dropper._remove_internet_blocks()
            self.assertTrue(result)
            
            # Test original routes restoration
            result = self.dropper._restore_original_routes()
            self.assertTrue(result)
            
            # Test original DNS restoration
            result = self.dropper._restore_original_dns()
            self.assertTrue(result)

class TestNetworkBlocker(unittest.TestCase):
    """Test network blocker functionality"""
    
    def setUp(self):
        """Set up test environment"""
        self.blocker = NetworkBlocker()
    
    def test_general_blocking(self):
        """Test general network blocking functionality"""
        # Mock subprocess calls
        with patch('subprocess.run') as mock_run:
            mock_run.return_value.returncode = 0
            
            # Test device blocking
            result = self.blocker.block_device('192.168.1.100')
            self.assertTrue(result)
            
            # Test device unblocking
            result = self.blocker.unblock_device('192.168.1.100')
            self.assertTrue(result)
    
    def test_bulk_operations(self):
        """Test bulk blocking operations"""
        test_ips = ['192.168.1.100', '192.168.1.101', '192.168.1.102']
        
        # Mock subprocess calls
        with patch('subprocess.run') as mock_run:
            mock_run.return_value.returncode = 0
            
            # Test bulk blocking
            results = self.blocker.block_multiple_devices(test_ips)
            self.assertIsInstance(results, dict)
            self.assertEqual(len(results), len(test_ips))
            
            # Test bulk unblocking
            results = self.blocker.unblock_multiple_devices(test_ips)
            self.assertIsInstance(results, dict)
            self.assertEqual(len(results), len(test_ips))

if __name__ == '__main__':
    unittest.main() 