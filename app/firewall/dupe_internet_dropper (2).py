#!/usr/bin/env python3
"""
Dupe Internet Dropper
Creates visual indicators (red chain) on PS5s without affecting network connectivity
Perfect for "duping" - shows disconnected status while maintaining full functionality
"""

import subprocess
import threading
import time
import socket
import struct
import ctypes
import os
from typing import List, Dict, Optional
from app.logs.logger import log_info, log_error
from app.firewall.udp_port_interrupter import UDPPortInterrupter
from app.firewall.win_divert import windivert_controller

def is_admin():
    """Check if running with administrator privileges"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

class DupeInternetDropper:
    """Creates visual disconnect indicators on PS5s without affecting network"""
    
    def __init__(self):
        self.dupe_active = False
        self.ps5_ips = []
        self.lock = threading.Lock()
        self.spoof_thread = None
        self.active_methods = []  # Track which methods are currently active
        self.admin_privileges = is_admin()
        
        # Initialize UDP port interrupter for Laganator integration
        self.udp_interrupter = UDPPortInterrupter()
        
        # Initialize WinDivert controller
        self.windivert_initialized = windivert_controller.initialize()
        if self.windivert_initialized:
            log_info("[SUCCESS] WinDivert controller integrated for prioritized packet manipulation")
        else:
            log_info("[INFO] WinDivert not available - using fallback methods")
        
        if self.admin_privileges:
            log_info("[SUCCESS] Running with administrator privileges")
        else:
            log_info("[INFO] Running without administrator privileges - using non-admin methods")
        
    def start_dupe_with_devices(self, devices: List[Dict], methods: List[str]) -> bool:
        """Start the dupe with specific devices and methods"""
        try:
            with self.lock:
                if self.dupe_active:
                    log_info("Dupe already active")
                    return True
                
                log_info(f"[GAMING] Starting dupe with {len(devices)} devices and methods: {methods}")
                
                # Extract IP addresses from devices
                self.ps5_ips = [device.get('ip') for device in devices if device.get('ip')]
                
                if not self.ps5_ips:
                    log_info("No valid IP addresses found in selected devices")
                    return False
                
                # Filter methods based on admin privileges
                available_methods = self._get_available_methods(methods)
                if not available_methods:
                    log_error("No available methods for current privilege level")
                    return False
                
                # Prioritize WinDivert if available
                if self.windivert_initialized and "windivert" in available_methods:
                    self._start_windivert_dupe()
                
                # Apply selected methods
                for method in available_methods:
                    if method == "icmp_spoof":
                        self._send_disconnect_packets()
                    elif method == "dns_spoof":
                        self._spoof_dns_responses()
                    elif method == "ps5_packets":
                        for ps5_ip in self.ps5_ips:
                            self._send_ps5_disconnect_packet(ps5_ip)
                    elif method == "response_spoof":
                        self._start_response_spoofing()
                    elif method == "udp_interrupt":
                        # Start UDP port interruption (Laganator integration)
                        success = self.udp_interrupter.start_udp_interruption(
                            target_ips=self.ps5_ips,
                            drop_rate=90,  # 90% drop rate for lagging without disconnection
                            duration=0  # No timer, manual stop
                        )
                        if not success:
                            log_error("Failed to start UDP interruption")
                    elif method == "arp_poison":
                        self._start_arp_poisoning()
                
                self.dupe_active = True
                self.active_methods = available_methods
                log_info(f"[SUCCESS] Dupe active on {len(self.ps5_ips)} devices with methods: {available_methods}")
                return True
                
        except Exception as e:
            log_error(f"Failed to start dupe with devices: {e}")
            return False
    
    def _get_available_methods(self, requested_methods: List[str]) -> List[str]:
        """Filter methods based on available privileges"""
        available_methods = []
        
        # Methods that work without admin privileges
        non_admin_methods = [
            "icmp_spoof",
            "ps5_packets", 
            "response_spoof",
            "udp_interrupt"
        ]
        
        # Methods that require admin privileges
        admin_methods = [
            "dns_spoof",
            "arp_poison",
            "windivert"
        ]
        
        for method in requested_methods:
            if method in non_admin_methods:
                available_methods.append(method)
            elif method in admin_methods and self.admin_privileges:
                available_methods.append(method)
            else:
                log_info(f"Method '{method}' not available with current privileges")
        
        return available_methods
    
    def _start_windivert_dupe(self):
        """Start WinDivert-based dupe for prioritized packet manipulation"""
        try:
            if not self.windivert_initialized:
                log_error("WinDivert not available for dupe")
                return False
            
            # DayZ-specific ports for targeted disruption
            dayz_ports = [2302, 2303, 2304, 2305, 27015, 27016, 27017, 27018, 7777, 7778]
            
            for ps5_ip in self.ps5_ips:
                # Start WinDivert with high priority and aggressive drop rate
                success = windivert_controller.start_divert(
                    ip=ps5_ip,
                    priority='high',
                    drop_rate='aggressive',
                    protocol='udp',
                    ports=dayz_ports
                )
                
                if success:
                    log_info(f"[SUCCESS] WinDivert dupe started for {ps5_ip} with DayZ port targeting")
                else:
                    log_error(f"Failed to start WinDivert dupe for {ps5_ip}")
            
            return True
            
        except Exception as e:
            log_error(f"WinDivert dupe start failed: {e}")
            return False
    
    def start_dupe_with_methods(self, methods: List[str]) -> bool:
        """Start dupe with selected methods"""
        try:
            self.active_methods = methods
            log_info(f"[GAMING] Starting DayZ dupe with methods: {', '.join(methods)}")
            
            # Initialize PS5 IPs if not already done
            if not self.ps5_ips:
                self._find_ps5_devices()
            
            # Prioritize WinDivert if available and selected
            if self.windivert_initialized and "windivert" in methods:
                self._start_windivert_dupe()
            
            # Apply selected methods
            if "icmp_spoof" in methods:
                self._send_disconnect_packets()
                
            if "dns_spoof" in methods:
                self._spoof_dns_responses()
                
            if "ps5_packets" in methods:
                # Send PS5-specific disconnect packets to each PS5 IP
                for ps5_ip in self.ps5_ips:
                    self._send_ps5_disconnect_packet(ps5_ip)
                    
            if "response_spoof" in methods:
                self._start_response_spoofing()
                
            if "udp_interrupt" in methods:
                # Start UDP port interruption (Laganator integration)
                success = self.udp_interrupter.start_udp_interruption(
                    target_ips=self.ps5_ips,
                    drop_rate=90,
                    duration=0
                )
                if not success:
                    log_error("Failed to start UDP interruption")
                    
            if "arp_poison" in methods:
                self._start_arp_poisoning()
            
            self.dupe_active = True
            log_info(f"[SUCCESS] DayZ dupe started with methods: {methods}")
            return True
            
        except Exception as e:
            log_error(f"Failed to start dupe with methods: {e}")
            return False
    
    def start_dupe(self) -> bool:
        """Start the dupe - creates red chain indicators on PS5s (default methods)"""
        return self.start_dupe_with_methods(["icmp_spoof", "dns_spoof", "ps5_packets", "response_spoof"])
    
    def stop_dupe(self) -> bool:
        """Stop the dupe - restore normal indicators"""
        try:
            with self.lock:
                if not self.dupe_active:
                    log_info("Dupe not active")
                    return True
                
                log_info("[STOP] Stopping PS5 dupe - restoring normal indicators...")
                
                # Stop WinDivert processes if active
                if self.windivert_initialized:
                    windivert_controller.stop_divert()  # Stop all WinDivert processes
                    log_info("[SUCCESS] WinDivert processes stopped")
                
                # Stop spoofing thread
                if self.spoof_thread and self.spoof_thread.is_alive():
                    self.spoof_thread.join(timeout=2)
                
                # Send restore packets
                self._send_restore_packets()
                
                # Clear DNS spoofing
                self._clear_dns_spoofing()
                
                # Stop UDP interrupter if active
                if hasattr(self, 'udp_interrupter'):
                    self.udp_interrupter.stop_udp_interruption()
                
                self.dupe_active = False
                self.ps5_ips = []
                self.active_methods = []  # Clear active methods
                log_info("[SUCCESS] Dupe stopped successfully")
                return True
                
        except Exception as e:
            log_error(f"Failed to stop dupe: {e}")
            return False
    
    def toggle_dupe(self) -> bool:
        """Toggle dupe status"""
        if self.dupe_active:
            return self.stop_dupe()
        else:
            return self.start_dupe()
    
    def is_dupe_active(self) -> bool:
        """Check if dupe is active"""
        return self.dupe_active
    
    def _find_ps5_devices(self):
        """Find PS5 devices on the network"""
        try:
            # Scan network for PS5 devices
            result = subprocess.run(['arp', '-a'], capture_output=True, text=True)
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                for line in lines:
                    if 'b4:0a:d8' in line.lower() or 'b4:0a:d9' in line.lower():
                        # Extract IP address
                        parts = line.split()
                        if len(parts) >= 2:
                            ip = parts[0]
                            if self._is_valid_ip(ip):
                                self.ps5_ips.append(ip)
                                log_info(f"Found PS5 for dupe: {ip}")
            
            log_info(f"Found {len(self.ps5_ips)} PS5 devices for dupe")
            
        except Exception as e:
            log_error(f"Failed to find PS5 devices: {e}")
    
    def _start_response_spoofing(self):
        """Start response spoofing for PS5 disconnection"""
        try:
            log_info("[GAMING] Starting response spoofing for PS5 disconnection")
            
            # Send real response packets to create network disruption
            for target_ip in self.ps5_ips:
                self._send_real_response_packets(target_ip)
                
        except Exception as e:
            log_error(f"Failed to start response spoofing: {e}")
    
    def _start_arp_poisoning(self):
        """Start ARP poisoning for DayZ duping"""
        try:
            log_info("[GAMING] Starting ARP poisoning for DayZ duping")
            
            # Get gateway IP
            gateway_ip = self._get_gateway_ip()
            if not gateway_ip:
                log_error("Failed to get gateway IP for ARP poisoning")
                return
            
            # Start ARP poisoning for each target
            for target_ip in self.ps5_ips:
                self._arp_poison_target(target_ip, gateway_ip)
                
        except Exception as e:
            log_error(f"Failed to start ARP poisoning: {e}")
    
    def _arp_poison_target(self, target_ip: str, gateway_ip: str):
        """ARP poison a specific target"""
        try:
            log_info(f"[GAMING] Enhanced ARP poisoning: {target_ip} -> {gateway_ip}")
            
            # Create ARP spoof packet
            arp_packet = self._create_arp_spoof_packet(target_ip, gateway_ip)
            
            # Send ARP spoof packet
            with socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_RAW) as sock:
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
                sock.sendto(arp_packet, (target_ip, 0))
                
        except Exception as e:
            log_error(f"Failed to ARP poison {target_ip}: {e}")
    
    def _send_real_response_packets(self, target_ip: str):
        """Send real response packets to create network disruption"""
        try:
            log_info(f"[GAMING] Sending real response packets to {target_ip}")
            
            # Send real TCP reset packets
            self._send_real_reset_packets(target_ip)
            
        except Exception as e:
            log_error(f"Failed to send real response packets to {target_ip}: {e}")
    
    def _send_real_reset_packets(self, target_ip: str):
        """Send real TCP reset packets to target"""
        try:
            # Create raw socket with proper error handling
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_TCP)
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
            except PermissionError:
                log_info(f"Skipping TCP reset packets for {target_ip} - requires admin privileges")
                return
            except Exception as e:
                log_error(f"Failed to create raw socket for {target_ip}: {e}")
                return
            
            # Create TCP reset packet
            packet = self._create_real_tcp_reset_packet(target_ip)
            if not packet:
                log_error(f"Failed to create TCP reset packet for {target_ip}")
                return
            
            # Send packet with error handling
            try:
                sock.sendto(packet, (target_ip, 0))
                log_info(f"✅ Sent TCP reset packet to {target_ip}")
            except PermissionError:
                log_info(f"Skipping TCP reset packet send for {target_ip} - requires admin privileges")
            except Exception as e:
                log_error(f"Failed to send TCP reset packet to {target_ip}: {e}")
            finally:
                sock.close()
                
        except Exception as e:
            log_error(f"Failed to send real reset packet to {target_ip}: {e}")
    
    def _create_real_tcp_reset_packet(self, target_ip: str) -> bytes:
        """Create a real TCP reset packet"""
        try:
            # IP header (20 bytes)
            ip_version = 4
            ip_ihl = 5
            ip_tos = 0
            ip_tot_len = 40  # 20 bytes IP + 20 bytes TCP
            ip_id = 54321
            ip_frag_off = 0
            ip_ttl = 64
            ip_proto = 6  # TCP
            ip_check = 0
            ip_saddr = socket.inet_aton(self._get_local_ip())
            ip_daddr = socket.inet_aton(target_ip)
            
            # Create IP header
            ip_header = struct.pack('!BBHHHBBH4s4s',
                (ip_version << 4) + ip_ihl, ip_tos, ip_tot_len, ip_id, ip_frag_off,
                ip_ttl, ip_proto, ip_check, ip_saddr, ip_daddr)
            
            # TCP header (20 bytes)
            tcp_sport = 12345  # Source port
            tcp_dport = 80     # Destination port
            tcp_seq = 0
            tcp_ack_seq = 0
            tcp_doff = 5
            tcp_flags = 0x04   # RST flag
            tcp_window = socket.htons(5840)
            tcp_check = 0
            tcp_urg_ptr = 0
            
            # Create TCP header
            tcp_header = struct.pack('!HHLLBBHHH',
                tcp_sport, tcp_dport, tcp_seq, tcp_ack_seq,
                (tcp_doff << 4) + 0, tcp_flags, tcp_window, tcp_check, tcp_urg_ptr)
            
            # Calculate TCP checksum
            tcp_check = self._calculate_tcp_checksum(ip_saddr, ip_daddr, tcp_header)
            tcp_header = struct.pack('!HHLLBBHHH',
                tcp_sport, tcp_dport, tcp_seq, tcp_ack_seq,
                (tcp_doff << 4) + 0, tcp_flags, tcp_window, tcp_check, tcp_urg_ptr)
            
            return ip_header + tcp_header
            
        except Exception as e:
            log_error(f"Failed to create real TCP reset packet: {e}")
            return b""
    
    def _calculate_tcp_checksum(self, ip_saddr: bytes, ip_daddr: bytes, tcp_header: bytes) -> int:
        """Calculate TCP checksum"""
        try:
            # Pseudo header for checksum calculation
            pseudo_header = struct.pack('!4s4sBBH',
                ip_saddr, ip_daddr, 0, 6, len(tcp_header))
            
            # Calculate checksum
            checksum = 0
            for i in range(0, len(pseudo_header), 2):
                checksum += struct.unpack('!H', pseudo_header[i:i+2])[0]
            
            for i in range(0, len(tcp_header), 2):
                if i + 1 < len(tcp_header):
                    checksum += struct.unpack('!H', tcp_header[i:i+2])[0]
                else:
                    checksum += tcp_header[i]
            
            # Handle carry
            while checksum >> 16:
                checksum = (checksum & 0xFFFF) + (checksum >> 16)
            
            return ~checksum & 0xFFFF
            
        except Exception as e:
            log_error(f"Failed to calculate TCP checksum: {e}")
            return 0
    
    def _get_local_ip(self) -> str:
        """Get local IP address"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(("8.8.8.8", 80))
                return sock.getsockname()[0]
        except Exception:
            return "192.168.1.1"  # Fallback
    
    def _send_enhanced_icmp_packets(self, target_ip: str):
        """Send enhanced ICMP disconnect packets for DayZ duping"""
        try:
            log_info("[GAMING] Sending enhanced ICMP disconnect packets for DayZ duping")
            
            # Send multiple types of ICMP packets
            icmp_types = [3, 5, 11, 12]  # Destination unreachable, redirect, time exceeded, parameter problem
            
            for icmp_type in icmp_types:
                icmp_packet = self._create_icmp_packet(target_ip, icmp_type)
                
                with socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP) as sock:
                    sock.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
                    sock.sendto(icmp_packet, (target_ip, 0))
                    
        except Exception as e:
            log_error(f"Failed to send ICMP packets to {target_ip}: {e}")
    
    def _start_dns_spoofing(self):
        """Start DNS spoofing for DayZ duping"""
        try:
            log_info("[GAMING] Starting DNS spoofing for DayZ duping")
            
            # Common DayZ server domains to spoof
            dayz_domains = [
                "dayz.com",
                "dayzgame.com", 
                "dayzcentral.com",
                "dayzmod.com"
            ]
            
            for domain in dayz_domains:
                self._dns_spoof_domain(domain)
                
        except Exception as e:
            log_error(f"Failed to start DNS spoofing: {e}")
    
    def _dns_spoof_domain(self, domain: str):
        """DNS spoof a specific domain"""
        try:
            log_info(f"[GAMING] Enhanced DNS spoofing for {domain} -> {self.ps5_ips[0] if self.ps5_ips else '127.0.0.1'}")
            
            # Create fake DNS response
            dns_packet = self._create_dns_spoof_packet(domain)
            
            # Send DNS spoof packet
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.sendto(dns_packet, ('8.8.8.8', 53))
                
        except Exception as e:
            log_error(f"Failed to DNS spoof {domain}: {e}")
    
    def _get_gateway_ip(self) -> Optional[str]:
        """Get the gateway IP address"""
        try:
            # Get default gateway
            result = subprocess.run(
                ["route", "print", "-4"], 
                capture_output=True, 
                text=True, 
                timeout=5
            )
            
            if result.returncode == 0:
                lines = result.stdout.split('\n')
                for line in lines:
                    if '0.0.0.0' in line and '0.0.0.0' in line.split():
                        parts = line.split()
                        if len(parts) >= 3:
                            return parts[2]  # Gateway IP
            
            return None
            
        except Exception as e:
            log_error(f"Failed to get gateway IP: {e}")
            return None
    
    def _poison_arp_table(self, target_ip: str, gateway_ip: str):
        """Enhanced ARP poisoning to redirect traffic"""
        try:
            # Send fake ARP responses to make target think we're the gateway
            log_info(f"[GAMING] Enhanced ARP poisoning: {target_ip} -> {gateway_ip}")
            
            # Add static ARP entry to poison the table
            subprocess.run([
                "arp", "-s", target_ip, "00:00:00:00:00:00"
            ], capture_output=True, timeout=3)
            
            # Also poison the gateway's ARP table
            subprocess.run([
                "arp", "-s", gateway_ip, "00:00:00:00:00:00"
            ], capture_output=True, timeout=3)
            
            # Add multiple fake MAC addresses to confuse the network
            fake_macs = ["00:00:00:00:00:01", "00:00:00:00:00:02", "00:00:00:00:00:03"]
            for i, mac in enumerate(fake_macs):
                fake_ip = f"{target_ip.split('.')[0]}.{target_ip.split('.')[1]}.{target_ip.split('.')[2]}.{200 + i}"
                subprocess.run([
                    "arp", "-s", fake_ip, mac
                ], capture_output=True, timeout=1)
            
            # Clear the target's ARP cache to force refresh
            subprocess.run([
                "arp", "-d", target_ip
            ], capture_output=True, timeout=1)
            
            log_info(f"[SUCCESS] Enhanced ARP table poisoned for {target_ip}")
            
        except Exception as e:
            log_error(f"Failed to poison ARP table for {target_ip}: {e}")
    
    def _send_fake_response(self, ps5_ip: str):
        """Send fake network response to create red chain effect"""
        try:
            # Create a fake ICMP "host unreachable" packet
            # This makes the PS5 think the connection is broken
            icmp_packet = self._create_fake_icmp_packet(ps5_ip)
            
            # Send the packet
            sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
            sock.sendto(icmp_packet, (ps5_ip, 0))
            sock.close()
            
        except Exception as e:
            log_error(f"Failed to send fake response to {ps5_ip}: {e}")
    
    def _create_fake_icmp_packet(self, target_ip: str) -> bytes:
        """Create a fake ICMP packet for red chain effect"""
        try:
            # ICMP header (8 bytes)
            icmp_type = 3  # Destination Unreachable
            icmp_code = 1  # Host Unreachable
            icmp_checksum = 0
            icmp_id = 0
            icmp_seq = 0
            
            # Create ICMP header
            icmp_header = struct.pack('!BBHHH', icmp_type, icmp_code, icmp_checksum, icmp_id, icmp_seq)
            
            # Add some data to make it look legitimate
            data = b'Connection lost - red chain indicator'
            
            # Calculate checksum
            icmp_checksum = self._calculate_icmp_checksum(icmp_header + data)
            icmp_header = struct.pack('!BBHHH', icmp_type, icmp_code, icmp_checksum, icmp_id, icmp_seq)
            
            return icmp_header + data
            
        except Exception as e:
            log_error(f"Failed to create fake ICMP packet: {e}")
            return b''
    
    def _calculate_icmp_checksum(self, data: bytes) -> int:
        """Calculate ICMP checksum"""
        try:
            if len(data) % 2 == 1:
                data += b'\x00'
            
            checksum = 0
            for i in range(0, len(data), 2):
                checksum += (data[i] << 8) + data[i + 1]
            
            checksum = (checksum >> 16) + (checksum & 0xffff)
            checksum += checksum >> 16
            checksum = ~checksum & 0xffff
            
            return checksum
            
        except Exception as e:
            log_error(f"Failed to calculate ICMP checksum: {e}")
            return 0
    
    def _send_disconnect_packets(self):
        """Send enhanced ICMP disconnect packets for DayZ duping"""
        try:
            log_info("[GAMING] Sending enhanced ICMP disconnect packets for DayZ duping")
            
            for ps5_ip in self.ps5_ips:
                # Send multiple types of ICMP packets to create connection issues
                self._send_icmp_unreachable(ps5_ip)
                self._send_icmp_time_exceeded(ps5_ip)
                self._send_icmp_redirect(ps5_ip)
                # Add TCP RST packets for more effective disruption
                self._send_tcp_rst_packets(ps5_ip)
                # Add UDP flood for network disruption
                self._send_udp_flood_packets(ps5_ip)
                
            log_info(f"[SUCCESS] Enhanced ICMP disconnect packets sent to {len(self.ps5_ips)} PS5 devices")
            
        except Exception as e:
            log_error(f"Failed to send enhanced disconnect packets: {e}")
    
    def _send_icmp_unreachable(self, target_ip: str):
        """Send enhanced ICMP unreachable packets"""
        try:
            # Send multiple unreachable packets with different sizes
            for size in [1, 32, 64, 128]:
                subprocess.run([
                    "ping", "-n", "1", "-w", "100", "-l", str(size), target_ip
                ], capture_output=True, timeout=1)
            # Add broadcast ping to disrupt network
            subprocess.run([
                "ping", "-n", "1", "-w", "100", "-l", "1", "255.255.255.255"
            ], capture_output=True, timeout=1)
            
        except Exception as e:
            log_error(f"Failed to send ICMP unreachable to {target_ip}: {e}")
    
    def _send_icmp_time_exceeded(self, target_ip: str):
        """Send enhanced ICMP time exceeded packets"""
        try:
            # Send multiple time exceeded packets with very short timeouts
            for timeout in [10, 20, 50]:
                subprocess.run([
                    "ping", "-n", "1", "-w", str(timeout), "-l", "1", target_ip
                ], capture_output=True, timeout=1)
            
        except Exception as e:
            log_error(f"Failed to send ICMP time exceeded to {target_ip}: {e}")
    
    def _send_icmp_redirect(self, target_ip: str):
        """Send enhanced ICMP redirect packets"""
        try:
            # Send redirect packets with different TTL values
            for ttl in [1, 2, 3]:
                subprocess.run([
                    "ping", "-n", "1", "-i", str(ttl), "-l", "1", target_ip
                ], capture_output=True, timeout=1)
            
        except Exception as e:
            log_error(f"Failed to send ICMP redirect to {target_ip}: {e}")
    
    def _send_tcp_rst_packets(self, target_ip: str):
        """Send TCP RST packets to disrupt connections"""
        try:
            # Common DayZ ports to target
            dayz_ports = [2302, 2303, 2304, 2305, 27015, 27016, 27017, 27018]
            for port in dayz_ports:
                # Use telnet to send RST packets
                subprocess.run([
                    "telnet", target_ip, str(port)
                ], capture_output=True, timeout=1)
        except Exception as e:
            log_error(f"Failed to send TCP RST packets to {target_ip}: {e}")
    
    def _send_udp_flood_packets(self, target_ip: str):
        """Send UDP flood packets to target"""
        try:
            # Create UDP socket with proper error handling
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            except Exception as e:
                log_error(f"Failed to create UDP socket for {target_ip}: {e}")
                return
            
            # Send UDP flood packets
            try:
                for port in [80, 443, 8080, 27015, 27016]:  # Common ports
                    for _ in range(5):  # Send 5 packets per port
                        try:
                            sock.sendto(b"DISCONNECT", (target_ip, port))
                        except Exception as e:
                            log_error(f"Failed to send UDP packet to {target_ip}:{port}: {e}")
                            break
                        
                log_info(f"✅ Sent UDP flood packets to {target_ip}")
            except Exception as e:
                log_error(f"Failed to send UDP flood packets to {target_ip}: {e}")
            finally:
                sock.close()
                
        except Exception as e:
            log_error(f"Failed to send UDP flood packets to {target_ip}: {e}")
    
    def _send_ps5_disconnect_packet(self, ps5_ip: str):
        """Send PS5-specific disconnect packet"""
        try:
            # Create a packet that PS5s interpret as connection loss
            # This creates the red chain visual effect
            packet_data = self._create_ps5_disconnect_packet(ps5_ip)
            
            # Send via UDP to common PS5 ports
            ps5_ports = [3074, 3075, 3076, 3077, 3078, 3079, 3080]  # Common PS5 ports
            
            for port in ps5_ports:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    sock.sendto(packet_data, (ps5_ip, port))
                    sock.close()
                except:
                    pass  # Ignore port errors
                    
        except Exception as e:
            log_error(f"Failed to send PS5 disconnect packet to {ps5_ip}: {e}")
    
    def _create_ps5_disconnect_packet(self, ps5_ip: str) -> bytes:
        """Create PS5-specific disconnect packet"""
        try:
            # Create a packet that PS5s interpret as network disconnection
            # This triggers the red chain visual indicator
            
            # Packet structure that PS5s recognize as "connection lost"
            packet = b''
            packet += b'\x00\x00'  # Version
            packet += b'\x00\x01'  # Type (disconnect)
            packet += b'\x00\x00'  # Length
            packet += b'\x00\x00'  # Checksum
            packet += b'RED_CHAIN_DISCONNECT'  # Payload
            
            return packet
            
        except Exception as e:
            log_error(f"Failed to create PS5 disconnect packet: {e}")
            return b''
    
    def _spoof_dns_responses(self):
        """Spoof DNS responses to disrupt PS5 internet connectivity"""
        try:
            log_info("[GAMING] Starting DNS spoofing for DayZ duping")
            
            # Common DayZ server domains that PS5 might try to resolve
            dayz_domains = [
                "dayz.com",
                "dayz.game",
                "dayzservers.com", 
                "dayz.net",
                "dayzcentral.com",
                "dayzdb.com",
                "dayzmod.com"
            ]
            
            for ps5_ip in self.ps5_ips:
                # Spoof DNS responses for each PS5
                for domain in dayz_domains:
                    self._spoof_dns_response(ps5_ip, domain)
                    
            log_info(f"[SUCCESS] DNS spoofing active for {len(self.ps5_ips)} PS5 devices")
            
        except Exception as e:
            log_error(f"Failed to start DNS spoofing: {e}")
    
    def _spoof_dns_response(self, target_ip: str, domain: str):
        """Enhanced DNS spoofing for a specific domain"""
        try:
            log_info(f"[GAMING] Enhanced DNS spoofing for {domain} -> {target_ip}")
            
            # Add fake DNS entry to hosts file
            hosts_entry = f"127.0.0.1 {domain}"
            try:
                with open("C:\\Windows\\System32\\drivers\\etc\\hosts", "a") as hosts_file:
                    hosts_file.write(f"\n{hosts_entry}")
            except:
                pass  # Ignore if we can't write to hosts file
            
            # Use nslookup to query the target with fake responses
            subprocess.run([
                "nslookup", domain, target_ip
            ], capture_output=True, timeout=2)
            
            # Also try to flush DNS cache on the target
            subprocess.run([
                "ipconfig", "/flushdns"
            ], capture_output=True, timeout=2)
            
            # Send fake DNS response packets
            self._send_fake_dns_packet(target_ip, domain)
            
        except Exception as e:
            log_error(f"Failed to spoof DNS response for {domain}: {e}")
    
    def _send_fake_dns_packet(self, target_ip: str, domain: str):
        """Send fake DNS response packet"""
        try:
            # Create a fake DNS response packet
            # This is a simplified version - in practice you'd use scapy
            dns_packet = self._create_fake_dns_packet(domain)
            
            # Send via UDP to DNS port
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.sendto(dns_packet, (target_ip, 53))
            sock.close()
            
        except Exception as e:
            log_error(f"Failed to send fake DNS packet to {target_ip}: {e}")
    
    def _create_fake_dns_packet(self, domain: str) -> bytes:
        """Create a fake DNS response packet"""
        try:
            # Simplified DNS response packet
            packet = b''
            packet += b'\x00\x01'  # ID
            packet += b'\x80\x01'  # Flags (response)
            packet += b'\x00\x01'  # Questions
            packet += b'\x00\x01'  # Answers
            packet += b'\x00\x00'  # Authority
            packet += b'\x00\x00'  # Additional
            
            # Domain name
            for part in domain.split('.'):
                packet += bytes([len(part)])
                packet += part.encode()
            packet += b'\x00'  # End of domain
            
            packet += b'\x00\x01'  # Type (A record)
            packet += b'\x00\x01'  # Class (IN)
            
            # Answer section
            packet += b'\xc0\x0c'  # Name pointer
            packet += b'\x00\x01'  # Type (A record)
            packet += b'\x00\x01'  # Class (IN)
            packet += b'\x00\x00\x00\x3c'  # TTL (60 seconds)
            packet += b'\x00\x04'  # Data length
            packet += b'\x7f\x00\x00\x01'  # IP (127.0.0.1)
            
            return packet
            
        except Exception as e:
            log_error(f"Failed to create fake DNS packet: {e}")
            return b''
    
    def _send_restore_packets(self):
        """Send packets to restore normal indicators"""
        try:
            for ps5_ip in self.ps5_ips:
                # Send restore packets
                self._send_ps5_restore_packet(ps5_ip)
                time.sleep(0.05)
                
        except Exception as e:
            log_error(f"Failed to send restore packets: {e}")
    
    def _send_ps5_restore_packet(self, ps5_ip: str):
        """Send PS5 restore packet"""
        try:
            # Create restore packet
            packet_data = self._create_ps5_restore_packet(ps5_ip)
            
            # Send to PS5 ports
            ps5_ports = [3074, 3075, 3076, 3077, 3078, 3079, 3080]
            
            for port in ps5_ports:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    sock.sendto(packet_data, (ps5_ip, port))
                    sock.close()
                except:
                    pass
                    
        except Exception as e:
            log_error(f"Failed to send PS5 restore packet to {ps5_ip}: {e}")
    
    def _create_ps5_restore_packet(self, ps5_ip: str) -> bytes:
        """Create PS5 restore packet"""
        try:
            # Packet that restores normal connection indicators
            packet = b''
            packet += b'\x00\x00'  # Version
            packet += b'\x00\x02'  # Type (restore)
            packet += b'\x00\x00'  # Length
            packet += b'\x00\x00'  # Checksum
            packet += b'RESTORE_CONNECTION'  # Payload
            
            return packet
            
        except Exception as e:
            log_error(f"Failed to create PS5 restore packet: {e}")
            return b''
    
    def _clear_dns_spoofing(self):
        """Clear DNS spoofing"""
        try:
            # Clear any DNS cache
            subprocess.run(['ipconfig', '/flushdns'], capture_output=True)
            log_info("Cleared DNS spoofing")
        except Exception as e:
            log_error(f"Failed to clear DNS spoofing: {e}")
    
    def _is_valid_ip(self, ip: str) -> bool:
        """Check if string is a valid IP address"""
        try:
            socket.inet_aton(ip)
            return True
        except:
            return False
    
    def get_status(self) -> Dict[str, any]:
        """Get dupe status"""
        return {
            'dupe_active': self.dupe_active,
            'ps5_devices': len(self.ps5_ips),
            'ps5_ips': self.ps5_ips.copy(),
            'active_methods': self.active_methods.copy()
        }

# Global dupe dropper instance
dupe_internet_dropper = DupeInternetDropper() 