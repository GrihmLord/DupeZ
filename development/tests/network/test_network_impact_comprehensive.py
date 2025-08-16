#!/usr/bin/env python3
"""
Network Impact Diagnostic Tool
Tests the actual effectiveness of network disruption methods
"""

import subprocess
import socket
import time
import threading
from typing import Dict, List, Tuple
import platform
import os

def test_ping_connectivity(target_ip: str) -> bool:
    """Test if target IP responds to ping"""
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

def test_port_connectivity(target_ip: str, port: int) -> bool:
    """Test if target IP responds on specific port"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((target_ip, port))
        sock.close()
        return result == 0
    except Exception as e:
        print(f"Port test failed for {target_ip}:{port}: {e}")
        return False

def test_arp_table(target_ip: str) -> Dict:
    """Check ARP table for target IP"""
    try:
        if platform.system() == "Windows":
            result = subprocess.run(["arp", "-a"], capture_output=True, text=True, timeout=5)
        else:
            result = subprocess.run(["arp", "-n"], capture_output=True, text=True, timeout=5)
        
        arp_entries = {}
        for line in result.stdout.split('\n'):
            if target_ip in line:
                parts = line.split()
                if len(parts) >= 2:
                    arp_entries[target_ip] = parts[1]
        
        return arp_entries
    except Exception as e:
        print(f"ARP table check failed: {e}")
        return {}

def test_route_table(target_ip: str) -> List[str]:
    """Check routing table for target IP"""
    try:
        if platform.system() == "Windows":
            result = subprocess.run(["route", "print"], capture_output=True, text=True, timeout=5)
        else:
            result = subprocess.run(["route", "-n"], capture_output=True, text=True, timeout=5)
        
        routes = []
        for line in result.stdout.split('\n'):
            if target_ip in line:
                routes.append(line.strip())
        
        return routes
    except Exception as e:
        print(f"Route table check failed: {e}")
        return []

def test_firewall_rules(target_ip: str) -> List[str]:
    """Check firewall rules for target IP"""
    try:
        if platform.system() == "Windows":
            result = subprocess.run(["netsh", "advfirewall", "firewall", "show", "rule", "name=all"], 
                                  capture_output=True, text=True, timeout=10)
        else:
            result = subprocess.run(["iptables", "-L"], capture_output=True, text=True, timeout=5)
        
        rules = []
        for line in result.stdout.split('\n'):
            if target_ip in line:
                rules.append(line.strip())
        
        return rules
    except Exception as e:
        print(f"Firewall rules check failed: {e}")
        return []

def test_network_interface() -> Dict:
    """Get current network interface information"""
    try:
        if platform.system() == "Windows":
            result = subprocess.run(["ipconfig"], capture_output=True, text=True, timeout=5)
        else:
            result = subprocess.run(["ifconfig"], capture_output=True, text=True, timeout=5)
        
        interface_info = {}
        current_interface = None
        
        for line in result.stdout.split('\n'):
            if 'adapter' in line.lower() or 'interface' in line.lower():
                current_interface = line.strip()
                interface_info[current_interface] = {}
            elif current_interface and ('ipv4' in line.lower() or 'inet ' in line.lower()):
                parts = line.split()
                for part in parts:
                    if part.count('.') == 3 and not part.startswith('127.'):
                        interface_info[current_interface]['ip'] = part
                        break
        
        return interface_info
    except Exception as e:
        print(f"Network interface check failed: {e}")
        return {}

def run_network_diagnostic(target_ip: str) -> Dict:
    """Run comprehensive network diagnostic on target IP"""
    print(f"🔍 Running network diagnostic on {target_ip}")
    print("=" * 50)
    
    diagnostic_results = {
        "target_ip": target_ip,
        "ping_success": False,
        "ports_open": [],
        "arp_entry": None,
        "route_entries": [],
        "firewall_rules": [],
        "interface_info": {}
    }
    
    # Test ping connectivity
    print(f"📡 Testing ping connectivity...")
    diagnostic_results["ping_success"] = test_ping_connectivity(target_ip)
    if diagnostic_results["ping_success"]:
        print(f"✅ {target_ip} responds to ping")
    else:
        print(f"❌ {target_ip} does not respond to ping")
    
    # Test common ports
    print(f"🔌 Testing common ports...")
    common_ports = [80, 443, 22, 21, 23, 25, 53, 110, 143, 993, 995, 8080, 8443]
    for port in common_ports:
        if test_port_connectivity(target_ip, port):
            diagnostic_results["ports_open"].append(port)
            print(f"✅ Port {port} is open")
    
    # Check ARP table
    print(f"📋 Checking ARP table...")
    arp_entries = test_arp_table(target_ip)
    if arp_entries:
        diagnostic_results["arp_entry"] = arp_entries
        print(f"✅ Found ARP entry: {arp_entries}")
    else:
        print(f"❌ No ARP entry found")
    
    # Check routing table
    print(f"🗺️ Checking routing table...")
    route_entries = test_route_table(target_ip)
    if route_entries:
        diagnostic_results["route_entries"] = route_entries
        print(f"✅ Found route entries: {len(route_entries)}")
    else:
        print(f"❌ No route entries found")
    
    # Check firewall rules
    print(f"🛡️ Checking firewall rules...")
    firewall_rules = test_firewall_rules(target_ip)
    if firewall_rules:
        diagnostic_results["firewall_rules"] = firewall_rules
        print(f"✅ Found firewall rules: {len(firewall_rules)}")
    else:
        print(f"❌ No firewall rules found")
    
    # Get network interface info
    print(f"🌐 Getting network interface info...")
    interface_info = test_network_interface()
    if interface_info:
        diagnostic_results["interface_info"] = interface_info
        print(f"✅ Network interfaces: {len(interface_info)}")
    else:
        print(f"❌ No interface info available")
    
    return diagnostic_results

def test_disruption_effectiveness(target_ip: str, disruption_method: str) -> Dict:
    """Test the effectiveness of a specific disruption method"""
    print(f"🎯 Testing {disruption_method} on {target_ip}")
    print("=" * 50)
    
    # Get baseline connectivity
    print(f"📊 Getting baseline connectivity...")
    baseline_ping = test_ping_connectivity(target_ip)
    baseline_ports = []
    for port in [80, 443, 22, 8080]:
        if test_port_connectivity(target_ip, port):
            baseline_ports.append(port)
    
    print(f"📈 Baseline: Ping={baseline_ping}, Open ports={baseline_ports}")
    
    # Simulate disruption
    print(f"⚡ Simulating {disruption_method}...")
    disruption_start = time.time()
    
    # Simulate different disruption methods
    if disruption_method == "arp_spoof":
        print(f"🎭 Simulating ARP spoofing attack...")
        time.sleep(3)  # Simulate attack duration
    elif disruption_method == "icmp_flood":
        print(f"🌊 Simulating ICMP flood...")
        time.sleep(3)  # Simulate attack duration
    elif disruption_method == "tcp_flood":
        print(f"🌊 Simulating TCP flood...")
        time.sleep(3)  # Simulate attack duration
    elif disruption_method == "firewall_block":
        print(f"🛡️ Simulating firewall block...")
        time.sleep(3)  # Simulate attack duration
    elif disruption_method == "route_blackhole":
        print(f"🕳️ Simulating route blackhole...")
        time.sleep(3)  # Simulate attack duration
    else:
        print(f"❓ Unknown disruption method: {disruption_method}")
        return {"success": False, "error": "Unknown method"}
    
    disruption_duration = time.time() - disruption_start
    
    # Test connectivity after disruption
    print(f"📊 Testing connectivity after disruption...")
    after_ping = test_ping_connectivity(target_ip)
    after_ports = []
    for port in [80, 443, 22, 8080]:
        if test_port_connectivity(target_ip, port):
            after_ports.append(port)
    
    print(f"📉 After disruption: Ping={after_ping}, Open ports={after_ports}")
    
    # Calculate effectiveness
    ping_disrupted = baseline_ping and not after_ping
    ports_disrupted = len(baseline_ports) > len(after_ports)
    overall_effective = ping_disrupted or ports_disrupted
    
    results = {
        "method": disruption_method,
        "target_ip": target_ip,
        "baseline_ping": baseline_ping,
        "baseline_ports": baseline_ports,
        "after_ping": after_ping,
        "after_ports": after_ports,
        "ping_disrupted": ping_disrupted,
        "ports_disrupted": ports_disrupted,
        "overall_effective": overall_effective,
        "disruption_duration": disruption_duration
    }
    
    if overall_effective:
        print(f"✅ {disruption_method} was effective")
    else:
        print(f"❌ {disruption_method} was not effective")
    
    return results

def main():
    """Main test function"""
    print("🌐 Network Impact Diagnostic Tool")
    print("=" * 60)
    
    # Test target IP
    test_target = "192.168.1.100"  # Common test IP
    
    print(f"🎯 Target IP: {test_target}")
    print(f"📅 Test Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Run comprehensive diagnostic
    diagnostic_results = run_network_diagnostic(test_target)
    
    print(f"\n📊 Diagnostic Summary:")
    print(f"   Target IP: {diagnostic_results['target_ip']}")
    print(f"   Ping Success: {diagnostic_results['ping_success']}")
    print(f"   Open Ports: {len(diagnostic_results['ports_open'])}")
    print(f"   ARP Entry: {'Yes' if diagnostic_results['arp_entry'] else 'No'}")
    print(f"   Route Entries: {len(diagnostic_results['route_entries'])}")
    print(f"   Firewall Rules: {len(diagnostic_results['firewall_rules'])}")
    
    # Test different disruption methods
    print(f"\n🎯 Testing Disruption Methods:")
    disruption_methods = ["arp_spoof", "icmp_flood", "tcp_flood", "firewall_block", "route_blackhole"]
    
    disruption_results = []
    for method in disruption_methods:
        result = test_disruption_effectiveness(test_target, method)
        disruption_results.append(result)
        print()
    
    # Summary
    print(f"📈 Disruption Effectiveness Summary:")
    print("=" * 50)
    effective_methods = [r for r in disruption_results if r['overall_effective']]
    ineffective_methods = [r for r in disruption_results if not r['overall_effective']]
    
    print(f"✅ Effective methods: {len(effective_methods)}")
    for result in effective_methods:
        print(f"   - {result['method']}")
    
    print(f"❌ Ineffective methods: {len(ineffective_methods)}")
    for result in ineffective_methods:
        print(f"   - {result['method']}")
    
    print(f"\n✅ Network impact diagnostic completed")

if __name__ == "__main__":
    main() 