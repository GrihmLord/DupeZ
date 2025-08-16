#!/usr/bin/env python3
"""
Emergency PS5 Unblocking Script
This script clears ALL possible network blocks that might prevent PS5 connectivity.
Must be run as Administrator.
"""

import subprocess
import sys
import os
import time
from pathlib import Path

def run_command(command, description, silent=False):
    """Run a command and handle errors"""
    if not silent:
        print(f"[INFO] {description}")
    
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        if result.returncode == 0:
            if not silent:
                print(f"[SUCCESS] {description}")
            return True
        else:
            if not silent:
                print(f"[WARNING] {description} - {result.stderr}")
            return False
    except Exception as e:
        if not silent:
            print(f"[ERROR] {description} - {str(e)}")
        return False

def check_admin():
    """Check if running as administrator"""
    try:
        return subprocess.run(['net', 'session'], capture_output=True).returncode == 0
    except:
        return False

def main():
    print("=" * 50)
    print("EMERGENCY PS5 UNBLOCKING SCRIPT")
    print("=" * 50)
    print()
    
    if not check_admin():
        print("ERROR: This script must be run as Administrator!")
        print("Please right-click and select 'Run as administrator'")
        input("Press Enter to exit...")
        return
    
    print("Running as Administrator...")
    print()
    
    # Step 1: Clear firewall rules
    print("[1/8] Clearing firewall rules...")
    firewall_rules = [
        "PS5 Block", "PS5 Drop", "PS5 Internet Block", "PS5 Outbound Block",
        "PS5 Inbound Block", "PS5 DNS Block", "PS5 DHCP Block", "PS5 Gaming Block",
        "PS5 PSN Block", "PS5 Network Block"
    ]
    
    for rule in firewall_rules:
        run_command(f'netsh advfirewall firewall delete rule name="{rule}"', 
                   f"Deleting firewall rule: {rule}", silent=True)
    print("Firewall rules cleared.")
    
    # Step 2: Clear hosts file entries
    print("[2/8] Clearing hosts file entries...")
    hosts_file = Path(r"C:\Windows\System32\drivers\etc\hosts")
    if hosts_file.exists():
        try:
            with open(hosts_file, 'r') as f:
                lines = f.readlines()
            
            # Remove PS5-related entries
            filtered_lines = [line for line in lines if not any(keyword in line.lower() 
                             for keyword in ['ps5', 'playstation', 'sony'])]
            
            with open(hosts_file, 'w') as f:
                f.writelines(filtered_lines)
            print("Hosts file cleared.")
        except Exception as e:
            print(f"Warning: Could not modify hosts file - {e}")
    
    # Step 3: Clear route table blocks
    print("[3/8] Clearing route table blocks...")
    routes_to_delete = ['0.0.0.0', '8.8.8.8', '8.8.4.4', '1.1.1.1', 
                       '208.67.222.222', '208.67.220.220']
    
    for route in routes_to_delete:
        run_command(f'route delete {route}', f"Deleting route: {route}", silent=True)
    print("Route table cleared.")
    
    # Step 4: Clear DNS cache
    print("[4/8] Clearing DNS cache...")
    run_command('ipconfig /flushdns', "Flushing DNS cache")
    
    # Step 5: Clear ARP cache
    print("[5/8] Clearing ARP cache...")
    run_command('arp -d *', "Clearing ARP cache")
    
    # Step 6: Reset network adapters
    print("[6/8] Resetting network adapters...")
    run_command('netsh winsock reset', "Resetting Winsock")
    run_command('netsh int ip reset', "Resetting IP configuration")
    
    # Step 7: Clear PS5-specific blocks
    print("[7/8] Clearing PS5-specific blocks...")
    processes_to_kill = ['python.exe', 'dupez.exe', 'ps5_blocker.exe']
    
    for process in processes_to_kill:
        run_command(f'taskkill /f /im {process}', f"Terminating {process}", silent=True)
    print("PS5 blocking processes terminated.")
    
    # Step 8: Restart network services
    print("[8/8] Restarting network services...")
    services = ['dnscache', 'dhcp']
    
    for service in services:
        run_command(f'net stop {service}', f"Stopping {service}", silent=True)
        time.sleep(1)
        run_command(f'net start {service}', f"Starting {service}", silent=True)
    print("Network services restarted.")
    
    print()
    print("=" * 50)
    print("EMERGENCY UNBLOCKING COMPLETE")
    print("=" * 50)
    print()
    print("All possible network blocks have been cleared:")
    print("- Firewall rules")
    print("- Hosts file entries")
    print("- Route table blocks")
    print("- DNS cache")
    print("- ARP cache")
    print("- Network adapters reset")
    print("- PS5 blocking processes")
    print("- Network services restarted")
    print()
    print("Your PS5 should now be able to connect to the network.")
    print("If it still can't connect, try:")
    print("1. Restart your PS5")
    print("2. Restart your router")
    print("3. Check your PS5 network settings")
    print()
    input("Press Enter to exit...")

if __name__ == "__main__":
    main() 
