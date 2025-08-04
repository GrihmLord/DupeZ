#!/usr/bin/env python3
"""
DayZ Firewall Controller - DayZPCFW Integration
Advanced firewall control for DayZ with timer, keybind, and button functionality
Based on DayZPCFW's Visual Basic .NET implementation
"""

import json
import subprocess
import threading
import time
import keyboard
import socket
import struct
import os
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
from app.logs.logger import log_info, log_error, log_warning

@dataclass
class DayZFirewallRule:
    """DayZ firewall rule configuration"""
    name: str
    ip: str
    port: int
    protocol: str = "UDP"
    action: str = "block"  # block, allow
    enabled: bool = True
    timer_duration: int = 0  # 0 = no timer
    keybind: str = "F12"

class DayZFirewallController:
    """Advanced DayZ firewall controller with DayZPCFW integration"""
    
    def __init__(self, config_file: str = "app/config/dayz_firewall.json"):
        self.config_file = config_file
        self.rules: List[DayZFirewallRule] = []
        self.active_rules: Dict[str, threading.Thread] = {}
        self.is_running = False
        self.global_keybind = "F12"  # Default global keybind
        self.global_timer_duration = 0  # 0 = no timer
        self.timer_active = False
        self.button_mode = False  # Button mode vs keybind mode
        self.auto_stop = True  # Auto-stop when timer expires
        
        # DayZ-specific settings
        self.dayz_ports = [2302, 2303, 2304, 2305, 27015, 27016, 27017, 27018]
        self.dayz_protocols = ["UDP", "TCP"]
        
        # Load configuration
        self.load_config()
        self.setup_global_keybind()
        
    def load_config(self):
        """Load firewall configuration from JSON file"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                    
                self.global_keybind = config.get('global_keybind', 'F12')
                self.global_timer_duration = config.get('global_timer_duration', 0)
                self.button_mode = config.get('button_mode', False)
                self.auto_stop = config.get('auto_stop', True)
                
                # Load rules
                rules_data = config.get('rules', [])
                self.rules = []
                for rule_data in rules_data:
                    rule = DayZFirewallRule(
                        name=rule_data.get('name', 'Unknown'),
                        ip=rule_data.get('ip', '0.0.0.0'),
                        port=rule_data.get('port', 2302),
                        protocol=rule_data.get('protocol', 'UDP'),
                        action=rule_data.get('action', 'block'),
                        enabled=rule_data.get('enabled', True),
                        timer_duration=rule_data.get('timer_duration', 0),
                        keybind=rule_data.get('keybind', 'F12')
                    )
                    self.rules.append(rule)
                    
                log_info(f"[SUCCESS] Loaded {len(self.rules)} DayZ firewall rules from config")
            else:
                # Create default configuration
                self.create_default_config()
                
        except Exception as e:
            log_error(f"Failed to load DayZ firewall config: {e}")
            self.create_default_config()
    
    def create_default_config(self):
        """Create default DayZ firewall configuration"""
        try:
            default_config = {
                "global_keybind": "F12",
                "global_timer_duration": 0,
                "button_mode": False,
                "auto_stop": True,
                "rules": [
                    {
                        "name": "DayZ Official Server Block",
                        "ip": "0.0.0.0",
                        "port": 2302,
                        "protocol": "UDP",
                        "action": "block",
                        "enabled": True,
                        "timer_duration": 0,
                        "keybind": "F12"
                    },
                    {
                        "name": "DayZ Community Server Block",
                        "ip": "0.0.0.0",
                        "port": 2303,
                        "protocol": "UDP",
                        "action": "block",
                        "enabled": True,
                        "timer_duration": 0,
                        "keybind": "F11"
                    }
                ]
            }
            
            # Ensure config directory exists
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
            
            with open(self.config_file, 'w') as f:
                json.dump(default_config, f, indent=2)
                
            log_info("[SUCCESS] Created default DayZ firewall configuration")
            
        except Exception as e:
            log_error(f"Failed to create default config: {e}")
    
    def setup_global_keybind(self):
        """Setup global keybind for DayZ firewall control"""
        try:
            # Remove existing keybind if any
            try:
                keyboard.remove_hotkey(self.global_keybind)
            except:
                pass
            
            # Add new keybind
            keyboard.add_hotkey(self.global_keybind, self.toggle_firewall)
            log_info(f"[SUCCESS] Global keybind set to {self.global_keybind}")
            
        except Exception as e:
            log_error(f"Failed to setup global keybind: {e}")
    
    def toggle_firewall(self):
        """Toggle DayZ firewall on/off (called by keybind)"""
        try:
            if self.is_running:
                self.stop_firewall()
                log_info("[GAMING] DayZ firewall stopped via keybind")
            else:
                self.start_firewall()
                log_info("[GAMING] DayZ firewall started via keybind")
                
        except Exception as e:
            log_error(f"Failed to toggle firewall via keybind: {e}")
    
    def start_firewall(self, timer_duration: int = None) -> bool:
        """Start DayZ firewall with optional timer"""
        try:
            if self.is_running:
                log_info("DayZ firewall already active")
                return True
            
            # Use provided timer or global timer
            effective_timer = timer_duration if timer_duration is not None else self.global_timer_duration
            
            log_info(f"[GAMING] Starting DayZ firewall")
            log_info(f"[GAMING] Timer duration: {effective_timer}s" if effective_timer > 0 else "[GAMING] Timer: Unlimited")
            
            self.is_running = True
            self.timer_active = effective_timer > 0
            
            # Apply all enabled rules
            for rule in self.rules:
                if rule.enabled:
                    self._apply_firewall_rule(rule)
                    
                    # Start timer for this rule if specified
                    if rule.timer_duration > 0:
                        timer_thread = threading.Thread(
                            target=self._rule_timer_worker,
                            args=(rule, rule.timer_duration),
                            daemon=True
                        )
                        timer_thread.start()
            
            # Start global timer if specified
            if effective_timer > 0:
                timer_thread = threading.Thread(
                    target=self._global_timer_worker,
                    args=(effective_timer,),
                    daemon=True
                )
                timer_thread.start()
            
            log_info("[GAMING] DayZ firewall started successfully")
            return True
            
        except Exception as e:
            log_error(f"Failed to start DayZ firewall: {e}")
            return False
    
    def stop_firewall(self) -> bool:
        """Stop DayZ firewall and remove all rules"""
        try:
            if not self.is_running:
                log_info("DayZ firewall already stopped")
                return True
            
            log_info("[GAMING] Stopping DayZ firewall...")
            
            self.is_running = False
            self.timer_active = False
            
            # Remove all rules
            for rule in self.rules:
                if rule.enabled:
                    self._remove_firewall_rule(rule)
            
            log_info("[GAMING] DayZ firewall stopped successfully")
            return True
            
        except Exception as e:
            log_error(f"Failed to stop DayZ firewall: {e}")
            return False
    
    def _apply_firewall_rule(self, rule: DayZFirewallRule):
        """Apply a specific firewall rule"""
        try:
            rule_name = f"DupeZ_DayZ_{rule.name}_{rule.ip}_{rule.port}"
            
            if rule.action == "block":
                # Create block rule
                cmd = [
                    "netsh", "advfirewall", "firewall", "add", "rule",
                    f"name={rule_name}",
                    "dir=in",
                    "action=block",
                    f"protocol={rule.protocol}",
                    f"localport={rule.port}",
                    f"remoteip={rule.ip}",
                    "enable=yes"
                ]
            else:
                # Create allow rule
                cmd = [
                    "netsh", "advfirewall", "firewall", "add", "rule",
                    f"name={rule_name}",
                    "dir=in",
                    "action=allow",
                    f"protocol={rule.protocol}",
                    f"localport={rule.port}",
                    f"remoteip={rule.ip}",
                    "enable=yes"
                ]
            
            # Execute command
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                log_info(f"[SUCCESS] Applied firewall rule: {rule.name}")
            else:
                log_error(f"Failed to apply firewall rule {rule.name}: {result.stderr}")
                
        except Exception as e:
            log_error(f"Error applying firewall rule {rule.name}: {e}")
    
    def _remove_firewall_rule(self, rule: DayZFirewallRule):
        """Remove a specific firewall rule"""
        try:
            rule_name = f"DupeZ_DayZ_{rule.name}_{rule.ip}_{rule.port}"
            
            cmd = [
                "netsh", "advfirewall", "firewall", "delete", "rule",
                f"name={rule_name}"
            ]
            
            # Execute command
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                log_info(f"[SUCCESS] Removed firewall rule: {rule.name}")
            else:
                log_error(f"Failed to remove firewall rule {rule.name}: {result.stderr}")
                
        except Exception as e:
            log_error(f"Error removing firewall rule {rule.name}: {e}")
    
    def _rule_timer_worker(self, rule: DayZFirewallRule, duration: int):
        """Worker thread for rule-specific timer"""
        try:
            log_info(f"[TIMER] Rule timer started for {rule.name}: {duration}s")
            
            # Wait for duration
            time.sleep(duration)
            
            # Remove rule if still active
            if self.is_running and rule.enabled:
                self._remove_firewall_rule(rule)
                log_info(f"[TIMER] Rule timer expired for {rule.name}")
                
        except Exception as e:
            log_error(f"Error in rule timer worker for {rule.name}: {e}")
    
    def _global_timer_worker(self, duration: int):
        """Worker thread for global timer"""
        try:
            log_info(f"[TIMER] Global timer started: {duration}s")
            
            # Wait for duration
            time.sleep(duration)
            
            # Stop firewall if auto-stop is enabled
            if self.auto_stop and self.is_running:
                self.stop_firewall()
                log_info("[TIMER] Global timer expired - firewall stopped")
                
        except Exception as e:
            log_error(f"Error in global timer worker: {e}")
    
    def add_rule(self, name: str, ip: str, port: int, protocol: str = "UDP", 
                 action: str = "block", timer_duration: int = 0, keybind: str = "F12") -> bool:
        """Add a new firewall rule"""
        try:
            rule = DayZFirewallRule(
                name=name,
                ip=ip,
                port=port,
                protocol=protocol,
                action=action,
                enabled=True,
                timer_duration=timer_duration,
                keybind=keybind
            )
            
            self.rules.append(rule)
            self.save_config()
            
            log_info(f"[SUCCESS] Added firewall rule: {name}")
            return True
            
        except Exception as e:
            log_error(f"Failed to add firewall rule: {e}")
            return False
    
    def remove_rule(self, name: str) -> bool:
        """Remove a firewall rule"""
        try:
            # Find and remove rule
            for i, rule in enumerate(self.rules):
                if rule.name == name:
                    # Remove firewall rule if active
                    if self.is_running and rule.enabled:
                        self._remove_firewall_rule(rule)
                    
                    # Remove from list
                    self.rules.pop(i)
                    self.save_config()
                    
                    log_info(f"[SUCCESS] Removed firewall rule: {name}")
                    return True
            
            log_error(f"Firewall rule not found: {name}")
            return False
            
        except Exception as e:
            log_error(f"Failed to remove firewall rule: {e}")
            return False
    
    def save_config(self):
        """Save current configuration to file"""
        try:
            config = {
                "global_keybind": self.global_keybind,
                "global_timer_duration": self.global_timer_duration,
                "button_mode": self.button_mode,
                "auto_stop": self.auto_stop,
                "rules": []
            }
            
            for rule in self.rules:
                rule_data = {
                    "name": rule.name,
                    "ip": rule.ip,
                    "port": rule.port,
                    "protocol": rule.protocol,
                    "action": rule.action,
                    "enabled": rule.enabled,
                    "timer_duration": rule.timer_duration,
                    "keybind": rule.keybind
                }
                config["rules"].append(rule_data)
            
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=2)
                
            log_info("[SUCCESS] DayZ firewall configuration saved")
            
        except Exception as e:
            log_error(f"Failed to save DayZ firewall config: {e}")
    
    def get_status(self) -> Dict[str, any]:
        """Get current firewall status"""
        return {
            "is_running": self.is_running,
            "timer_active": self.timer_active,
            "button_mode": self.button_mode,
            "global_keybind": self.global_keybind,
            "global_timer_duration": self.global_timer_duration,
            "active_rules": len(self.active_rules),
            "total_rules": len(self.rules),
            "enabled_rules": len([r for r in self.rules if r.enabled])
        }
    
    def get_rules(self) -> List[DayZFirewallRule]:
        """Get list of firewall rules"""
        return self.rules.copy()
    
    def set_global_keybind(self, keybind: str):
        """Set global keybind"""
        try:
            # Remove old keybind
            try:
                keyboard.remove_hotkey(self.global_keybind)
            except:
                pass
            
            self.global_keybind = keybind
            self.setup_global_keybind()
            self.save_config()
            
        except Exception as e:
            log_error(f"Failed to set global keybind: {e}")
    
    def set_global_timer(self, duration: int):
        """Set global timer duration"""
        self.global_timer_duration = max(0, duration)
        self.save_config()
        log_info(f"[SUCCESS] Global timer set to {duration}s")
    
    def toggle_button_mode(self, enabled: bool):
        """Toggle button mode vs keybind mode"""
        self.button_mode = enabled
        self.save_config()
        log_info(f"[SUCCESS] Button mode {'enabled' if enabled else 'disabled'}")
    
    def cleanup(self):
        """Cleanup resources"""
        try:
            # Stop firewall
            if self.is_running:
                self.stop_firewall()
            
            # Remove keybind
            try:
                keyboard.remove_hotkey(self.global_keybind)
            except:
                pass
                
            log_info("[SUCCESS] DayZ firewall controller cleaned up")
            
        except Exception as e:
            log_error(f"Error during cleanup: {e}")

# Global instance
dayz_firewall = DayZFirewallController() 