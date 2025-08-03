#!/usr/bin/env python3
"""
Comprehensive Test Runner for PulseDropPro
Runs all tests and provides detailed reporting
"""

import sys
import os
import unittest
import time
import json
from datetime import datetime
from pathlib import Path

# Add the app directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'app'))

def discover_tests():
    """Discover all test files in the tests directory"""
    test_files = []
    tests_dir = Path(__file__).parent
    
    # Find all test files
    for test_file in tests_dir.rglob('test_*.py'):
        if test_file.is_file():
            test_files.append(str(test_file))
    
    return test_files

def run_test_suite(test_files, verbose=True):
    """Run the test suite and return results"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Load all test files
    for test_file in test_files:
        try:
            # Convert file path to module path
            module_path = test_file.replace('/', '.').replace('\\', '.')
            module_path = module_path.replace('.py', '')
            
            # Load tests from the module
            module_tests = loader.discover(
                os.path.dirname(test_file),
                pattern=os.path.basename(test_file)
            )
            suite.addTests(module_tests)
            
        except Exception as e:
            print(f"Error loading tests from {test_file}: {e}")
    
    # Run the test suite
    runner = unittest.TextTestRunner(verbosity=2 if verbose else 1)
    start_time = time.time()
    result = runner.run(suite)
    end_time = time.time()
    
    return result, end_time - start_time

def generate_test_report(result, duration, test_files):
    """Generate a comprehensive test report"""
    report = {
        'timestamp': datetime.now().isoformat(),
        'duration': duration,
        'total_tests': result.testsRun,
        'failures': len(result.failures),
        'errors': len(result.errors),
        'skipped': len(result.skipped) if hasattr(result, 'skipped') else 0,
        'success_rate': ((result.testsRun - len(result.failures) - len(result.errors)) / result.testsRun * 100) if result.testsRun > 0 else 0,
        'test_files': test_files,
        'failures_details': [],
        'errors_details': []
    }
    
    # Add failure details
    for test, traceback in result.failures:
        report['failures_details'].append({
            'test': str(test),
            'traceback': traceback
        })
    
    # Add error details
    for test, traceback in result.errors:
        report['errors_details'].append({
            'test': str(test),
            'traceback': traceback
        })
    
    return report

def print_test_report(report):
    """Print a formatted test report"""
    print("\n" + "="*60)
    print("                    PULSEDROP PRO TEST REPORT")
    print("="*60)
    print(f"Timestamp: {report['timestamp']}")
    print(f"Duration: {report['duration']:.2f} seconds")
    print(f"Total Tests: {report['total_tests']}")
    print(f"Failures: {report['failures']}")
    print(f"Errors: {report['errors']}")
    print(f"Success Rate: {report['success_rate']:.1f}%")
    print("-"*60)
    
    if report['failures'] > 0:
        print("\nFAILURES:")
        for failure in report['failures_details']:
            print(f"  • {failure['test']}")
            print(f"    {failure['traceback']}")
    
    if report['errors'] > 0:
        print("\nERRORS:")
        for error in report['errors_details']:
            print(f"  • {error['test']}")
            print(f"    {error['traceback']}")
    
    print("\n" + "="*60)

def save_test_report(report, filename='test_report.json'):
    """Save test report to JSON file"""
    try:
        with open(filename, 'w') as f:
            json.dump(report, f, indent=2)
        print(f"\nTest report saved to: {filename}")
    except Exception as e:
        print(f"Error saving test report: {e}")

def run_specific_test_category(category):
    """Run tests for a specific category"""
    categories = {
        'unit': 'tests/unit/',
        'integration': 'tests/integration/',
        'gui': 'tests/gui/',
        'network': 'tests/network/'
    }
    
    if category not in categories:
        print(f"Unknown category: {category}")
        print(f"Available categories: {list(categories.keys())}")
        return
    
    category_dir = categories[category]
    test_files = []
    
    # Find test files in the category directory
    category_path = Path(category_dir)
    if category_path.exists():
        for test_file in category_path.rglob('test_*.py'):
            if test_file.is_file():
                test_files.append(str(test_file))
    
    if not test_files:
        print(f"No test files found in {category_dir}")
        return
    
    print(f"\nRunning {category} tests...")
    result, duration = run_test_suite(test_files)
    report = generate_test_report(result, duration, test_files)
    print_test_report(report)
    
    return report

def main():
    """Main test runner function"""
    import argparse
    
    parser = argparse.ArgumentParser(description='PulseDropPro Test Runner')
    parser.add_argument('--category', choices=['unit', 'integration', 'gui', 'network', 'all'],
                       default='all', help='Test category to run')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--report', '-r', help='Save report to file')
    parser.add_argument('--quick', '-q', action='store_true', help='Quick test run')
    
    args = parser.parse_args()
    
    print("PulseDropPro Test Runner")
    print("="*40)
    
    if args.category == 'all':
        # Run all tests
        test_files = discover_tests()
        if not test_files:
            print("No test files found!")
            return
        
        print(f"Found {len(test_files)} test files:")
        for test_file in test_files:
            print(f"  • {test_file}")
        
        print(f"\nRunning all tests...")
        result, duration = run_test_suite(test_files, args.verbose)
        report = generate_test_report(result, duration, test_files)
        print_test_report(report)
        
        if args.report:
            save_test_report(report, args.report)
        
        # Exit with appropriate code
        if report['failures'] > 0 or report['errors'] > 0:
            sys.exit(1)
        else:
            sys.exit(0)
    
    else:
        # Run specific category
        report = run_specific_test_category(args.category)
        
        if args.report and report:
            save_test_report(report, args.report)
        
        # Exit with appropriate code
        if report and (report['failures'] > 0 or report['errors'] > 0):
            sys.exit(1)
        else:
            sys.exit(0)

if __name__ == '__main__':
    main() 