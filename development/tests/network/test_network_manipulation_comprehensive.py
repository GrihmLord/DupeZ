#!/usr/bin/env python3
"""
Comprehensive Network Manipulation Test
Tests all network manipulation features to ensure they are fully functional
"""

import sys
import os
import time
import subprocess
import threading
from typing import Dict, List, Optional

# Add the app directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from app.firewall.network_disruptor import NetworkDisruptor
from app.firewall.internet_dropper import InternetDropper
from app.firewall.ps5_blocker import PS5Blocker
from app.network.network_manipulator import NetworkManipulator
from app.logs.logger import log_info, log_error

class NetworkManipulationTester:
    """Comprehensive tester for all network manipulation features"""
    
    def __init__(self):
        self.test_results = {}
        self.test_device_ip = "192.168.1.100"  # Test device IP
        self.ps5_test_ip = "192.168.137.224"   # Test PS5 IP
        
    def run_all_tests(self) -> Dict[str, bool]:
        """Run all network manipulation tests"""
        print("🔧 Starting Comprehensive Network Manipulation Tests...")
        print("=" * 60)
        
        # Test 1: Network Disruptor
        print("\n📡 Testing Network Disruptor...")
        self.test_results['network_disruptor'] = self.test_network_disruptor()
        
        # Test 2: Internet Dropper
        print("\n🌐 Testing Internet Dropper...")
        self.test_results['internet_dropper'] = self.test_internet_dropper()
        
        # Test 3: PS5 Blocker
        print("\n🎮 Testing PS5 Blocker...")
        self.test_results['ps5_blocker'] = self.test_ps5_blocker()
        
        # Test 4: Network Manipulator
        print("\n🔧 Testing Network Manipulator...")
        self.test_results['network_manipulator'] = self.test_network_manipulator()
        
        # Test 5: Integration Tests
        print("\n🔗 Testing Integration...")
        self.test_results['integration'] = self.test_integration()
        
        # Print results
        self.print_results()
        
        return self.test_results
    
    def test_network_disruptor(self) -> bool:
        """Test Network Disruptor functionality"""
        try:
            print("  - Initializing Network Disruptor...")
            disruptor = NetworkDisruptor()
            
            # Test initialization
            if not disruptor.initialize():
                print("  ❌ Network Disruptor initialization failed")
                return False
            print("  ✅ Network Disruptor initialized successfully")
            
            # Test device disconnection
            print("  - Testing device disconnection...")
            if disruptor.disconnect_device(self.test_device_ip, methods=['arp_spoof']):
                print("  ✅ Device disconnection successful")
                
                # Wait a moment
                time.sleep(2)
                
                # Test reconnection
                print("  - Testing device reconnection...")
                if disruptor.reconnect_device(self.test_device_ip):
                    print("  ✅ Device reconnection successful")
                else:
                    print("  ❌ Device reconnection failed")
                    return False
            else:
                print("  ❌ Device disconnection failed")
                return False
            
            # Test multiple methods
            print("  - Testing multiple disruption methods...")
            methods = ['arp_spoof', 'packet_drop', 'blackhole_route']
            if disruptor.disconnect_device(self.test_device_ip, methods=methods):
                print("  ✅ Multiple methods successful")
                
                # Clean up
                disruptor.reconnect_device(self.test_device_ip)
            else:
                print("  ❌ Multiple methods failed")
                return False
            
            print("  ✅ Network Disruptor tests passed")
            return True
            
        except Exception as e:
            print(f"  ❌ Network Disruptor test failed: {e}")
            return False
    
    def test_internet_dropper(self) -> bool:
        """Test Internet Dropper functionality"""
        try:
            print("  - Initializing Internet Dropper...")
            dropper = InternetDropper()
            
            # Test internet drop
            print("  - Testing internet drop...")
            if dropper.drop_internet():
                print("  ✅ Internet dropped successfully")
                
                # Test status
                if dropper.is_internet_dropped():
                    print("  ✅ Internet drop status confirmed")
                else:
                    print("  ❌ Internet drop status incorrect")
                    return False
                
                # Wait a moment
                time.sleep(2)
                
                # Test internet restore
                print("  - Testing internet restore...")
                if dropper.restore_internet():
                    print("  ✅ Internet restored successfully")
                else:
                    print("  ❌ Internet restore failed")
                    return False
            else:
                print("  ❌ Internet drop failed")
                return False
            
            # Test toggle functionality
            print("  - Testing toggle functionality...")
            if dropper.toggle_internet():
                print("  ✅ Toggle to drop successful")
                if dropper.toggle_internet():
                    print("  ✅ Toggle to restore successful")
                else:
                    print("  ❌ Toggle to restore failed")
                    return False
            else:
                print("  ❌ Toggle to drop failed")
                return False
            
            print("  ✅ Internet Dropper tests passed")
            return True
            
        except Exception as e:
            print(f"  ❌ Internet Dropper test failed: {e}")
            return False
    
    def test_ps5_blocker(self) -> bool:
        """Test PS5 Blocker functionality"""
        try:
            print("  - Initializing PS5 Blocker...")
            blocker = PS5Blocker()
            
            # Test PS5 blocking
            print("  - Testing PS5 blocking...")
            if blocker.block_ps5(self.ps5_test_ip):
                print("  ✅ PS5 blocked successfully")
                
                # Test blocked status
                if blocker.is_ps5_blocked(self.ps5_test_ip):
                    print("  ✅ PS5 block status confirmed")
                else:
                    print("  ❌ PS5 block status incorrect")
                    return False
                
                # Wait a moment
                time.sleep(2)
                
                # Test PS5 unblocking
                print("  - Testing PS5 unblocking...")
                if blocker.unblock_ps5(self.ps5_test_ip):
                    print("  ✅ PS5 unblocked successfully")
                else:
                    print("  ❌ PS5 unblocking failed")
                    return False
            else:
                print("  ❌ PS5 blocking failed")
                return False
            
            # Test multiple PS5s
            print("  - Testing multiple PS5 blocking...")
            ps5_ips = [self.ps5_test_ip, "192.168.1.141"]
            results = blocker.block_all_ps5s(ps5_ips)
            if all(results.values()):
                print("  ✅ Multiple PS5 blocking successful")
                
                # Clean up
                blocker.unblock_all_ps5s(ps5_ips)
            else:
                print("  ❌ Multiple PS5 blocking failed")
                return False
            
            print("  ✅ PS5 Blocker tests passed")
            return True
            
        except Exception as e:
            print(f"  ❌ PS5 Blocker test failed: {e}")
            return False
    
    def test_network_manipulator(self) -> bool:
        """Test Network Manipulator functionality"""
        try:
            print("  - Initializing Network Manipulator...")
            manipulator = NetworkManipulator()
            
            # Test IP blocking
            print("  - Testing IP blocking...")
            if manipulator.block_ip(self.test_device_ip):
                print("  ✅ IP blocking successful")
                
                # Test unblocking
                if manipulator.unblock_ip(self.test_device_ip):
                    print("  ✅ IP unblocking successful")
                else:
                    print("  ❌ IP unblocking failed")
                    return False
            else:
                print("  ❌ IP blocking failed")
                return False
            
            # Test traffic throttling
            print("  - Testing traffic throttling...")
            if manipulator.throttle_connection(self.test_device_ip, bandwidth_mbps=1.0, latency_ms=100):
                print("  ✅ Traffic throttling successful")
                
                # Get active rules
                rules = manipulator.get_active_rules()
                if rules:
                    print(f"  ✅ Active rules found: {len(rules)}")
                else:
                    print("  ❌ No active rules found")
                    return False
                
                # Clear all rules
                if manipulator.clear_all_rules():
                    print("  ✅ All rules cleared successfully")
                else:
                    print("  ❌ Failed to clear all rules")
                    return False
            else:
                print("  ❌ Traffic throttling failed")
                return False
            
            print("  ✅ Network Manipulator tests passed")
            return True
            
        except Exception as e:
            print(f"  ❌ Network Manipulator test failed: {e}")
            return False
    
    def test_integration(self) -> bool:
        """Test integration between components"""
        try:
            print("  - Testing component integration...")
            
            # Test PS5 blocking with network disruptor
            print("  - Testing PS5 blocking with network disruptor...")
            disruptor = NetworkDisruptor()
            blocker = PS5Blocker()
            
            if disruptor.initialize():
                # Block PS5
                if blocker.block_ps5(self.ps5_test_ip):
                    print("  ✅ PS5 blocking integration successful")
                    
                    # Also disconnect with disruptor
                    if disruptor.disconnect_device(self.ps5_test_ip):
                        print("  ✅ PS5 disruption integration successful")
                        
                        # Clean up
                        disruptor.reconnect_device(self.ps5_test_ip)
                        blocker.unblock_ps5(self.ps5_test_ip)
                    else:
                        print("  ❌ PS5 disruption integration failed")
                        return False
                else:
                    print("  ❌ PS5 blocking integration failed")
                    return False
            else:
                print("  ❌ Network disruptor initialization failed")
                return False
            
            # Test internet drop with network manipulator
            print("  - Testing internet drop with network manipulator...")
            dropper = InternetDropper()
            manipulator = NetworkManipulator()
            
            if dropper.drop_internet():
                # Try to block some IPs while internet is dropped
                if manipulator.block_ip("8.8.8.8"):
                    print("  ✅ Internet drop with network manipulator successful")
                    
                    # Clean up
                    manipulator.unblock_ip("8.8.8.8")
                    dropper.restore_internet()
                else:
                    print("  ❌ Internet drop with network manipulator failed")
                    dropper.restore_internet()
                    return False
            else:
                print("  ❌ Internet drop integration failed")
                return False
            
            print("  ✅ Integration tests passed")
            return True
            
        except Exception as e:
            print(f"  ❌ Integration test failed: {e}")
            return False
    
    def print_results(self):
        """Print test results summary"""
        print("\n" + "=" * 60)
        print("📊 NETWORK MANIPULATION TEST RESULTS")
        print("=" * 60)
        
        passed = 0
        total = len(self.test_results)
        
        for test_name, result in self.test_results.items():
            status = "✅ PASS" if result else "❌ FAIL"
            print(f"{test_name.replace('_', ' ').title():<25} {status}")
            if result:
                passed += 1
        
        print("-" * 60)
        print(f"Overall: {passed}/{total} tests passed")
        
        if passed == total:
            print("🎉 ALL NETWORK MANIPULATION FEATURES ARE FULLY FUNCTIONAL!")
        else:
            print("⚠️  Some network manipulation features need attention")
        
        print("=" * 60)

def main():
    """Main test runner"""
    tester = NetworkManipulationTester()
    results = tester.run_all_tests()
    
    # Return exit code based on results
    if all(results.values()):
        print("\n✅ All network manipulation features are fully functional!")
        return 0
    else:
        print("\n❌ Some network manipulation features need fixing!")
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code) 