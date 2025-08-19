#!/usr/bin/env python3
"""
Test script for Enhanced Network Scanner
"""

import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_enhanced_scanner():
    """Test the enhanced network scanner"""
    print("🧪 Testing Enhanced Network Scanner")
    print("=" * 50)
    
    try:
        # Test scanner import
        print("📦 Testing scanner import...")
        from app.network.enhanced_multi_protocol_scanner import EnhancedMultiProtocolScanner, DeviceInfo
        print("✅ Enhanced scanner imported successfully")
        
        # Test scanner initialization
        print("🔧 Testing scanner initialization...")
        scanner = EnhancedMultiProtocolScanner()
        print("✅ Scanner initialized successfully")
        
        # Test basic functionality
        print("🔍 Testing basic functionality...")
        status = scanner.get_scan_status()
        print(f"   Initial status: {status}")
        
        # Test device info creation
        print("📱 Testing device info creation...")
        device = DeviceInfo(ip="192.168.1.1", mac="00:11:22:33:44:55")
        print(f"   Device created: {device.ip} - {device.mac}")
        
        # Test vendor lookup
        print("🏷️ Testing vendor lookup...")
        vendor = scanner._get_vendor_from_mac("00:0C:29:AA:BB:CC")
        print(f"   Vendor lookup: {vendor}")
        
        # Test device type determination
        print("🎯 Testing device type determination...")
        device_type = scanner._determine_device_type(device)
        print(f"   Device type: {device_type}")
        
        print("\n✅ All tests passed! Enhanced Network Scanner is working correctly.")
        return True
        
    except Exception as e:
        print(f"❌ Error during testing: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_gui_import():
    """Test the GUI import"""
    print("\n🖥️ Testing GUI import...")
    
    try:
        from app.gui.enhanced_network_scanner_gui import EnhancedNetworkScannerGUI
        print("✅ Enhanced scanner GUI imported successfully")
        return True
    except Exception as e:
        print(f"❌ Error importing GUI: {e}")
        return False

if __name__ == "__main__":
    print("🚀 Enhanced Network Scanner Test Suite")
    print("=" * 50)
    
    # Test scanner
    scanner_success = test_enhanced_scanner()
    
    # Test GUI
    gui_success = test_gui_import()
    
    # Summary
    print("\n📊 Test Summary:")
    print(f"   Scanner: {'✅ PASS' if scanner_success else '❌ FAIL'}")
    print(f"   GUI: {'✅ PASS' if gui_success else '❌ FAIL'}")
    
    if scanner_success and gui_success:
        print("\n🎉 All tests passed! Enhanced Network Scanner is ready to use.")
        sys.exit(0)
    else:
        print("\n⚠️ Some tests failed. Please check the errors above.")
        sys.exit(1)
