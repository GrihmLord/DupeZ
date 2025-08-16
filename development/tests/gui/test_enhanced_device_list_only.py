#!/usr/bin/env python3
"""
Simple test for Enhanced Device List only
"""

import sys
import os
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel

# Add the app directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def main():
    """Test Enhanced Device List only"""
    print("🧪 Testing Enhanced Device List (Only)...")
    
    try:
        # Create QApplication
        app = QApplication(sys.argv)
        
        # Import and create the widget
        from app.gui.enhanced_device_list import EnhancedDeviceList
        
        # Create test window
        test_window = QWidget()
        test_window.setWindowTitle("Enhanced Device List Test")
        test_window.setGeometry(100, 100, 1200, 800)
        
        layout = QVBoxLayout()
        
        # Add status label
        status_label = QLabel("Enhanced Device List Test - No Crashes!")
        status_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #27ae60; padding: 20px;")
        layout.addWidget(status_label)
        
        # Add the enhanced device list
        device_list = EnhancedDeviceList()
        layout.addWidget(device_list)
        
        test_window.setLayout(layout)
        
        # Show the window
        test_window.show()
        
        print("✅ Enhanced Device List created successfully!")
        print("✅ No crashes detected!")
        print("💡 Close the window to exit.")
        
        # Run the application
        app.exec()
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    main() 