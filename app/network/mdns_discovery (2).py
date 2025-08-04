# app/network/mdns_discovery.py

import socket
import threading
import time
from typing import List, Dict, Optional
from app.logs.logger import log_info, log_error

class MDNSDiscovery:
    def __init__(self):
        self.discovered_devices = []
        self.discovery_running = False
        self.discovery_thread = None
        
    def start_discovery(self):
        """Start mDNS discovery in background"""
        if self.discovery_running:
            return
            
        self.discovery_running = True
        self.discovery_thread = threading.Thread(target=self._discovery_loop, daemon=True)
        self.discovery_thread.start()
        log_info("mDNS discovery started")
    
    def stop_discovery(self):
        """Stop mDNS discovery"""
        self.discovery_running = False
        if self.discovery_thread:
            self.discovery_thread.join(timeout=5)
        log_info("mDNS discovery stopped")
    
    def _discovery_loop(self):
        """Main discovery loop"""
        while self.discovery_running:
            try:
                self._discover_devices()
                time.sleep(30)  # Scan every 30 seconds
            except Exception as e:
                log_error(f"mDNS discovery error: {e}")
                time.sleep(60)
    
    def _discover_devices(self):
        """Discover devices using mDNS"""
        try:
            # Create mDNS socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(5)
            
            # Send mDNS query
            query = self._create_mdns_query()
            sock.sendto(query, ('224.0.0.251', 5353))
            
            # Listen for responses
            devices = []
            start_time = time.time()
            
            while time.time() - start_time < 10:  # Listen for 10 seconds
                try:
                    data, addr = sock.recvfrom(1024)
                    device = self._parse_mdns_response(data, addr[0])
                    if device:
                        devices.append(device)
                except socket.timeout:
                    continue
                except Exception as e:
                    log_error(f"Error parsing mDNS response: {e}")
            
            sock.close()
            
            # Update discovered devices
            self.discovered_devices = devices
            log_info(f"mDNS discovered {len(devices)} devices")
            
        except Exception as e:
            log_error(f"mDNS discovery failed: {e}")
    
    def _create_mdns_query(self) -> bytes:
        """Create mDNS query packet"""
        # Simplified mDNS query for device discovery
        query = b'\x00\x00'  # Transaction ID
        query += b'\x00\x01'  # Flags
        query += b'\x00\x01'  # Questions
        query += b'\x00\x00'  # Answer RRs
        query += b'\x00\x00'  # Authority RRs
        query += b'\x00\x00'  # Additional RRs
        
        # Query name (simplified)
        query += b'\x07_local\x04_udp\x05local\x00'
        query += b'\x00\x0c'  # Type (PTR)
        query += b'\x00\x01'  # Class (IN)
        
        return query
    
    def _parse_mdns_response(self, data: bytes, source_ip: str) -> Optional[Dict]:
        """Parse mDNS response packet"""
        try:
            if len(data) < 12:
                return None
            
            # Extract basic info
            device = {
                "ip": source_ip,
                "mac": "Unknown",
                "vendor": "Unknown",
                "hostname": f"mdns-{source_ip.replace('.', '-')}",
                "local": False,
                "traffic": 0,
                "discovery_method": "mDNS"
            }
            
            # Try to extract hostname from response
            if b'local' in data:
                device["hostname"] = f"mdns-device-{source_ip}"
            
            return device
            
        except Exception as e:
            log_error(f"Failed to parse mDNS response: {e}")
            return None
    
    def get_discovered_devices(self) -> List[Dict]:
        """Get list of devices discovered via mDNS"""
        return self.discovered_devices.copy()
    
    def is_discovery_running(self) -> bool:
        """Check if discovery is running"""
        return self.discovery_running

# Global mDNS discovery instance
mdns_discovery = MDNSDiscovery()

def start_mdns_discovery():
    """Start mDNS discovery"""
    mdns_discovery.start_discovery()

def stop_mdns_discovery():
    """Stop mDNS discovery"""
    mdns_discovery.stop_discovery()

def get_mdns_devices() -> List[Dict]:
    """Get devices discovered via mDNS"""
    return mdns_discovery.get_discovered_devices()
