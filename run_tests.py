#!/usr/bin/env python3
"""
Test runner for PulseDropPro GUI button tests
"""

import sys
import os
import subprocess
import argparse

def install_test_dependencies():
    """Install test dependencies if not already installed"""
    try:
        import pytest
        import pytest_qt
        print("✓ Test dependencies already installed")
        return True
    except ImportError:
        print("Installing test dependencies...")
        try:
            subprocess.check_call([
                sys.executable, "-m", "pip", "install", "-r", "requirements-test.txt"
            ])
            print("✓ Test dependencies installed successfully")
            return True
        except subprocess.CalledProcessError as e:
            print(f"✗ Failed to install test dependencies: {e}")
            return False

def run_button_tests(verbose=False, coverage=False):
    """Run the GUI button tests"""
    if not install_test_dependencies():
        return False
    
    # Build the test command
    cmd = [sys.executable, "-m", "pytest"]
    
    if verbose:
        cmd.append("-v")
    
    if coverage:
        cmd.extend(["--cov=app", "--cov-report=html", "--cov-report=term"])
    
    # Add the test file
    cmd.append("tests/test_gui_buttons.py")
    
    print("Running GUI button tests...")
    print(f"Command: {' '.join(cmd)}")
    print("-" * 50)
    
    try:
        result = subprocess.run(cmd, check=True)
        print("-" * 50)
        print("✓ All tests passed!")
        return True
    except subprocess.CalledProcessError as e:
        print("-" * 50)
        print(f"✗ Tests failed with exit code: {e.returncode}")
        return False

def run_specific_test(test_name, verbose=False):
    """Run a specific test by name"""
    if not install_test_dependencies():
        return False
    
    cmd = [sys.executable, "-m", "pytest"]
    
    if verbose:
        cmd.append("-v")
    
    # Add the specific test
    cmd.extend([f"tests/test_gui_buttons.py::{test_name}"])
    
    print(f"Running specific test: {test_name}")
    print(f"Command: {' '.join(cmd)}")
    print("-" * 50)
    
    try:
        result = subprocess.run(cmd, check=True)
        print("-" * 50)
        print("✓ Test passed!")
        return True
    except subprocess.CalledProcessError as e:
        print("-" * 50)
        print(f"✗ Test failed with exit code: {e.returncode}")
        return False

def list_available_tests():
    """List all available tests"""
    if not install_test_dependencies():
        return False
    
    cmd = [sys.executable, "-m", "pytest", "--collect-only", "-q", "tests/test_gui_buttons.py"]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print("Available tests:")
        print("-" * 30)
        for line in result.stdout.split('\n'):
            if '::' in line and 'test_' in line:
                test_name = line.split('::')[-1].strip()
                if test_name:
                    print(f"  {test_name}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ Failed to list tests: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Run PulseDropPro GUI button tests")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--coverage", "-c", action="store_true", help="Generate coverage report")
    parser.add_argument("--list", "-l", action="store_true", help="List available tests")
    parser.add_argument("--test", "-t", help="Run specific test by name")
    
    args = parser.parse_args()
    
    if args.list:
        return list_available_tests()
    elif args.test:
        return run_specific_test(args.test, args.verbose)
    else:
        return run_button_tests(args.verbose, args.coverage)

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 