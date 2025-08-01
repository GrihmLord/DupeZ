# app/gui/hotkey.py

import threading
import time
from typing import Callable, List, Dict, Optional
from app.logs.logger import log_info, log_error

try:
    import keyboard
    KEYBOARD_AVAILABLE = True
except ImportError:
    KEYBOARD_AVAILABLE = False
    log_error("keyboard module not available. Hotkeys will be disabled.")

class HotkeyListener:
    """Enhanced hotkey listener with multiple key support and configuration"""
    
    def __init__(self, callback: Callable, keys: List[str] = None, config: Dict = None):
        self.callback = callback
        self.keys = keys or ['w']  # Default key
        self.config = config or {}
        self._running = False
        self._thread = None
        self._hotkey_handlers = {}
        
        # Configuration options
        self.cooldown = self.config.get('cooldown', 0.5)  # Seconds between triggers
        self.last_trigger_time = 0
        self.enabled = self.config.get('enabled', True)
        
        if not KEYBOARD_AVAILABLE:
            log_error("Hotkey functionality disabled - keyboard module not available")
            self.enabled = False
    
    def start(self):
        """Start listening for hotkeys"""
        if not self.enabled:
            log_info("Hotkeys disabled")
            return
            
        if self._running:
            log_info("Hotkey listener already running")
            return
        
        try:
            self._running = True
            self._thread = threading.Thread(target=self._listen_loop, daemon=True)
            self._thread.start()
            log_info(f"Hotkey listener started with keys: {', '.join(self.keys)}")
        except Exception as e:
            log_error(f"Failed to start hotkey listener: {e}")
            self._running = False
    
    def stop(self):
        """Stop listening for hotkeys"""
        if not self._running:
            return
        
        self._running = False
        
        # Unregister all hotkeys
        for handler in self._hotkey_handlers.values():
            try:
                keyboard.remove_hotkey(handler)
            except Exception as e:
                log_error(f"Error removing hotkey: {e}")
        
        self._hotkey_handlers.clear()
        
        # Wait for thread to finish
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        
        log_info("Hotkey listener stopped")
    
    def _listen_loop(self):
        """Main listening loop"""
        try:
            # Register hotkeys for each key
            for key in self.keys:
                self._register_hotkey(key)
            
            # Keep the thread alive
            while self._running:
                time.sleep(0.1)
                
        except Exception as e:
            log_error(f"Hotkey listener error: {e}")
        finally:
            self._running = False
    
    def _register_hotkey(self, key: str):
        """Register a single hotkey"""
        try:
            def hotkey_callback():
                self._trigger_callback(key)
            
            keyboard.add_hotkey(key, hotkey_callback, suppress=True)
            self._hotkey_handlers[key] = hotkey_callback
            log_info(f"Registered hotkey: {key}")
            
        except Exception as e:
            log_error(f"Failed to register hotkey '{key}': {e}")
    
    def _trigger_callback(self, key: str):
        """Trigger the callback with cooldown protection"""
        if not self._running:
            return
        
        current_time = time.time()
        if current_time - self.last_trigger_time < self.cooldown:
            return
        
        try:
            log_info(f"Hotkey triggered: {key}")
            self.callback()
            self.last_trigger_time = current_time
        except Exception as e:
            log_error(f"Hotkey callback error: {e}")
    
    def add_key(self, key: str):
        """Add a new hotkey"""
        if key not in self.keys:
            self.keys.append(key)
            if self._running:
                self._register_hotkey(key)
            log_info(f"Added hotkey: {key}")
    
    def remove_key(self, key: str):
        """Remove a hotkey"""
        if key in self.keys:
            self.keys.remove(key)
            if key in self._hotkey_handlers:
                try:
                    keyboard.remove_hotkey(self._hotkey_handlers[key])
                    del self._hotkey_handlers[key]
                except Exception as e:
                    log_error(f"Error removing hotkey '{key}': {e}")
            log_info(f"Removed hotkey: {key}")
    
    def set_keys(self, keys: List[str]):
        """Set new hotkeys"""
        # Remove old keys
        for key in list(self.keys):
            self.remove_key(key)
        
        # Add new keys
        self.keys = keys
        for key in keys:
            self.add_key(key)
    
    def is_running(self) -> bool:
        """Check if the listener is running"""
        return self._running
    
    def get_active_keys(self) -> List[str]:
        """Get list of active hotkeys"""
        return self.keys.copy()
    
    def set_cooldown(self, cooldown: float):
        """Set the cooldown period between triggers"""
        self.cooldown = max(0.1, cooldown)  # Minimum 0.1 seconds
        log_info(f"Hotkey cooldown set to {self.cooldown}s")
    
    def enable(self):
        """Enable hotkey functionality"""
        self.enabled = True
        log_info("Hotkeys enabled")
    
    def disable(self):
        """Disable hotkey functionality"""
        self.enabled = False
        self.stop()
        log_info("Hotkeys disabled")


class HotkeyManager:
    """Manager for multiple hotkey listeners"""
    
    def __init__(self):
        self.listeners: Dict[str, HotkeyListener] = {}
    
    def add_listener(self, name: str, callback: Callable, keys: List[str] = None, 
                    config: Dict = None) -> HotkeyListener:
        """Add a new hotkey listener"""
        listener = HotkeyListener(callback, keys, config)
        self.listeners[name] = listener
        return listener
    
    def remove_listener(self, name: str):
        """Remove a hotkey listener"""
        if name in self.listeners:
            self.listeners[name].stop()
            del self.listeners[name]
            log_info(f"Removed hotkey listener: {name}")
    
    def start_all(self):
        """Start all listeners"""
        for name, listener in self.listeners.items():
            listener.start()
    
    def stop_all(self):
        """Stop all listeners"""
        for name, listener in self.listeners.items():
            listener.stop()
    
    def get_listener(self, name: str) -> Optional[HotkeyListener]:
        """Get a specific listener by name"""
        return self.listeners.get(name)
    
    def get_all_listeners(self) -> Dict[str, HotkeyListener]:
        """Get all listeners"""
        return self.listeners.copy()


# Global hotkey manager instance
hotkey_manager = HotkeyManager()

def create_hotkey_listener(callback: Callable, keys: List[str] = None, 
                          config: Dict = None) -> HotkeyListener:
    """Create a new hotkey listener"""
    return HotkeyListener(callback, keys, config)

def get_hotkey_manager() -> HotkeyManager:
    """Get the global hotkey manager"""
    return hotkey_manager
