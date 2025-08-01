# app/plugins/plugin_manager.py

import os
import sys
import importlib
import importlib.util
import json
import threading
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime
import inspect
from pathlib import Path
from app.logs.logger import log_info, log_error, log_warning

@dataclass
class PluginInfo:
    """Information about a plugin"""
    name: str
    version: str
    description: str
    author: str
    category: str
    enabled: bool = True
    file_path: str = ""
    load_time: datetime = field(default_factory=datetime.now)
    dependencies: List[str] = field(default_factory=list)
    settings: Dict[str, Any] = field(default_factory=dict)

@dataclass
class PluginRule:
    """A custom rule created by a plugin"""
    name: str
    description: str
    plugin_name: str
    rule_type: str  # blocking, monitoring, alerting, automation
    conditions: List[Dict[str, Any]]
    actions: List[Dict[str, Any]]
    enabled: bool = True
    priority: int = 50
    created_at: datetime = field(default_factory=datetime.now)

class PluginBase:
    """Base class for all plugins"""
    
    def __init__(self, plugin_info: PluginInfo):
        self.info = plugin_info
        self.is_loaded = False
        self.hooks = {}
        self.rules = []
    
    def on_load(self):
        """Called when the plugin is loaded"""
        pass
    
    def on_unload(self):
        """Called when the plugin is unloaded"""
        pass
    
    def on_device_detected(self, device):
        """Called when a new device is detected"""
        pass
    
    def on_device_blocked(self, device):
        """Called when a device is blocked"""
        pass
    
    def on_device_unblocked(self, device):
        """Called when a device is unblocked"""
        pass
    
    def on_traffic_anomaly(self, anomaly):
        """Called when a traffic anomaly is detected"""
        pass
    
    def on_network_scan_complete(self, devices):
        """Called when a network scan completes"""
        pass
    
    def register_hook(self, hook_name: str, callback: Callable):
        """Register a callback for a specific hook"""
        if hook_name not in self.hooks:
            self.hooks[hook_name] = []
        self.hooks[hook_name].append(callback)
    
    def add_rule(self, rule: PluginRule):
        """Add a custom rule to the plugin"""
        rule.plugin_name = self.info.name
        self.rules.append(rule)
    
    def get_settings(self) -> Dict[str, Any]:
        """Get plugin settings"""
        return self.info.settings
    
    def set_setting(self, key: str, value: Any):
        """Set a plugin setting"""
        self.info.settings[key] = value

class PluginManager:
    """Manages plugin loading, unloading, and execution"""
    
    def __init__(self, plugins_dir: str = "app/plugins"):
        self.plugins_dir = Path(plugins_dir)
        self.plugins: Dict[str, PluginBase] = {}
        self.plugin_info: Dict[str, PluginInfo] = {}
        self.hooks: Dict[str, List[Callable]] = {}
        self.rules: List[PluginRule] = []
        self.settings_file = self.plugins_dir / "plugin_settings.json"
        
        # Create plugins directory if it doesn't exist
        self.plugins_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize hooks
        self._init_hooks()
        
        # Load plugin settings
        self.load_settings()
        
        # Load all plugins
        self.load_all_plugins()
    
    def _init_hooks(self):
        """Initialize available hooks"""
        self.hooks = {
            'device_detected': [],
            'device_blocked': [],
            'device_unblocked': [],
            'traffic_anomaly': [],
            'network_scan_complete': [],
            'before_block': [],
            'after_block': [],
            'before_unblock': [],
            'after_unblock': [],
            'periodic': []
        }
    
    def load_all_plugins(self):
        """Load all available plugins"""
        try:
            # Look for plugin files
            for plugin_file in self.plugins_dir.glob("*.py"):
                if plugin_file.name.startswith("__"):
                    continue
                
                plugin_name = plugin_file.stem
                if plugin_name not in self.plugins:
                    self.load_plugin(plugin_name, str(plugin_file))
            
            log_info(f"Loaded {len(self.plugins)} plugins")
            
        except Exception as e:
            log_error(f"Error loading plugins: {e}")
    
    def load_plugin(self, plugin_name: str, file_path: str) -> bool:
        """Load a specific plugin"""
        try:
            # Load the module
            spec = importlib.util.spec_from_file_location(plugin_name, file_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            # Look for plugin class
            plugin_class = None
            for name, obj in inspect.getmembers(module):
                if (inspect.isclass(obj) and 
                    issubclass(obj, PluginBase) and 
                    obj != PluginBase):
                    plugin_class = obj
                    break
            
            if not plugin_class:
                log_warning(f"No plugin class found in {file_path}")
                return False
            
            # Create plugin info
            plugin_info = PluginInfo(
                name=plugin_name,
                version=getattr(module, '__version__', '1.0.0'),
                description=getattr(module, '__description__', 'No description'),
                author=getattr(module, '__author__', 'Unknown'),
                category=getattr(module, '__category__', 'General'),
                file_path=file_path
            )
            
            # Create plugin instance
            plugin = plugin_class(plugin_info)
            
            # Check if plugin should be enabled
            if plugin_name in self.plugin_info:
                plugin_info.enabled = self.plugin_info[plugin_name].enabled
                plugin_info.settings = self.plugin_info[plugin_name].settings
            
            # Load plugin if enabled
            if plugin_info.enabled:
                plugin.on_load()
                plugin.is_loaded = True
                
                # Register hooks
                for hook_name in self.hooks.keys():
                    if hasattr(plugin, f'on_{hook_name}'):
                        callback = getattr(plugin, f'on_{hook_name}')
                        if callable(callback):
                            self.register_hook(hook_name, callback)
                
                # Add rules
                for rule in plugin.rules:
                    self.add_rule(rule)
            
            # Store plugin
            self.plugins[plugin_name] = plugin
            self.plugin_info[plugin_name] = plugin_info
            
            log_info(f"Plugin loaded: {plugin_name}")
            return True
            
        except Exception as e:
            log_error(f"Error loading plugin {plugin_name}: {e}")
            return False
    
    def unload_plugin(self, plugin_name: str) -> bool:
        """Unload a specific plugin"""
        try:
            if plugin_name not in self.plugins:
                return False
            
            plugin = self.plugins[plugin_name]
            
            # Unload plugin
            if plugin.is_loaded:
                plugin.on_unload()
                plugin.is_loaded = False
            
            # Remove hooks
            for hook_name in self.hooks.keys():
                if hasattr(plugin, f'on_{hook_name}'):
                    callback = getattr(plugin, f'on_{hook_name}')
                    if callback in self.hooks[hook_name]:
                        self.hooks[hook_name].remove(callback)
            
            # Remove rules
            self.rules = [rule for rule in self.rules if rule.plugin_name != plugin_name]
            
            # Remove plugin
            del self.plugins[plugin_name]
            
            log_info(f"Plugin unloaded: {plugin_name}")
            return True
            
        except Exception as e:
            log_error(f"Error unloading plugin {plugin_name}: {e}")
            return False
    
    def reload_plugin(self, plugin_name: str) -> bool:
        """Reload a specific plugin"""
        if self.unload_plugin(plugin_name):
            plugin_info = self.plugin_info.get(plugin_name)
            if plugin_info:
                return self.load_plugin(plugin_name, plugin_info.file_path)
        return False
    
    def enable_plugin(self, plugin_name: str) -> bool:
        """Enable a plugin"""
        if plugin_name in self.plugins:
            plugin = self.plugins[plugin_name]
            if not plugin.is_loaded:
                plugin.on_load()
                plugin.is_loaded = True
                plugin.info.enabled = True
                
                # Register hooks
                for hook_name in self.hooks.keys():
                    if hasattr(plugin, f'on_{hook_name}'):
                        callback = getattr(plugin, f'on_{hook_name}')
                        if callable(callback):
                            self.register_hook(hook_name, callback)
                
                # Add rules
                for rule in plugin.rules:
                    self.add_rule(rule)
                
                log_info(f"Plugin enabled: {plugin_name}")
                return True
        return False
    
    def disable_plugin(self, plugin_name: str) -> bool:
        """Disable a plugin"""
        if plugin_name in self.plugins:
            plugin = self.plugins[plugin_name]
            if plugin.is_loaded:
                plugin.on_unload()
                plugin.is_loaded = False
                plugin.info.enabled = False
                
                # Remove hooks
                for hook_name in self.hooks.keys():
                    if hasattr(plugin, f'on_{hook_name}'):
                        callback = getattr(plugin, f'on_{hook_name}')
                        if callback in self.hooks[hook_name]:
                            self.hooks[hook_name].remove(callback)
                
                # Remove rules
                self.rules = [rule for rule in self.rules if rule.plugin_name != plugin_name]
                
                log_info(f"Plugin disabled: {plugin_name}")
                return True
        return False
    
    def register_hook(self, hook_name: str, callback: Callable):
        """Register a callback for a specific hook"""
        if hook_name in self.hooks:
            if callback not in self.hooks[hook_name]:
                self.hooks[hook_name].append(callback)
    
    def call_hook(self, hook_name: str, *args, **kwargs):
        """Call all registered callbacks for a hook"""
        if hook_name in self.hooks:
            for callback in self.hooks[hook_name]:
                try:
                    callback(*args, **kwargs)
                except Exception as e:
                    log_error(f"Error in hook {hook_name}: {e}")
    
    def add_rule(self, rule: PluginRule):
        """Add a custom rule"""
        self.rules.append(rule)
        log_info(f"Added rule: {rule.name} from {rule.plugin_name}")
    
    def remove_rule(self, rule_name: str, plugin_name: str = None):
        """Remove a custom rule"""
        if plugin_name:
            self.rules = [rule for rule in self.rules 
                         if not (rule.name == rule_name and rule.plugin_name == plugin_name)]
        else:
            self.rules = [rule for rule in self.rules if rule.name != rule_name]
    
    def get_rules(self, plugin_name: str = None) -> List[PluginRule]:
        """Get all rules or rules from a specific plugin"""
        if plugin_name:
            return [rule for rule in self.rules if rule.plugin_name == plugin_name]
        return self.rules
    
    def evaluate_rules(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Evaluate all enabled rules against a context"""
        results = []
        
        for rule in self.rules:
            if not rule.enabled:
                continue
            
            try:
                # Check conditions
                conditions_met = True
                for condition in rule.conditions:
                    if not self._evaluate_condition(condition, context):
                        conditions_met = False
                        break
                
                if conditions_met:
                    # Execute actions
                    for action in rule.actions:
                        result = self._execute_action(action, context)
                        results.append({
                            'rule': rule.name,
                            'plugin': rule.plugin_name,
                            'action': action,
                            'result': result
                        })
            
            except Exception as e:
                log_error(f"Error evaluating rule {rule.name}: {e}")
        
        return results
    
    def _evaluate_condition(self, condition: Dict[str, Any], context: Dict[str, Any]) -> bool:
        """Evaluate a single condition"""
        condition_type = condition.get('type', '')
        
        if condition_type == 'device_type':
            device_type = condition.get('value', '')
            device = context.get('device')
            if device:
                if device_type == 'gaming' and device.is_gaming_device:
                    return True
                elif device_type == 'mobile' and device.is_mobile:
                    return True
                elif device_type == 'router' and device.is_router:
                    return True
        
        elif condition_type == 'ip_range':
            ip_range = condition.get('value', '')
            device = context.get('device')
            if device:
                # Simple IP range check
                ip_parts = device.ip.split('.')
                if len(ip_parts) == 4:
                    ip_num = int(ip_parts[0]) * 16777216 + int(ip_parts[1]) * 65536 + int(ip_parts[2]) * 256 + int(ip_parts[3])
                    # This is a simplified check - in a real implementation you'd use proper IP range parsing
                    return True
        
        elif condition_type == 'traffic_threshold':
            threshold = condition.get('value', 0)
            traffic = context.get('traffic', 0)
            return traffic > threshold
        
        elif condition_type == 'time_of_day':
            time_range = condition.get('value', {})
            current_hour = datetime.now().hour
            start_hour = time_range.get('start', 0)
            end_hour = time_range.get('end', 23)
            return start_hour <= current_hour <= end_hour
        
        return False
    
    def _execute_action(self, action: Dict[str, Any], context: Dict[str, Any]) -> bool:
        """Execute a single action"""
        action_type = action.get('type', '')
        
        if action_type == 'block_device':
            device = context.get('device')
            if device:
                # This would call the controller to block the device
                self.call_hook('before_block', device)
                # controller.block_device(device.ip)
                self.call_hook('after_block', device)
                return True
        
        elif action_type == 'unblock_device':
            device = context.get('device')
            if device:
                self.call_hook('before_unblock', device)
                # controller.unblock_device(device.ip)
                self.call_hook('after_unblock', device)
                return True
        
        elif action_type == 'send_alert':
            message = action.get('message', 'Plugin alert')
            log_warning(f"Plugin alert: {message}")
            return True
        
        elif action_type == 'log_event':
            message = action.get('message', 'Plugin event')
            log_info(f"Plugin event: {message}")
            return True
        
        return False
    
    def get_plugin_info(self) -> List[PluginInfo]:
        """Get information about all plugins"""
        return list(self.plugin_info.values())
    
    def get_plugin(self, plugin_name: str) -> Optional[PluginBase]:
        """Get a specific plugin"""
        return self.plugins.get(plugin_name)
    
    def save_settings(self):
        """Save plugin settings to file"""
        try:
            settings = {}
            for name, info in self.plugin_info.items():
                settings[name] = {
                    'enabled': info.enabled,
                    'settings': info.settings
                }
            
            with open(self.settings_file, 'w') as f:
                json.dump(settings, f, indent=2)
            
            log_info("Plugin settings saved")
            
        except Exception as e:
            log_error(f"Error saving plugin settings: {e}")
    
    def load_settings(self):
        """Load plugin settings from file"""
        try:
            if self.settings_file.exists():
                with open(self.settings_file, 'r') as f:
                    settings = json.load(f)
                
                for name, data in settings.items():
                    if name not in self.plugin_info:
                        self.plugin_info[name] = PluginInfo(
                            name=name,
                            version='1.0.0',
                            description='Unknown',
                            author='Unknown',
                            category='General'
                        )
                    
                    self.plugin_info[name].enabled = data.get('enabled', True)
                    self.plugin_info[name].settings = data.get('settings', {})
                
                log_info("Plugin settings loaded")
            
        except Exception as e:
            log_error(f"Error loading plugin settings: {e}")
    
    def create_plugin_template(self, plugin_name: str, category: str = "General"):
        """Create a template for a new plugin"""
        template = f'''# {plugin_name}.py
"""
Plugin: {plugin_name}
Category: {category}
Description: Add your plugin description here
Author: Your Name
Version: 1.0.0
"""

from app.plugins.plugin_manager import PluginBase, PluginInfo, PluginRule

class {plugin_name.title().replace('_', '')}Plugin(PluginBase):
    """{plugin_name} plugin implementation"""
    
    def on_load(self):
        """Called when the plugin is loaded"""
        super().on_load()
        
        # Add your initialization code here
        print(f"{plugin_name} plugin loaded!")
        
        # Example: Add a custom rule
        rule = PluginRule(
            name="Example Rule",
            description="An example rule that blocks gaming devices during work hours",
            plugin_name=self.info.name,
            rule_type="blocking",
            conditions=[
                {{
                    "type": "device_type",
                    "value": "gaming"
                }},
                {{
                    "type": "time_of_day",
                    "value": {{
                        "start": 9,
                        "end": 17
                    }}
                }}
            ],
            actions=[
                {{
                    "type": "block_device"
                }},
                {{
                    "type": "send_alert",
                    "message": "Gaming device blocked during work hours"
                }}
            ]
        )
        self.add_rule(rule)
    
    def on_device_detected(self, device):
        """Called when a new device is detected"""
        # Add your device detection logic here
        pass
    
    def on_device_blocked(self, device):
        """Called when a device is blocked"""
        # Add your blocking logic here
        pass
    
    def on_traffic_anomaly(self, anomaly):
        """Called when a traffic anomaly is detected"""
        # Add your anomaly handling logic here
        pass
'''
        
        plugin_file = self.plugins_dir / f"{plugin_name}.py"
        with open(plugin_file, 'w') as f:
            f.write(template)
        
        log_info(f"Plugin template created: {plugin_file}")
        return str(plugin_file)
    
    def cleanup(self):
        """Cleanup resources"""
        try:
            # Unload all plugins
            for plugin_name in list(self.plugins.keys()):
                self.unload_plugin(plugin_name)
            
            # Save settings
            self.save_settings()
            
            log_info("Plugin manager cleaned up")
            
        except Exception as e:
            log_error(f"Error during plugin cleanup: {e}") 