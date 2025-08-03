#!/usr/bin/env python3
"""
Comprehensive Test Suite for PulseDrop Pro
Consolidates all testing functionality into one organized test sequence
"""

import sys
import os
import time
import subprocess
import socket
import threading
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import all necessary modules
try:
    from app.firewall.blocker import block_device, unblock_device, is_ip_blocked, clear_all_blocks, get_blocked_ips
    from app.firewall.netcut_blocker import netcut_blocker
    from app.ps5.ps5_network_tool import ps5_network_tool
    from app.logs.logger import log_info, log_error
    IMPORTS_SUCCESS = True
except ImportError as e:
    print(f"❌ Import error: {e}")
    IMPORTS_SUCCESS = False

@dataclass
class TestResult:
    """Test result data structure"""
    name: str
    success: bool
    message: str
    duration: float
    details: Optional[Dict] = None

class ComprehensiveTester:
    """Comprehensive test suite for PulseDrop Pro"""
    
    def __init__(self):
        self.results: List[TestResult] = []
        self.test_ips = ["192.168.1.100", "192.168.1.150", "192.168.137.165"]  # PS5 IP
        self.start_time = time.time()
        
    def run_test(self, name: str, test_func, *args, **kwargs) -> TestResult:
        """Run a single test and record results"""
        print(f"\n🧪 Running: {name}")
        start_time = time.time()
        
        try:
            result = test_func(*args, **kwargs)
            duration = time.time() - start_time
            
            if result:
                print(f"✅ {name} - PASSED ({duration:.2f}s)")
                return TestResult(name, True, "Test passed", duration)
            else:
                print(f"❌ {name} - FAILED ({duration:.2f}s)")
                return TestResult(name, False, "Test failed", duration)
                
        except Exception as e:
            duration = time.time() - start_time
            print(f"❌ {name} - ERROR ({duration:.2f}s): {e}")
            return TestResult(name, False, f"Test error: {e}", duration)
    
    def test_imports(self) -> bool:
        """Test that all required modules can be imported"""
        if not IMPORTS_SUCCESS:
            return False
        
        required_modules = [
            'app.firewall.blocker',
            'app.firewall.netcut_blocker', 
            'app.ps5.ps5_network_tool',
            'app.logs.logger'
        ]
        
        for module in required_modules:
            try:
                __import__(module)
            except ImportError:
                return False
        
        return True
    
    def test_network_connectivity(self) -> bool:
        """Test basic network connectivity"""
        try:
            # Test local connectivity
            socket.create_connection(("8.8.8.8", 53), timeout=5)
            return True
        except:
            return False
    
    def test_ps5_connectivity(self) -> bool:
        """Test PS5 connectivity"""
        ps5_ip = "192.168.137.165"
        try:
            # Quick ping test
            result = subprocess.run(
                ["ping", "-n", "1", ps5_ip], 
                capture_output=True, 
                timeout=10
            )
            return result.returncode == 0
        except:
            return False
    
    def test_blocking_system(self) -> bool:
        """Test core blocking functionality"""
        try:
            test_ip = "192.168.1.100"
            
            # Test blocking
            block_result = block_device(test_ip)
            if not block_result:
                return False
            
            # Test blocked status
            if not is_ip_blocked(test_ip):
                return False
            
            # Test unblocking
            unblock_result = unblock_device(test_ip)
            if not unblock_result:
                return False
            
            # Test unblocked status
            if is_ip_blocked(test_ip):
                return False
            
            return True
        except Exception as e:
            log_error(f"Blocking test error: {e}")
            return False
    
    def test_netcut_blocker(self) -> bool:
        """Test NetCut-style blocking"""
        try:
            test_ip = "192.168.1.150"
            
            # Test NetCut blocking
            block_result = netcut_blocker.block_device(test_ip)
            if not block_result:
                return False
            
            # Test NetCut unblocking
            unblock_result = netcut_blocker.unblock_device(test_ip)
            if not unblock_result:
                return False
            
            return True
        except Exception as e:
            log_error(f"NetCut test error: {e}")
            return False
    
    def test_ps5_network_tool(self) -> bool:
        """Test PS5 network tool functionality"""
        try:
            # Test initialization
            if not hasattr(ps5_network_tool, 'ps5_devices'):
                return False
            
            # Test scanning
            devices = ps5_network_tool.scan_for_ps5_devices()
            if not isinstance(devices, list):
                return False
            
            # Test monitoring start/stop
            ps5_network_tool.start_monitoring()
            time.sleep(1)
            ps5_network_tool.stop_monitoring()
            
            return True
        except Exception as e:
            log_error(f"PS5 tool test error: {e}")
            return False
    
    def test_ps5_specific_blocking(self) -> bool:
        """Test PS5-specific blocking"""
        try:
            ps5_ip = "192.168.137.165"
            
            # Test PS5 blocking
            block_result = ps5_network_tool.block_ps5_device(ps5_ip)
            if not block_result:
                return False
            
            # Test PS5 unblocking
            unblock_result = ps5_network_tool.unblock_ps5_device(ps5_ip)
            if not unblock_result:
                return False
            
            return True
        except Exception as e:
            log_error(f"PS5 blocking test error: {e}")
            return False
    
    def test_mass_blocking(self) -> bool:
        """Test mass blocking/unblocking"""
        try:
            # Test mass blocking
            block_results = ps5_network_tool.block_all_ps5_devices()
            if not isinstance(block_results, dict):
                return False
            
            # Test mass unblocking
            unblock_results = ps5_network_tool.unblock_all_ps5_devices()
            if not isinstance(unblock_results, dict):
                return False
            
            return True
        except Exception as e:
            log_error(f"Mass blocking test error: {e}")
            return False
    
    def test_clear_all_blocks(self) -> bool:
        """Test clearing all blocks"""
        try:
            # Clear all blocks
            clear_result = clear_all_blocks()
            if not clear_result:
                return False
            
            # Verify no blocked IPs
            blocked_ips = get_blocked_ips()
            if blocked_ips:
                return False
            
            return True
        except Exception as e:
            log_error(f"Clear blocks test error: {e}")
            return False
    
    def test_gui_components(self) -> bool:
        """Test GUI component imports"""
        try:
            # Test GUI imports
            from app.gui.device_list import DeviceListWidget
            from app.gui.network_manipulator_gui import NetworkManipulatorGUI
            from app.gui.sidebar import SidebarWidget
            from app.gui.ps5_gui import PS5NetworkGUI
            
            return True
        except ImportError as e:
            log_error(f"GUI test error: {e}")
            return False
    
    def test_logging_system(self) -> bool:
        """Test logging system"""
        try:
            log_info("Test log message")
            log_error("Test error message")
            return True
        except Exception as e:
            return False
    
    def cleanup_test_environment(self) -> bool:
        """Clean up test environment"""
        try:
            # Clear all blocks
            clear_all_blocks()
            
            # Stop PS5 monitoring
            ps5_network_tool.stop_monitoring()
            
            # Clear NetCut disruptions
            netcut_blocker.clear_all_disruptions()
            
            return True
        except Exception as e:
            log_error(f"Cleanup error: {e}")
            return False
    
    def run_comprehensive_test(self) -> Dict:
        """Run the complete comprehensive test suite"""
        print("🚀 COMPREHENSIVE PULSEDROP PRO TEST SUITE")
        print("=" * 50)
        
        # Define test sequence
        tests = [
            ("Module Imports", self.test_imports),
            ("Network Connectivity", self.test_network_connectivity),
            ("PS5 Connectivity", self.test_ps5_connectivity),
            ("Core Blocking System", self.test_blocking_system),
            ("NetCut Blocker", self.test_netcut_blocker),
            ("PS5 Network Tool", self.test_ps5_network_tool),
            ("PS5-Specific Blocking", self.test_ps5_specific_blocking),
            ("Mass Blocking", self.test_mass_blocking),
            ("Clear All Blocks", self.test_clear_all_blocks),
            ("GUI Components", self.test_gui_components),
            ("Logging System", self.test_logging_system),
            ("Environment Cleanup", self.cleanup_test_environment)
        ]
        
        # Run all tests
        for test_name, test_func in tests:
            result = self.run_test(test_name, test_func)
            self.results.append(result)
        
        # Generate summary
        return self.generate_summary()
    
    def generate_summary(self) -> Dict:
        """Generate comprehensive test summary"""
        total_tests = len(self.results)
        passed_tests = sum(1 for r in self.results if r.success)
        failed_tests = total_tests - passed_tests
        total_duration = time.time() - self.start_time
        
        print("\n" + "=" * 50)
        print("📊 COMPREHENSIVE TEST SUMMARY")
        print("=" * 50)
        print(f"Total Tests: {total_tests}")
        print(f"Passed: {passed_tests} ✅")
        print(f"Failed: {failed_tests} ❌")
        print(f"Success Rate: {(passed_tests/total_tests)*100:.1f}%")
        print(f"Total Duration: {total_duration:.2f}s")
        
        if failed_tests > 0:
            print("\n❌ FAILED TESTS:")
            for result in self.results:
                if not result.success:
                    print(f"  - {result.name}: {result.message}")
        
        print("\n✅ PASSED TESTS:")
        for result in self.results:
            if result.success:
                print(f"  - {result.name} ({result.duration:.2f}s)")
        
        return {
            "total_tests": total_tests,
            "passed_tests": passed_tests,
            "failed_tests": failed_tests,
            "success_rate": (passed_tests/total_tests)*100,
            "total_duration": total_duration,
            "results": self.results
        }

def main():
    """Main test execution"""
    print("🎯 PulseDrop Pro - Comprehensive Test Suite")
    print("Cleaning up testing and creating one comprehensive test sequence...")
    
    # Create and run comprehensive tester
    tester = ComprehensiveTester()
    summary = tester.run_comprehensive_test()
    
    # Final status
    if summary["failed_tests"] == 0:
        print("\n🎉 ALL TESTS PASSED! System is ready for use.")
        return True
    else:
        print(f"\n⚠️  {summary['failed_tests']} test(s) failed. Please review failed tests above.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 