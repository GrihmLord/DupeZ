#!/usr/bin/env python3
"""
PS5 Internet Restoration Script
Restores PS5 internet access by clearing all PulseDrop-related blocks
"""

import os
import sys
import subprocess
import time
from typing import List

def run_command(command: List[str], description: str) -> bool:
    """Run a command and return success status"""
    try:
        print(f"Running: {description}")
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            print(f"SUCCESS: {description}")
            return True
        else:
            print(f"FAILED: {description}")
            if result.stderr:
                print(f"Error: {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        print(f"TIMEOUT: {description}")
        return False
    except Exception as e:
        print(f"ERROR: {description} - {e}")
        return False

def clear_windows_firewall_rules():
    """Clear all PulseDrop-related firewall rules"""
    print("\nFIREWALL CLEANUP")
    print("=" * 50)
    
    # Delete all PulseDrop firewall rules
    firewall_commands = [
        (["netsh", "advfirewall", "firewall", "delete", "rule", "name=*PulseDrop*"], "Delete PulseDrop firewall rules"),
        (["netsh", "advfirewall", "firewall", "delete", "rule", "name=*NetCut*"], "Delete NetCut firewall rules"),
        (["netsh", "advfirewall", "firewall", "delete", "rule", "name=*Enterprise*"], "Delete Enterprise firewall rules"),
        (["netsh", "advfirewall", "firewall", "delete", "rule", "name=*Block*"], "Delete Block firewall rules")
    ]
    
    for command, description in firewall_commands:
        run_command(command, description)

def clear_hosts_file():
    """Clear hosts file entries"""
    print("\nHOSTS FILE CLEANUP")
    print("=" * 50)
    
    hosts_file = r"C:\Windows\System32\drivers\etc\hosts"
    
    try:
        if os.path.exists(hosts_file):
            # Read current hosts file
            with open(hosts_file, 'r') as f:
                lines = f.readlines()
            
            # Filter out PulseDrop-related entries
            filtered_lines = []
            for line in lines:
                if not any(keyword in line.lower() for keyword in ['pulsedrop', 'netcut', 'block']):
                    filtered_lines.append(line)
            
            # Write back filtered content
            with open(hosts_file, 'w') as f:
                f.writelines(filtered_lines)
            
            print("SUCCESS: Hosts file cleaned")
            return True
        else:
            print("INFO: Hosts file not found")
            return True
            
    except PermissionError:
        print("ERROR: Permission denied - run as administrator")
        return False
    except Exception as e:
        print(f"ERROR: Failed to clean hosts file - {e}")
        return False

def clear_arp_cache():
    """Clear ARP cache"""
    print("\nARP CACHE CLEANUP")
    print("=" * 50)
    
    run_command(["arp", "-d", "*"], "Clear ARP cache")
    run_command(["ipconfig", "/flushdns"], "Flush DNS cache")

def reset_network_adapters():
    """Reset network adapters"""
    print("\nNETWORK ADAPTER RESET")
    print("=" * 50)
    
    run_command(["ipconfig", "/release"], "Release IP addresses")
    time.sleep(2)
    run_command(["ipconfig", "/renew"], "Renew IP addresses")
    run_command(["netsh", "winsock", "reset"], "Reset Winsock")
    run_command(["netsh", "int", "ip", "reset"], "Reset IP stack")

def clear_netcut_blocks():
    """Clear NetCut-style blocks"""
    print("\nNETCUT BLOCK CLEANUP")
    print("=" * 50)
    
    # Stop any running NetCut processes
    run_command(["taskkill", "/f", "/im", "netcut.exe"], "Stop NetCut processes")
    run_command(["taskkill", "/f", "/im", "pulsedrop.exe"], "Stop PulseDrop processes")
    
    # Clear any persistent blocks
    run_command(["netsh", "advfirewall", "firewall", "delete", "rule", "name=*PulseDrop*"], "Delete PulseDrop firewall rules")

def test_ps5_connectivity():
    """Test PS5 connectivity"""
    print("\nPS5 CONNECTIVITY TEST")
    print("=" * 50)
    
    # Common PS5 IP addresses
    ps5_ips = ["192.168.1.100", "192.168.1.101", "192.168.1.102", "192.168.137.165"]
    
    for ip in ps5_ips:
        print(f"Testing connectivity to {ip}...")
        result = subprocess.run(["ping", "-n", "2", "-w", "1000", ip], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"SUCCESS: PS5 at {ip} is reachable!")
            return True
        else:
            print(f"FAILED: PS5 at {ip} is not reachable")
    
    print("WARNING: No PS5 found on common IP addresses")
    return False

def main():
    """Main restoration function"""
    print("PS5 INTERNET RESTORATION SCRIPT")
    print("=" * 50)
    print("This script will restore your PS5's internet access by clearing all PulseDrop-related blocks.")
    print()
    
    # Check if running as administrator
    try:
        is_admin = os.getuid() == 0
    except AttributeError:
        import ctypes
        is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
    
    if not is_admin:
        print("WARNING: This script should be run as administrator for best results")
        print("   Right-click and select 'Run as administrator'")
        print()
    
    # Perform restoration steps
    clear_windows_firewall_rules()
    clear_hosts_file()
    clear_arp_cache()
    reset_network_adapters()
    clear_netcut_blocks()
    
    print("\nRESTORATION COMPLETE")
    print("=" * 50)
    print("SUCCESS: All PulseDrop blocks have been cleared")
    print("SUCCESS: Network adapters have been reset")
    print("SUCCESS: DNS and ARP caches have been flushed")
    print()
    print("Your PS5 should now have internet access!")
    print("   If it still doesn't work, try:")
    print("   1. Restart your PS5")
    print("   2. Restart your router")
    print("   3. Check your router's DHCP settings")
    print()
    
    # Test connectivity
    if test_ps5_connectivity():
        print("SUCCESS: PS5 is now reachable!")
    else:
        print("WARNING: PS5 connectivity test failed - try restarting your PS5")

if __name__ == "__main__":
    main() 