#!/usr/bin/env python3
"""
Test PS5 Detection Script
Scans the network to detect PS5 devices
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.network.enhanced_scanner import EnhancedNetworkScanner
from app.logs.logger import log_info, log_error

def test_ps5_detection():
    """Test PS5 detection on the network"""
    print("[SCAN] Testing PS5 Detection...")
    
    # Test both network ranges
    networks = ["192.168.1.0/24", "10.5.0.0/24"]
    
    for network in networks:
        print(f"\n📡 Scanning network {network}...")
        
        try:
            # Create scanner instance
            scanner = EnhancedNetworkScanner(max_threads=20, timeout=2)
            
            # Scan the network
            devices = scanner.scan_network(network, quick_scan=True)
            
            print(f"[STATS] Found {len(devices)} devices on {network}:")
            
            ps5_devices = []
            for device in devices:
                ip = device.get('ip', 'Unknown')
                mac = device.get('mac', 'Unknown')
                hostname = device.get('hostname', 'Unknown')
                vendor = device.get('vendor', 'Unknown')
                device_type = device.get('device_type', 'Unknown')
                is_ps5 = device.get('is_ps5', False)
                
                # Check for PS5 indicators manually
                mac_lower = mac.lower()
                hostname_lower = hostname.lower()
                vendor_lower = vendor.lower()
                
                ps5_indicators = [
                    'ps5' in hostname_lower,
                    'playstation' in hostname_lower,
                    'sony' in hostname_lower,
                    'ps5' in vendor_lower,
                    'playstation' in vendor_lower,
                    'sony' in vendor_lower,
                    mac_lower.startswith('b4:0a:d8'),
                    mac_lower.startswith('b4:0a:d9'),
                    mac_lower.startswith('b4:0a:da'),
                    mac_lower.startswith('b4:0a:db'),
                ]
                
                if any(ps5_indicators):
                    device['is_ps5'] = True
                    device['device_type'] = 'PlayStation 5'
                    ps5_devices.append(device)
                    print(f"  [GAMING] PS5 DETECTED: {ip} | {mac} | {hostname} | {vendor}")
                else:
                    print(f"  [DEVICE] {ip} | {mac} | {hostname} | {vendor} | {device_type}")
            
            if ps5_devices:
                print(f"\n[GAMING] Found {len(ps5_devices)} PS5 device(s) on {network}:")
                for ps5 in ps5_devices:
                    print(f"  [GAMING] PS5: {ps5.get('ip')} | {ps5.get('mac')} | {ps5.get('hostname')}")
                return ps5_devices
            else:
                print(f"\n[FAILED] No PS5 devices detected on {network}")
        
        except Exception as e:
            log_error(f"Test failed for {network}: {e}")
            print(f"[FAILED] Error scanning {network}: {e}")
    
    print("\n💡 PS5 Detection Tips:")
    print("1. Make sure your PS5 is connected to the network")
    print("2. Check if your PS5 is on a different IP range")
    print("3. Try connecting your PS5 to the same network as your computer")
    print("4. Check your router's device list for the PS5's IP address")
    
    return []

if __name__ == "__main__":
    test_ps5_detection() 