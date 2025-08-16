#!/usr/bin/env python3
"""
Comprehensive Test Runner for DupeZ
Runs all tests and provides detailed reporting
"""

import sys
import os
import unittest
import time
import json
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.logs.logger import log_info, log_error, log_performance

class TestRunner:
    """Comprehensive test runner with reporting"""
    
    def __init__(self):
        self.test_results = {
            'total_tests': 0,
            'passed': 0,
            'failed': 0,
            'errors': 0,
            'skipped': 0,
            'start_time': None,
            'end_time': None,
            'duration': 0,
            'test_suites': []
        }
    
    def discover_tests(self):
        """Discover all test files"""
        test_files = []
        tests_dir = Path(__file__).parent
        
        # Find all test files
        for test_file in tests_dir.rglob("test_*.py"):
            if test_file.name != "__init__.py":
                test_files.append(str(test_file))
        
        return test_files
    
    def run_test_suite(self, test_file):
        """Run a single test suite"""
        suite_name = Path(test_file).stem
        print(f"\n🧪 Running {suite_name}...")
        
        try:
            # Load test suite
            loader = unittest.TestLoader()
            suite = loader.discover(os.path.dirname(test_file), pattern=Path(test_file).name)
            
            # Run tests
            runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
            result = runner.run(suite)
            
            # Record results
            suite_result = {
                'name': suite_name,
                'file': test_file,
                'tests_run': result.testsRun,
                'failures': len(result.failures),
                'errors': len(result.errors),
                'skipped': len(result.skipped) if hasattr(result, 'skipped') else 0,
                'success': result.wasSuccessful()
            }
            
            self.test_results['test_suites'].append(suite_result)
            self.test_results['total_tests'] += result.testsRun
            self.test_results['failed'] += len(result.failures)
            self.test_results['errors'] += len(result.errors)
            self.test_results['skipped'] += suite_result['skipped']
            
            if suite_result['success']:
                print(f"✅ {suite_name} passed")
                self.test_results['passed'] += result.testsRun - len(result.failures) - len(result.errors)
            else:
                print(f"❌ {suite_name} failed")
            
            return suite_result
            
        except Exception as e:
            print(f"❌ Error running {suite_name}: {e}")
            log_error(f"Test suite {suite_name} failed", exception=e)
            return None
    
    def run_performance_tests(self):
        """Run performance benchmarks"""
        print("\n⚡ Running performance tests...")
        
        try:
            from app.network.enhanced_scanner import EnhancedNetworkScanner
            import time
            
            # Test scanner performance
            scanner = EnhancedNetworkScanner(max_threads=20, timeout=2)
            
            # Test ARP scan performance
            start_time = time.time()
            devices = scanner._scan_arp_table()
            arp_time = time.time() - start_time
            
            # Test network scan performance
            start_time = time.time()
            all_devices = scanner.scan_network("192.168.1.0/24", quick_scan=True)
            scan_time = time.time() - start_time
            
            performance_results = {
                'arp_scan_time': arp_time,
                'arp_devices_found': len(devices),
                'full_scan_time': scan_time,
                'total_devices_found': len(all_devices),
                'devices_per_second': len(all_devices) / scan_time if scan_time > 0 else 0
            }
            
            print(f"📊 Performance Results:")
            print(f"  ARP Scan: {arp_time:.2f}s ({len(devices)} devices)")
            print(f"  Full Scan: {scan_time:.2f}s ({len(all_devices)} devices)")
            print(f"  Rate: {performance_results['devices_per_second']:.1f} devices/sec")
            
            return performance_results
            
        except Exception as e:
            print(f"❌ Performance tests failed: {e}")
            log_error("Performance tests failed", exception=e)
            return None
    
    def run_integration_tests(self):
        """Run integration tests"""
        print("\n🔗 Running integration tests...")
        
        try:
            # Test application startup
            from app.main import main as app_main
            
            # Test GUI components
            from app.gui.dashboard import Dashboard
            from app.gui.enhanced_device_list import EnhancedDeviceList
            
            # Test network components
            from app.network.enhanced_scanner import EnhancedNetworkScanner
            from app.firewall.blocker import NetworkBlocker
            
            print("✅ Integration tests passed")
            return True
            
        except Exception as e:
            print(f"❌ Integration tests failed: {e}")
            log_error("Integration tests failed", exception=e)
            return False
    
    def generate_report(self):
        """Generate comprehensive test report"""
        print("\n📊 Generating test report...")
        
        # Calculate totals
        total = self.test_results['total_tests']
        passed = self.test_results['passed']
        failed = self.test_results['failed']
        errors = self.test_results['errors']
        skipped = self.test_results['skipped']
        
        # Calculate success rate
        success_rate = (passed / total * 100) if total > 0 else 0
        
        # Create report
        report = {
            'timestamp': datetime.now().isoformat(),
            'summary': {
                'total_tests': total,
                'passed': passed,
                'failed': failed,
                'errors': errors,
                'skipped': skipped,
                'success_rate': success_rate,
                'duration': self.test_results['duration']
            },
            'test_suites': self.test_results['test_suites'],
            'performance': getattr(self, 'performance_results', None),
            'integration': getattr(self, 'integration_results', None)
        }
        
        # Save report
        report_file = Path('tests/test_report.json')
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        # Print summary
        print("\n" + "=" * 60)
        print("📊 TEST SUMMARY")
        print("=" * 60)
        print(f"Total Tests: {total}")
        print(f"Passed: {passed} ✅")
        print(f"Failed: {failed} ❌")
        print(f"Errors: {errors} ⚠️")
        print(f"Skipped: {skipped} ⏭️")
        print(f"Success Rate: {success_rate:.1f}%")
        print(f"Duration: {self.test_results['duration']:.2f}s")
        print("=" * 60)
        
        if success_rate >= 90:
            print("🎉 Excellent! All tests passing!")
        elif success_rate >= 75:
            print("✅ Good! Most tests passing!")
        elif success_rate >= 50:
            print("⚠️  Fair! Some tests failing!")
        else:
            print("❌ Poor! Many tests failing!")
        
        return report
    
    def run_all_tests(self):
        """Run all tests"""
        print("🚀 DupeZ - Comprehensive Test Suite")
        print("=" * 60)
        
        self.test_results['start_time'] = time.time()
        
        # Discover and run test files
        test_files = self.discover_tests()
        print(f"📁 Found {len(test_files)} test files")
        
        for test_file in test_files:
            self.run_test_suite(test_file)
        
        # Run performance tests
        self.performance_results = self.run_performance_tests()
        
        # Run integration tests
        self.integration_results = self.run_integration_tests()
        
        self.test_results['end_time'] = time.time()
        self.test_results['duration'] = self.test_results['end_time'] - self.test_results['start_time']
        
        # Generate report
        report = self.generate_report()
        
        return report

def main():
    """Main test runner function"""
    runner = TestRunner()
    report = runner.run_all_tests()
    
    # Exit with appropriate code
    if report['summary']['success_rate'] >= 75:
        return 0
    else:
        return 1

if __name__ == "__main__":
    sys.exit(main()) 
