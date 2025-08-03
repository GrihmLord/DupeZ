#!/usr/bin/env python3
"""
Unblock Specific MAC Address
Targets MAC address b40ad8b9bdb0 for unblocking
"""

import subprocess
import re
import os

def run_command(cmd, capture_output=True):
    """Run a command and return the result"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=capture_output, text=True)
        return result.returncode == 0, result.stdout, result.stderr
    except Exception as e:
        return False, "", str(e)

def find_device_by_mac(target_mac):
    """Find device IP by MAC address"""
    print(f"🔍 Looking for device with MAC: {target_mac}")
    
    # Get ARP table
    success, output, _ = run_command("arp -a")
    if not success:
        print("❌ Failed to get ARP table")
        return None
    
    # Parse ARP table for the target MAC
    target_mac_normalized = target_mac.replace(":", "").lower()
    
    for line in output.split('\n'):
        if target_mac_normalized in line.lower() or target_mac in line.lower():
            # Extract IP address from the line
            match = re.search(r'(\d+\.\d+\.\d+\.\d+)', line)
            if match:
                ip = match.group(1)
                print(f"✅ Found device: {ip}")
                return ip
    
    print("❌ Device not found in ARP table")
    return None

def clear_hosts_blocks():
    """Clear all blocks from hosts file"""
    print("📝 Clearing hosts file blocks...")
    
    hosts_file = r"C:\Windows\System32\drivers\etc\hosts"
    
    # Read hosts file
    try:
        with open(hosts_file, 'r') as f:
            lines = f.readlines()
    except Exception as e:
        print(f"❌ Failed to read hosts file: {e}")
        return False
    
    # Filter out blocked entries
    original_lines = []
    blocked_count = 0
    
    for line in lines:
        # Keep original lines (no localhost redirects)
        if not line.strip().endswith("localhost") and not line.strip().endswith("127.0.0.1"):
            original_lines.append(line)
        else:
            blocked_count += 1
    
    # Write back original content
    try:
        with open(hosts_file, 'w') as f:
            f.writelines(original_lines)
        print(f"  ✓ Removed {blocked_count} blocked entries")
        return True
    except Exception as e:
        print(f"❌ Failed to write hosts file: {e}")
        return False

def clear_route_blocks():
    """Clear route table blocks"""
    print("🛣️  Clearing route table blocks...")
    
    # Common blocked IPs
    blocked_ips = [
        "192.168.1.154", "192.168.1.180", "192.168.1.181",
        "192.168.137.165", "192.168.137.217", "192.168.1.93", "192.168.1.96"
    ]
    
    for ip in blocked_ips:
        cmd = f"route delete {ip}"
        success, _, _ = run_command(cmd)
        if success:
            print(f"  ✓ Deleted route: {ip}")
        else:
            print(f"  - No route found: {ip}")
    
    return True

def clear_caches():
    """Clear DNS and ARP caches"""
    print("🗑️  Clearing caches...")
    
    # Clear DNS cache
    success, _, _ = run_command("ipconfig /flushdns")
    if success:
        print("  ✓ DNS cache cleared")
    else:
        print("  ❌ Failed to clear DNS cache")
    
    # Clear ARP cache
    success, _, _ = run_command("arp -d *")
    if success:
        print("  ✓ ARP cache cleared")
    else:
        print("  ❌ Failed to clear ARP cache")
    
    return True

def test_connectivity(ip_address):
    """Test connectivity to a specific IP"""
    if not ip_address:
        return False
    
    print(f"🔍 Testing connectivity to {ip_address}...")
    success, _, _ = run_command(f"ping -n 1 {ip_address}")
    
    if success:
        print(f"  ✅ {ip_address} is reachable")
        return True
    else:
        print(f"  ❌ {ip_address} is not reachable")
        return False

def main():
    """Main unblock function"""
    target_mac = "b40ad8b9bdb0"
    
    print("=" * 50)
    print(f"    Unblock MAC Address: {target_mac}")
    print("=" * 50)
    print()
    
    # Check if running as administrator
    try:
        is_admin = os.getuid() == 0
    except AttributeError:
        is_admin = subprocess.run(['net', 'session'], capture_output=True).returncode == 0
    
    if not is_admin:
        print("⚠️  WARNING: This script should be run as Administrator")
        print("   Some operations may fail without admin privileges")
        print()
    
    # Find the device
    device_ip = find_device_by_mac(target_mac)
    print()
    
    # Clear all blocks
    clear_hosts_blocks()
    print()
    
    clear_route_blocks()
    print()
    
    clear_caches()
    print()
    
    # Test connectivity
    if device_ip:
        test_connectivity(device_ip)
    else:
        # Test common PS5 IPs
        test_ips = ["192.168.1.93", "192.168.1.96"]
        for ip in test_ips:
            test_connectivity(ip)
    
    print()
    print("=" * 50)
    print("    Unblock Complete!")
    print("=" * 50)
    print()
    
    if device_ip:
        print(f"✅ Device {target_mac} ({device_ip}) should now be unblocked!")
    else:
        print(f"✅ Device {target_mac} should now be unblocked!")
    
    print("If this is your PS5, it should now have internet access.")
    print()
    print("If it still doesn't work:")
    print("1. Restart your PS5")
    print("2. Check your router settings")
    print("3. Try connecting via WiFi instead of Ethernet")
    print()
    
    input("Press Enter to exit...")

if __name__ == "__main__":
    main() 