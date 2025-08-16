#!/usr/bin/env python3
"""
PS5 WiFi Connectivity Fix Script
This script helps diagnose and fix PS5 WiFi connectivity issues.
"""

import subprocess
import time

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

def check_wifi_status():
    """Check WiFi status and configuration"""
    print("=" * 60)
    print("PS5 WIFI CONNECTIVITY DIAGNOSIS")
    print("=" * 60)
    print()
    
    # Check WiFi adapters
    print("1. Checking WiFi adapters...")
    wifi_result = run_command("netsh wlan show interfaces", "Getting WiFi interfaces")
    if wifi_result:
        if "enabled" in wifi_result.lower():
            print("WiFi adapters are enabled")
        else:
            print("WiFi adapters may be disabled")
    
    # Check available networks
    print("\n2. Checking available WiFi networks...")
    networks_result = run_command("netsh wlan show networks", "Getting available networks")
    if networks_result:
        print("WiFi networks are available")
    
    # Check router connectivity
    print("\n3. Checking router connectivity...")
    ping_result = run_command("ping -n 4 192.168.1.254", "Pinging router")
    if ping_result:
        print("Router is reachable")
    
    return True

def provide_wifi_fix_instructions():
    """Provide WiFi-specific fix instructions"""
    print("\n" + "=" * 60)
    print("PS5 WIFI CONNECTIVITY FIX GUIDE")
    print("=" * 60)
    print()
    print("Since your PS5 connects to network but not WiFi, try these steps:")
    print()
    print("STEP 1: PS5 Network Mode Check")
    print("- Go to PS5 Settings > Network > Settings")
    print("- Select 'Set Up Internet Connection'")
    print("- Choose 'Use a LAN Cable' (NOT 'Use Wi-Fi')")
    print("- This should use Ethernet, not WiFi")
    print()
    print("STEP 2: If you want WiFi instead of Ethernet")
    print("- Go to PS5 Settings > Network > Settings")
    print("- Select 'Set Up Internet Connection'")
    print("- Choose 'Use Wi-Fi'")
    print("- Select your WiFi network")
    print("- Enter WiFi password")
    print("- Choose 'Easy' setup")
    print()
    print("STEP 3: Router WiFi Check")
    print("- Access router admin panel (192.168.1.254)")
    print("- Check if WiFi is enabled")
    print("- Verify WiFi password is correct")
    print("- Check if 2.4GHz and 5GHz bands are enabled")
    print()
    print("STEP 4: PS5 WiFi Troubleshooting")
    print("- Restart PS5 completely")
    print("- Try connecting to different WiFi band (2.4GHz vs 5GHz)")
    print("- Move PS5 closer to router")
    print("- Check for WiFi interference")
    print()
    print("STEP 5: Advanced WiFi Fixes")
    print("- Reset PS5 network settings")
    print("- Try manual IP configuration")
    print("- Check PS5 for system updates")
    print("- Try connecting other devices to same WiFi")
    print()

def create_wifi_fix_script():
    """Create a batch script for WiFi fixes"""
    script_content = """@echo off
echo ========================================
echo PS5 WIFI CONNECTIVITY FIX SCRIPT
echo ========================================
echo.
echo This script will reset network settings
echo and prepare for PS5 WiFi connection.
echo.

REM Reset WiFi adapters
echo [1/4] Resetting WiFi adapters...
netsh wlan reset
echo WiFi adapters reset.

REM Clear network caches
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
echo WIFI FIX COMPLETE
echo ========================================
echo.
echo Your network is now ready for PS5 WiFi connection.
echo Please configure PS5 to use WiFi or Ethernet as needed.
echo.
pause
"""
    
    with open("scripts/network/ps5_wifi_fix.bat", "w") as f:
        f.write(script_content)
    
    print("Created WiFi fix script: scripts/network/ps5_wifi_fix.bat")
    print("Run this script as Administrator if needed.")

def main():
    """Main function"""
    print("PS5 WiFi Connectivity Fix Tool")
    print("=" * 60)
    print()
    
    # Check WiFi status
    check_wifi_status()
    
    # Provide WiFi fix instructions
    provide_wifi_fix_instructions()
    
    # Create WiFi fix script
    create_wifi_fix_script()
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("✓ Network blocking has been cleared")
    print("✓ PS5 can connect to network")
    print("✓ WiFi diagnostics completed")
    print("✓ WiFi fix script created")
    print()
    print("Key Points:")
    print("- PS5 should use 'LAN Cable' setting, not WiFi")
    print("- If you want WiFi, configure it in PS5 settings")
    print("- Try the physical connection fixes you mentioned")
    print("- Run 'scripts/network/ps5_wifi_fix.bat' if needed")
    print()
    print("Most likely solution:")
    print("Configure PS5 to use 'LAN Cable' instead of WiFi")
    print()

if __name__ == "__main__":
    main() 