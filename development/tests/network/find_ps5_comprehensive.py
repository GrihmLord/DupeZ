#!/usr/bin/env python3
"""
Comprehensive PS5 Detection Script
Uses multiple methods to find PS5 devices on the network
"""

import subprocess
import socket
import threading
import time
import ipaddress
from concurrent.futures import ThreadPoolExecutor, as_completed

def ping_host(ip):
    """Ping a host to check if it's online"""
    try:
        result = subprocess.run(['ping', '-n', '1', '-w', '1000', ip], 
                              capture_output=True, text=True, timeout=2)
        return result.returncode == 0
    except:
        return False

def get_arp_table():
    """Get ARP table to find devices"""
    try:
        result = subprocess.run(['arp', '-a'], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout
        return ""
    except:
        return ""

def scan_network_comprehensive():
    """Comprehensive network scan for PS5"""
    print("🔍 Comprehensive PS5 Detection...")
    
    # Get local network info
    try:
        result = subprocess.run(['ipconfig'], capture_output=True, text=True)
        print("📡 Network Configuration:")
        for line in result.stdout.split('\n'):
            if 'IPv4' in line and '192.168' in line:
                print(f"  {line.strip()}")
    except:
        pass
    
    # Get ARP table
    print("\n📋 ARP Table (recently seen devices):")
    arp_table = get_arp_table()
    ps5_candidates = []
    
    for line in arp_table.split('\n'):
        if '192.168.1.' in line or '10.5.0.' in line:
            print(f"  {line.strip()}")
            # Check for PS5 indicators
            line_lower = line.lower()
            if any(indicator in line_lower for indicator in ['ps5', 'playstation', 'sony', 'b4:0a:d8', 'b4:0a:d9']):
                ps5_candidates.append(line.strip())
    
    if ps5_candidates:
        print(f"\n🎮 Potential PS5 devices found in ARP table:")
        for candidate in ps5_candidates:
            print(f"  🎮 {candidate}")
    
    # Comprehensive ping scan
    print(f"\n📡 Scanning network ranges...")
    networks = [
        "192.168.1.0/24",
        "10.5.0.0/24", 
        "192.168.0.0/24",
        "10.0.0.0/24"
    ]
    
    all_devices = []
    
    for network in networks:
        print(f"\n🔍 Scanning {network}...")
        try:
            network_obj = ipaddress.IPv4Network(network, strict=False)
            devices_found = 0
            
            with ThreadPoolExecutor(max_workers=50) as executor:
                future_to_ip = {executor.submit(ping_host, str(ip)): str(ip) 
                               for ip in network_obj.hosts()}
                
                for future in as_completed(future_to_ip):
                    ip = future_to_ip[future]
                    try:
                        if future.result():
                            devices_found += 1
                            all_devices.append(ip)
                            print(f"  ✅ {ip} - Online")
                    except:
                        pass
            
            print(f"  📊 Found {devices_found} online devices on {network}")
            
        except Exception as e:
            print(f"  ❌ Error scanning {network}: {e}")
    
    # Try to get device info for online devices
    print(f"\n🔍 Getting device information for {len(all_devices)} online devices...")
    
    for ip in all_devices[:20]:  # Limit to first 20 for speed
        try:
            # Try to get hostname
            try:
                hostname = socket.gethostbyaddr(ip)[0]
            except:
                hostname = "Unknown"
            
            # Check for PS5 indicators
            hostname_lower = hostname.lower()
            if any(indicator in hostname_lower for indicator in ['ps5', 'playstation', 'sony']):
                print(f"  🎮 PS5 CANDIDATE: {ip} | {hostname}")
            else:
                print(f"  📱 {ip} | {hostname}")
                
        except Exception as e:
            print(f"  ❌ Error getting info for {ip}: {e}")
    
    print(f"\n💡 PS5 Detection Summary:")
    print(f"  📊 Total devices found: {len(all_devices)}")
    print(f"  🎮 PS5 candidates in ARP: {len(ps5_candidates)}")
    print(f"\n🔧 Next Steps:")
    print(f"  1. Check your router's device list for PS5")
    print(f"  2. Look for devices with 'PS5', 'PlayStation', or 'Sony' in the name")
    print(f"  3. Check for MAC addresses starting with b4:0a:d8, b4:0a:d9, etc.")
    print(f"  4. Try connecting PS5 to the same network as your computer")

if __name__ == "__main__":
    scan_network_comprehensive() 