#!/usr/bin/env python3
"""
Simple PS5 Disconnect Tool
Direct network disruption for PS5 - no GUI, no complex dependencies
"""

import subprocess
import socket
import time
import platform
import os
import sys

def check_admin():
    """Check if running as administrator"""
    try:
        if platform.system() == "Windows":
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        else:
            return os.geteuid() == 0
    except:
        return False

def get_network_info():
    """Get basic network information"""
    try:
        # Get local IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        
        # Get gateway (simplified)
        gateway = "192.168.1.1"  # Common default
        
        return {
            "local_ip": local_ip,
            "gateway": gateway,
            "subnet": '.'.join(local_ip.split('.')[:-1]) + '.0/24'
        }
    except Exception as e:
        print(f"Error getting network info: {e}")
        return {
            "local_ip": "192.168.1.100",
            "gateway": "192.168.1.1",
            "subnet": "192.168.1.0/24"
        }

def ping_test(target_ip):
    """Test if target responds to ping"""
    try:
        if platform.system() == "Windows":
            result = subprocess.run(["ping", "-n", "1", "-w", "1000", target_ip], 
                                  capture_output=True, text=True, timeout=5)
        else:
            result = subprocess.run(["ping", "-c", "1", "-W", "1", target_ip], 
                                  capture_output=True, text=True, timeout=5)
        
        return result.returncode == 0
    except Exception as e:
        print(f"Ping test failed: {e}")
        return False

def block_with_firewall(target_ip):
    """Block PS5 using Windows Firewall"""
    print(f"Adding firewall rules to block {target_ip}...")
    
    try:
        # Add inbound rule
        subprocess.run([
            "netsh", "advfirewall", "firewall", "add", "rule",
            f"name=PS5Block_{target_ip.replace('.', '_')}_In",
            "dir=in", "action=block", f"remoteip={target_ip}", "enable=yes"
        ], capture_output=True, timeout=5)
        
        # Add outbound rule
        subprocess.run([
            "netsh", "advfirewall", "firewall", "add", "rule",
            f"name=PS5Block_{target_ip.replace('.', '_')}_Out",
            "dir=out", "action=block", f"remoteip={target_ip}", "enable=yes"
        ], capture_output=True, timeout=5)
        
        print(f"✅ Firewall rules added for {target_ip}")
        return True
        
    except Exception as e:
        print(f"❌ Firewall blocking failed: {e}")
        return False

def unblock_firewall(target_ip):
    """Remove firewall rules"""
    print(f"Removing firewall rules for {target_ip}...")
    
    try:
        # Remove inbound rule
        subprocess.run([
            "netsh", "advfirewall", "firewall", "delete", "rule",
            f"name=PS5Block_{target_ip.replace('.', '_')}_In"
        ], capture_output=True, timeout=5)
        
        # Remove outbound rule
        subprocess.run([
            "netsh", "advfirewall", "firewall", "delete", "rule",
            f"name=PS5Block_{target_ip.replace('.', '_')}_Out"
        ], capture_output=True, timeout=5)
        
        print(f"✅ Firewall rules removed for {target_ip}")
        return True
        
    except Exception as e:
        print(f"❌ Firewall unblocking failed: {e}")
        return False

def add_route_blackhole(target_ip):
    """Add route blackhole for PS5"""
    print(f"Adding route blackhole for {target_ip}...")
    
    try:
        # Add blackhole route
        subprocess.run([
            "route", "add", target_ip, "0.0.0.0", "metric", "1"
        ], capture_output=True, timeout=5)
        
        print(f"✅ Route blackhole added for {target_ip}")
        return True
        
    except Exception as e:
        print(f"❌ Route blackhole failed: {e}")
        return False

def remove_route_blackhole(target_ip):
    """Remove route blackhole"""
    print(f"Removing route blackhole for {target_ip}...")
    
    try:
        # Remove blackhole route
        subprocess.run([
            "route", "delete", target_ip
        ], capture_output=True, timeout=5)
        
        print(f"✅ Route blackhole removed for {target_ip}")
        return True
        
    except Exception as e:
        print(f"❌ Route blackhole removal failed: {e}")
        return False

def main():
    """Main function"""
    print("🎮 Simple PS5 Disconnect Tool")
    print("=" * 40)
    
    # Check admin privileges
    if not check_admin():
        print("❌ This tool requires administrator privileges")
        print("Right-click and select 'Run as administrator'")
        input("Press Enter to exit...")
        return
    
    print("✅ Administrator privileges confirmed")
    
    # Get network info
    network_info = get_network_info()
    print(f"📡 Network: {network_info['local_ip']} -> {network_info['gateway']}")
    
    # Get target PS5 IP
    target_ip = input("Enter PS5 IP address: ").strip()
    if not target_ip:
        print("❌ No IP address provided")
        return
    
    # Test connectivity
    print(f"\n🔍 Testing connectivity to {target_ip}...")
    if ping_test(target_ip):
        print(f"✅ {target_ip} is reachable")
    else:
        print(f"❌ {target_ip} is not reachable")
        print("Continue anyway? (y/n): ", end="")
        if input().lower() != 'y':
            return
    
    # Choose action
    print(f"\n🎯 Choose action:")
    print("1. Block PS5 (Firewall)")
    print("2. Block PS5 (Route Blackhole)")
    print("3. Unblock PS5 (Firewall)")
    print("4. Unblock PS5 (Route Blackhole)")
    print("5. Test connectivity")
    
    choice = input("Enter choice (1-5): ").strip()
    
    if choice == "1":
        block_with_firewall(target_ip)
    elif choice == "2":
        add_route_blackhole(target_ip)
    elif choice == "3":
        unblock_firewall(target_ip)
    elif choice == "4":
        remove_route_blackhole(target_ip)
    elif choice == "5":
        if ping_test(target_ip):
            print(f"✅ {target_ip} is reachable")
        else:
            print(f"❌ {target_ip} is not reachable")
    else:
        print("❌ Invalid choice")
    
    print("\n✅ Operation completed")

if __name__ == "__main__":
    main() 