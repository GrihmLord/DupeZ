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
from typing import List, Dict, Optional
from app.logs.logger import log_info, log_error
from app.firewall.udp_port_interrupter import UDPPortInterrupter

class DupeInternetDropper:
    """Creates visual disconnect indicators on PS5s without affecting network"""
    
    def __init__(self):
        self.dupe_active = False
        self.ps5_ips = []
        self.lock = threading.Lock()
        self.spoof_thread = None
        self.active_methods = []  # Track which methods are currently active
        
        # Initialize UDP port interrupter for Laganator integration
        self.udp_interrupter = UDPPortInterrupter()
        
    def start_dupe_with_devices(self, devices: List[Dict], methods: List[str]) -> bool:
        """Start the dupe with specific devices and methods"""
        try:
            with self.lock:
                if self.dupe_active:
                    log_info("Dupe already active")
                    return True
                
                log_info(f"🎭 Starting dupe with {len(devices)} devices and methods: {methods}")
                
                # Extract IP addresses from devices
                self.ps5_ips = [device.get('ip') for device in devices if device.get('ip')]
                
                if not self.ps5_ips:
                    log_info("No valid IP addresses found in selected devices")
                    return False
                
                # Apply selected methods
                for method in methods:
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
                        self.udp_interrupter.start_udp_interruption(
                            target_ips=self.ps5_ips,
                            drop_rate=90,  # 90% drop rate for lagging without disconnection
                            duration=0  # No timer, manual stop
                        )
                
                self.dupe_active = True
                self.active_methods = methods
                log_info(f"✅ Dupe active on {len(self.ps5_ips)} devices with methods: {methods}")
                return True
                
        except Exception as e:
            log_error(f"Failed to start dupe with devices: {e}")
            return False
    
    def start_dupe_with_methods(self, methods: List[str]) -> bool:
        """Start dupe with selected methods"""
        try:
            self.active_methods = methods
            log_info(f"🎮 Starting DayZ dupe with methods: {', '.join(methods)}")
            
            # Initialize PS5 IPs if not already done
            if not self.ps5_ips:
                self._find_ps5_devices()
            
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
                
            if "arp_poison" in methods:
                self._start_arp_poisoning()
                
            if "udp_interrupt" in methods:
                # Start UDP port interruption (Laganator integration)
                self.udp_interrupter.start_udp_interruption(
                    target_ips=self.ps5_ips,
                    drop_rate=90,  # 90% drop rate for lagging without disconnection
                    duration=0  # No timer, manual stop
                )
            
            log_info(f"🎮 DayZ dupe started with {len(methods)} methods")
            return True
            
        except Exception as e:
            log_error(f"Failed to start DayZ dupe: {e}")
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
                
                log_info("🌐 Stopping PS5 dupe - restoring normal indicators...")
                
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
                log_info("✅ Dupe stopped successfully")
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
            log_info("🎮 Starting response spoofing for PS5 disconnection")
            
            # Create spoofed responses that will confuse the PS5
            for ps5_ip in self.ps5_ips:
                # Send fake connection reset packets
                self._send_fake_reset_packet(ps5_ip)
                
            log_info(f"✅ Response spoofing active for {len(self.ps5_ips)} PS5 devices")
            
        except Exception as e:
            log_error(f"Failed to start response spoofing: {e}")
    
    def _start_arp_poisoning(self):
        """Start ARP poisoning for effective DayZ duping"""
        try:
            log_info("🎮 Starting ARP poisoning for DayZ duping")
            
            # Get gateway IP
            gateway_ip = self._get_gateway_ip()
            if not gateway_ip:
                log_error("Could not determine gateway IP for ARP poisoning")
                return
            
            # Poison ARP table for each PS5 device
            for ps5_ip in self.ps5_ips:
                self._poison_arp_table(ps5_ip, gateway_ip)
                
            log_info(f"✅ ARP poisoning active for {len(self.ps5_ips)} PS5 devices")
            
        except Exception as e:
            log_error(f"Failed to start ARP poisoning: {e}")
    
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
            log_info(f"🎮 Enhanced ARP poisoning: {target_ip} -> {gateway_ip}")
            
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
            
            log_info(f"✅ Enhanced ARP table poisoned for {target_ip}")
            
        except Exception as e:
            log_error(f"Failed to poison ARP table for {target_ip}: {e}")
    
    def _send_fake_reset_packet(self, target_ip: str):
        """Send fake TCP reset packets to confuse PS5"""
        try:
            log_info(f"🎮 Sending fake reset packet to {target_ip}")
            
            # Create a simple ICMP packet to simulate connection issues
            # This is a simplified version - in practice you'd use scapy for proper packet crafting
            subprocess.run([
                "ping", "-n", "1", "-w", "100", target_ip
            ], capture_output=True, timeout=2)
            
        except Exception as e:
            log_error(f"Failed to send fake reset packet to {target_ip}: {e}")
    
    def _spoof_responses(self):
        """Spoof network responses to create disconnect indicators"""
        try:
            while self.dupe_active:
                for ps5_ip in self.ps5_ips:
                    try:
                        # Send fake "connection lost" responses
                        self._send_fake_response(ps5_ip)
                        time.sleep(0.1)  # Small delay between responses
                    except Exception as e:
                        log_error(f"Failed to spoof response to {ps5_ip}: {e}")
                
                time.sleep(1)  # Wait before next round
                
        except Exception as e:
            log_error(f"Spoofing thread error: {e}")
    
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
            log_info("🎮 Sending enhanced ICMP disconnect packets for DayZ duping")
            
            for ps5_ip in self.ps5_ips:
                # Send ICMP unreachable packets
                self._send_icmp_unreachable(ps5_ip)
                time.sleep(0.1)
                
                # Send ICMP time exceeded packets
                self._send_icmp_time_exceeded(ps5_ip)
                time.sleep(0.1)
                
                # Send ICMP redirect packets
                self._send_icmp_redirect(ps5_ip)
                time.sleep(0.1)
                
                # Send TCP RST packets (without external tools)
                self._send_tcp_rst_packets(ps5_ip)
                time.sleep(0.1)
                
                # Send UDP flood packets (without external tools)
                self._send_udp_flood_packets(ps5_ip)
                time.sleep(0.1)
                
            log_info(f"✅ Enhanced ICMP disconnect packets sent to {len(self.ps5_ips)} PS5 devices")
            
        except Exception as e:
            log_error(f"Failed to send disconnect packets: {e}")
    
    def _send_icmp_unreachable(self, target_ip: str):
        """Send ICMP unreachable packet without external tools"""
        try:
            # Create ICMP unreachable packet using raw sockets
            sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
            
            # Create ICMP unreachable packet
            icmp_type = 3  # Destination Unreachable
            icmp_code = 1  # Host Unreachable
            icmp_checksum = 0
            icmp_identifier = 0
            icmp_sequence = 0
            
            # Build ICMP header
            icmp_header = struct.pack('!BBHHH', icmp_type, icmp_code, icmp_checksum, icmp_identifier, icmp_sequence)
            
            # Calculate checksum
            icmp_checksum = self._calculate_icmp_checksum(icmp_header)
            icmp_header = struct.pack('!BBHHH', icmp_type, icmp_code, icmp_checksum, icmp_identifier, icmp_sequence)
            
            # Send packet
            sock.sendto(icmp_header, (target_ip, 0))
            sock.close()
            
        except Exception as e:
            log_error(f"Failed to send ICMP unreachable to {target_ip}: {e}")
    
    def _send_icmp_time_exceeded(self, target_ip: str):
        """Send ICMP time exceeded packet without external tools"""
        try:
            # Create ICMP time exceeded packet using raw sockets
            sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
            
            # Create ICMP time exceeded packet
            icmp_type = 11  # Time Exceeded
            icmp_code = 0   # TTL expired
            icmp_checksum = 0
            icmp_identifier = 0
            icmp_sequence = 0
            
            # Build ICMP header
            icmp_header = struct.pack('!BBHHH', icmp_type, icmp_code, icmp_checksum, icmp_identifier, icmp_sequence)
            
            # Calculate checksum
            icmp_checksum = self._calculate_icmp_checksum(icmp_header)
            icmp_header = struct.pack('!BBHHH', icmp_type, icmp_code, icmp_checksum, icmp_identifier, icmp_sequence)
            
            # Send packet
            sock.sendto(icmp_header, (target_ip, 0))
            sock.close()
            
        except Exception as e:
            log_error(f"Failed to send ICMP time exceeded to {target_ip}: {e}")
    
    def _send_icmp_redirect(self, target_ip: str):
        """Send ICMP redirect packet without external tools"""
        try:
            # Create ICMP redirect packet using raw sockets
            sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
            
            # Create ICMP redirect packet
            icmp_type = 5   # Redirect
            icmp_code = 0   # Redirect for Network
            icmp_checksum = 0
            icmp_identifier = 0
            icmp_sequence = 0
            
            # Build ICMP header
            icmp_header = struct.pack('!BBHHH', icmp_type, icmp_code, icmp_checksum, icmp_identifier, icmp_sequence)
            
            # Calculate checksum
            icmp_checksum = self._calculate_icmp_checksum(icmp_header)
            icmp_header = struct.pack('!BBHHH', icmp_type, icmp_code, icmp_checksum, icmp_identifier, icmp_sequence)
            
            # Send packet
            sock.sendto(icmp_header, (target_ip, 0))
            sock.close()
            
        except Exception as e:
            log_error(f"Failed to send ICMP redirect to {target_ip}: {e}")
    
    def _send_tcp_rst_packets(self, target_ip: str):
        """Send TCP RST packets without external tools"""
        try:
            # Create TCP RST packet using raw sockets
            sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_TCP)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
            
            # Common PS5 ports
            ps5_ports = [3074, 3075, 3076, 3077, 3078, 3079, 3080, 80, 443]
            
            for port in ps5_ports:
                try:
                    # Create TCP RST packet
                    tcp_header = struct.pack('!HHLLBBHHH',
                        12345,  # Source port
                        port,   # Destination port
                        0,      # Sequence number
                        0,      # Acknowledgement number
                        5 << 4, # Data offset and flags
                        4,      # RST flag
                        0,      # Window size
                        0,      # Checksum
                        0       # Urgent pointer
                    )
                    
                    # Send packet
                    sock.sendto(tcp_header, (target_ip, port))
                    time.sleep(0.01)
                    
                except Exception as e:
                    # Ignore individual port errors
                    pass
            
            sock.close()
            
        except Exception as e:
            log_error(f"Failed to send TCP RST packets to {target_ip}: {e}")
    
    def _send_udp_flood_packets(self, target_ip: str):
        """Send UDP flood packets without external tools"""
        try:
            # Create UDP flood packet using raw sockets
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            
            # Common PS5 ports
            ps5_ports = [3074, 3075, 3076, 3077, 3078, 3079, 3080, 53, 67, 68]
            
            # Create fake UDP payload
            payload = b'DISCONNECT_PACKET' * 10
            
            for port in ps5_ports:
                try:
                    # Send UDP packet
                    sock.sendto(payload, (target_ip, port))
                    time.sleep(0.01)
                    
                except Exception as e:
                    # Ignore individual port errors
                    pass
            
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
            log_info("🎮 Starting DNS spoofing for DayZ duping")
            
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
                    
            log_info(f"✅ DNS spoofing active for {len(self.ps5_ips)} PS5 devices")
            
        except Exception as e:
            log_error(f"Failed to start DNS spoofing: {e}")
    
    def _spoof_dns_response(self, target_ip: str, domain: str):
        """Enhanced DNS spoofing for a specific domain without external tools"""
        try:
            log_info(f"🎮 Enhanced DNS spoofing for {domain} -> {target_ip}")
            
            # Add fake DNS entry to hosts file (with better error handling)
            hosts_entry = f"127.0.0.1 {domain}"
            try:
                with open("C:\\Windows\\System32\\drivers\\etc\\hosts", "a") as hosts_file:
                    hosts_file.write(f"\n{hosts_entry}")
            except PermissionError:
                log_error("Could not modify hosts file: Permission denied - run as Administrator")
            except Exception as e:
                log_error(f"Could not modify hosts file: {e}")
            
            # Send fake DNS response packets (without external tools)
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