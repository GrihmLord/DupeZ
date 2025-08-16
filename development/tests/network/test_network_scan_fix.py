#!/usr/bin/env python3
"""
Test script to verify network scanner functionality after fixes
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.network.enhanced_scanner import EnhancedNetworkScanner
from app.logs.logger import log_info, log_error

def test_network_scanner():
    """Test the enhanced network scanner"""
    print("Testing Enhanced Network Scanner...")
    
    try:
        # Create scanner instance
        scanner = EnhancedNetworkScanner(max_threads=10, timeout=2)
        print("✓ Scanner created successfully")
        
        # Test ARP table scan
        print("\nTesting ARP table scan...")
        arp_devices = scanner._scan_arp_table()
        print(f"✓ Found {len(arp_devices)} devices via ARP table")
        
        # Test IP scan
        print("\nTesting IP scan...")
        ip_addresses = scanner._generate_ip_list("192.168.1.0/24")
        print(f"✓ Generated {len(ip_addresses)} IP addresses to scan")
        
        # Test a quick scan
        print("\nTesting quick network scan...")
        devices = scanner.scan_network("192.168.1.0/24", quick_scan=True)
        print(f"✓ Found {len(devices)} total devices")
        
        # Check for PS5s
        ps5_devices = [d for d in devices if d.get('is_ps5', False)]
        print(f"✓ Found {len(ps5_devices)} PS5 devices")
        
        # Show some device details
        if devices:
            print("\nSample devices found:")
            for i, device in enumerate(devices[:5]):
                print(f"  {i+1}. {device.get('ip', 'Unknown')} - {device.get('vendor', 'Unknown')} - {device.get('device_type', 'Unknown')}")
        
        print("\n✓ Network scanner test completed successfully!")
        return True
        
    except Exception as e:
        print(f"✗ Network scanner test failed: {e}")
        log_error("Network scanner test failed", exception=e)
        return False

if __name__ == "__main__":
    success = test_network_scanner()
    sys.exit(0 if success else 1) 