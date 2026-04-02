"""
Data persistence system for DupeZ application
Ensures all user changes are automatically saved
"""

import json
import os
import time
from typing import Dict, List, Any, Optional
from dataclasses import asdict, dataclass
from pathlib import Path

from app.logs.logger import log_info, log_error


def _resolve_data_directory() -> str:
    """Resolve a writable data directory that works for both dev and PyInstaller.

    When running from source the relative ``app/data`` path is fine.
    When running as a frozen PyInstaller exe the bundled ``app/data`` inside
    ``_MEIPASS`` is **read-only**, so we store user data next to the exe
    instead (``<exe_dir>/app/data``).  ``main.py`` already calls
    ``os.chdir(os.path.dirname(sys.executable))`` for frozen builds, so the
    relative path resolves correctly — but we make it absolute here to be
    safe.
    """
    import sys
    if getattr(sys, 'frozen', False):
        # Next to the exe — writable, survives restarts
        base = os.path.dirname(sys.executable)
    else:
        # Dev: project root (wherever dupez.py lives)
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, "app", "data")


@dataclass
class PersistenceConfig:
    """Configuration for data persistence"""
    auto_save: bool = True
    save_interval: int = 30  # seconds
    backup_enabled: bool = True
    max_backups: int = 5
    data_directory: str = ""

    def __post_init__(self):
        if not self.data_directory:
            self.data_directory = _resolve_data_directory()


class DataPersistenceManager:
    """Centralized data persistence manager"""

    def __init__(self, config: PersistenceConfig = None):
        self.config = config or PersistenceConfig()
        self.data_directory = Path(self.config.data_directory)
        self.data_directory.mkdir(parents=True, exist_ok=True)
        
        # Track data changes
        self._dirty_data = set()
        self._last_save_time = time.time()
        
        # Initialize data structures
        self._data_cache = {}
        
        log_info("Data persistence manager initialized")
    
    def save_data(self, data_type: str, data: Any, force: bool = False) -> bool:
        """Save data to persistent storage"""
        try:
            # Check if we need to save
            if not force and not self._should_save(data_type):
                return True
            
            # Prepare file path
            file_path = self.data_directory / f"{data_type}.json"
            
            # Create backup if enabled
            if self.config.backup_enabled and file_path.exists():
                self._create_backup(file_path)
            
            # Save data
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            # Update tracking
            self._dirty_data.discard(data_type)
            self._last_save_time = time.time()
            
            log_info(f"Data saved successfully: {data_type}")
            return True
            
        except Exception as e:
            log_error(f"Failed to save {data_type}: {e}")
            return False
    
    def load_data(self, data_type: str, default: Any = None) -> Any:
        """Load data from persistent storage"""
        try:
            file_path = self.data_directory / f"{data_type}.json"
            
            if not file_path.exists():
                return default
            
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Cache the data
            self._data_cache[data_type] = data
            
            log_info(f"Data loaded successfully: {data_type}")
            return data
            
        except Exception as e:
            log_error(f"Failed to load {data_type}: {e}")
            return default
    
    def mark_dirty(self, data_type: str):
        """Mark data as changed (needs saving)"""
        self._dirty_data.add(data_type)
        log_info(f"Data marked as dirty: {data_type}")
    
    def auto_save_all(self) -> bool:
        """Auto-save all dirty data"""
        if not self.config.auto_save:
            return True
        
        success = True
        for data_type in list(self._dirty_data):
            if not self.save_data(data_type, self._data_cache.get(data_type, {})):
                success = False
        
        return success
    
    def _should_save(self, data_type: str) -> bool:
        """Check if data should be saved"""
        # Always save if marked as dirty
        if data_type in self._dirty_data:
            return True
        
        # Check save interval
        if time.time() - self._last_save_time > self.config.save_interval:
            return True
        
        return False
    
    def _create_backup(self, file_path: Path):
        """Create backup of existing file"""
        try:
            timestamp = int(time.time())
            backup_path = file_path.with_suffix(f".backup.{timestamp}.json")
            
            # Keep only max_backups
            backup_files = list(file_path.parent.glob(f"{file_path.stem}.backup.*.json"))
            backup_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            
            if len(backup_files) >= self.config.max_backups:
                for old_backup in backup_files[self.config.max_backups:]:
                    old_backup.unlink()
            
            # Create new backup
            import shutil
            shutil.copy2(file_path, backup_path)
            
        except Exception as e:
            log_error(f"Failed to create backup: {e}")
    
    def get_data_info(self) -> Dict[str, Any]:
        """Get information about stored data"""
        try:
            info = {
                "data_directory": str(self.data_directory),
                "total_files": 0,
                "total_size": 0,
                "dirty_data": list(self._dirty_data),
                "cached_data": list(self._data_cache.keys())
            }
            
            for file_path in self.data_directory.glob("*.json"):
                if file_path.is_file():
                    info["total_files"] += 1
                    info["total_size"] += file_path.stat().st_size
            
            return info
            
        except Exception as e:
            log_error(f"Failed to get data info: {e}")
            return {}


# Global persistence manager instance
persistence_manager = DataPersistenceManager()


class AutoSaveMixin:
    """Mixin to add auto-save functionality to classes"""
    
    def __init__(self, data_type: str):
        self._data_type = data_type
        self._auto_save_enabled = True
    
    def save_changes(self, data: Any, force: bool = False):
        """Save changes to persistent storage"""
        if self._auto_save_enabled:
            persistence_manager.mark_dirty(self._data_type)
            return persistence_manager.save_data(self._data_type, data, force)
        return True
    
    def load_saved_data(self, default: Any = None):
        """Load saved data"""
        return persistence_manager.load_data(self._data_type, default)
    
    def enable_auto_save(self, enabled: bool = True):
        """Enable or disable auto-save"""
        self._auto_save_enabled = enabled
        log_info(f"Auto-save {'enabled' if enabled else 'disabled'} for {self._data_type}")


# Specific data managers for different data types
class SettingsManager(AutoSaveMixin):
    """Manager for application settings"""
    
    def __init__(self):
        super().__init__("settings")
        self.settings = self.load_saved_data({})
    
    def update_setting(self, key: str, value: Any):
        """Update a setting and save"""
        self.settings[key] = value
        self.save_changes(self.settings)
    
    def get_setting(self, key: str, default: Any = None):
        """Get a setting value"""
        return self.settings.get(key, default)


class DeviceManager(AutoSaveMixin):
    """Manager for device data"""
    
    def __init__(self):
        super().__init__("devices")
        self.devices = self.load_saved_data([])
    
    def add_device(self, device: Dict):
        """Add a device and save"""
        self.devices.append(device)
        self.save_changes(self.devices)
    
    def update_device(self, ip: str, updates: Dict):
        """Update a device and save"""
        for device in self.devices:
            if device.get('ip') == ip:
                device.update(updates)
                self.save_changes(self.devices)
                break
    
    def remove_device(self, ip: str):
        """Remove a device and save"""
        self.devices = [d for d in self.devices if d.get('ip') != ip]
        self.save_changes(self.devices)


class AccountManager(AutoSaveMixin):
    """Manager for DayZ account data"""
    
    def __init__(self):
        super().__init__("dayz_accounts")
        self.accounts = self.load_saved_data([])
    
    def add_account(self, account: Dict):
        """Add an account and save"""
        self.accounts.append(account)
        self.save_changes(self.accounts)
    
    def update_account(self, account_name: str, updates: Dict):
        """Update an account and save"""
        for account in self.accounts:
            if account.get('account') == account_name:
                account.update(updates)
                self.save_changes(self.accounts)
                break
    
    def remove_account(self, account_name: str):
        """Remove an account and save"""
        self.accounts = [a for a in self.accounts if a.get('account') != account_name]
        self.save_changes(self.accounts)


class MarkerManager(AutoSaveMixin):
    """Manager for map markers and loot locations"""
    
    def __init__(self):
        super().__init__("dayz_markers")
        self.markers = self.load_saved_data({
            "markers": [],
            "loot_locations": [],
            "gps_coordinates": {}
        })
    
    def add_marker(self, marker: Dict):
        """Add a marker and save"""
        self.markers["markers"].append(marker)
        self.save_changes(self.markers)
    
    def add_loot_location(self, loot: Dict):
        """Add a loot location and save"""
        self.markers["loot_locations"].append(loot)
        self.save_changes(self.markers)
    
    def update_gps_coordinates(self, coordinates: Dict):
        """Update GPS coordinates and save"""
        self.markers["gps_coordinates"].update(coordinates)
        self.save_changes(self.markers)


class NicknameManager(AutoSaveMixin):
    """Manager for device nicknames — friendly names for scanned devices.

    Stores {mac_or_ip: nickname} mappings.  MAC is preferred key when
    available because IPs can change across DHCP leases.
    """

    def __init__(self):
        super().__init__("device_nicknames")
        self.nicknames: Dict[str, str] = self.load_saved_data({})

    def set_nickname(self, key: str, nickname: str):
        """Set or update a nickname for a device (key = MAC or IP)."""
        if nickname:
            self.nicknames[key] = nickname
        else:
            self.nicknames.pop(key, None)
        self.save_changes(self.nicknames, force=True)

    def get_nickname(self, mac: str = "", ip: str = "") -> str:
        """Get nickname — tries MAC first, falls back to IP."""
        if mac and mac in self.nicknames:
            return self.nicknames[mac]
        if ip and ip in self.nicknames:
            return self.nicknames[ip]
        return ""

    def remove_nickname(self, key: str):
        """Remove a nickname."""
        if key in self.nicknames:
            del self.nicknames[key]
            self.save_changes(self.nicknames, force=True)

    def get_all(self) -> Dict[str, str]:
        return dict(self.nicknames)


class DeviceCacheManager(AutoSaveMixin):
    """Persists discovered devices across restarts so the device list
    isn't empty on every launch."""

    def __init__(self):
        super().__init__("device_cache")
        self._cache: List[Dict] = self.load_saved_data([])

    def update_cache(self, devices: List[Dict]):
        """Replace the cached device list with the latest scan results."""
        self._cache = devices
        self.save_changes(self._cache, force=True)

    def get_cached_devices(self) -> List[Dict]:
        """Return the last-known device list."""
        return list(self._cache)

    def clear(self):
        self._cache = []
        self.save_changes(self._cache, force=True)


# Global manager instances
settings_manager = SettingsManager()
device_manager = DeviceManager()
account_manager = AccountManager()
marker_manager = MarkerManager()
nickname_manager = NicknameManager()
device_cache_manager = DeviceCacheManager()


def save_all_data():
    """Save all pending data"""
    return persistence_manager.auto_save_all()


def get_persistence_info():
    """Get information about data persistence"""
    return persistence_manager.get_data_info() 