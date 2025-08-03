#!/usr/bin/env python3
"""
Development environment setup
"""

import subprocess
import sys

def setup_dev_environment():
    """Set up development environment"""
    print("Setting up PulseDropPro development environment...")
    
    # Install development dependencies
    subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', 'requirements-test.txt'])
    
    # Run tests
    subprocess.run([sys.executable, 'run_tests.py'])
    
    print("Development environment setup complete!")

if __name__ == '__main__':
    setup_dev_environment()
