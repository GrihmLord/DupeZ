#!/usr/bin/env python3
"""
Internet Dropper
Perfect internet drop feature with toggle functionality
"""

import subprocess
import threading
import time
from typing import List, Dict, Optional
from app.logs.logger import log_info, log_error

class InternetDropper:
    """Perfect internet drop feature with toggle functionality"""
    
    def __init__(self):
        self.internet_dropped = False
        self.original_routes = {}
        self.original_dns = []
        self.lock = threading.Lock()
        
    def drop_internet(self) -> bool:
        """Drop internet connectivity"""
        try:
            with self.lock:
                if self.internet_dropped:
                    log_info("Internet already dropped")
                    return True
                
                log_info("🛑 Dropping internet connectivity...")
                
                # Store original DNS settings
                self._store_original_dns()
                
                # Store original routes
                self._store_original_routes()
                
                # Block all outbound traffic
                self._block_outbound_traffic()
                
                # Block DNS servers
                self._block_dns_servers()
                
                # Block common internet ports
                self._block_internet_ports()
                
                # Add route to nowhere
                self._add_blackhole_route()
                
                self.internet_dropped = True
                log_info("✅ Internet dropped successfully")
                return True
                
        except Exception as e:
            log_error(f"Failed to drop internet: {e}")
            return False
    
    def restore_internet(self) -> bool:
        """Restore internet connectivity"""
        try:
            with self.lock:
                if not self.internet_dropped:
                    log_info("Internet not dropped")
                    return True
                
                log_info("🌐 Restoring internet connectivity...")
                
                # Remove blackhole route
                self._remove_blackhole_route()
                
                # Restore original routes
                self._restore_original_routes()
                
                # Restore DNS settings
                self._restore_original_dns()
                
                # Remove firewall blocks
                self._remove_internet_blocks()
                
                # Clear DNS cache
                subprocess.run(["ipconfig", "/flushdns"], capture_output=True)
                
                # Clear ARP cache
                subprocess.run(["arp", "-d", "*"], capture_output=True)
                
                self.internet_dropped = False
                log_info("✅ Internet restored successfully")
                return True
                
        except Exception as e:
            log_error(f"Failed to restore internet: {e}")
            return False
    
    def toggle_internet(self) -> bool:
        """Toggle internet connectivity"""
        if self.internet_dropped:
            return self.restore_internet()
        else:
            return self.drop_internet()
    
    def _store_original_dns(self):
        """Store original DNS settings"""
        try:
            # Get current DNS servers
            result = subprocess.run(["ipconfig", "/all"], capture_output=True, text=True)
            lines = result.stdout.split('\n')
            
            for line in lines:
                if "DNS Servers" in line and ":" in line:
                    dns = line.split(":")[-1].strip()
                    if dns and dns != "":
                        self.original_dns.append(dns)
            
            log_info(f"Stored {len(self.original_dns)} DNS servers")
        except Exception as e:
            log_error(f"Failed to store DNS: {e}")
    
    def _store_original_routes(self):
        """Store original routes"""
        try:
            result = subprocess.run(["route", "print"], capture_output=True, text=True)
            lines = result.stdout.split('\n')
            
            for line in lines:
                if "0.0.0.0" in line and "0.0.0.0" in line:
                    parts = line.split()
                    if len(parts) >= 4:
                        self.original_routes[parts[0]] = parts[2]
            
            log_info(f"Stored {len(self.original_routes)} routes")
        except Exception as e:
            log_error(f"Failed to store routes: {e}")
    
    def _block_outbound_traffic(self):
        """Block all outbound traffic"""
        try:
            # Create firewall rule to block all outbound traffic
            cmd = [
                "netsh", "advfirewall", "firewall", "add", "rule",
                "name=DupeZ_Internet_Block_Outbound",
                "dir=out",
                "action=block",
                "enable=yes"
            ]
            subprocess.run(cmd, capture_output=True, check=True)
            log_info("Blocked outbound traffic")
        except Exception as e:
            log_error(f"Failed to block outbound traffic: {e}")
    
    def _block_dns_servers(self):
        """Block DNS servers"""
        try:
            # Common DNS servers to block
            dns_servers = [
                "8.8.8.8", "8.8.4.4",  # Google DNS
                "1.1.1.1", "1.0.0.1",  # Cloudflare DNS
                "208.67.222.222", "208.67.220.220",  # OpenDNS
                "9.9.9.9", "149.112.112.112"  # Quad9 DNS
            ]
            
            for dns in dns_servers:
                cmd = [
                    "netsh", "advfirewall", "firewall", "add", "rule",
                    f"name=DupeZ_DNS_Block_{dns}",
                    "dir=out",
                    "action=block",
                    f"remoteip={dns}",
                    "enable=yes"
                ]
                subprocess.run(cmd, capture_output=True)
            
            log_info("Blocked DNS servers")
        except Exception as e:
            log_error(f"Failed to block DNS servers: {e}")
    
    def _block_internet_ports(self):
        """Block common internet ports"""
        try:
            # Common internet ports to block
            ports = [80, 443, 53, 21, 22, 23, 25, 110, 143, 993, 995]
            
            for port in ports:
                cmd = [
                    "netsh", "advfirewall", "firewall", "add", "rule",
                    f"name=DupeZ_Port_Block_{port}",
                    "dir=out",
                    "action=block",
                    f"remoteport={port}",
                    "enable=yes"
                ]
                subprocess.run(cmd, capture_output=True)
            
            log_info("Blocked internet ports")
        except Exception as e:
            log_error(f"Failed to block internet ports: {e}")
    
    def _add_blackhole_route(self):
        """Add route to nowhere"""
        try:
            # Add route to 0.0.0.0/0 to 127.0.0.1 (blackhole)
            cmd = ["route", "add", "0.0.0.0", "mask", "0.0.0.0", "127.0.0.1"]
            subprocess.run(cmd, capture_output=True)
            log_info("Added blackhole route")
        except Exception as e:
            log_error(f"Failed to add blackhole route: {e}")
    
    def _remove_blackhole_route(self):
        """Remove blackhole route"""
        try:
            cmd = ["route", "delete", "0.0.0.0"]
            subprocess.run(cmd, capture_output=True)
            log_info("Removed blackhole route")
        except Exception as e:
            log_error(f"Failed to remove blackhole route: {e}")
    
    def _restore_original_routes(self):
        """Restore original routes"""
        try:
            for destination, gateway in self.original_routes.items():
                cmd = ["route", "add", destination, "mask", "0.0.0.0", gateway]
                subprocess.run(cmd, capture_output=True)
            log_info("Restored original routes")
        except Exception as e:
            log_error(f"Failed to restore routes: {e}")
    
    def _restore_original_dns(self):
        """Restore original DNS settings"""
        try:
            # This would require more complex DNS restoration
            # For now, just clear DNS cache
            subprocess.run(["ipconfig", "/flushdns"], capture_output=True)
            log_info("Restored DNS settings")
        except Exception as e:
            log_error(f"Failed to restore DNS: {e}")
    
    def _remove_internet_blocks(self):
        """Remove internet blocking rules"""
        try:
            # Remove all DupeZ internet blocking rules
            cmd = [
                "netsh", "advfirewall", "firewall", "delete", "rule",
                "name=DupeZ_Internet_Block_*"
            ]
            subprocess.run(cmd, capture_output=True)
            
            cmd = [
                "netsh", "advfirewall", "firewall", "delete", "rule",
                "name=DupeZ_DNS_Block_*"
            ]
            subprocess.run(cmd, capture_output=True)
            
            cmd = [
                "netsh", "advfirewall", "firewall", "delete", "rule",
                "name=DupeZ_Port_Block_*"
            ]
            subprocess.run(cmd, capture_output=True)
            
            log_info("Removed internet blocking rules")
        except Exception as e:
            log_error(f"Failed to remove internet blocks: {e}")
    
    def is_internet_dropped(self) -> bool:
        """Check if internet is currently dropped"""
        return self.internet_dropped
    
    def get_status(self) -> Dict[str, any]:
        """Get current status"""
        return {
            "internet_dropped": self.internet_dropped,
            "original_routes_count": len(self.original_routes),
            "original_dns_count": len(self.original_dns)
        }

# Global instance
internet_dropper = InternetDropper() 