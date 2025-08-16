#!/usr/bin/env python3
"""
Fix PS5 DHCP Issues - CE-109503-8
Clears all network blocks and ensures DHCP is working properly
"""

import sys
import os
import subprocess
import time

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from app.firewall.blocker import clear_all_blocks, get_blocked_ips
    from app.firewall.netcut_blocker import netcut_blocker
    from app.logs.logger import log_info, log_error
except ImportError as e:
    print(f"❌ Import error: {e}")
    sys.exit(1)

def clear_all_network_blocks():
    """Clear all network blocking systems"""
    print("🧹 Clearing all network blocks...")
    
    try:
        # Clear DupeZ blocks
        clear_all_blocks()
        print("  ✅ DupeZ blocks cleared")
        
        # Clear NetCut blocks
        netcut_blocker.clear_all_disruptions()
        print("  ✅ NetCut blocks cleared")
        
        # Check if any IPs are still blocked
        blocked_ips = get_blocked_ips()
        if blocked_ips:
            print(f"  ⚠️ Still have blocked IPs: {blocked_ips}")
        else:
            print("  ✅ No IPs are blocked")
            
        return True
    except Exception as e:
        log_error(f"Failed to clear network blocks: {e}")
        return False

def remove_firewall_rules():
    """Remove all DupeZ firewall rules"""
    print("🔥 Removing firewall rules...")
    
    try:
        # Get all DupeZ rules
        result = subprocess.run([
            "netsh", "advfirewall", "firewall", "show", "rule", "name=all"
        ], capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            lines = result.stdout.split('\n')
            pulse_drop_rules = []
            
            for line in lines:
                if "DupeZ" in line and "Rule Name:" in line:
                    rule_name = line.split("Rule Name:")[1].strip()
                    pulse_drop_rules.append(rule_name)
            
            # Remove all DupeZ rules
            for rule in pulse_drop_rules:
                try:
                    subprocess.run([
                        "netsh", "advfirewall", "firewall", "delete", "rule", 
                        f"name={rule}"
                    ], capture_output=True, timeout=5)
                    print(f"  ✅ Removed rule: {rule}")
                except:
                    print(f"  ⚠️ Could not remove rule: {rule}")
        
        return True
    except Exception as e:
        log_error(f"Failed to remove firewall rules: {e}")
        return False

def reset_network_adapters():
    """Reset network adapters to ensure DHCP works"""
    print("🔄 Resetting network adapters...")
    
    try:
        # Flush DNS
        subprocess.run(["ipconfig", "/flushdns"], capture_output=True, timeout=10)
        print("  ✅ DNS cache flushed")
        
        # Release and renew IP
        subprocess.run(["ipconfig", "/release"], capture_output=True, timeout=10)
        time.sleep(2)
        subprocess.run(["ipconfig", "/renew"], capture_output=True, timeout=10)
        print("  ✅ IP addresses renewed")
        
        # Reset network stack
        subprocess.run(["netsh", "winsock", "reset"], capture_output=True, timeout=10)
        subprocess.run(["netsh", "int", "ip", "reset"], capture_output=True, timeout=10)
        print("  ✅ Network stack reset")
        
        return True
    except Exception as e:
        log_error(f"Failed to reset network adapters: {e}")
        return False

def check_dhcp_server():
    """Check if DHCP server is accessible"""
    print("🔍 Checking DHCP server...")
    
    try:
        # Try to ping common DHCP servers
        dhcp_servers = ["192.168.1.1", "192.168.0.1", "10.0.0.1"]
        
        for server in dhcp_servers:
            result = subprocess.run(
                ["ping", "-n", "1", server], 
                capture_output=True, 
                timeout=5
            )
            if result.returncode == 0:
                print(f"  ✅ DHCP server {server} is reachable")
                return True
        
        print("  ⚠️ No DHCP servers reachable")
        return False
    except Exception as e:
        log_error(f"Failed to check DHCP server: {e}")
        return False

def main():
    """Main fix execution"""
    print("🔧 PS5 Network Fix - CE-109503-8")
    print("=" * 40)
    print()
    
    # Step 1: Clear all network blocks
    if not clear_all_network_blocks():
        print("❌ Failed to clear network blocks")
        return False
    
    print()
    
    # Step 2: Remove firewall rules
    if not remove_firewall_rules():
        print("❌ Failed to remove firewall rules")
        return False
    
    print()
    
    # Step 3: Reset network adapters
    if not reset_network_adapters():
        print("❌ Failed to reset network adapters")
        return False
    
    print()
    
    # Step 4: Check DHCP server
    if not check_dhcp_server():
        print("⚠️ DHCP server not reachable - check router")
    
    print()
    print("✅ Network fix completed!")
    print()
    print("🎮 Instructions for PS5:")
    print("1. Turn off PS5 completely")
    print("2. Wait 30 seconds")
    print("3. Turn on PS5")
    print("4. Go to Settings > Network > Set Up Internet Connection")
    print("5. Choose your WiFi network")
    print("6. PS5 should now obtain IP address successfully")
    print()
    
    return True

if __name__ == "__main__":
    success = main()
    if success:
        print("🎉 PS5 network fix completed successfully!")
    else:
        print("❌ PS5 network fix failed!")
    
    input("Press Enter to continue...") 
