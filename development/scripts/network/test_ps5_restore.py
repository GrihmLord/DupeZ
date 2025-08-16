#!/usr/bin/env python3
"""
Test PS5 Restoration Script
This script tests the PS5 restoration functionality.
"""

import subprocess
import sys
import os

def test_ps5_restore():
    """Test PS5 restoration functionality"""
    print("=" * 50)
    print("PS5 RESTORATION TEST")
    print("=" * 50)
    
    # Test 1: Check if PS5 restoration script exists
    script_path = "scripts/network/restore_ps5_internet.py"
    if os.path.exists(script_path):
        print(f"✅ PS5 restoration script found: {script_path}")
    else:
        print(f"❌ PS5 restoration script not found: {script_path}")
        return False
    
    # Test 2: Check if emergency unblock script exists
    emergency_script = "scripts/network/emergency_ps5_unblock.py"
    if os.path.exists(emergency_script):
        print(f"✅ Emergency PS5 unblock script found: {emergency_script}")
    else:
        print(f"❌ Emergency PS5 unblock script not found: {emergency_script}")
    
    # Test 3: Check if batch files exist
    batch_files = [
        "scripts/network/emergency_ps5_unblock.bat",
        "scripts/network/ps5_restore_final.bat",
        "scripts/network/ps5_wifi_fix.bat"
    ]
    
    for batch_file in batch_files:
        if os.path.exists(batch_file):
            print(f"✅ Batch file found: {batch_file}")
        else:
            print(f"❌ Batch file not found: {batch_file}")
    
    # Test 4: Check network connectivity
    print("\nTesting network connectivity...")
    try:
        result = subprocess.run(["ping", "-n", "4", "8.8.8.8"], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            print("✅ Internet connectivity: OK")
        else:
            print("❌ Internet connectivity: FAILED")
    except Exception as e:
        print(f"❌ Network test failed: {e}")
    
    # Test 5: Check ARP table for PS5
    print("\nChecking ARP table for PS5 devices...")
    try:
        result = subprocess.run(["arp", "-a"], capture_output=True, text=True)
        if result.returncode == 0:
            arp_output = result.stdout.lower()
            if "sony" in arp_output or "playstation" in arp_output:
                print("✅ PS5 device found in ARP table")
            else:
                print("ℹ️ No PS5 devices found in ARP table")
        else:
            print("❌ Failed to get ARP table")
    except Exception as e:
        print(f"❌ ARP table check failed: {e}")
    
    print("\n" + "=" * 50)
    print("PS5 RESTORATION TEST COMPLETE")
    print("=" * 50)
    print()
    print("If PS5 restoration is not working:")
    print("1. Run 'scripts/network/emergency_ps5_unblock.bat' as Administrator")
    print("2. Run 'scripts/network/ps5_restore_final.bat' as Administrator")
    print("3. Check PS5 network settings (Use LAN Cable, not WiFi)")
    print("4. Restart PS5 and router if needed")
    print()
    
    return True

if __name__ == "__main__":
    test_ps5_restore() 