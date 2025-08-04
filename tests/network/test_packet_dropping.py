#!/usr/bin/env python3
"""
Test Packet Dropping Functionality
Verifies that the packet dropping system is working correctly
"""

import sys
import os
import subprocess
import time

# Add the app directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

from app.firewall.udp_port_interrupter import UDPPortInterrupter
from app.firewall.dupe_internet_dropper import DupeInternetDropper
from app.logs.logger import log_info, log_error

def test_packet_dropping():
    """Test packet dropping functionality"""
    print("🧪 Testing Packet Dropping Functionality")
    
    try:
        # Initialize UDP interrupter
        udp_interrupter = UDPPortInterrupter()
        print("[SUCCESS] UDP interrupter initialized")
        
        # Test target IP (use localhost for testing)
        test_ip = "127.0.0.1"
        
        # Start UDP interruption
        print(f"[TARGET] Starting UDP interruption for {test_ip}")
        success = udp_interrupter.start_udp_interruption(
            target_ips=[test_ip],
            drop_rate=90,
            duration=10  # 10 second test
        )
        
        if success:
            print("[SUCCESS] UDP interruption started successfully")
            
            # Wait a moment for rules to be applied
            time.sleep(2)
            
            # Verify packet dropping
            stats = udp_interrupter.get_packet_statistics(test_ip)
            print(f"[STATS] Packet statistics: {stats}")
            
            # Check if firewall rules are active
            if stats.get("firewall_rules_active", False):
                print("[SUCCESS] Firewall rules are active")
            else:
                print("[FAILED] Firewall rules not found")
                
            # Wait for the duration
            print("⏳ Waiting for UDP interruption to complete...")
            time.sleep(8)
            
            # Stop UDP interruption
            udp_interrupter.stop_udp_interruption()
            print("[SUCCESS] UDP interruption stopped")
            
        else:
            print("[FAILED] Failed to start UDP interruption")
            
    except Exception as e:
        print(f"[FAILED] Test failed: {e}")
        log_error(f"Packet dropping test failed: {e}")

def test_dupe_internet_dropper():
    """Test dupe internet dropper functionality"""
    print("\n[ACTOR] Testing Dupe Internet Dropper")
    
    try:
        # Initialize dupe internet dropper
        dupe_dropper = DupeInternetDropper()
        print("[SUCCESS] Dupe internet dropper initialized")
        
        # Get real network devices
        from app.network.enhanced_scanner import get_enhanced_scanner
        
        scanner = get_enhanced_scanner()
        real_devices = scanner.scan_network("192.168.1.0/24", quick_scan=True)
        
        if not real_devices:
            print("  [WARNING] No real devices found, using localhost for safe test")
            test_devices = [
                {"ip": "127.0.0.1", "mac": "00:11:22:33:44:55", "hostname": "TestDevice"}
            ]
        else:
            # Use real discovered devices
            test_devices = real_devices[:2]  # Use first 2 devices
            print(f"  [DEVICE] Using {len(test_devices)} real devices for testing")
        
        # Test methods
        test_methods = ["udp_interrupt", "icmp_spoof"]
        
        # Start dupe
        print(f"[GAMING] Starting dupe with methods: {test_methods}")
        success = dupe_dropper.start_dupe_with_devices(test_devices, test_methods)
        
        if success:
            print("[SUCCESS] Dupe started successfully")
            
            # Check status
            status = dupe_dropper.get_status()
            print(f"[STATS] Dupe status: {status}")
            
            # Wait a moment
            time.sleep(3)
            
            # Stop dupe
            dupe_dropper.stop_dupe()
            print("[SUCCESS] Dupe stopped")
            
        else:
            print("[FAILED] Failed to start dupe")
            
    except Exception as e:
        print(f"[FAILED] Test failed: {e}")
        log_error(f"Dupe internet dropper test failed: {e}")

def check_firewall_rules():
    """Check if firewall rules are properly configured"""
    print("\n[SHIELD] Checking Firewall Rules")
    
    try:
        # List all PulseDrop firewall rules
        cmd = [
            "netsh", "advfirewall", "firewall", "show", "rule",
            "name=all"
        ]
        
        result = subprocess.run(cmd, capture_output=True, timeout=10)
        if result.returncode == 0:
            output = result.stdout.decode()
            
            # Look for PulseDrop rules
            pulse_drop_rules = [line for line in output.split('\n') if 'PulseDrop' in line]
            
            if pulse_drop_rules:
                print("[SUCCESS] Found PulseDrop firewall rules:")
                for rule in pulse_drop_rules:
                    print(f"  - {rule.strip()}")
            else:
                print("[FAILED] No PulseDrop firewall rules found")
                
        else:
            print("[FAILED] Failed to check firewall rules")
            
    except Exception as e:
        print(f"[FAILED] Firewall check failed: {e}")

def main():
    """Run all packet dropping tests"""
    print("[ROCKET] Starting Packet Dropping Tests")
    print("=" * 50)
    
    # Test UDP interrupter
    test_packet_dropping()
    
    # Test dupe internet dropper
    test_dupe_internet_dropper()
    
    # Check firewall rules
    check_firewall_rules()
    
    print("\n" + "=" * 50)
    print("[SUCCESS] Packet dropping tests completed")

if __name__ == "__main__":
    main() 