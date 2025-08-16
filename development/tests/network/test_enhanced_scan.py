#!/usr/bin/env python3
"""
Enhanced Network Scanner Test
Tests the improved scanning methods
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.network.enhanced_scanner import EnhancedNetworkScanner
from app.logs.logger import log_info, log_error

def test_enhanced_scanning():
    """Test the enhanced scanning methods"""
    print("🔍 Testing Enhanced Network Scanner...")
    
    try:
        # Create scanner instance
        scanner = EnhancedNetworkScanner(max_threads=20, timeout=2)
        
        # Test ARP table scanning
        print("\n📡 Testing ARP Table Scan...")
        arp_devices = scanner._scan_arp_table()
        print(f"✅ Found {len(arp_devices)} devices via ARP table")
        
        # Show ARP devices
        for device in arp_devices[:10]:  # Show first 10
            print(f"  📱 {device.get('ip', 'Unknown')} - {device.get('mac', 'Unknown')} - {device.get('hostname', 'Unknown')}")
        
        # Test full network scan
        print("\n📡 Testing Full Network Scan...")
        all_devices = scanner.scan_network("192.168.1.0/24", quick_scan=True)
        print(f"✅ Found {len(all_devices)} total devices")
        
        # Show all devices
        print("\n📊 All Detected Devices:")
        for i, device in enumerate(all_devices, 1):
            detection_method = device.get('detection_method', 'unknown')
            is_ps5 = "🎮 PS5" if device.get('is_ps5', False) else "📱 Device"
            print(f"  {i:2d}. {is_ps5} - {device.get('ip', 'Unknown')} - {device.get('mac', 'Unknown')} - {device.get('hostname', 'Unknown')} ({detection_method})")
        
        # Show PS5 devices specifically
        ps5_devices = [d for d in all_devices if d.get('is_ps5', False)]
        if ps5_devices:
            print(f"\n🎮 Found {len(ps5_devices)} PS5 devices:")
            for ps5 in ps5_devices:
                print(f"  🎮 PS5 - {ps5.get('ip', 'Unknown')} - {ps5.get('mac', 'Unknown')} - {ps5.get('hostname', 'Unknown')}")
        else:
            print("\n❌ No PS5 devices detected")
        
        # Show detection method breakdown
        detection_methods = {}
        for device in all_devices:
            method = device.get('detection_method', 'unknown')
            detection_methods[method] = detection_methods.get(method, 0) + 1
        
        print(f"\n📈 Detection Method Breakdown:")
        for method, count in detection_methods.items():
            print(f"  {method}: {count} devices")
        
        return all_devices
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return []

if __name__ == "__main__":
    test_enhanced_scanning() 