#!/usr/bin/env python3
"""
Test script to verify Enhanced Network Scanner fixes
"""

import sys
import os
import traceback
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QPushButton, QLabel, QTextEdit
from PyQt6.QtCore import QTimer

# Add the app directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_enhanced_device_list():
    """Test the Enhanced Device List widget"""
    try:
        print("🧪 Testing Enhanced Device List...")
        
        # Import the widget
        from app.gui.enhanced_device_list import EnhancedDeviceList
        
        # Create a simple test window
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
        
        # Create test window
        test_window = QWidget()
        test_window.setWindowTitle("Enhanced Network Scanner Test")
        test_window.setGeometry(100, 100, 1200, 800)
        
        layout = QVBoxLayout()
        
        # Add status label
        status_label = QLabel("Testing Enhanced Network Scanner...")
        status_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #2c3e50;")
        layout.addWidget(status_label)
        
        # Add the enhanced device list
        device_list = EnhancedDeviceList()
        layout.addWidget(device_list)
        
        # Add log output
        log_output = QTextEdit()
        log_output.setMaximumHeight(150)
        log_output.setPlaceholderText("Test logs will appear here...")
        layout.addWidget(log_output)
        
        # Add test buttons
        button_layout = QVBoxLayout()
        
        test_scan_btn = QPushButton("Test Scan (Safe)")
        test_scan_btn.clicked.connect(lambda: test_safe_scan(device_list, log_output))
        button_layout.addWidget(test_scan_btn)
        
        test_ui_btn = QPushButton("Test UI Elements")
        test_ui_btn.clicked.connect(lambda: test_ui_elements(device_list, log_output))
        button_layout.addWidget(test_ui_btn)
        
        test_cleanup_btn = QPushButton("Test Cleanup")
        test_cleanup_btn.clicked.connect(lambda: test_cleanup(device_list, log_output))
        button_layout.addWidget(test_cleanup_btn)
        
        layout.addLayout(button_layout)
        
        test_window.setLayout(layout)
        
        # Log success
        log_output.append("✅ Enhanced Device List created successfully!")
        log_output.append("✅ No crashes detected during initialization")
        
        # Show the window
        test_window.show()
        
        print("✅ Enhanced Device List test completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Enhanced Device List test failed: {e}")
        traceback.print_exc()
        return False

def test_safe_scan(device_list, log_output):
    """Test a safe scan operation with real network data"""
    try:
        log_output.append("🔍 Starting real network scan test...")
        
        # Import real network scanner
        from app.network.enhanced_scanner import get_enhanced_scanner
        
        # Perform real network scan
        scanner = get_enhanced_scanner()
        real_devices = scanner.scan_network("192.168.1.0/24", quick_scan=True)
        
        # Process real discovered devices
        if real_devices:
            device_list.on_scan_complete(real_devices)
            log_output.append("✅ Real network scan completed!")
            log_output.append(f"📊 Discovered {len(real_devices)} real devices")
            
            # Log some real device details
            for device in real_devices[:3]:  # Show first 3 devices
                log_output.append(f"  📱 {device.get('hostname', 'Unknown')} - {device.get('ip', 'N/A')}")
        else:
            log_output.append("⚠️ No devices found in network scan")
        
    except Exception as e:
        log_output.append(f"❌ Real network scan test failed: {e}")
        traceback.print_exc()

def test_ui_elements(device_list, log_output):
    """Test UI elements functionality"""
    try:
        log_output.append("🎨 Testing UI elements...")
        
        # Test various UI operations
        device_list.update_quick_stats()
        device_list.update_status("UI test in progress...")
        
        # Test search functionality
        device_list.filter_devices_by_search("")
        
        log_output.append("✅ UI elements test completed!")
        
    except Exception as e:
        log_output.append(f"❌ UI elements test failed: {e}")
        traceback.print_exc()

def test_cleanup(device_list, log_output):
    """Test cleanup functionality"""
    try:
        log_output.append("🧹 Testing cleanup...")
        
        # Test cleanup operations
        device_list.clear_devices()
        device_list.update_quick_stats()
        
        log_output.append("✅ Cleanup test completed!")
        
    except Exception as e:
        log_output.append(f"❌ Cleanup test failed: {e}")
        traceback.print_exc()

def test_network_topology():
    """Test the Network Topology widget"""
    try:
        print("🧪 Testing Network Topology...")
        
        # Ensure QApplication exists
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
        
        # Import the widget
        from app.gui.network_topology_view import NetworkTopologyWidget
        
        # Create test window
        test_window = QWidget()
        test_window.setWindowTitle("Network Topology Test")
        test_window.setGeometry(100, 100, 1000, 700)
        
        layout = QVBoxLayout()
        
        # Add status label
        status_label = QLabel("Testing Network Topology...")
        status_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #2c3e50;")
        layout.addWidget(status_label)
        
        # Add the topology widget
        topology_widget = NetworkTopologyWidget()
        layout.addWidget(topology_widget)
        
        test_window.setLayout(layout)
        
        # Show the window
        test_window.show()
        
        print("✅ Network Topology test completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Network Topology test failed: {e}")
        traceback.print_exc()
        return False

def main():
    """Main test function"""
    print("🚀 Testing Enhanced Network Scanner Fixes")
    print("=" * 50)
    
    # Test 1: Enhanced Device List
    print("\n1. Testing Enhanced Device List...")
    success1 = test_enhanced_device_list()
    
    # Test 2: Network Topology (if first test succeeds)
    if success1:
        print("\n2. Testing Network Topology...")
        success2 = test_network_topology()
    else:
        print("\n2. Skipping Network Topology test due to previous failure")
        success2 = False
    
    # Summary
    print("\n" + "=" * 50)
    print("📊 Test Results:")
    print(f"Enhanced Device List: {'✅ PASS' if success1 else '❌ FAIL'}")
    print(f"Network Topology: {'✅ PASS' if success2 else '❌ FAIL'}")
    
    if success1 and success2:
        print("\n🎉 All tests passed! Enhanced Network Scanner should be working.")
    else:
        print("\n⚠️ Some tests failed. Check the error messages above.")
    
    # Keep the application running if tests passed
    if success1 or success2:
        app = QApplication.instance()
        if app:
            print("\n💡 Test windows are open. Close them to exit.")
            app.exec()

if __name__ == "__main__":
    main() 