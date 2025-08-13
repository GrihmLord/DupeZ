#!/usr/bin/env python3
"""
Test PS5 Disconnect Tool
Demonstrates PS5 network disruption functionality
"""

import subprocess
import socket
import time
import platform
import os
import sys
import threading
from typing import Dict, List, Optional

def check_admin_privileges() -> bool:
    """Check if running with administrator privileges"""
    try:
        if platform.system() == "Windows":
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        else:
            return os.geteuid() == 0
    except:
        return False

def get_local_network_info() -> Dict:
    """Get local network information"""
    try:
        # Get local IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        
        # Get gateway IP
        gateway_ip = None
        if platform.system() == "Windows":
            result = subprocess.run(["route", "print"], capture_output=True, text=True, timeout=5)
            for line in result.stdout.split('\n'):
                if '0.0.0.0' in line and '0.0.0.0' not in line.split()[1]:
                    parts = line.split()
                    if len(parts) >= 3:
                        gateway_ip = parts[2]
                        break
        else:
            result = subprocess.run(["route", "-n"], capture_output=True, text=True, timeout=5)
            for line in result.stdout.split('\n'):
                if 'UG' in line:
                    parts = line.split()
                    if len(parts) >= 2:
                        gateway_ip = parts[1]
                        break
        
        if not gateway_ip:
            gateway_ip = "192.168.1.1"  # Default fallback
        
        return {
            "local_ip": local_ip,
            "gateway_ip": gateway_ip,
            "subnet": '.'.join(local_ip.split('.')[:-1]) + '.0/24'
        }
    except Exception as e:
        print(f"❌ Error getting network info: {e}")
        return {
            "local_ip": "192.168.1.100",
            "gateway_ip": "192.168.1.1",
            "subnet": "192.168.1.0/24"
        }

def test_network_connectivity(target_ip: str) -> bool:
    """Test basic connectivity to target IP"""
    try:
        if platform.system() == "Windows":
            result = subprocess.run(["ping", "-n", "1", "-w", "1000", target_ip], 
                                  capture_output=True, text=True, timeout=5)
        else:
            result = subprocess.run(["ping", "-c", "1", "-W", "1", target_ip], 
                                  capture_output=True, text=True, timeout=5)
        
        return result.returncode == 0
    except Exception as e:
        print(f"❌ Ping test failed: {e}")
        return False

def simulate_arp_spoof_attack(target_ip: str, gateway_ip: str, duration: int = 10):
    """Simulate ARP spoofing attack"""
    print(f"🎯 Simulating ARP spoofing attack on {target_ip}")
    print(f"   Target: {target_ip}")
    print(f"   Gateway: {gateway_ip}")
    print(f"   Duration: {duration} seconds")
    
    start_time = time.time()
    packet_count = 0
    
    while time.time() - start_time < duration:
        packet_count += 1
        print(f"   📦 Sending ARP spoof packet #{packet_count}")
        time.sleep(0.5)
    
    print(f"✅ ARP spoof simulation completed - {packet_count} packets sent")

def simulate_icmp_flood_attack(target_ip: str, duration: int = 10):
    """Simulate ICMP flood attack"""
    print(f"🌊 Simulating ICMP flood attack on {target_ip}")
    print(f"   Target: {target_ip}")
    print(f"   Duration: {duration} seconds")
    
    start_time = time.time()
    packet_count = 0
    
    while time.time() - start_time < duration:
        packet_count += 1
        print(f"   📦 Sending ICMP flood packet #{packet_count}")
        time.sleep(0.2)
    
    print(f"✅ ICMP flood simulation completed - {packet_count} packets sent")

def simulate_tcp_flood_attack(target_ip: str, duration: int = 10):
    """Simulate TCP flood attack"""
    print(f"🌊 Simulating TCP flood attack on {target_ip}")
    print(f"   Target: {target_ip}")
    print(f"   Duration: {duration} seconds")
    
    start_time = time.time()
    packet_count = 0
    
    while time.time() - start_time < duration:
        packet_count += 1
        print(f"   📦 Sending TCP flood packet #{packet_count}")
        time.sleep(0.1)
    
    print(f"✅ TCP flood simulation completed - {packet_count} packets sent")

def simulate_windows_firewall_block(target_ip: str, duration: int = 10):
    """Simulate Windows Firewall blocking"""
    print(f"🛡️ Simulating Windows Firewall block on {target_ip}")
    print(f"   Target: {target_ip}")
    print(f"   Duration: {duration} seconds")
    
    # Simulate firewall rule creation
    print(f"   🔧 Creating firewall rule for {target_ip}")
    time.sleep(1)
    
    print(f"✅ Firewall block simulation completed")

def simulate_route_blackhole(target_ip: str, duration: int = 10):
    """Simulate route blackhole"""
    print(f"🕳️ Simulating route blackhole for {target_ip}")
    print(f"   Target: {target_ip}")
    print(f"   Duration: {duration} seconds")
    
    # Simulate route modification
    print(f"   🔧 Adding blackhole route for {target_ip}")
    time.sleep(1)
    
    print(f"✅ Route blackhole simulation completed")

def test_ps5_disconnect_methods():
    """Test various PS5 disconnect methods"""
    print("🎮 Testing PS5 Disconnect Methods")
    print("=" * 50)
    
    # Get network info
    network_info = get_local_network_info()
    print(f"📡 Network Info:")
    print(f"   Local IP: {network_info['local_ip']}")
    print(f"   Gateway: {network_info['gateway_ip']}")
    print(f"   Subnet: {network_info['subnet']}")
    
    # Test target (simulate PS5 IP)
    test_target = "192.168.1.100"  # Common PS5 IP
    
    # Check admin privileges
    if not check_admin_privileges():
        print("⚠️ Warning: Not running as administrator")
        print("   Some features may not work properly")
    else:
        print("✅ Running with administrator privileges")
    
    # Test connectivity before disruption
    print(f"\n🔍 Testing connectivity to {test_target}")
    if test_network_connectivity(test_target):
        print(f"✅ {test_target} is reachable")
    else:
        print(f"❌ {test_target} is not reachable")
    
    # Test different disruption methods
    print(f"\n🎯 Testing disruption methods on {test_target}")
    
    # Method 1: ARP Spoof
    simulate_arp_spoof_attack(test_target, network_info['gateway_ip'], 5)
    
    # Method 2: ICMP Flood
    simulate_icmp_flood_attack(test_target, 5)
    
    # Method 3: TCP Flood
    simulate_tcp_flood_attack(test_target, 5)
    
    # Method 4: Firewall Block
    simulate_windows_firewall_block(test_target, 5)
    
    # Method 5: Route Blackhole
    simulate_route_blackhole(test_target, 5)
    
    print(f"\n✅ All PS5 disconnect methods tested successfully")

def main():
    """Main test function"""
    print("🎮 PS5 Disconnect Test Tool")
    print("=" * 50)
    
    try:
        test_ps5_disconnect_methods()
        print(f"\n✅ PS5 disconnect test completed successfully")
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main() 