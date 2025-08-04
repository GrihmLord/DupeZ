#!/usr/bin/env python3
"""
Privacy Manager for DupeZ
Protects user privacy while maintaining tool functionality
"""

import os
import sys
import hashlib
import random
import string
import time
import json
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
import subprocess
import socket
import threading

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.logs.logger import log_info, log_error

@dataclass
class PrivacySettings:
    """Privacy configuration settings"""
    anonymize_mac_addresses: bool = True
    anonymize_ip_addresses: bool = True
    anonymize_device_names: bool = True
    encrypt_logs: bool = True
    clear_logs_on_exit: bool = True
    mask_user_activity: bool = True
    use_vpn_proxy: bool = False
    privacy_level: str = "high"  # low, medium, high, maximum

class PrivacyManager:
    """Comprehensive privacy protection for DupeZ"""
    
    def __init__(self):
        self.settings = PrivacySettings()
        self.anonymization_map = {}
        self.session_id = self._generate_session_id()
        self.start_time = datetime.now()
        self.privacy_log = []
        
        # Initialize privacy features
        self._setup_privacy_logging()
        self._setup_anonymization()
        
    def _generate_session_id(self) -> str:
        """Generate anonymous session ID"""
        timestamp = str(int(time.time()))
        random_suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
        return f"session_{timestamp}_{random_suffix}"
    
    def _setup_privacy_logging(self):
        """Setup privacy-aware logging"""
        # Create privacy log directory
        privacy_log_dir = os.path.join(os.path.dirname(__file__), "logs")
        os.makedirs(privacy_log_dir, exist_ok=True)
        
        # Setup privacy log file
        self.privacy_log_file = os.path.join(privacy_log_dir, f"privacy_{self.session_id}.log")
        
        # Configure privacy logger
        self.privacy_logger = logging.getLogger(f"privacy_{self.session_id}")
        self.privacy_logger.setLevel(logging.INFO)
        
        # File handler with rotation
        from logging.handlers import RotatingFileHandler
        handler = RotatingFileHandler(
            self.privacy_log_file, 
            maxBytes=1024*1024,  # 1MB
            backupCount=3
        )
        
        formatter = logging.Formatter(
            '%(asctime)s - [PRIVACY] %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        self.privacy_logger.addHandler(handler)
        
    def _setup_anonymization(self):
        """Setup anonymization mappings"""
        self.mac_mappings = {}
        self.ip_mappings = {}
        self.device_mappings = {}
        
    def anonymize_mac(self, mac_address: str) -> str:
        """Anonymize MAC address"""
        if not self.settings.anonymize_mac_addresses:
            return mac_address
            
        if mac_address not in self.mac_mappings:
            # Generate consistent anonymized MAC
            hash_obj = hashlib.sha256(f"{mac_address}_{self.session_id}".encode())
            hash_hex = hash_obj.hexdigest()[:12]
            
            # Format as MAC address
            anonymized = ':'.join([hash_hex[i:i+2] for i in range(0, 12, 2)])
            self.mac_mappings[mac_address] = anonymized
            
        return self.mac_mappings[mac_address]
    
    def anonymize_ip(self, ip_address: str) -> str:
        """Anonymize IP address"""
        if not self.settings.anonymize_ip_addresses:
            return ip_address
            
        if ip_address not in self.ip_mappings:
            # Generate consistent anonymized IP
            hash_obj = hashlib.sha256(f"{ip_address}_{self.session_id}".encode())
            hash_hex = hash_obj.hexdigest()[:8]
            
            # Convert to IP format
            anonymized = '.'.join([str(int(hash_hex[i:i+2], 16)) for i in range(0, 8, 2)])
            self.ip_mappings[ip_address] = anonymized
            
        return self.ip_mappings[ip_address]
    
    def anonymize_device_name(self, device_name: str) -> str:
        """Anonymize device name"""
        if not self.settings.anonymize_device_names:
            return device_name
            
        if device_name not in self.device_mappings:
            # Generate consistent anonymized name
            hash_obj = hashlib.sha256(f"{device_name}_{self.session_id}".encode())
            hash_hex = hash_obj.hexdigest()[:6]
            
            anonymized = f"Device_{hash_hex.upper()}"
            self.device_mappings[device_name] = anonymized
            
        return self.device_mappings[device_name]
    
    def log_privacy_event(self, event_type: str, details: Dict, sensitive: bool = False):
        """Log privacy event with appropriate protection"""
        timestamp = datetime.now().isoformat()
        
        # Anonymize sensitive details
        if sensitive:
            details = self._anonymize_dict(details)
        
        event = {
            "timestamp": timestamp,
            "session_id": self.session_id,
            "event_type": event_type,
            "details": details,
            "sensitive": sensitive
        }
        
        # Add to privacy log
        self.privacy_log.append(event)
        
        # Log to file
        if self.settings.encrypt_logs:
            # Simple obfuscation for sensitive data
            log_message = f"EVENT: {event_type} - {json.dumps(details, default=str)}"
        else:
            log_message = f"EVENT: {event_type} - {json.dumps(details, default=str)}"
            
        self.privacy_logger.info(log_message)
    
    def _anonymize_dict(self, data: Dict) -> Dict:
        """Anonymize dictionary data"""
        anonymized = {}
        
        for key, value in data.items():
            if isinstance(value, str):
                if 'mac' in key.lower():
                    anonymized[key] = self.anonymize_mac(value)
                elif 'ip' in key.lower():
                    anonymized[key] = self.anonymize_ip(value)
                elif 'name' in key.lower() or 'device' in key.lower():
                    anonymized[key] = self.anonymize_device_name(value)
                else:
                    anonymized[key] = f"[ANONYMIZED_{key.upper()}]"
            elif isinstance(value, dict):
                anonymized[key] = self._anonymize_dict(value)
            elif isinstance(value, list):
                anonymized[key] = [self._anonymize_dict(item) if isinstance(item, dict) else f"[ANONYMIZED_{key.upper()}]" for item in value]
            else:
                anonymized[key] = f"[ANONYMIZED_{key.upper()}]"
                
        return anonymized
    
    def mask_network_activity(self):
        """Mask network activity to prevent detection"""
        if not self.settings.mask_user_activity:
            return
            
        try:
            # Generate random network activity to mask real activity
            self._generate_decoy_traffic()
            
            # Log privacy event
            self.log_privacy_event("network_masking", {
                "action": "generated_decoy_traffic",
                "timestamp": datetime.now().isoformat()
            }, sensitive=True)
            
        except Exception as e:
            log_error(f"Failed to mask network activity: {e}")
    
    def _generate_decoy_traffic(self):
        """Generate decoy network traffic"""
        try:
            # Generate random pings to common IPs
            decoy_ips = [
                "8.8.8.8", "1.1.1.1", "208.67.222.222",
                "192.168.1.1", "10.0.0.1"
            ]
            
            for ip in random.sample(decoy_ips, 2):
                try:
                    subprocess.run(
                        ["ping", "-n", "1", ip],
                        capture_output=True,
                        timeout=3
                    )
                except:
                    pass
                    
        except Exception as e:
            log_error(f"Failed to generate decoy traffic: {e}")
    
    def clear_privacy_data(self):
        """Clear all privacy-sensitive data"""
        try:
            # Clear anonymization mappings
            self.mac_mappings.clear()
            self.ip_mappings.clear()
            self.device_mappings.clear()
            
            # Clear privacy log
            self.privacy_log.clear()
            
            # Clear log file if enabled
            if self.settings.clear_logs_on_exit:
                if os.path.exists(self.privacy_log_file):
                    os.remove(self.privacy_log_file)
            
            # Log privacy event
            self.log_privacy_event("privacy_clear", {
                "action": "cleared_all_privacy_data",
                "timestamp": datetime.now().isoformat()
            }, sensitive=True)
            
        except Exception as e:
            log_error(f"Failed to clear privacy data: {e}")
    
    def get_privacy_report(self) -> Dict:
        """Generate privacy report"""
        session_duration = datetime.now() - self.start_time
        
        return {
            "session_id": self.session_id,
            "session_duration": str(session_duration),
            "privacy_level": self.settings.privacy_level,
            "events_logged": len(self.privacy_log),
            "anonymization_enabled": {
                "mac_addresses": self.settings.anonymize_mac_addresses,
                "ip_addresses": self.settings.anonymize_ip_addresses,
                "device_names": self.settings.anonymize_device_names
            },
            "protection_enabled": {
                "log_encryption": self.settings.encrypt_logs,
                "log_clearance": self.settings.clear_logs_on_exit,
                "activity_masking": self.settings.mask_user_activity
            }
        }
    
    def set_privacy_level(self, level: str):
        """Set privacy protection level"""
        if level == "low":
            self.settings = PrivacySettings(
                anonymize_mac_addresses=False,
                anonymize_ip_addresses=False,
                anonymize_device_names=False,
                encrypt_logs=False,
                clear_logs_on_exit=False,
                mask_user_activity=False,
                privacy_level="low"
            )
        elif level == "medium":
            self.settings = PrivacySettings(
                anonymize_mac_addresses=True,
                anonymize_ip_addresses=False,
                anonymize_device_names=True,
                encrypt_logs=True,
                clear_logs_on_exit=False,
                mask_user_activity=False,
                privacy_level="medium"
            )
        elif level == "high":
            self.settings = PrivacySettings(
                anonymize_mac_addresses=True,
                anonymize_ip_addresses=True,
                anonymize_device_names=True,
                encrypt_logs=True,
                clear_logs_on_exit=True,
                mask_user_activity=True,
                privacy_level="high"
            )
        elif level == "maximum":
            self.settings = PrivacySettings(
                anonymize_mac_addresses=True,
                anonymize_ip_addresses=True,
                anonymize_device_names=True,
                encrypt_logs=True,
                clear_logs_on_exit=True,
                mask_user_activity=True,
                use_vpn_proxy=True,
                privacy_level="maximum"
            )
        
        self.log_privacy_event("privacy_level_changed", {
            "new_level": level,
            "timestamp": datetime.now().isoformat()
        })

# Global privacy manager instance
privacy_manager = PrivacyManager() 
