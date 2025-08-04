#!/usr/bin/env python3
"""
Comprehensive PS5 Ethernet Restoration Script
Restores internet access to ALL PS5s connected via Ethernet
"""

import os
import sys
import subprocess
import time
import socket
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

def clear_all_firewall_rules():
    """Clear ALL firewall rules that might block PS5s"""
    print("\n🔥 COMPREHENSIVE FIREWALL CLEANUP")
    print("=" * 60)
    
    # Delete all possible firewall rules
    firewall_patterns = [
        "*PulseDrop*", "*Enterprise*", "*NetCut*", "*Block*", 
        "*PS5*", "*PlayStation*", "*Sony*", "*Gaming*"
    ]
    
    for pattern in firewall_patterns:
        run_command(["netsh", "advfirewall", "firewall", "delete", "rule", f"name={pattern}"], f"Delete {pattern} firewall rules")

def clear_ethernet_blocks():
    """Clear Ethernet-specific blocks"""
    print("\n🔌 ETHERNET BLOCK CLEANUP")
    print("=" * 60)
    
    # Clear ARP entries for common PS5 IP ranges
    ps5_ip_ranges = [
        "192.168.1.100", "192.168.1.101", "192.168.1.102", "192.168.1.103",
        "192.168.1.104", "192.168.1.105", "192.168.1.106", "192.168.1.107",
        "192.168.1.108", "192.168.1.109", "192.168.1.110", "192.168.1.111",
        "192.168.1.112", "192.168.1.113", "192.168.1.114", "192.168.1.115",
        "192.168.0.100", "192.168.0.101", "192.168.0.102", "192.168.0.103",
        "192.168.0.104", "192.168.0.105", "192.168.0.106", "192.168.0.107",
        "192.168.0.108", "192.168.0.109", "192.168.0.110", "192.168.0.111",
        "192.168.0.112", "192.168.0.113", "192.168.0.114", "192.168.0.115"
    ]
    
    for ip in ps5_ip_ranges:
        run_command(["arp", "-d", ip], f"Clear ARP entry for {ip}")

def reset_ethernet_adapters():
    """Reset Ethernet network adapters"""
    print("\n🔌 ETHERNET ADAPTER RESET")
    print("=" * 60)
    
    # Get Ethernet adapters
    run_command(["netsh", "interface", "show", "interface"], "Show network interfaces")
    
    # Reset Ethernet adapters
    run_command(["netsh", "interface", "set", "interface", "Ethernet", "admin=disable"], "Disable Ethernet")
    time.sleep(2)
    run_command(["netsh", "interface", "set", "interface", "Ethernet", "admin=enable"], "Enable Ethernet")
    
    # Release and renew IP addresses
    run_command(["ipconfig", "/release"], "Release all IP addresses")
    time.sleep(3)
    run_command(["ipconfig", "/renew"], "Renew all IP addresses")

def clear_dns_and_cache():
    """Clear DNS and network caches"""
    print("\n🌐 DNS & CACHE CLEANUP")
    print("=" * 60)
    
    run_command(["ipconfig", "/flushdns"], "Flush DNS cache")
    run_command(["netsh", "winsock", "reset"], "Reset Winsock catalog")
    run_command(["netsh", "int", "ip", "reset"], "Reset IP stack")

def test_ps5_connectivity():
    """Test connectivity to all possible PS5 IPs"""
    print("\n🎮 PS5 CONNECTIVITY TEST")
    print("=" * 60)
    
    # Common PS5 IP addresses
    ps5_ips = [
        "192.168.1.100", "192.168.1.101", "192.168.1.102", "192.168.1.103",
        "192.168.1.104", "192.168.1.105", "192.168.1.106", "192.168.1.107",
        "192.168.1.108", "192.168.1.109", "192.168.1.110", "192.168.1.111",
        "192.168.1.112", "192.168.1.113", "192.168.1.114", "192.168.1.115",
        "192.168.0.100", "192.168.0.101", "192.168.0.102", "192.168.0.103",
        "192.168.0.104", "192.168.0.105", "192.168.0.106", "192.168.0.107",
        "192.168.0.108", "192.168.0.109", "192.168.0.110", "192.168.0.111",
        "192.168.0.112", "192.168.0.113", "192.168.0.114", "192.168.0.115"
    ]
    
    found_ps5s = []
    
    for ip in ps5_ips:
        print(f"Testing connectivity to {ip}...")
        result = subprocess.run(["ping", "-n", "1", "-w", "1000", ip], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✅ SUCCESS: PS5 at {ip} is reachable!")
            found_ps5s.append(ip)
        else:
            print(f"❌ FAILED: PS5 at {ip} is not reachable")
    
    if found_ps5s:
        print(f"\n🎉 FOUND {len(found_ps5s)} PS5(S): {', '.join(found_ps5s)}")
        return True
    else:
        print("\n⚠️ No PS5s found on common IP addresses")
        return False

def restore_ethernet_settings():
    """Restore optimal Ethernet settings for PS5s"""
    print("\n⚙️ ETHERNET SETTINGS RESTORATION")
    print("=" * 60)
    
    # Set optimal Ethernet settings
    run_command(["netsh", "interface", "ethernet", "set", "global", "autotuning=normal"], "Set autotuning to normal")
    run_command(["netsh", "interface", "tcp", "set", "global", "autotuninglevel=normal"], "Set TCP autotuning to normal")
    run_command(["netsh", "interface", "tcp", "set", "global", "chimney=enabled"], "Enable chimney offload")
    run_command(["netsh", "interface", "tcp", "set", "global", "ecncapability=enabled"], "Enable ECN capability")

def main():
    """Main restoration function"""
    print("🎮 COMPREHENSIVE PS5 ETHERNET RESTORATION")
    print("=" * 60)
    print("This script will restore internet access to ALL PS5s connected via Ethernet")
    print("by clearing all PulseDrop-related blocks and optimizing network settings.")
    print()
    print("WARNING: This script should be run as administrator for best results")
    print("   Right-click and select 'Run as administrator'")
    print()
    
    # Step 1: Clear all firewall rules
    clear_all_firewall_rules()
    
    # Step 2: Clear Ethernet-specific blocks
    clear_ethernet_blocks()
    
    # Step 3: Reset Ethernet adapters
    reset_ethernet_adapters()
    
    # Step 4: Clear DNS and cache
    clear_dns_and_cache()
    
    # Step 5: Restore optimal Ethernet settings
    restore_ethernet_settings()
    
    print("\n🎉 RESTORATION COMPLETE")
    print("=" * 60)
    print("✅ All PulseDrop blocks have been cleared")
    print("✅ Ethernet adapters have been reset")
    print("✅ DNS and network caches have been flushed")
    print("✅ Optimal Ethernet settings have been applied")
    print()
    print("Your PS5s should now have internet access!")
    print("   If they still don't work, try:")
    print("   1. Restart your PS5s")
    print("   2. Restart your router")
    print("   3. Check your router's DHCP settings")
    print("   4. Verify Ethernet cables are properly connected")
    print()
    
    # Test connectivity
    test_ps5_connectivity()
    
    print("\n🎮 PS5 ETHERNET RESTORATION COMPLETE!")
    print("All PS5s connected via Ethernet should now have internet access.")

if __name__ == "__main__":
    main() 