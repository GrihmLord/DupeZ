#!/usr/bin/env python3
"""
Firewall Tests for DupeZ
Tests firewall blocking and unblocking functionality
"""

import unittest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.firewall.netcut_blocker import NetCutBlocker
from app.firewall.network_disruptor import NetworkDisruptor
from app.firewall.blocker import NetworkBlocker
from app.logs.logger import log_info, log_error

class TestFirewall(unittest.TestCase):
    """Test firewall functionality"""
    
    def setUp(self):
        """Setup test environment"""
        self.blocker = NetworkBlocker()
        self.netcut = NetCutBlocker()
        self.disruptor = NetworkDisruptor()
    
    def test_firewall_initialization(self):
        """Test firewall components initialize correctly"""
        self.assertIsNotNone(self.blocker)
        self.assertIsNotNone(self.netcut)
        self.assertIsNotNone(self.disruptor)
    
    def test_block_device_by_ip(self):
        """Test blocking a device by IP address"""
        test_ip = "192.168.1.100"
        try:
            result = self.blocker.block_device(test_ip)
            self.assertTrue(result)
            log_info(f"Successfully blocked device: {test_ip}")
        except Exception as e:
            log_error(f"Failed to block device: {test_ip}", exception=e)
            self.fail(f"Blocking failed: {e}")
    
    def test_unblock_device_by_ip(self):
        """Test unblocking a device by IP address"""
        test_ip = "192.168.1.100"
        try:
            result = self.blocker.unblock_device(test_ip)
            self.assertTrue(result)
            log_info(f"Successfully unblocked device: {test_ip}")
        except Exception as e:
            log_error(f"Failed to unblock device: {test_ip}", exception=e)
            self.fail(f"Unblocking failed: {e}")
    
    def test_block_device_by_mac(self):
        """Test blocking a device by MAC address"""
        test_mac = "00:11:22:33:44:55"
        try:
            result = self.blocker.block_device_by_mac(test_mac)
            self.assertTrue(result)
            log_info(f"Successfully blocked device by MAC: {test_mac}")
        except Exception as e:
            log_error(f"Failed to block device by MAC: {test_mac}", exception=e)
            self.fail(f"MAC blocking failed: {e}")
    
    def test_netcut_functionality(self):
        """Test NetCut blocking functionality"""
        test_ip = "192.168.1.100"
        try:
            # Test ARP poisoning
            result = self.netcut.start_arp_poisoning(test_ip)
            self.assertTrue(result)
            log_info(f"NetCut ARP poisoning started for: {test_ip}")
            
            # Test stopping
            stop_result = self.netcut.stop_arp_poisoning()
            self.assertTrue(stop_result)
            log_info("NetCut ARP poisoning stopped")
        except Exception as e:
            log_error(f"NetCut test failed: {e}", exception=e)
            self.fail(f"NetCut functionality failed: {e}")
    
    def test_network_disruption(self):
        """Test network disruption functionality"""
        test_ip = "192.168.1.100"
        try:
            # Test traffic disruption
            result = self.disruptor.disrupt_traffic(test_ip)
            self.assertTrue(result)
            log_info(f"Traffic disruption started for: {test_ip}")
            
            # Test restoration
            restore_result = self.disruptor.restore_traffic(test_ip)
            self.assertTrue(restore_result)
            log_info(f"Traffic restored for: {test_ip}")
        except Exception as e:
            log_error(f"Network disruption test failed: {e}", exception=e)
            self.fail(f"Network disruption failed: {e}")
    
    def test_firewall_rules(self):
        """Test firewall rule management"""
        try:
            # Test adding firewall rule
            rule_name = "TestBlockRule"
            target_ip = "192.168.1.100"
            result = self.blocker.add_firewall_rule(rule_name, target_ip)
            self.assertTrue(result)
            log_info(f"Firewall rule added: {rule_name}")
            
            # Test removing firewall rule
            remove_result = self.blocker.remove_firewall_rule(rule_name)
            self.assertTrue(remove_result)
            log_info(f"Firewall rule removed: {rule_name}")
        except Exception as e:
            log_error(f"Firewall rule test failed: {e}", exception=e)
            self.fail(f"Firewall rule management failed: {e}")
    
    def test_ps5_specific_blocking(self):
        """Test PS5-specific blocking functionality"""
        ps5_ip = "192.168.1.141"  # Your detected PS5
        try:
            # Test PS5 blocking
            result = self.blocker.block_ps5(ps5_ip)
            self.assertTrue(result)
            log_info(f"PS5 blocked: {ps5_ip}")
            
            # Test PS5 unblocking
            unblock_result = self.blocker.unblock_ps5(ps5_ip)
            self.assertTrue(unblock_result)
            log_info(f"PS5 unblocked: {ps5_ip}")
        except Exception as e:
            log_error(f"PS5 blocking test failed: {e}", exception=e)
            self.fail(f"PS5 blocking failed: {e}")

if __name__ == "__main__":
    unittest.main()
