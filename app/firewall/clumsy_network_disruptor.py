#!/usr/bin/env python3
"""
Clumsy-based Network Disruptor Module
Integrates Clumsy's WinDivert functionality for effective network disruption
"""

import os
import sys
import time
import threading
import subprocess
import platform
from typing import Dict, List, Optional, Tuple
from app.logs.logger import log_info, log_error

try:
    import ctypes
    from ctypes import wintypes
    WINDOWS_API_AVAILABLE = True
except ImportError:
    WINDOWS_API_AVAILABLE = False

class ClumsyNetworkDisruptor:
    """Network disruptor based on Clumsy's WinDivert functionality"""
    
    def __init__(self):
        self.is_running = False
        self.clumsy_process = None
        self.disrupted_devices = {}
        self.clumsy_path = None
        self.windivert_path = None
        self._initialize_paths()
        
    def _initialize_paths(self):
        """Initialize paths to Clumsy and WinDivert files"""
        try:
            # Get the current directory
            current_dir = os.path.dirname(os.path.abspath(__file__))
            
            # Set paths for WinDivert files
            self.windivert_dll = os.path.join(current_dir, "WinDivert.dll")
            self.windivert_sys = os.path.join(current_dir, "WinDivert64.sys")
            self.clumsy_exe = os.path.join(current_dir, "clumsy.exe")
            
            # Check if running as compiled executable (PyInstaller)
            if getattr(sys, 'frozen', False):
                # Running as compiled executable
                base_path = sys._MEIPASS
                self.windivert_dll = os.path.join(base_path, "app", "firewall", "WinDivert.dll")
                self.windivert_sys = os.path.join(base_path, "app", "firewall", "WinDivert64.sys")
                self.clumsy_exe = os.path.join(base_path, "app", "firewall", "clumsy.exe")
                log_info(f"Running as compiled executable, using PyInstaller paths")
            
            # Check if WinDivert files exist
            if not os.path.exists(self.windivert_dll):
                log_error(f"WinDivert.dll not found at: {self.windivert_dll}")
            else:
                log_info(f"WinDivert.dll found at: {self.windivert_dll}")
                
            if not os.path.exists(self.windivert_sys):
                log_error(f"WinDivert64.sys not found at: {self.windivert_sys}")
            else:
                log_info(f"WinDivert64.sys found at: {self.windivert_sys}")
                
            if not os.path.exists(self.clumsy_exe):
                log_error(f"clumsy.exe not found at: {self.clumsy_exe}")
            else:
                log_info(f"clumsy.exe found at: {self.clumsy_exe}")
                
            log_info(f"Clumsy disruptor initialized - WinDivert DLL: {self.windivert_dll}")
            
        except Exception as e:
            log_error(f"Failed to initialize Clumsy paths: {e}")
    
    def initialize(self) -> bool:
        """Initialize the Clumsy network disruptor"""
        try:
            log_info("Initializing Clumsy Network Disruptor...")
            
            # Check if WinDivert files are available
            if not os.path.exists(self.windivert_dll):
                log_error("WinDivert.dll not found - cannot initialize Clumsy disruptor")
                log_error(f"Expected path: {self.windivert_dll}")
                return False
                
            if not os.path.exists(self.windivert_sys):
                log_error("WinDivert64.sys not found - cannot initialize Clumsy disruptor")
                log_error(f"Expected path: {self.windivert_sys}")
                return False
                
            if not os.path.exists(self.clumsy_exe):
                log_error("clumsy.exe not found - cannot initialize Clumsy disruptor")
                log_error(f"Expected path: {self.clumsy_exe}")
                return False
            
            # Check administrator privileges
            if not self._is_admin():
                log_error("Clumsy disruptor requires Administrator privileges")
                log_error("Please run the application as Administrator for full Clumsy functionality")
                log_error("Enterprise network disruptor will be used as fallback")
                return False
            
            log_info("Clumsy Network Disruptor initialized successfully")
            log_info(f"WinDivert DLL: {self.windivert_dll}")
            log_info(f"WinDivert SYS: {self.windivert_sys}")
            log_info(f"Clumsy EXE: {self.clumsy_exe}")
            return True
            
        except Exception as e:
            log_error(f"Failed to initialize Clumsy disruptor: {e}")
            return False
    
    def _is_admin(self) -> bool:
        """Check if running with administrator privileges"""
        try:
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin()
        except:
            return False
    
    def _create_clumsy_config(self, target_ip: str, methods: List[str]) -> str:
        """Create a Clumsy configuration for the target device"""
        config = []
        
        # Base filter for the target IP - Clumsy expects this exact format
        base_filter = f"Filter: ip.Addr == {target_ip}"
        config.append(base_filter)
        
        # Add method-specific configurations using Clumsy's actual syntax
        # Note: Clumsy uses different parameter names than expected
        if "drop" in methods:
            config.append("Drop_Inbound = true")
            config.append("Drop_Outbound = true")
            config.append("Drop_Chance = 95")
        
        if "lag" in methods:
            config.append("Lag_Inbound = true")
            config.append("Lag_Outbound = true")
            config.append("Lag_Delay = 500")
        
        if "throttle" in methods:
            config.append("Throttle_Inbound = true")
            config.append("Throttle_Outbound = true")
            config.append("Throttle_Chance = 80")
            config.append("Throttle_Timeframe = 100")
        
        if "duplicate" in methods:
            config.append("Duplicate_Inbound = true")
            config.append("Duplicate_Outbound = true")
            config.append("Duplicate_Chance = 50")
            config.append("Duplicate_Count = 5")
        
        if "corrupt" in methods:
            config.append("Tamper_Inbound = true")
            config.append("Tamper_Outbound = true")
            config.append("Tamper_Chance = 30")
            config.append("Tamper_RedoChecksum = true")
        
        if "rst" in methods:
            config.append("SetTCPRST_Inbound = true")
            config.append("SetTCPRST_Outbound = true")
            config.append("SetTCPRST_Chance = 70")
        
        # Add default settings if no methods specified
        if not methods:
            config.append("Drop_Inbound = true")
            config.append("Drop_Outbound = true")
            config.append("Drop_Chance = 90")
            config.append("Lag_Inbound = true")
            config.append("Lag_Outbound = true")
            config.append("Lag_Delay = 300")
        
        # Create the configuration string with proper line breaks
        config_str = "\n".join(config)
        
        log_info(f"Created Clumsy config for {target_ip}: {config_str}")
        return config_str
    
    def _save_clumsy_config(self, config: str, target_ip: str) -> str:
        """Save Clumsy configuration to a temporary file"""
        try:
            # Use the config directory for consistency
            config_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "config")
            os.makedirs(config_dir, exist_ok=True)
            
            config_file = os.path.join(config_dir, f"clumsy_config_{target_ip.replace('.', '_')}.txt")
            
            with open(config_file, 'w') as f:
                f.write(config)
            
            log_info(f"Saved Clumsy config to: {config_file}")
            return config_file
            
        except Exception as e:
            log_error(f"Failed to save Clumsy config: {e}")
            return None
    
    def disconnect_device_clumsy(self, target_ip: str, methods: List[str] = None) -> bool:
        """Disconnect a device using Clumsy's WinDivert functionality"""
        if methods is None:
            methods = ["drop", "lag", "throttle"]
        
        try:
            log_info(f"Starting Clumsy disconnect for {target_ip}")
            log_info(f"Methods: {methods}")
            
            if target_ip in self.disrupted_devices:
                log_info(f"Device {target_ip} is already being disrupted")
                return True
            
            # Create Clumsy configuration file
            config = self._create_clumsy_config(target_ip, methods)
            config_file = self._save_clumsy_config(config, target_ip)
            
            if not config_file:
                log_error("Failed to create Clumsy configuration")
                return False
            
            # Start Clumsy process with proper configuration file
            # Clumsy expects a config file, not command line arguments
            clumsy_cmd = [
                self.clumsy_exe,
                config_file
            ]
            
            log_info(f"Starting Clumsy with command: {' '.join(clumsy_cmd)}")
            log_info(f"Config file: {config_file}")
            
            # Start the Clumsy process
            try:
                # Use shell=True for better compatibility with Clumsy
                self.clumsy_process = subprocess.Popen(
                    clumsy_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    shell=True
                )
                
                # Wait a moment for the process to start
                time.sleep(3)
                
                # Check if process is still running
                if self.clumsy_process.poll() is None:
                    # Process is running successfully
                    self.disrupted_devices[target_ip] = {
                        'process': self.clumsy_process,
                        'methods': methods,
                        'start_time': time.time(),
                        'config_file': config_file
                    }
                    
                    log_info(f"Clumsy disruption started successfully for {target_ip}")
                    return True
                else:
                    # Process failed, get error output
                    stdout, stderr = self.clumsy_process.communicate()
                    log_error(f"Clumsy process failed to start for {target_ip}")
                    log_error(f"stdout: {stdout.decode() if stdout else 'None'}")
                    log_error(f"stderr: {stderr.decode() if stderr else 'None'}")
                    
                    # Try alternative approach - direct execution
                    log_info("Trying alternative Clumsy execution method...")
                    return self._try_alternative_clumsy_execution(target_ip, config_file, methods)
                    
            except Exception as e:
                log_error(f"Failed to start Clumsy process: {e}")
                # Try alternative approach
                return self._try_alternative_clumsy_execution(target_ip, config_file, methods)
                
        except Exception as e:
            log_error(f"Error in Clumsy disconnect: {e}")
            return False
    
    def _try_alternative_clumsy_execution(self, target_ip: str, config_file: str, methods: List[str]) -> bool:
        """Try alternative method to execute Clumsy if primary method fails"""
        try:
            log_info(f"Trying alternative Clumsy execution for {target_ip}")
            
            # Try running Clumsy with different parameters
            alt_cmd = [
                self.clumsy_exe,
                "-f", config_file,  # Use -f flag for config file
                "-q"  # Quiet mode
            ]
            
            log_info(f"Alternative command: {' '.join(alt_cmd)}")
            
            alt_process = subprocess.Popen(
                alt_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            
            time.sleep(2)
            
            if alt_process.poll() is None:
                # Alternative method worked
                self.disrupted_devices[target_ip] = {
                    'process': alt_process,
                    'methods': methods,
                    'start_time': time.time(),
                    'config_file': config_file
                }
                
                log_info(f"Alternative Clumsy execution successful for {target_ip}")
                return True
            else:
                # Get error output
                stdout, stderr = alt_process.communicate()
                log_error(f"Alternative Clumsy execution failed for {target_ip}")
                log_error(f"stdout: {stdout.decode() if stdout else 'None'}")
                log_error(f"stderr: {stderr.decode() if stderr else 'None'}")
                
                # Try one more approach - direct file execution
                return self._try_direct_clumsy_execution(target_ip, config_file, methods)
                
        except Exception as e:
            log_error(f"Alternative Clumsy execution failed: {e}")
            return False
    
    def _try_direct_clumsy_execution(self, target_ip: str, config_file: str, methods: List[str]) -> bool:
        """Try direct execution of Clumsy with minimal parameters"""
        try:
            log_info(f"Trying direct Clumsy execution for {target_ip}")
            
            # Try running Clumsy directly with the config file
            direct_cmd = [self.clumsy_exe, config_file]
            
            log_info(f"Direct command: {' '.join(direct_cmd)}")
            
            direct_process = subprocess.Popen(
                direct_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            
            time.sleep(2)
            
            if direct_process.poll() is None:
                # Direct method worked
                self.disrupted_devices[target_ip] = {
                    'process': direct_process,
                    'methods': methods,
                    'start_time': time.time(),
                    'config_file': config_file
                }
                
                log_info(f"Direct Clumsy execution successful for {target_ip}")
                return True
            else:
                # Get error output
                stdout, stderr = direct_process.communicate()
                log_error(f"Direct Clumsy execution failed for {target_ip}")
                log_error(f"stdout: {stdout.decode() if stdout else 'None'}")
                log_error(f"stderr: {stderr.decode() if stderr else 'None'}")
                
                # All methods failed
                log_error(f"All Clumsy execution methods failed for {target_ip}")
                return False
                
        except Exception as e:
            log_error(f"Direct Clumsy execution failed: {e}")
            return False
    
    def reconnect_device_clumsy(self, target_ip: str) -> bool:
        """Reconnect a device by stopping Clumsy disruption"""
        try:
            if target_ip not in self.disrupted_devices:
                log_info(f"Device {target_ip} is not being disrupted")
                return True
            
            device_info = self.disrupted_devices[target_ip]
            process = device_info.get('process')
            config_file = device_info.get('config_file')
            
            # Stop the Clumsy process
            if process and process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
                log_info(f"Clumsy process stopped for {target_ip}")
            
            # Clean up configuration file
            if config_file and os.path.exists(config_file):
                try:
                    os.remove(config_file)
                except:
                    pass
            
            # Remove from disrupted devices
            del self.disrupted_devices[target_ip]
            
            log_info(f"Clumsy reconnection completed for {target_ip}")
            return True
            
        except Exception as e:
            log_error(f"Error in Clumsy reconnection: {e}")
            return False
    
    def get_disrupted_devices_clumsy(self) -> List[str]:
        """Get list of devices being disrupted by Clumsy"""
        return list(self.disrupted_devices.keys())
    
    def get_device_status_clumsy(self, target_ip: str) -> Dict:
        """Get status of a device being disrupted by Clumsy"""
        if target_ip not in self.disrupted_devices:
            return {'disrupted': False}
        
        device_info = self.disrupted_devices[target_ip]
        process = device_info.get('process')
        
        return {
            'disrupted': True,
            'methods': device_info.get('methods', []),
            'start_time': device_info.get('start_time', 0),
            'process_running': process.poll() is None if process else False
        }
    
    def clear_all_disruptions_clumsy(self) -> bool:
        """Clear all Clumsy disruptions"""
        try:
            success_count = 0
            for target_ip in list(self.disrupted_devices.keys()):
                if self.reconnect_device_clumsy(target_ip):
                    success_count += 1
            
            log_info(f"Cleared {success_count} Clumsy disruptions")
            return True
            
        except Exception as e:
            log_error(f"Error clearing Clumsy disruptions: {e}")
            return False
    
    def start_clumsy(self):
        """Start the Clumsy disruptor"""
        self.is_running = True
        log_info("Clumsy Network Disruptor started")
    
    def stop_clumsy(self):
        """Stop the Clumsy disruptor"""
        self.is_running = False
        self.clear_all_disruptions_clumsy()
        log_info("Clumsy Network Disruptor stopped")
    
    def test_clumsy_config(self, target_ip: str = "127.0.0.1") -> bool:
        """Test Clumsy configuration with a simple localhost test"""
        try:
            log_info(f"Testing Clumsy configuration with {target_ip}")
            
            # Create a simple test configuration
            test_config = f"""Filter: ip.Addr == {target_ip}
Drop_Inbound = true
Drop_Outbound = true
Drop_Chance = 50
Lag_Inbound = true
Lag_Outbound = true
Lag_Delay = 100"""
            
            # Save test config
            config_file = self._save_clumsy_config(test_config, f"test_{target_ip.replace('.', '_')}")
            if not config_file:
                return False
            
            # Try to start Clumsy with test config
            test_cmd = [self.clumsy_exe, config_file]
            
            try:
                test_process = subprocess.Popen(
                    test_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                
                # Wait a moment
                time.sleep(1)
                
                if test_process.poll() is None:
                    # Process is running, stop it
                    test_process.terminate()
                    test_process.wait(timeout=3)
                    
                    # Clean up test config
                    try:
                        if os.path.exists(config_file):
                            os.remove(config_file)
                    except:
                        pass
                    
                    log_info("Clumsy test configuration successful")
                    return True
                else:
                    # Process failed, get error output
                    stdout, stderr = test_process.communicate()
                    log_error(f"Clumsy test failed. stdout: {stdout.decode()}, stderr: {stderr.decode()}")
                    return False
                    
            except Exception as e:
                log_error(f"Failed to test Clumsy: {e}")
                return False
                
        except Exception as e:
            log_error(f"Error in Clumsy test: {e}")
            return False
    
    def get_clumsy_status(self) -> Dict:
        """Get detailed status of Clumsy disruptor"""
        return {
            "is_running": self.is_running,
            "windivert_dll_exists": os.path.exists(self.windivert_dll) if self.windivert_dll else False,
            "windivert_sys_exists": os.path.exists(self.windivert_sys) if self.windivert_sys else False,
            "clumsy_exe_exists": os.path.exists(self.clumsy_exe) if self.clumsy_exe else False,
            "disrupted_devices_count": len(self.disrupted_devices),
            "disrupted_devices": list(self.disrupted_devices.keys()),
            "is_admin": self._is_admin()
        }

# Global instance
# Global instance - Singleton pattern to prevent duplicate initialization
_clumsy_network_disruptor = None

def get_clumsy_network_disruptor():
    """Get singleton clumsy network disruptor instance"""
    global _clumsy_network_disruptor
    if _clumsy_network_disruptor is None:
        _clumsy_network_disruptor = ClumsyNetworkDisruptor()
    return _clumsy_network_disruptor

# Backward compatibility
clumsy_network_disruptor = get_clumsy_network_disruptor() 