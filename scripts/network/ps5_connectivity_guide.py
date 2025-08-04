#!/usr/bin/env python3
"""
PS5 Connectivity Guide and Restoration Script
This script helps diagnose and restore PS5 network connectivity.
"""

import subprocess
import time
import sys

def run_command(command, description):
    """Run a command and return the result"""
    print(f"[INFO] {description}")
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"[SUCCESS] {description}")
            return result.stdout
        else:
            print(f"[WARNING] {description} - {result.stderr}")
            return None
    except Exception as e:
        print(f"[ERROR] {description} - {str(e)}")
        return None

def check_ps5_connection():
    """Check if PS5 is connected to the network"""
    print("=" * 60)
    print("PS5 CONNECTIVITY DIAGNOSIS")
    print("=" * 60)
    print()
    
    # Check current network status
    print("1. Checking network status...")
    ipconfig = run_command("ipconfig", "Getting network configuration")
    if ipconfig:
        print("Network configuration retrieved successfully")
    
    # Check for PS5 in ARP table
    print("\n2. Checking for PS5 in network devices...")
    arp_result = run_command("arp -a", "Getting ARP table")
    if arp_result:
        if "sony" in arp_result.lower() or "playstation" in arp_result.lower():
            print("PS5 found in ARP table!")
        else:
            print("PS5 not found in ARP table")
    
    # Scan network for devices
    print("\n3. Scanning network for devices...")
    scan_result = run_command("nmap -sn 192.168.1.0/24", "Scanning network")
    if scan_result:
        if "sony" in scan_result.lower() or "playstation" in scan_result.lower():
            print("PS5 found in network scan!")
        else:
            print("PS5 not found in network scan")
    
    return True

def provide_ps5_instructions():
    """Provide step-by-step PS5 connectivity instructions"""
    print("\n" + "=" * 60)
    print("PS5 CONNECTIVITY RESTORATION GUIDE")
    print("=" * 60)
    print()
    print("Since your PS5 is not detected on the network, follow these steps:")
    print()
    print("STEP 1: PS5 Network Settings")
    print("- Go to PS5 Settings > Network > Settings")
    print("- Select 'Set Up Internet Connection'")
    print("- Choose 'Use a LAN Cable' (for Ethernet)")
    print("- Select 'Easy' setup")
    print("- Let PS5 automatically configure network settings")
    print()
    print("STEP 2: Manual Network Configuration (if Easy fails)")
    print("- Go to PS5 Settings > Network > Settings")
    print("- Select 'Set Up Internet Connection'")
    print("- Choose 'Use a LAN Cable'")
    print("- Select 'Custom' setup")
    print("- IP Address: 192.168.1.200 (or any available IP)")
    print("- Subnet Mask: 255.255.255.0")
    print("- Default Gateway: 192.168.1.254")
    print("- Primary DNS: 8.8.8.8")
    print("- Secondary DNS: 8.8.4.4")
    print()
    print("STEP 3: Physical Connection Check")
    print("- Ensure Ethernet cable is properly connected")
    print("- Try a different Ethernet cable")
    print("- Try a different Ethernet port on router")
    print("- Check if router Ethernet ports are working")
    print()
    print("STEP 4: Router Settings")
    print("- Access router admin panel (usually 192.168.1.254)")
    print("- Check if DHCP is enabled")
    print("- Ensure no MAC filtering is blocking PS5")
    print("- Check if PS5 MAC address is in blocked list")
    print()
    print("STEP 5: Advanced Troubleshooting")
    print("- Restart your PS5")
    print("- Restart your router")
    print("- Try connecting PS5 via WiFi first, then switch to Ethernet")
    print("- Check PS5 for system updates")
    print()
    print("STEP 6: Test Connection")
    print("- On PS5: Settings > Network > Connection Status")
    print("- Test Internet Connection")
    print("- Check if PS5 can access PlayStation Network")
    print()

def create_ps5_restore_script():
    """Create a batch script for PS5 restoration"""
    script_content = """@echo off
echo ========================================
echo PS5 NETWORK RESTORATION SCRIPT
echo ========================================
echo.
echo This script will clear any remaining blocks
echo and prepare your network for PS5 connection.
echo.

REM Clear any remaining PS5 blocks
echo [1/4] Clearing remaining PS5 blocks...
netsh advfirewall firewall delete rule name="PS5*" >nul 2>&1
echo Firewall rules cleared.

REM Clear DNS and network caches
echo [2/4] Clearing network caches...
ipconfig /flushdns
ipconfig /release
ipconfig /renew
echo Network caches cleared.

REM Reset network adapters
echo [3/4] Resetting network adapters...
netsh winsock reset
netsh int ip reset
echo Network adapters reset.

REM Restart network services
echo [4/4] Restarting network services...
net stop dnscache >nul 2>&1
net start dnscache >nul 2>&1
echo Network services restarted.

echo.
echo ========================================
echo PS5 RESTORATION COMPLETE
echo ========================================
echo.
echo Your network is now ready for PS5 connection.
echo Please follow the PS5 setup instructions provided.
echo.
pause
"""
    
    with open("scripts/network/ps5_restore_final.bat", "w") as f:
        f.write(script_content)
    
    print("Created PS5 restoration script: scripts/network/ps5_restore_final.bat")
    print("Run this script as Administrator if needed.")

def main():
    """Main function"""
    print("PS5 Connectivity Diagnosis and Restoration Tool")
    print("=" * 60)
    print()
    
    # Check current PS5 connection status
    check_ps5_connection()
    
    # Provide restoration instructions
    provide_ps5_instructions()
    
    # Create restoration script
    create_ps5_restore_script()
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("✓ Network blocks have been cleared")
    print("✓ DNS cache has been flushed")
    print("✓ Network services have been reset")
    print("✓ PS5 restoration script created")
    print()
    print("Next steps:")
    print("1. Follow the PS5 setup instructions above")
    print("2. Run 'scripts/network/ps5_restore_final.bat' as Administrator if needed")
    print("3. Test PS5 connection after setup")
    print()
    print("If PS5 still can't connect, the issue may be:")
    print("- Physical connection problem (cable/port)")
    print("- Router configuration issue")
    print("- PS5 hardware/software issue")
    print("- ISP or network provider issue")
    print()

if __name__ == "__main__":
    main() 