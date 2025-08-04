#!/usr/bin/env python3
"""
Enhanced PS5 Internet Restoration Script
Comprehensive PS5 connectivity restoration with advanced error handling
"""

import subprocess
import sys
import os
import time
import socket
import platform
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import re

# Add the app directory to the path for logging
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from app.logs.logger import log_info, log_error, log_performance

class PS5RestorationEngine:
    """Enhanced PS5 restoration engine with comprehensive error handling"""
    
    def __init__(self):
        self.restoration_methods = [
            self._clear_firewall_rules,
            self._clear_hosts_file,
            self._clear_route_table,
            self._clear_dns_cache,
            self._clear_arp_cache,
            self._reset_network_adapters,
            self._restart_network_services,
            self._clear_ps5_specific_blocks,
            self._test_connectivity
        ]
        self.ps5_devices = []
        self.restoration_log = []
        
    def restore_ps5_connectivity(self, target_mac: Optional[str] = None) -> Dict:
        """Comprehensive PS5 connectivity restoration"""
        start_time = time.time()
        success_count = 0
        total_methods = len(self.restoration_methods)
        
        log_info("Starting comprehensive PS5 connectivity restoration")
        
        try:
            # Step 1: Detect PS5 devices
            print("🔍 Detecting PS5 devices...")
            self._detect_ps5_devices()
            
            # Step 2: Run all restoration methods
            for i, method in enumerate(self.restoration_methods, 1):
                try:
                    method_name = method.__name__.replace('_', ' ').title()
                    print(f"🔄 [{i}/{total_methods}] Running: {method_name}")
                    log_info(f"Running restoration method {i}/{total_methods}: {method.__name__}")
                    
                    if target_mac and 'mac' in method.__name__.lower():
                        result = method(target_mac)
                    else:
                        result = method()
                    
                    if result:
                        success_count += 1
                        self.restoration_log.append({
                            'method': method.__name__,
                            'status': 'SUCCESS',
                            'timestamp': time.time()
                        })
                        print(f"✅ [{i}/{total_methods}] {method_name} completed successfully")
                        log_info(f"Method {method.__name__} completed successfully")
                    else:
                        self.restoration_log.append({
                            'method': method.__name__,
                            'status': 'FAILED',
                            'timestamp': time.time()
                        })
                        print(f"❌ [{i}/{total_methods}] {method_name} failed")
                        log_error(f"Method {method.__name__} failed")
                        
                except Exception as e:
                    log_error(f"Method {method.__name__} failed with exception", exception=e)
                    self.restoration_log.append({
                        'method': method.__name__,
                        'status': 'ERROR',
                        'error': str(e),
                        'timestamp': time.time()
                    })
                    print(f"⚠️ [{i}/{total_methods}] {method_name} failed with error")
            
            # Step 3: Final connectivity test
            connectivity_result = self._test_ps5_connectivity()
            
            # Calculate restoration duration
            duration = time.time() - start_time
            
            # Log performance
            log_performance("PS5 restoration", duration, 
                          success_rate=f"{success_count}/{total_methods}",
                          ps5_devices_found=len(self.ps5_devices))
            
            return {
                'success': success_count >= total_methods * 0.7,  # 70% success rate
                'methods_executed': total_methods,
                'methods_successful': success_count,
                'duration': duration,
                'ps5_devices': self.ps5_devices,
                'connectivity_test': connectivity_result,
                'restoration_log': self.restoration_log
            }
            
        except Exception as e:
            log_error("PS5 restoration failed completely", exception=e)
            return {
                'success': False,
                'error': str(e),
                'duration': time.time() - start_time,
                'restoration_log': self.restoration_log
            }
    
    def _detect_ps5_devices(self) -> bool:
        """Detect PS5 devices on the network"""
        try:
            log_info("Detecting PS5 devices on network")
            
            # Get ARP table
            arp_result = self._run_command(['arp', '-a'])
            if not arp_result:
                log_error("Failed to get ARP table")
                return False
            
            # Parse ARP table for PS5 devices
            ps5_indicators = ['b4:0a:d8', 'b4:0a:d9', 'b4:0a:da', 'b4:0a:db', 'sony', 'playstation']
            
            for line in arp_result.split('\n'):
                line_lower = line.lower()
                for indicator in ps5_indicators:
                    if indicator in line_lower:
                        # Extract IP and MAC
                        ip_match = re.search(r'(\d+\.\d+\.\d+\.\d+)', line)
                        mac_match = re.search(r'([0-9a-fA-F]{2}[:-]){5}([0-9a-fA-F]{2})', line)
                        
                        if ip_match and mac_match:
                            ps5_device = {
                                'ip': ip_match.group(1),
                                'mac': mac_match.group(0),
                                'detected_by': indicator
                            }
                            self.ps5_devices.append(ps5_device)
                            log_info(f"PS5 device detected: {ps5_device['ip']} ({ps5_device['mac']})")
            
            log_info(f"Detected {len(self.ps5_devices)} PS5 devices")
            return True
            
        except Exception as e:
            log_error("PS5 device detection failed", exception=e)
            return False
    
    def _clear_firewall_rules(self) -> bool:
        """Clear all PS5-related firewall rules"""
        try:
            log_info("Clearing PS5 firewall rules")
            
            # PS5-related firewall rule names
            ps5_rules = [
                "PS5 Block", "PS5 Drop", "PS5 Internet Block", "PS5 Outbound Block",
                "PS5 Inbound Block", "PS5 DNS Block", "PS5 DHCP Block", "PS5 Gaming Block",
                "PS5 PSN Block", "PS5 Network Block", "PS5*"
            ]
            
            success_count = 0
            for rule in ps5_rules:
                try:
                    result = self._run_command(['netsh', 'advfirewall', 'firewall', 'delete', 'rule', f'name="{rule}"'])
                    if result is not None:
                        success_count += 1
                except:
                    pass  # Rule might not exist
            
            log_info(f"Cleared {success_count} firewall rules")
            return success_count > 0
            
        except Exception as e:
            log_error("Failed to clear firewall rules", exception=e)
            return False
    
    def _clear_hosts_file(self) -> bool:
        """Clear PS5-related entries from hosts file"""
        try:
            log_info("Clearing hosts file entries")
            
            hosts_file = Path(r"C:\Windows\System32\drivers\etc\hosts")
            if not hosts_file.exists():
                log_info("Hosts file not found")
                return True
            
            # Read current hosts file
            with open(hosts_file, 'r') as f:
                lines = f.readlines()
            
            # Filter out PS5-related entries
            ps5_keywords = ['ps5', 'playstation', 'sony', 'psn']
            filtered_lines = []
            
            for line in lines:
                line_lower = line.lower()
                if not any(keyword in line_lower for keyword in ps5_keywords):
                    filtered_lines.append(line)
            
            # Write back filtered content
            with open(hosts_file, 'w') as f:
                f.writelines(filtered_lines)
            
            log_info("Hosts file cleared successfully")
            return True
            
        except Exception as e:
            log_error("Failed to clear hosts file", exception=e)
            return False
    
    def _clear_route_table(self) -> bool:
        """Clear PS5-related routes from route table"""
        try:
            log_info("Clearing route table entries")
            
            # Routes that might block PS5
            routes_to_delete = [
                '0.0.0.0', '8.8.8.8', '8.8.4.4', '1.1.1.1',
                '208.67.222.222', '208.67.220.220'
            ]
            
            success_count = 0
            for route in routes_to_delete:
                try:
                    result = self._run_command(['route', 'delete', route])
                    if result is not None:
                        success_count += 1
                except:
                    pass  # Route might not exist
            
            log_info(f"Cleared {success_count} route table entries")
            return True
            
        except Exception as e:
            log_error("Failed to clear route table", exception=e)
            return False
    
    def _clear_dns_cache(self) -> bool:
        """Clear DNS cache"""
        try:
            log_info("Clearing DNS cache")
            
            result = self._run_command(['ipconfig', '/flushdns'])
            if result is not None:
                log_info("DNS cache cleared successfully")
                return True
            else:
                log_error("Failed to clear DNS cache")
                return False
                
        except Exception as e:
            log_error("Failed to clear DNS cache", exception=e)
            return False
    
    def _clear_arp_cache(self) -> bool:
        """Clear ARP cache"""
        try:
            log_info("Clearing ARP cache")
            
            result = self._run_command(['arp', '-d', '*'])
            if result is not None:
                log_info("ARP cache cleared successfully")
                return True
            else:
                log_error("Failed to clear ARP cache")
                return False
                
        except Exception as e:
            log_error("Failed to clear ARP cache", exception=e)
            return False
    
    def _reset_network_adapters(self) -> bool:
        """Reset network adapters"""
        try:
            log_info("Resetting network adapters")
            
            # Reset Winsock (can take longer)
            winsock_result = self._run_command(['netsh', 'winsock', 'reset'], timeout=120)
            
            # Reset IP configuration (can take longer)
            ip_result = self._run_command(['netsh', 'int', 'ip', 'reset'], timeout=120)
            
            if winsock_result is not None and ip_result is not None:
                log_info("Network adapters reset successfully")
                return True
            else:
                log_error("Failed to reset network adapters")
                return False
                
        except Exception as e:
            log_error("Failed to reset network adapters", exception=e)
            return False
    
    def _restart_network_services(self) -> bool:
        """Restart network services"""
        try:
            log_info("Restarting network services")
            
            services = ['dnscache', 'dhcp']
            success_count = 0
            
            for service in services:
                try:
                    log_info(f"Restarting service: {service}")
                    
                    # Stop service (can take time)
                    stop_result = self._run_command(['net', 'stop', service], timeout=90)
                    time.sleep(2)  # Give more time between stop and start
                    
                    # Start service (can take time)
                    start_result = self._run_command(['net', 'start', service], timeout=90)
                    
                    if stop_result is not None and start_result is not None:
                        success_count += 1
                        log_info(f"Service {service} restarted successfully")
                    else:
                        log_error(f"Failed to restart service {service}")
                        
                except Exception as e:
                    log_error(f"Failed to restart service {service}", exception=e)
            
            log_info(f"Restarted {success_count}/{len(services)} network services")
            return success_count > 0
            
        except Exception as e:
            log_error("Failed to restart network services", exception=e)
            return False
    
    def _clear_ps5_specific_blocks(self) -> bool:
        """Clear PS5-specific blocking processes"""
        try:
            log_info("Clearing PS5-specific blocks")
            
            # Kill potential blocking processes
            processes_to_kill = ['python.exe', 'dupez.exe', 'ps5_blocker.exe']
            killed_count = 0
            
            for process in processes_to_kill:
                try:
                    result = self._run_command(['taskkill', '/f', '/im', process])
                    if result is not None:
                        killed_count += 1
                except:
                    pass  # Process might not be running
            
            log_info(f"Killed {killed_count} potential blocking processes")
            return True
            
        except Exception as e:
            log_error("Failed to clear PS5-specific blocks", exception=e)
            return False
    
    def _test_connectivity(self) -> bool:
        """Test basic internet connectivity"""
        try:
            log_info("Testing internet connectivity")
            
            # Test DNS resolution
            try:
                socket.gethostbyname("www.google.com")
                log_info("DNS resolution working")
                return True
            except:
                log_error("DNS resolution failed")
                return False
                
        except Exception as e:
            log_error("Connectivity test failed", exception=e)
            return False
    
    def _test_ps5_connectivity(self) -> Dict:
        """Test PS5-specific connectivity"""
        try:
            log_info("Testing PS5 connectivity")
            
            results = {}
            for ps5_device in self.ps5_devices:
                ip = ps5_device['ip']
                
                # Test ping to PS5
                ping_result = self._run_command(['ping', '-n', '4', ip])
                ping_success = ping_result is not None and 'TTL=' in ping_result
                
                # Test common PS5 ports
                ports_to_test = [80, 443, 3074, 3075, 3659]  # Common gaming ports
                open_ports = []
                
                for port in ports_to_test:
                    try:
                        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        sock.settimeout(2)
                        result = sock.connect_ex((ip, port))
                        sock.close()
                        if result == 0:
                            open_ports.append(port)
                    except:
                        pass
                
                results[ip] = {
                    'ping_success': ping_success,
                    'open_ports': open_ports,
                    'mac': ps5_device['mac']
                }
            
            log_info(f"PS5 connectivity test completed for {len(results)} devices")
            return results
            
        except Exception as e:
            log_error("PS5 connectivity test failed", exception=e)
            return {}
    
    def _run_command(self, command: List[str], timeout: int = 60) -> Optional[str]:
        """Run a command and return output"""
        try:
            log_info(f"Running command: {' '.join(command)} (timeout: {timeout}s)")
            result = subprocess.run(
                command, 
                capture_output=True, 
                text=True, 
                timeout=timeout
            )
            if result.returncode == 0:
                log_info(f"Command completed successfully: {' '.join(command)}")
                return result.stdout
            else:
                log_error(f"Command failed with return code {result.returncode}: {' '.join(command)}")
                if result.stderr:
                    log_error(f"Error output: {result.stderr}")
                return None
        except subprocess.TimeoutExpired:
            log_error(f"Command timed out after {timeout}s: {' '.join(command)}")
            return None
        except Exception as e:
            log_error(f"Command failed with exception: {' '.join(command)}", exception=e)
            return None

def main():
    """Main restoration function"""
    print("=" * 60)
    print("ENHANCED PS5 INTERNET RESTORATION")
    print("=" * 60)
    print()
    
    # Check for admin privileges
    if not _is_admin():
        print("ERROR: This script requires administrator privileges!")
        print("Please run as administrator.")
        input("Press Enter to exit...")
        return
    
    # Create restoration engine
    engine = PS5RestorationEngine()
    
    # Get target MAC if provided
    target_mac = None
    if len(sys.argv) > 1:
        target_mac = sys.argv[1]
        print(f"Target MAC address: {target_mac}")
    
    # Run restoration
    print("Starting PS5 connectivity restoration...")
    result = engine.restore_ps5_connectivity(target_mac)
    
    # Display results
    print("\n" + "=" * 60)
    print("RESTORATION RESULTS")
    print("=" * 60)
    
    if result['success']:
        print("✅ PS5 restoration completed successfully!")
    else:
        print("❌ PS5 restoration failed!")
    
    print(f"Methods executed: {result['methods_executed']}")
    print(f"Methods successful: {result['methods_successful']}")
    print(f"Duration: {result['duration']:.2f} seconds")
    
    if 'ps5_devices' in result:
        print(f"PS5 devices detected: {len(result['ps5_devices'])}")
        for device in result['ps5_devices']:
            print(f"  - {device['ip']} ({device['mac']})")
    
    if 'connectivity_test' in result:
        print("\nConnectivity Test Results:")
        for ip, test_result in result['connectivity_test'].items():
            status = "✅" if test_result['ping_success'] else "❌"
            print(f"  {status} {ip}: Ping={test_result['ping_success']}, Ports={test_result['open_ports']}")
    
    print("\n" + "=" * 60)
    print("RESTORATION COMPLETE")
    print("=" * 60)
    
    if result['success']:
        print("Your PS5 should now be able to connect to the internet.")
        print("If it still can't connect, try:")
        print("1. Restart your PS5")
        print("2. Restart your router")
        print("3. Check PS5 network settings")
    else:
        print("Restoration was not completely successful.")
        print("Please try running the emergency unblock script as administrator.")
    
    input("\nPress Enter to exit...")

def _is_admin() -> bool:
    """Check if running as administrator"""
    try:
        return subprocess.run(['net', 'session'], capture_output=True).returncode == 0
    except:
        return False

if __name__ == "__main__":
    main() 
