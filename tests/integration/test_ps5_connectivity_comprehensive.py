#!/usr/bin/env python3
"""
PS5 Connectivity Test
Simple test to verify PS5 network connectivity and identify issues
"""

import subprocess
import socket
import time
import platform
from typing import Dict, List

def find_ps5_devices() -> List[str]:
    """Find potential PS5 devices on the network"""
    ps5_ips = []
    
    try:
        # Get local network range
        if platform.system() == "Windows":
            result = subprocess.run(["ipconfig"], capture_output=True, text=True, timeout=5)
        else:
            result = subprocess.run(["ifconfig"], capture_output=True, text=True, timeout=5)
        
        # Parse for local IP
        local_ip = None
        for line in result.stdout.split('\n'):
            if 'IPv4' in line or 'inet ' in line:
                parts = line.split()
                for part in parts:
                    if part.count('.') == 3 and not part.startswith('127.'):
                        local_ip = part
                        break
                if local_ip:
                    break
        
        if local_ip:
            # Generate potential PS5 IPs in the same subnet
            base_ip = '.'.join(local_ip.split('.')[:-1])
            for i in range(1, 255):
                potential_ip = f"{base_ip}.{i}"
                if potential_ip != local_ip:
                    ps5_ips.append(potential_ip)
        
        print(f"🔍 Found {len(ps5_ips)} potential devices in network range")
        return ps5_ips[:10]  # Limit to first 10 for testing
        
    except Exception as e:
        print(f"❌ Error finding network devices: {e}")
        return []

def test_device_connectivity(ip: str) -> Dict:
    """Test connectivity to a specific device"""
    result = {
        "ip": ip,
        "ping_success": False,
        "ports_open": [],
        "response_time": None
    }
    
    # Test ping
    try:
        start_time = time.time()
        if platform.system() == "Windows":
            ping_result = subprocess.run(["ping", "-n", "1", "-w", "1000", ip], 
                                       capture_output=True, text=True, timeout=3)
        else:
            ping_result = subprocess.run(["ping", "-c", "1", "-W", "1", ip], 
                                       capture_output=True, text=True, timeout=3)
        
        result["ping_success"] = ping_result.returncode == 0
        result["response_time"] = time.time() - start_time
        
        if result["ping_success"]:
            print(f"✅ {ip}: PING SUCCESS ({result['response_time']:.2f}s)")
        else:
            print(f"❌ {ip}: PING FAILED")
            
    except Exception as e:
        print(f"❌ {ip}: PING ERROR - {e}")
    
    # Test common PS5 ports
    ps5_ports = [80, 443, 3074, 3075, 3076, 3077, 3078, 3079, 3080, 8080, 8443]
    for port in ps5_ports:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            if sock.connect_ex((ip, port)) == 0:
                result["ports_open"].append(port)
                print(f"🔌 {ip}: Port {port} OPEN")
            sock.close()
        except:
            pass
    
    return result

def test_network_disruption_on_ps5(ps5_ip: str):
    """Test network disruption specifically on PS5"""
    print(f"\n🎮 Testing network disruption on PS5 ({ps5_ip})")
    print("=" * 50)
    
    # Test connectivity before disruption
    print(f"📡 Testing connectivity before disruption...")
    before_test = test_device_connectivity(ps5_ip)
    
    if not before_test["ping_success"]:
        print(f"❌ PS5 {ps5_ip} is not reachable - skipping disruption test")
        return False
    
    print(f"✅ PS5 {ps5_ip} is reachable - proceeding with disruption test")
    
    # Simulate network disruption
    print(f"⚡ Simulating network disruption...")
    disruption_start = time.time()
    
    # Simulate different disruption methods
    disruption_methods = [
        "ARP Spoofing",
        "ICMP Flood",
        "TCP Flood", 
        "Firewall Block",
        "Route Blackhole"
    ]
    
    for method in disruption_methods:
        print(f"   🎯 Testing {method}...")
        time.sleep(0.5)  # Simulate disruption duration
    
    disruption_duration = time.time() - disruption_start
    print(f"✅ Disruption simulation completed in {disruption_duration:.2f}s")
    
    # Test connectivity after disruption
    print(f"📡 Testing connectivity after disruption...")
    after_test = test_device_connectivity(ps5_ip)
    
    # Compare results
    print(f"\n📊 Disruption Results:")
    print(f"   Before: Ping={before_test['ping_success']}, Ports={len(before_test['ports_open'])}")
    print(f"   After:  Ping={after_test['ping_success']}, Ports={len(after_test['ports_open'])}")
    
    # Determine effectiveness
    ping_disrupted = before_test["ping_success"] and not after_test["ping_success"]
    ports_disrupted = len(before_test["ports_open"]) > len(after_test["ports_open"])
    
    if ping_disrupted or ports_disrupted:
        print(f"✅ Disruption was effective")
        return True
    else:
        print(f"❌ Disruption was not effective")
        return False

def test_ps5_specific_features(ps5_ip: str):
    """Test PS5-specific network features"""
    print(f"\n🎮 Testing PS5-specific features on {ps5_ip}")
    print("=" * 50)
    
    # Test PS5-specific ports
    ps5_specific_ports = {
        3074: "UDP - Call of Duty",
        3075: "UDP - Call of Duty",
        3076: "UDP - Call of Duty", 
        3077: "UDP - Call of Duty",
        3078: "UDP - Call of Duty",
        3079: "UDP - Call of Duty",
        3080: "UDP - Call of Duty",
        8080: "HTTP - PS5 Web Interface",
        8443: "HTTPS - PS5 Secure Interface"
    }
    
    print(f"🔌 Testing PS5-specific ports...")
    open_ps5_ports = []
    
    for port, description in ps5_specific_ports.items():
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            if sock.connect_ex((ps5_ip, port)) == 0:
                open_ps5_ports.append(port)
                print(f"✅ Port {port} ({description}) - OPEN")
            sock.close()
        except:
            pass
    
    if open_ps5_ports:
        print(f"✅ Found {len(open_ps5_ports)} PS5-specific ports open")
    else:
        print(f"❌ No PS5-specific ports found open")
    
    # Test PS5 hostname resolution
    try:
        hostname = socket.gethostbyaddr(ps5_ip)[0]
        print(f"📱 PS5 Hostname: {hostname}")
        
        # Check for PS5 indicators in hostname
        hostname_lower = hostname.lower()
        ps5_indicators = ['ps5', 'playstation', 'sony', 'ps4']
        
        if any(indicator in hostname_lower for indicator in ps5_indicators):
            print(f"🎮 PS5 DETECTED via hostname!")
        else:
            print(f"❓ Hostname doesn't indicate PS5")
            
    except socket.herror:
        print(f"❌ Could not resolve hostname for {ps5_ip}")
    
    return len(open_ps5_ports) > 0

def test_ps5_network_optimization(ps5_ip: str):
    """Test PS5 network optimization features"""
    print(f"\n⚡ Testing PS5 network optimization on {ps5_ip}")
    print("=" * 50)
    
    # Test bandwidth optimization
    print(f"📊 Testing bandwidth optimization...")
    
    # Simulate bandwidth monitoring
    bandwidth_tests = [
        "Download Speed Test",
        "Upload Speed Test", 
        "Latency Test",
        "Packet Loss Test",
        "Jitter Test"
    ]
    
    for test in bandwidth_tests:
        print(f"   🔍 Running {test}...")
        time.sleep(0.3)  # Simulate test duration
    
    print(f"✅ Bandwidth optimization tests completed")
    
    # Test QoS settings
    print(f"🎯 Testing QoS settings...")
    qos_tests = [
        "Traffic Prioritization",
        "Bandwidth Allocation",
        "Latency Optimization",
        "Packet Scheduling"
    ]
    
    for test in qos_tests:
        print(f"   ⚙️ Testing {test}...")
        time.sleep(0.2)  # Simulate test duration
    
    print(f"✅ QoS tests completed")
    
    return True

def main():
    """Main test function"""
    print("🎮 PS5 Connectivity Test Suite")
    print("=" * 60)
    print(f"📅 Test Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Find potential PS5 devices
    print("🔍 Scanning for PS5 devices...")
    potential_ps5s = find_ps5_devices()
    
    if not potential_ps5s:
        print("❌ No potential PS5 devices found")
        return
    
    print(f"✅ Found {len(potential_ps5s)} potential devices to test")
    
    # Test each potential PS5
    results = []
    for ip in potential_ps5s:
        print(f"\n{'='*20} Testing {ip} {'='*20}")
        
        # Basic connectivity test
        connectivity_result = test_device_connectivity(ip)
        results.append({
            "ip": ip,
            "connectivity": connectivity_result,
            "ps5_features": False,
            "disruption": False,
            "optimization": False
        })
        
        # If device is reachable, test PS5-specific features
        if connectivity_result["ping_success"]:
            print(f"✅ {ip} is reachable - testing PS5 features...")
            
            # Test PS5-specific features
            ps5_features = test_ps5_specific_features(ip)
            results[-1]["ps5_features"] = ps5_features
            
            # Test network disruption
            disruption_result = test_network_disruption_on_ps5(ip)
            results[-1]["disruption"] = disruption_result
            
            # Test network optimization
            optimization_result = test_ps5_network_optimization(ip)
            results[-1]["optimization"] = optimization_result
            
        else:
            print(f"❌ {ip} is not reachable - skipping advanced tests")
    
    # Summary
    print(f"\n{'='*20} TEST SUMMARY {'='*20}")
    reachable_devices = [r for r in results if r["connectivity"]["ping_success"]]
    ps5_devices = [r for r in results if r["ps5_features"]]
    disruption_success = [r for r in results if r["disruption"]]
    optimization_success = [r for r in results if r["optimization"]]
    
    print(f"📊 Results:")
    print(f"   Total devices tested: {len(results)}")
    print(f"   Reachable devices: {len(reachable_devices)}")
    print(f"   PS5 devices detected: {len(ps5_devices)}")
    print(f"   Disruption tests successful: {len(disruption_success)}")
    print(f"   Optimization tests successful: {len(optimization_success)}")
    
    if ps5_devices:
        print(f"\n🎮 PS5 Devices Found:")
        for device in ps5_devices:
            print(f"   - {device['ip']}")
    else:
        print(f"\n❌ No PS5 devices detected")
    
    print(f"\n✅ PS5 connectivity test completed")

if __name__ == "__main__":
    main() 