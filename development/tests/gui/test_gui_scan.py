#!/usr/bin/env python3
"""
Test GUI scan functionality
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication
from app.gui.enhanced_device_list import EnhancedDeviceList
from app.logs.logger import log_info, log_error

def test_gui_scan():
    """Test the GUI scan functionality"""
    print("Testing GUI Enhanced Device List...")
    
    try:
        # Create QApplication
        app = QApplication(sys.argv)
        
        # Create enhanced device list
        device_list = EnhancedDeviceList()
        device_list.show()
        
        print("✓ Enhanced Device List created and displayed")
        
        # Test scan functionality
        print("\nTesting scan functionality...")
        device_list.start_scan()
        
        print("✓ Scan started successfully")
        print("✓ GUI test completed - check the application window")
        
        # Run the application
        return app.exec()
        
    except Exception as e:
        print(f"✗ GUI test failed: {e}")
        log_error("GUI test failed", exception=e)
        return 1

if __name__ == "__main__":
    exit_code = test_gui_scan()
    sys.exit(exit_code) 