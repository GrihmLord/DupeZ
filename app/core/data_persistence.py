"""
Data persistence system for DupeZ application
Ensures all user changes are automatically saved
"""

import json
import os
import shutil
import threading
import time
from typing import Dict, List, Any
from dataclasses import dataclass
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

        self._lock = threading.Lock()
        self._dirty_data: set = set()
        self._last_save_time = time.time()
        self._data_cache: Dict[str, Any] = {}

        log_info("Data persistence manager initialized")

    def save_data(self, data_type: str, data: Any, force: bool = False) -> bool:
        """Save data to persistent storage (thread-safe)."""
        with self._lock:
            try:
                if not force and not self._should_save(data_type):
                    return True

                file_path = self.data_directory / f"{data_type}.json"

                if self.config.backup_enabled and file_path.exists():
                    self._create_backup(file_path)

                # Update cache so auto_save_all has current data
                self._data_cache[data_type] = data

                # Atomic write: tmp → fsync → replace
                tmp_path = file_path.with_suffix(".tmp")
                try:
                    with open(tmp_path, 'w', encoding='utf-8') as f:
                        json.dump(data, f, indent=2, ensure_ascii=False)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(str(tmp_path), str(file_path))
                except Exception:
                    # Clean up tmp on failure
                    try:
                        tmp_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                    raise

                self._dirty_data.discard(data_type)
                self._last_save_time = time.time()
                return True

            except Exception as e:
                log_error(f"Failed to save {data_type}: {e}")
                return False

    def load_data(self, data_type: str, default: Any = None) -> Any:
        """Load data from persistent storage, falling back to backups on corruption."""
        file_path = self.data_directory / f"{data_type}.json"

        # Try main file first
        data = self._try_load_json(file_path)
        if data is not None:
            with self._lock:
                self._data_cache[data_type] = data
            return data

        # Main file missing or corrupt — try backups (newest first)
        backups = sorted(
            file_path.parent.glob(f"{file_path.stem}.backup.*.json"),
            key=lambda p: p.stat().st_mtime, reverse=True
        )
        for backup in backups:
            data = self._try_load_json(backup)
            if data is not None:
                log_info(f"Recovered {data_type} from backup: {backup.name}")
                with self._lock:
                    self._data_cache[data_type] = data
                return data

        if file_path.exists():
            log_error(f"Failed to load {data_type}: main file and all backups corrupt")
        return default

    @staticmethod
    def _try_load_json(path: Path):
        """Attempt to load JSON from path. Returns None on any failure."""
        try:
            if not path.exists():
                return None
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    def mark_dirty(self, data_type: str):
        """Mark data as changed (needs saving)."""
        with self._lock:
            self._dirty_data.add(data_type)

    def auto_save_all(self) -> bool:
        """Auto-save all dirty data that has cached values."""
        if not self.config.auto_save:
            return True

        with self._lock:
            to_save = {dt: self._data_cache[dt]
                       for dt in list(self._dirty_data)
                       if dt in self._data_cache}

        success = True
        for data_type, data in to_save.items():
            if not self.save_data(data_type, data):
                success = False
        return success

    def _should_save(self, data_type: str) -> bool:
        """Check if data should be saved"""
        # Always save if marked as dirty
        if data_type in self._dirty_data:
            return True

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

# ── Generic collection manager (replaces per-type boilerplate) ───────
class CollectionManager(AutoSaveMixin):
    """Generic CRUD manager for list-based persistent collections.

    Eliminates the repeated add/update/remove pattern across
    DeviceManager, AccountManager, etc.
    """

    def __init__(self, data_type: str, key_field: str = "ip", default=None):
        super().__init__(data_type)
        self._key_field = key_field
        self.items: Any = self.load_saved_data(default if default is not None else [])

    def add(self, item: Dict):
        self.items.append(item)
        self.save_changes(self.items)

    def update(self, key_value: str, updates: Dict):
        for item in self.items:
            if item.get(self._key_field) == key_value:
                item.update(updates)
                self.save_changes(self.items)
                return

    def remove(self, key_value: str):
        self.items = [i for i in self.items if i.get(self._key_field) != key_value]
        self.save_changes(self.items)

# ── Specific managers (thin wrappers for backwards compatibility) ────
class SettingsManager(AutoSaveMixin):
    """Manager for application settings (dict-based, not a collection)."""

    def __init__(self):
        super().__init__("settings")
        self.settings = self.load_saved_data({})

    def update_setting(self, key: str, value: Any):
        self.settings[key] = value
        self.save_changes(self.settings)

    def get_setting(self, key: str, default: Any = None):
        return self.settings.get(key, default)

class DeviceManager(CollectionManager):
    """Manager for device data."""
    def __init__(self):
        super().__init__("devices", key_field="ip")
    # Backwards-compat aliases
    @property
    def devices(self): return self.items
    def add_device(self, d): self.add(d)
    def update_device(self, ip, u): self.update(ip, u)
    def remove_device(self, ip): self.remove(ip)

class AccountManager(CollectionManager):
    """Manager for DayZ account data."""
    def __init__(self):
        super().__init__("dayz_accounts", key_field="account")
    @property
    def accounts(self): return self.items
    def add_account(self, a): self.add(a)
    def update_account(self, name, u): self.update(name, u)
    def remove_account(self, name): self.remove(name)

class MarkerManager(AutoSaveMixin):
    """Manager for map markers and loot locations."""

    def __init__(self):
        super().__init__("dayz_markers")
        self.markers = self.load_saved_data({
            "markers": [], "loot_locations": [], "gps_coordinates": {}
        })

    def add_marker(self, marker: Dict):
        self.markers["markers"].append(marker)
        self.save_changes(self.markers)

    def add_loot_location(self, loot: Dict):
        self.markers["loot_locations"].append(loot)
        self.save_changes(self.markers)

    def update_gps_coordinates(self, coordinates: Dict):
        self.markers["gps_coordinates"].update(coordinates)
        self.save_changes(self.markers)

class NicknameManager(AutoSaveMixin):
    """Device nicknames — MAC-preferred key → friendly name."""

    def __init__(self):
        super().__init__("device_nicknames")
        self.nicknames: Dict[str, str] = self.load_saved_data({})

    def set_nickname(self, key: str, nickname: str):
        if nickname:
            self.nicknames[key] = nickname
        else:
            self.nicknames.pop(key, None)
        self.save_changes(self.nicknames, force=True)

    def get_nickname(self, mac: str = "", ip: str = "") -> str:
        if mac and mac in self.nicknames:
            return self.nicknames[mac]
        if ip and ip in self.nicknames:
            return self.nicknames[ip]
        return ""

    def remove_nickname(self, key: str):
        if key in self.nicknames:
            del self.nicknames[key]
            self.save_changes(self.nicknames, force=True)

    def get_all(self) -> Dict[str, str]:
        return dict(self.nicknames)

class DeviceCacheManager(AutoSaveMixin):
    """Persists discovered devices across restarts."""

    def __init__(self):
        super().__init__("device_cache")
        self._cache: List[Dict] = self.load_saved_data([])

    def update_cache(self, devices: List[Dict]):
        self._cache = devices
        self.save_changes(self._cache, force=True)

    def get_cached_devices(self) -> List[Dict]:
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

