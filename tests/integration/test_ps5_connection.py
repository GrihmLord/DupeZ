#!/usr/bin/env python3
"""
Test PS5 Connection Script
Tests different methods to connect to PS5
"""

import subprocess
import socket
import time

def test_ps5_connection():
    """Test different connection methods to PS5"""
    print("[GAMING] Testing PS5 Connection Methods...")
    
    # Common PS5 IP addresses to test
    test_ips = [
        "192.168.1.100",  # Common PS5 IP
        "192.168.1.101", 
        "192.168.1.102",
        "192.168.1.103",
        "192.168.1.104",
        "192.168.1.105",
        "192.168.1.110",
        "192.168.1.120",
        "192.168.1.130",
        "192.168.1.140",
        "192.168.1.150",
        "192.168.1.160",
        "192.168.1.170",
        "192.168.1.180",
        "192.168.1.190",
        "192.168.1.200",
        "10.5.0.100",
        "10.5.0.101",
        "10.5.0.102",
    ]
    
    print("[SCAN] Testing common PS5 IP addresses...")
    found_ps5 = []
    
    for ip in test_ips:
        try:
            # Test ping
            result = subprocess.run(['ping', '-n', '1', '-w', '1000', ip], 
                                  capture_output=True, text=True, timeout=2)
            
            if result.returncode == 0:
                print(f"  [SUCCESS] {ip} - Responds to ping")
                
                # Try to get hostname
                try:
                    hostname = socket.gethostbyaddr(ip)[0]
                    print(f"     [DEVICE] Hostname: {hostname}")
                    
                    # Check for PS5 indicators
                    hostname_lower = hostname.lower()
                    if any(indicator in hostname_lower for indicator in ['ps5', 'playstation', 'sony']):
                        print(f"     [GAMING] PS5 DETECTED: {ip} | {hostname}")
                        found_ps5.append((ip, hostname))
                    
                except socket.herror:
                    print(f"     [DEVICE] No hostname found")
                    
                    # Try to connect to common PS5 ports
                    ps5_ports = [80, 443, 8080, 3000, 8081]
                    for port in ps5_ports:
                        try:
                            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                            sock.settimeout(1)
                            result = sock.connect_ex((ip, port))
                            if result == 0:
                                print(f"     [DISCONNECT] Port {port} open - potential PS5")
                                found_ps5.append((ip, f"Port {port} open"))
                            sock.close()
                        except:
                            pass
            else:
                print(f"  [FAILED] {ip} - No response")
                
        except Exception as e:
            print(f"  [FAILED] {ip} - Error: {e}")
    
    if found_ps5:
        print(f"\n[GAMING] Potential PS5 devices found:")
        for ip, info in found_ps5:
            print(f"  [GAMING] {ip} | {info}")
    else:
        print(f"\n[FAILED] No PS5 devices found in common IP ranges")
    
    print(f"\n💡 Manual PS5 Detection Tips:")
    print(f"  1. On your PS5, go to Settings > Network > Connection Status")
    print(f"  2. Note the IP address shown")
    print(f"  3. Check your router's device list for PS5")
    print(f"  4. Try connecting PS5 to the same network as your computer")
    print(f"  5. Make sure PS5 is not in sleep mode")

if __name__ == "__main__":
    test_ps5_connection() 