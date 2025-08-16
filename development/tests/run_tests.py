#!/usr/bin/env python3
"""
Quick test runner for DupeZ
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tests'))

from run_all_tests import main

if __name__ == '__main__':
    main()
