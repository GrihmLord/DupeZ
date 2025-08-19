"""
Latency Manager for DupeZ Application
Centralized management of all latency-related operations and configurations
"""

import json
import time
import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from pathlib import Path

from app.logs.logger import log_info, log_error, log_warning

@dataclass
class LatencyProfile:
    """Data class for latency profile information"""
    name: str
    target_ms: int
    max_ms: int
    priority: str
    description: str
    bandwidth_reserved: int
    qos_level: str

@dataclass
class ServerLatency:
    """Data class for server latency configuration"""
    name: str
    ip: str
    ports: List[int]
    target_latency: int
    max_latency: int
    priority: str
    auto_optimize: bool
    ddos_protection: bool

class LatencyManager:
    """Centralized latency management for DupeZ application"""
    
    def __init__(self, config_path: str = "app/config/latency_config.json"):
        self.config_path = Path(config_path)
        self.config = {}
        self.latency_profiles = {}
        self.server_configs = {}
        self.optimization_enabled = True
        self.last_optimization = 0
        self.optimization_cooldown = 300
        
        self._load_configuration()
        self._initialize_profiles()
        
    def _load_configuration(self) -> None:
        """Load latency configuration from file"""
        try:
            if self.config_path.exists():
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
                log_info("Latency configuration loaded successfully")
            else:
                log_warning("Latency configuration file not found, using defaults")
                self._create_default_config()
        except Exception as e:
            log_error(f"Failed to load latency configuration: {e}")
            self._create_default_config()
    
    def _create_default_config(self) -> None:
        """Create default latency configuration"""
        self.config = {
            "latency_configuration": {
                "version": "2.0.0",
                "last_updated": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "description": "Default latency configuration for DupeZ application"
            },
            "gaming_latency_tiers": {
                "low": {
                    "name": "Low Latency",
                    "target_ms": 25,
                    "max_ms": 40,
                    "priority": "HIGH",
                    "description": "For standard gaming",
                    "bandwidth_reserved": 200,
                    "qos_level": "HIGH"
                }
            }
        }
    
    def _initialize_profiles(self) -> None:
        """Initialize latency profiles from configuration"""
        try:
            # Initialize gaming latency tiers
            for tier_name, tier_data in self.config.get("gaming_latency_tiers", {}).items():
                self.latency_profiles[tier_name] = LatencyProfile(
                    name=tier_data.get("name", tier_name),
                    target_ms=tier_data.get("target_ms", 50),
                    max_ms=tier_data.get("max_ms", 100),
                    priority=tier_data.get("priority", "NORMAL"),
                    description=tier_data.get("description", ""),
                    bandwidth_reserved=tier_data.get("bandwidth_reserved", 100),
                    qos_level=tier_data.get("qos_level", "NORMAL")
                )
            
            # Initialize server configurations
            for server_name, server_data in self.config.get("dayz_server_latency", {}).items():
                self.server_configs[server_name] = ServerLatency(
                    name=server_data.get("name", server_name),
                    ip=server_data.get("ip", ""),
                    ports=server_data.get("ports", []),
                    target_latency=server_data.get("target_latency", 50),
                    max_latency=server_data.get("max_latency", 100),
                    priority=server_data.get("priority", "NORMAL"),
                    auto_optimize=server_data.get("auto_optimize", True),
                    ddos_protection=server_data.get("ddos_protection", False)
                )
            
            log_info(f"Initialized {len(self.latency_profiles)} latency profiles and {len(self.server_configs)} server configs")
            
        except Exception as e:
            log_error(f"Failed to initialize latency profiles: {e}")
    
    def get_latency_profile(self, profile_name: str) -> Optional[LatencyProfile]:
        """Get latency profile by name"""
        return self.latency_profiles.get(profile_name)
    
    def get_server_config(self, server_name: str) -> Optional[ServerLatency]:
        """Get server configuration by name"""
        return self.server_configs.get(server_name)
    
    def get_all_profiles(self) -> Dict[str, LatencyProfile]:
        """Get all available latency profiles"""
        return self.latency_profiles.copy()
    
    def get_all_servers(self) -> Dict[str, ServerLatency]:
        """Get all available server configurations"""
        return self.server_configs.copy()
    
    def get_optimal_profile(self, target_latency: int) -> Optional[LatencyProfile]:
        """Get optimal latency profile for target latency"""
        best_profile = None
        best_score = float('inf')
        
        for profile in self.latency_profiles.values():
            if profile.target_ms <= target_latency:
                score = abs(profile.target_ms - target_latency)
                if score < best_score:
                    best_score = score
                    best_profile = profile
        
        return best_profile
    
    def get_duping_profile(self, profile_name: str) -> Optional[Dict[str, Any]]:
        """Get duping latency profile"""
        duping_profiles = self.config.get("duping_latency_profiles", {})
        return duping_profiles.get(profile_name)
    
    def get_qos_policy(self, traffic_type: str) -> Optional[Dict[str, Any]]:
        """Get QoS policy for traffic type"""
        qos_policies = self.config.get("network_optimization", {}).get("qos_policies", {})
        return qos_policies.get(traffic_type)
    
    def can_optimize(self) -> bool:
        """Check if optimization can be performed (respecting cooldown)"""
        if not self.optimization_enabled:
            return False
        
        current_time = time.time()
        return (current_time - self.last_optimization) >= self.optimization_cooldown
    
    def perform_optimization(self) -> Dict[str, Any]:
        """Perform latency optimization"""
        if not self.can_optimize():
            return {"success": False, "reason": "Optimization cooldown active"}
        
        try:
            # Get current optimization settings
            auto_opt = self.config.get("network_optimization", {}).get("auto_optimization", {})
            thresholds = auto_opt.get("optimization_thresholds", {})
            
            # Perform optimization logic here
            optimization_result = {
                "success": True,
                "timestamp": time.time(),
                "thresholds_applied": thresholds,
                "optimizations_performed": []
            }
            
            self.last_optimization = time.time()
            log_info("Latency optimization performed successfully")
            
            return optimization_result
            
        except Exception as e:
            log_error(f"Failed to perform latency optimization: {e}")
            return {"success": False, "reason": str(e)}
    
    def update_server_latency(self, server_name: str, new_latency: int) -> bool:
        """Update server latency measurement"""
        try:
            if server_name in self.server_configs:
                server = self.server_configs[server_name]
                
                # Check if optimization is needed
                if server.auto_optimize and new_latency > server.max_latency:
                    if self.can_optimize():
                        self.perform_optimization()
                        log_info(f"Auto-optimization triggered for {server_name} (latency: {new_latency}ms)")
                
                return True
            return False
            
        except Exception as e:
            log_error(f"Failed to update server latency: {e}")
            return False
    
    def get_scheduled_optimization(self, time_slot: str) -> Optional[Dict[str, Any]]:
        """Get scheduled optimization for time slot"""
        schedules = self.config.get("scheduled_optimizations", {})
        return schedules.get(time_slot)
    
    def save_configuration(self) -> bool:
        """Save current configuration to file"""
        try:
            # Update timestamp
            self.config["latency_configuration"]["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
            
            # Ensure directory exists
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            
            log_info("Latency configuration saved successfully")
            return True
            
        except Exception as e:
            log_error(f"Failed to save latency configuration: {e}")
            return False
    
    def reload_configuration(self) -> bool:
        """Reload configuration from file"""
        try:
            self._load_configuration()
            self._initialize_profiles()
            log_info("Latency configuration reloaded successfully")
            return True
        except Exception as e:
            log_error(f"Failed to reload latency configuration: {e}")
            return False
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """Get performance summary for all latency configurations"""
        try:
            summary = {
                "total_profiles": len(self.latency_profiles),
                "total_servers": len(self.server_configs),
                "optimization_enabled": self.optimization_enabled,
                "last_optimization": self.last_optimization,
                "profiles": {},
                "servers": {}
            }
            
            # Add profile summaries
            for name, profile in self.latency_profiles.items():
                summary["profiles"][name] = {
                    "target_ms": profile.target_ms,
                    "max_ms": profile.max_ms,
                    "priority": profile.priority,
                    "qos_level": profile.qos_level
                }
            
            # Add server summaries
            for name, server in self.server_configs.items():
                summary["servers"][name] = {
                    "ip": server.ip,
                    "target_latency": server.target_latency,
                    "max_latency": server.max_latency,
                    "priority": server.priority,
                    "auto_optimize": server.auto_optimize
                }
            
            return summary
            
        except Exception as e:
            log_error(f"Failed to generate performance summary: {e}")
            return {"error": str(e)}

# Global instance
latency_manager = LatencyManager()
