#!/usr/bin/env python3
"""
PS5 Network Diagnostic Tool
Comprehensive test for PS5 detection and network disruption
"""

import socket
import subprocess
import time
import sys
import os
from typing import Dict, List, Optional

def run_command(command: List[str], description: str = "") -> Optional[str]:
    """Run a command and return output"""
    try:
        print(f"🔍 {description}...")
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return result.stdout
        else:
            print(f"❌ Command failed: {result.stderr}")
            return None
    except Exception as e:
        print(f"❌ Error running command: {e}")
        return None

def check_admin_privileges() -> bool:
    """Check if running with administrator privileges"""
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def get_network_devices() -> List[Dict]:
    """Get all devices on the network"""
    devices = []
    
    # Get ARP table
    arp_result = run_command(["arp", "-a"], "Getting ARP table")
    if arp_result:
        for line in arp_result.split('\n'):
            if 'dynamic' in line.lower() or 'static' in line.lower():
                parts = line.split()
                if len(parts) >= 2:
                    ip = parts[0]
                    mac = parts[1] if len(parts) > 1 else "Unknown"
                    devices.append({
                        'ip': ip,
                        'mac': mac,
                        'type': 'arp_table'
                    })
    
    # Get network scan results
    scan_result = run_command(["nmap", "-sn", "192.168.1.0/24"], "Scanning network")
    if scan_result:
        for line in scan_result.split('\n'):
            if 'Nmap scan report' in line:
                ip = line.split()[-1]
                devices.append({
                    'ip': ip,
                    'mac': 'Unknown',
                    'type': 'nmap_scan'
                })
    
    return devices

def identify_ps5_devices(devices: List[Dict]) -> List[Dict]:
    """Identify PS5 devices from the device list"""
    ps5_devices = []
    
    for device in devices:
        ip = device.get('ip', '')
        mac = device.get('mac', '').lower()
        
        # Check MAC address for Sony OUI
        sony_ouis = ['00:50:c2', '00:1f:a7', '00:19:c5', 'b4:0a:d8', 'b4:0a:d9']
        is_sony = any(mac.startswith(oui) for oui in sony_ouis)
        
        # Try to get hostname
        try:
            hostname = socket.gethostbyaddr(ip)[0].lower()
        except:
            hostname = ""
        
        # Check for PS5 indicators
        is_ps5 = (
            is_sony or
            'ps5' in hostname or
            'playstation' in hostname or
            'sony' in hostname
        )
        
        if is_ps5:
            device['is_ps5'] = True
            device['hostname'] = hostname
            ps5_devices.append(device)
            print(f"🎮 PS5 detected: {ip} ({hostname}) - MAC: {mac}")
    
    return ps5_devices

def test_connectivity(ip: str) -> Dict:
    """Test connectivity to a device"""
    results = {
        'ping_success': False,
        'ports_open': [],
        'response_time': 0
    }
    
    # Test ping
    start_time = time.time()
    ping_result = run_command(["ping", "-n", "1", "-w", "1000", ip], f"Pinging {ip}")
    results['response_time'] = time.time() - start_time
    
    if ping_result and "TTL=" in ping_result:
        results['ping_success'] = True
        print(f"✅ {ip} responds to ping")
    else:
        print(f"❌ {ip} does not respond to ping")
    
    # Test common ports
    common_ports = [80, 443, 8080, 3000, 8081, 22, 21, 23, 25, 53]
    for port in common_ports:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex((ip, port))
            if result == 0:
                results['ports_open'].append(port)
                print(f"✅ {ip}:{port} is open")
            sock.close()
        except:
            pass
    
    return results

def test_network_disruption(ps5_ip: str) -> bool:
    """Test network disruption on PS5"""
    print(f"\n🎯 Testing network disruption on PS5 ({ps5_ip})")
    
    # Test connectivity before disruption
    print("📡 Testing connectivity before disruption...")
    before_test = test_connectivity(ps5_ip)
    
    if not before_test['ping_success']:
        print(f"❌ PS5 {ps5_ip} is not reachable - cannot test disruption")
        return False
    
    print(f"✅ PS5 {ps5_ip} is reachable - proceeding with disruption test")
    
    # Import and test enterprise network disruptor
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from app.firewall.enterprise_network_disruptor import EnterpriseNetworkDisruptor
        
        # Initialize disruptor
        disruptor = EnterpriseNetworkDisruptor()
        if not disruptor.initialize():
            print("❌ Failed to initialize enterprise network disruptor")
            return False
        
        print("✅ Enterprise network disruptor initialized")
        
        # Test disconnect
        print("🔌 Testing disconnect...")
        success = disruptor.disconnect_device_enterprise(ps5_ip, ["arp_spoof", "icmp_flood"])
        
        if success:
            print("✅ Disconnect initiated successfully")
            
            # Wait a moment for disruption to take effect
            time.sleep(3)
            
            # Test connectivity after disruption
            print("📡 Testing connectivity after disruption...")
            after_test = test_connectivity(ps5_ip)
            
            # Compare results
            ping_disrupted = before_test['ping_success'] and not after_test['ping_success']
            ports_disrupted = len(before_test['ports_open']) > len(after_test['ports_open'])
            
            if ping_disrupted or ports_disrupted:
                print("✅ Network disruption is working!")
                print(f"   Ping disrupted: {ping_disrupted}")
                print(f"   Ports disrupted: {ports_disrupted}")
            else:
                print("❌ Network disruption not effective")
                print(f"   Before: Ping={before_test['ping_success']}, Ports={len(before_test['ports_open'])}")
                print(f"   After:  Ping={after_test['ping_success']}, Ports={len(after_test['ports_open'])}")
            
            # Cleanup
            print("🔄 Cleaning up...")
            disruptor.reconnect_device_enterprise(ps5_ip)
            
            return ping_disrupted or ports_disrupted
        else:
            print("❌ Failed to initiate disconnect")
            return False
            
    except Exception as e:
        print(f"❌ Error testing network disruption: {e}")
        return False

def main():
    """Main diagnostic function"""
    print("=" * 60)
    print("🎮 PS5 NETWORK DIAGNOSTIC TOOL")
    print("=" * 60)
    print()
    
    # Check admin privileges
    print("🔐 Checking administrator privileges...")
    if check_admin_privileges():
        print("✅ Running with administrator privileges")
    else:
        print("❌ NOT running with administrator privileges")
        print("⚠️  Network disruption features require administrator privileges")
        print("   Please run this script as Administrator")
        return
    
    # Get network devices
    print("\n📡 Scanning network for devices...")
    devices = get_network_devices()
    print(f"Found {len(devices)} devices on network")
    
    # Identify PS5 devices
    print("\n🎮 Identifying PS5 devices...")
    ps5_devices = identify_ps5_devices(devices)
    
    if not ps5_devices:
        print("❌ No PS5 devices detected on network")
        print("\n💡 Troubleshooting tips:")
        print("1. Make sure your PS5 is connected to the same network")
        print("2. Check if PS5 is powered on and connected")
        print("3. Try restarting your PS5")
        print("4. Check your router settings")
        return
    
    print(f"✅ Found {len(ps5_devices)} PS5 device(s)")
    
    # Test each PS5 device
    for i, ps5_device in enumerate(ps5_devices, 1):
        print(f"\n🎮 Testing PS5 #{i}: {ps5_device['ip']}")
        print("-" * 40)
        
        # Test basic connectivity
        connectivity = test_connectivity(ps5_device['ip'])
        
        if connectivity['ping_success']:
            print(f"✅ PS5 {ps5_device['ip']} is reachable")
            
            # Test network disruption
            disruption_works = test_network_disruption(ps5_device['ip'])
            
            if disruption_works:
                print(f"✅ Network disruption is working on PS5 {ps5_device['ip']}")
            else:
                print(f"❌ Network disruption is NOT working on PS5 {ps5_device['ip']}")
                print("\n🔧 Possible issues:")
                print("1. PS5 may have network protection enabled")
                print("2. Router may be blocking the disruption")
                print("3. PS5 may be using a different network interface")
                print("4. Firewall may be blocking the disruption")
        else:
            print(f"❌ PS5 {ps5_device['ip']} is not reachable")
    
    print("\n" + "=" * 60)
    print("🎮 DIAGNOSTIC COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    main() 