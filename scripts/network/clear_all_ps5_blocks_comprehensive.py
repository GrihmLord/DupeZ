#!/usr/bin/env python3
"""
Comprehensive PS5 Block Clearer
Clears all external blocks that might be affecting PS5 connectivity
"""

import subprocess
import os
import shutil
from datetime import datetime

def run_command(cmd, capture_output=True):
    """Run a command and return the result"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=capture_output, text=True)
        return result.returncode == 0, result.stdout, result.stderr
    except Exception as e:
        return False, "", str(e)

def clear_firewall_rules():
    """Clear all PS5 and DupeZ firewall rules"""
    print("🔥 Clearing Windows Firewall rules...")
    
    rules_to_delete = [
        "*PS5*",
        "*DupeZ*",
        "*Internet_Block*",
        "*DNS_Block*",
        "*Port_Block*"
    ]
    
    for rule in rules_to_delete:
        cmd = f'netsh advfirewall firewall delete rule name="{rule}"'
        success, _, _ = run_command(cmd)
        if success:
            print(f"  ✓ Cleared rule: {rule}")
        else:
            print(f"  - No rule found: {rule}")
    
    print("✅ Firewall rules cleared")

def clear_route_blocks():
    """Clear all route table blocks"""
    print("🛣️  Clearing route table blocks...")
    
    # Get current routes
    success, output, _ = run_command("route print")
    if not success:
        print("❌ Failed to get route table")
        return
    
    # Find blocked routes (routes pointing to 127.0.0.1)
    blocked_routes = []
    for line in output.split('\n'):
        if '127.0.0.1' in line and '192.168.' in line:
            parts = line.split()
            if len(parts) >= 4:
                target_ip = parts[0]
                if target_ip.startswith('192.168.'):
                    blocked_routes.append(target_ip)
    
    # Delete blocked routes
    for ip in blocked_routes:
        cmd = f"route delete {ip}"
        success, _, _ = run_command(cmd)
        if success:
            print(f"  ✓ Deleted route: {ip}")
        else:
            print(f"  - Failed to delete route: {ip}")
    
    print("✅ Route table blocks cleared")

def clear_hosts_blocks():
    """Clear all blocks from hosts file"""
    print("📝 Clearing hosts file blocks...")
    
    hosts_file = r"C:\Windows\System32\drivers\etc\hosts"
    
    # Create backup
    backup_file = f"{hosts_file}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    try:
        shutil.copy2(hosts_file, backup_file)
        print(f"  ✓ Created backup: {backup_file}")
    except Exception as e:
        print(f"  ⚠️  Failed to create backup: {e}")
    
    # Read hosts file
    try:
        with open(hosts_file, 'r') as f:
            lines = f.readlines()
    except Exception as e:
        print(f"❌ Failed to read hosts file: {e}")
        return
    
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
    except Exception as e:
        print(f"❌ Failed to write hosts file: {e}")
        return
    
    print("✅ Hosts file blocks cleared")

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
    
    print("✅ Caches cleared")

def test_connectivity():
    """Test connectivity to potential PS5 devices"""
    print("🔍 Testing PS5 connectivity...")
    
    # Common PS5 IP addresses found in your network
    test_ips = [
        "192.168.1.93",
        "192.168.1.96", 
        "192.168.1.154",
        "192.168.1.180",
        "192.168.1.181",
        "192.168.137.165",
        "192.168.137.217"
    ]
    
    reachable_ips = []
    
    for ip in test_ips:
        success, _, _ = run_command(f"ping -n 1 {ip}")
        if success:
            print(f"  ✅ {ip} is reachable")
            reachable_ips.append(ip)
        else:
            print(f"  ❌ {ip} is not reachable")
    
    return reachable_ips

def main():
    """Main restoration function"""
    print("=" * 50)
    print("    PS5 Connection Restoration Script")
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
    
    # Perform all clearing operations
    clear_firewall_rules()
    print()
    
    clear_route_blocks()
    print()
    
    clear_hosts_blocks()
    print()
    
    clear_caches()
    print()
    
    # Test connectivity
    reachable_ips = test_connectivity()
    print()
    
    # Summary
    print("=" * 50)
    print("    Restoration Complete!")
    print("=" * 50)
    print()
    
    if reachable_ips:
        print(f"✅ Found {len(reachable_ips)} reachable devices:")
        for ip in reachable_ips:
            print(f"   • {ip}")
        print()
        print("Your PS5 should now have internet access!")
    else:
        print("❌ No devices are currently reachable")
        print("This might indicate:")
        print("   • PS5 is powered off")
        print("   • PS5 is connected via WiFi")
        print("   • Network configuration issues")
    
    print()
    print("If your PS5 still doesn't have internet:")
    print("1. Restart your PS5")
    print("2. Check your router settings")
    print("3. Try connecting via WiFi instead of Ethernet")
    print("4. Check if your PS5 is using a different IP address")
    print()
    
    input("Press Enter to exit...")

if __name__ == "__main__":
    main() 
