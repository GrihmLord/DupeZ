#!/usr/bin/env python3
"""
Test Scan Button Fix
Tests the network scan button functionality to ensure it works properly
"""

import sys
import os
import time
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QPushButton, QLabel
from PyQt6.QtCore import Qt, QTimer

# Add the app directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

def test_scan_button_functionality():
    """Test the scan button functionality"""
    print("🔍 Testing Scan Button Functionality...")
    
    try:
        # Test 1: Import enhanced device list
        print("  - Testing imports...")
        from app.gui.enhanced_device_list import EnhancedDeviceList
        print("    ✅ Enhanced device list imports successful")
        
        # Test 2: Create QApplication
        print("  - Testing QApplication creation...")
        app = QApplication(sys.argv)
        print("    ✅ QApplication created successfully")
        
        # Test 3: Create enhanced device list
        print("  - Testing enhanced device list creation...")
        device_list = EnhancedDeviceList()
        print("    ✅ Enhanced device list created successfully")
        
        # Test 4: Test scan button exists
        print("  - Testing scan button existence...")
        if hasattr(device_list, 'scan_button'):
            print("    ✅ Scan button exists")
            print(f"    ✅ Scan button text: {device_list.scan_button.text()}")
            print(f"    ✅ Scan button enabled: {device_list.scan_button.isEnabled()}")
        else:
            print("    ❌ Scan button not found")
            return False
        
        # Test 5: Test scanner initialization
        print("  - Testing scanner initialization...")
        if hasattr(device_list, 'scanner') and device_list.scanner:
            print("    ✅ Scanner initialized successfully")
        else:
            print("    ❌ Scanner not initialized")
            return False
        
        # Test 6: Test scan method exists
        print("  - Testing scan method existence...")
        if hasattr(device_list, 'start_scan'):
            print("    ✅ Start scan method exists")
        else:
            print("    ❌ Start scan method not found")
            return False
        
        # Test 7: Test signal connections
        print("  - Testing signal connections...")
        if device_list.scan_button.receivers(device_list.scan_button.clicked) > 0:
            print("    ✅ Scan button signal connected")
        else:
            print("    ❌ Scan button signal not connected")
            return False
        
        return True
        
    except Exception as e:
        print(f"    ❌ Scan button test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def create_test_gui():
    """Create a test GUI to verify scan button functionality"""
    print("\n🖥️ Creating Test GUI for Scan Button...")
    
    app = QApplication(sys.argv)
    
    # Create main window
    window = QMainWindow()
    window.setWindowTitle("Scan Button Test")
    window.setGeometry(100, 100, 800, 600)
    
    # Create central widget
    central_widget = QWidget()
    window.setCentralWidget(central_widget)
    
    # Create layout
    layout = QVBoxLayout(central_widget)
    
    # Add title
    title = QLabel("Network Scan Button Test")
    title.setAlignment(Qt.AlignmentFlag.AlignCenter)
    title.setStyleSheet("color: #ffffff; background-color: #2c3e50; padding: 10px; border-radius: 5px; font-weight: bold;")
    layout.addWidget(title)
    
    # Add status label
    status_label = QLabel("Ready to test scan button")
    status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    status_label.setStyleSheet("color: #ffffff; background-color: #34495e; padding: 8px; border-radius: 3px;")
    layout.addWidget(status_label)
    
    # Create enhanced device list
    try:
        from app.gui.enhanced_device_list import EnhancedDeviceList
        device_list = EnhancedDeviceList()
        layout.addWidget(device_list)
        
        # Test scan button functionality
        def test_scan():
            status_label.setText("Testing scan button...")
            try:
                device_list.start_scan()
                status_label.setText("Scan started successfully!")
            except Exception as e:
                status_label.setText(f"Scan failed: {e}")
        
        # Add test button
        test_button = QPushButton("Test Scan Button")
        test_button.setStyleSheet("""
            QPushButton {
                background-color: #27ae60;
                color: white;
                border: none;
                padding: 10px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2ecc71;
            }
        """)
        test_button.clicked.connect(test_scan)
        layout.addWidget(test_button)
        
        print("    ✅ Test GUI created successfully")
        print("    🔍 Click the 'Test Scan Button' to test the scan functionality")
        
    except Exception as e:
        error_label = QLabel(f"Error creating device list: {e}")
        error_label.setStyleSheet("color: #e74c3c; background-color: #2c3e50; padding: 10px; border-radius: 5px;")
        layout.addWidget(error_label)
        print(f"    ❌ Error creating device list: {e}")
    
    # Set dark theme
    app.setStyleSheet("""
        QMainWindow {
            background-color: #1e1e1e;
        }
        QWidget {
            background-color: #1e1e1e;
            color: #ffffff;
        }
    """)
    
    # Show window
    window.show()
    
    print("    📱 GUI window opened - test the scan button functionality")
    
    return app.exec()

def main():
    """Main test function"""
    print("🚀 Starting Scan Button Functionality Tests")
    print("=" * 50)
    
    # Test scan button functionality
    button_ok = test_scan_button_functionality()
    
    if button_ok:
        print("\n✅ Scan button functionality test passed")
        print("🖥️ Launching test GUI...")
        
        # Create and run test GUI
        return create_test_gui()
    else:
        print("\n❌ Scan button functionality test failed")
        return 1

if __name__ == "__main__":
    main() 