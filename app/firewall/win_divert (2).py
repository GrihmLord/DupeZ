# app/firewall/win_divert.py

import threading
import subprocess
import time
import os
import platform
from typing import Dict, List, Optional, Tuple
from app.logs.logger import log_info, log_error

class WinDivertController:
    """Advanced WinDivert controller for prioritized packet manipulation"""
    
    def __init__(self):
        self.divert_processes = {}  # {ip: process}
        self.active_filters = {}    # {ip: filter_string}
        self.is_running = False
        self.priority_levels = {
            'high': '--priority=1',
            'medium': '--priority=2', 
            'low': '--priority=3'
        }
        self.drop_rates = {
            'aggressive': 100,    # 100% drop
            'moderate': 75,       # 75% drop
            'light': 50,          # 50% drop
            'minimal': 25         # 25% drop
        }
        
    def initialize(self):
        """Initialize WinDivert controller"""
        try:
            # Check if WinDivert is available
            if not self._check_windivert_availability():
                log_error("WinDivert not available - falling back to firewall methods")
                return False
                
            self.is_running = True
            log_info("[SUCCESS] WinDivert controller initialized")
            return True
            
        except Exception as e:
            log_error(f"WinDivert initialization failed: {e}")
            return False
    
    def _check_windivert_availability(self) -> bool:
        """Check if WinDivert is available on the system"""
        try:
            # Check for WinDivert executable
            windivert_paths = [
                "WinDivert64.exe",
                "WinDivert32.exe", 
                os.path.join(os.getcwd(), "WinDivert64.exe"),
                os.path.join(os.getcwd(), "WinDivert32.exe"),
                "C:\\Windows\\System32\\WinDivert64.exe",
                os.path.join(os.path.dirname(__file__), "WinDivert64.exe"),
                os.path.join(os.path.dirname(__file__), "WinDivert32.exe")
            ]
            
            for path in windivert_paths:
                if os.path.exists(path):
                    log_info(f"[SUCCESS] WinDivert found at: {path}")
                    
                    # Test if WinDivert is working
                    try:
                        result = subprocess.run([path, "--help"], 
                                              capture_output=True, 
                                              text=True, 
                                              timeout=5)
                        if result.returncode == 0 or "WinDivert" in result.stdout:
                            log_info(f"[SUCCESS] WinDivert is working correctly: {path}")
                            return True
                        else:
                            log_error(f"WinDivert test failed: {result.stderr}")
                    except subprocess.TimeoutExpired:
                        log_info(f"[SUCCESS] WinDivert is working (help command executed): {path}")
                        return True
                    except Exception as e:
                        log_error(f"WinDivert test error: {e}")
                        continue
                    
            log_error("WinDivert executable not found or not working")
            log_info("[INFO] Please download WinDivert from: https://reqrypt.org/windivert.html")
            log_info("[INFO] Or run: python download_windivert_manual.py")
            return False
            
        except Exception as e:
            log_error(f"WinDivert availability check failed: {e}")
            return False
    
    def start_divert(self, ip: str, priority: str = 'high', drop_rate: str = 'aggressive', 
                    protocol: str = 'all', ports: List[int] = None) -> bool:
        """Start WinDivert for specific IP with advanced options"""
        try:
            if not self.is_running:
                log_error("WinDivert controller not initialized")
                return False
                
            # Stop existing divert for this IP
            self.stop_divert(ip)
            
            # Build advanced filter
            filter_string = self._build_advanced_filter(ip, protocol, ports)
            
            # Build command with priority and drop rate
            command = self._build_divert_command(filter_string, priority, drop_rate)
            
            # Start WinDivert process
            process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            
            # Store process and filter info
            self.divert_processes[ip] = process
            self.active_filters[ip] = filter_string
            
            log_info(f"[SUCCESS] WinDivert started for {ip} with {priority} priority, {drop_rate} drop rate")
            return True
            
        except Exception as e:
            log_error(f"WinDivert start failed for {ip}: {e}")
            return False
    
    def _build_advanced_filter(self, ip: str, protocol: str, ports: List[int] = None) -> str:
        """Build advanced WinDivert filter string"""
        try:
            # Base filter for outbound traffic to target IP
            filter_parts = [f"outbound and ip.DstAddr == {ip}"]
            
            # Add protocol filter
            if protocol.lower() == 'tcp':
                filter_parts.append("and tcp")
            elif protocol.lower() == 'udp':
                filter_parts.append("and udp")
            elif protocol.lower() == 'icmp':
                filter_parts.append("and icmp")
            
            # Add port filters if specified
            if ports:
                port_conditions = []
                for port in ports:
                    if protocol.lower() == 'tcp':
                        port_conditions.append(f"tcp.DstPort == {port}")
                    elif protocol.lower() == 'udp':
                        port_conditions.append(f"udp.DstPort == {port}")
                
                if port_conditions:
                    filter_parts.append(f"and ({' or '.join(port_conditions)})")
            
            return " ".join(filter_parts)
            
        except Exception as e:
            log_error(f"Filter building failed: {e}")
            return f"outbound and ip.DstAddr == {ip}"
    
    def _build_divert_command(self, filter_string: str, priority: str, drop_rate: str) -> List[str]:
        """Build WinDivert command with advanced options"""
        try:
            command = ["WinDivert64.exe"]
            
            # Add filter
            command.append(filter_string)
            
            # Add priority
            if priority in self.priority_levels:
                command.append(self.priority_levels[priority])
            
            # Add drop rate
            if drop_rate in self.drop_rates:
                rate = self.drop_rates[drop_rate]
                command.extend(["--drop", f"--rate={rate}"])
            
            # Add additional options for better performance
            command.extend([
                "--loopback",  # Include loopback traffic
                "--no-reset",  # Don't reset connections
                "--no-checksum"  # Skip checksum validation for speed
            ])
            
            return command
            
        except Exception as e:
            log_error(f"Command building failed: {e}")
            return ["WinDivert64.exe", filter_string, "--drop"]
    
    def stop_divert(self, ip: str = None) -> bool:
        """Stop WinDivert for specific IP or all"""
        try:
            if ip:
                # Stop specific IP
                if ip in self.divert_processes:
                    process = self.divert_processes[ip]
                    process.terminate()
                    process.wait(timeout=5)
                    del self.divert_processes[ip]
                    del self.active_filters[ip]
                    log_info(f"[SUCCESS] WinDivert stopped for {ip}")
                    return True
            else:
                # Stop all processes
                for ip, process in self.divert_processes.items():
                    try:
                        process.terminate()
                        process.wait(timeout=5)
                    except:
                        process.kill()
                
                self.divert_processes.clear()
                self.active_filters.clear()
                log_info("[SUCCESS] All WinDivert processes stopped")
                return True
                
        except Exception as e:
            log_error(f"WinDivert stop failed: {e}")
            return False
    
    def get_active_diverts(self) -> List[str]:
        """Get list of active diverted IPs"""
        return list(self.divert_processes.keys())
    
    def is_diverting(self, ip: str) -> bool:
        """Check if specific IP is being diverted"""
        return ip in self.divert_processes
    
    def update_divert_settings(self, ip: str, priority: str = None, drop_rate: str = None) -> bool:
        """Update divert settings for specific IP"""
        try:
            if ip not in self.divert_processes:
                log_error(f"No active divert for {ip}")
                return False
            
            # Stop current divert
            self.stop_divert(ip)
            
            # Get current filter
            filter_string = self.active_filters.get(ip, f"outbound and ip.DstAddr == {ip}")
            
            # Restart with new settings
            return self.start_divert(ip, priority or 'high', drop_rate or 'aggressive')
            
        except Exception as e:
            log_error(f"Update divert settings failed for {ip}: {e}")
            return False
    
    def cleanup(self):
        """Cleanup all WinDivert processes"""
        try:
            self.stop_divert()  # Stop all
            self.is_running = False
            log_info("[SUCCESS] WinDivert controller cleaned up")
        except Exception as e:
            log_error(f"WinDivert cleanup failed: {e}")

# Global instance
windivert_controller = WinDivertController()

# Legacy functions for backward compatibility
def start_divert(ip: str):
    """Legacy function - use WinDivertController instead"""
    return windivert_controller.start_divert(ip)

def stop_divert(ip: str = None):
    """Legacy function - use WinDivertController instead"""
    return windivert_controller.stop_divert(ip)
