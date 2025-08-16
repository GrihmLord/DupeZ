#!/usr/bin/env python3
"""
Test script to check device scanning functionality
"""

import sys
import os

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_device_scan():
    """Test the device scanning functionality"""
    try:
        print("Testing device scanning...")
        
        # Import the scanning module
        from app.network.device_scan import scan_devices, get_local_ip
        
        # Get local IP
        local_ip = get_local_ip()
        print(f"Local IP: {local_ip}")
        
        # Scan for devices
        print("Scanning for devices...")
        devices = scan_devices(quick=True)
        
        print(f"Found {len(devices)} devices")
        
        if devices:
            print("Device list:")
            for i, device in enumerate(devices[:10]):  # Show first 10 devices
                ip = device.get('ip', 'N/A')
                hostname = device.get('hostname', 'N/A')
                mac = device.get('mac', 'N/A')
                vendor = device.get('vendor', 'N/A')
                print(f"  {i+1}. {ip} - {hostname} ({mac}) - {vendor}")
        else:
            print("No devices found!")
            
        return len(devices) > 0
        
    except Exception as e:
        print(f"Error testing device scan: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_enhanced_scanner():
    """Test the enhanced scanner"""
    try:
        print("\nTesting enhanced scanner...")
        
        from app.network.enhanced_scanner import EnhancedNetworkScanner
        
        scanner = EnhancedNetworkScanner()
        devices = scanner.scan_network(quick_scan=True)
        
        print(f"Enhanced scanner found {len(devices)} devices")
        
        if devices:
            print("Enhanced scanner device list:")
            for i, device in enumerate(devices[:10]):
                ip = device.get('ip', 'N/A')
                hostname = device.get('hostname', 'N/A')
                mac = device.get('mac', 'N/A')
                device_type = device.get('device_type', 'N/A')
                print(f"  {i+1}. {ip} - {hostname} ({mac}) - {device_type}")
        else:
            print("Enhanced scanner found no devices!")
            
        return len(devices) > 0
        
    except Exception as e:
        print(f"Error testing enhanced scanner: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("=== DupeZ Device Scanning Test ===\n")
    
    # Test basic device scan
    basic_success = test_device_scan()
    
    # Test enhanced scanner
    enhanced_success = test_enhanced_scanner()
    
    print(f"\n=== Test Results ===")
    print(f"Basic scanner: {'PASS' if basic_success else 'FAIL'}")
    print(f"Enhanced scanner: {'PASS' if enhanced_success else 'FAIL'}")
    
    if not basic_success and not enhanced_success:
        print("\n❌ Both scanners failed - there may be a network configuration issue")
    elif basic_success or enhanced_success:
        print("\n✅ At least one scanner is working")
    else:
        print("\n⚠️ Mixed results - some scanners working, others not") 