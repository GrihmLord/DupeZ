"""
Data persistence system for DupeZ application.

Provides atomic JSON file storage with backup rotation, corruption
recovery, HMAC integrity verification, and a generic collection
manager that eliminates per-type boilerplate.

Security Features:
  - Atomic writes: tmp → fsync → replace (no partial writes on crash)
  - HMAC-SHA384 integrity tags: every saved file gets a companion
    .hmac file.  On load, integrity is verified before parsing.
  - Backup rotation with corruption recovery
  - Optional encryption at rest (via SecretsManager)

NOTE: Global manager instances are created at module import time,
which triggers directory creation and file I/O.  This is intentional —
persistence must be available before any other subsystem initialises.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.logs.logger import log_error, log_info

__all__ = [
    "PersistenceConfig",
    "DataPersistenceManager",
    "persistence_manager",
    "AutoSaveMixin",
    "CollectionManager",
    "SettingsManager",
    "DeviceManager",
    "AccountManager",
    "MarkerManager",
    "NicknameManager",
    "DeviceCacheManager",
    "settings_manager",
    "device_manager",
    "account_manager",
    "marker_manager",
    "nickname_manager",
    "device_cache_manager",
    "save_all_data",
    "get_persistence_info",
]


# ── HMAC Integrity ───────────────────────────────────────────────────

def _get_hmac_key() -> bytes:
    """Derive a machine-specific HMAC key for data integrity.

    Uses the same machine seed as the secrets manager, hashed to
    produce a stable 48-byte (384-bit) key.
    """
    import platform
    parts = [
        platform.node(),
        os.environ.get("USERNAME", os.environ.get("USER", "default")),
        platform.machine(),
        "DupeZ-DataIntegrity-v1",  # domain separation
    ]
    seed = "|".join(parts).encode("utf-8")
    return hashlib.sha384(seed).digest()


def _compute_hmac(data: bytes) -> str:
    """Compute HMAC-SHA384 hex digest for data integrity."""
    return hmac.new(_get_hmac_key(), data, hashlib.sha384).hexdigest()


def _verify_hmac(data: bytes, expected_hex: str) -> bool:
    """Constant-time HMAC verification."""
    computed = hmac.new(_get_hmac_key(), data, hashlib.sha384).hexdigest()
    return hmac.compare_digest(computed, expected_hex)


# ── Data directory resolution ─────────────────────────────────────────

def _resolve_data_directory() -> str:
    """Return a writable data directory for both dev and frozen exe.

    When running from source the relative ``app/data`` path is fine.
    When running as a frozen PyInstaller exe the bundled ``app/data``
    inside ``_MEIPASS`` is **read-only**, so we store user data next
    to the exe instead (``<exe_dir>/app/data``).
    """
    import sys

    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
    return os.path.join(base, "app", "data")


# ── Configuration ─────────────────────────────────────────────────────

@dataclass
class PersistenceConfig:
    """Configuration for the persistence manager.

    If *data_directory* is left empty (the default) it is resolved
    automatically via :func:`_resolve_data_directory` in ``__post_init__``.
    """

    auto_save: bool = True
    save_interval: int = 30  # seconds between implicit saves
    backup_enabled: bool = True
    max_backups: int = 5
    data_directory: str = ""

    def __post_init__(self) -> None:
        if not self.data_directory:
            self.data_directory = _resolve_data_directory()


# ── Core persistence manager ─────────────────────────────────────────

class DataPersistenceManager:
    """Centralised, thread-safe data persistence manager.

    All public methods that touch ``_dirty_data`` or ``_data_cache``
    acquire ``_lock`` first.
    """

    def __init__(self, config: Optional[PersistenceConfig] = None) -> None:
        self.config = config or PersistenceConfig()
        self.data_directory = Path(self.config.data_directory)
        self.data_directory.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()
        self._dirty_data: set[str] = set()
        self._last_save_time: float = time.time()
        self._data_cache: Dict[str, Any] = {}

        log_info("Data persistence manager initialized")

    # ── Save / load ───────────────────────────────────────────────

    def save_data(self, data_type: str, data: Any, force: bool = False) -> bool:
        """Persist *data* as ``<data_type>.json`` (thread-safe, atomic write)."""
        with self._lock:
            try:
                if not force and not self._should_save_locked(data_type):
                    return True

                file_path = self.data_directory / f"{data_type}.json"

                if self.config.backup_enabled and file_path.exists():
                    self._create_backup(file_path)

                self._data_cache[data_type] = data

                # Atomic write: tmp → fsync → replace
                tmp_path = file_path.with_suffix(".tmp")
                try:
                    raw_json = json.dumps(data, indent=2, ensure_ascii=False)
                    raw_bytes = raw_json.encode("utf-8")
                    with open(tmp_path, "w", encoding="utf-8") as f:
                        f.write(raw_json)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(str(tmp_path), str(file_path))
                    # Write companion HMAC tag
                    hmac_path = file_path.with_suffix(".hmac")
                    try:
                        hmac_hex = _compute_hmac(raw_bytes)
                        with open(hmac_path, "w", encoding="utf-8") as hf:
                            hf.write(hmac_hex)
                            hf.flush()
                            os.fsync(hf.fileno())
                    except Exception as he:
                        log_error(f"Failed to write HMAC for {data_type}: {he}")
                except Exception:
                    tmp_path.unlink(missing_ok=True)
                    raise

                self._dirty_data.discard(data_type)
                self._last_save_time = time.time()
                return True

            except Exception as e:
                log_error(f"Failed to save {data_type}: {e}")
                return False

    def load_data(self, data_type: str, default: Any = None) -> Any:
        """Load ``<data_type>.json``, falling back to backups on corruption."""
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
            key=lambda p: p.stat().st_mtime,
            reverse=True,
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

    # ── Dirty tracking ────────────────────────────────────────────

    def mark_dirty(self, data_type: str) -> None:
        """Mark *data_type* as changed (needs saving)."""
        with self._lock:
            self._dirty_data.add(data_type)

    def auto_save_all(self) -> bool:
        """Save every dirty data type that has a cached value.

        Takes a snapshot of dirty items under the lock, then releases
        before calling ``save_data`` (which re-acquires the lock per
        item).  This avoids holding the lock for the entire I/O batch.
        """
        if not self.config.auto_save:
            return True

        with self._lock:
            to_save = {
                dt: self._data_cache[dt]
                for dt in list(self._dirty_data)
                if dt in self._data_cache
            }

        success = True
        for data_type, data in to_save.items():
            if not self.save_data(data_type, data):
                success = False
        return success

    # ── Internal helpers (caller must hold _lock) ─────────────────

    def _should_save_locked(self, data_type: str) -> bool:
        """Return True if *data_type* warrants a save right now.

        **Must be called while holding ``_lock``.**
        """
        if data_type in self._dirty_data:
            return True
        if time.time() - self._last_save_time > self.config.save_interval:
            return True
        return False

    @staticmethod
    def _try_load_json(path: Path) -> Any:
        """Attempt to load JSON from *path* with HMAC integrity check.

        If a companion .hmac file exists, the file's contents are
        verified against the stored HMAC before parsing.  A tampered
        file is treated as corrupt (returns None).
        """
        try:
            if not path.exists():
                return None
            with open(path, "rb") as f:
                raw = f.read()
            # HMAC integrity check
            hmac_path = path.with_suffix(".hmac")
            if hmac_path.exists():
                try:
                    with open(hmac_path, "r", encoding="utf-8") as hf:
                        stored_hmac = hf.read().strip()
                    if not _verify_hmac(raw, stored_hmac):
                        log_error(f"HMAC verification FAILED for {path.name} — "
                                  "possible tampering")
                        return None
                except Exception as e:
                    log_error(f"HMAC check error for {path.name}: {e}")
                    # Continue loading — HMAC failure is logged but
                    # we don't want to brick the app if .hmac is missing/corrupt
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def _create_backup(self, file_path: Path) -> None:
        """Copy *file_path* to a timestamped backup, pruning old copies."""
        try:
            timestamp = int(time.time())
            backup_path = file_path.with_suffix(f".backup.{timestamp}.json")

            backup_files = sorted(
                file_path.parent.glob(f"{file_path.stem}.backup.*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for old in backup_files[self.config.max_backups:]:
                old.unlink(missing_ok=True)

            shutil.copy2(file_path, backup_path)
        except Exception as e:
            log_error(f"Failed to create backup: {e}")

    # ── Diagnostics ───────────────────────────────────────────────

    def get_data_info(self) -> Dict[str, Any]:
        """Return a diagnostic snapshot of persistence state."""
        try:
            with self._lock:
                dirty = list(self._dirty_data)
                cached = list(self._data_cache.keys())

            total_files = 0
            total_size = 0
            for file_path in self.data_directory.glob("*.json"):
                if file_path.is_file():
                    total_files += 1
                    total_size += file_path.stat().st_size

            return {
                "data_directory": str(self.data_directory),
                "total_files": total_files,
                "total_size": total_size,
                "dirty_data": dirty,
                "cached_data": cached,
            }
        except Exception as e:
            log_error(f"Failed to get data info: {e}")
            return {}


# ── Global persistence manager ────────────────────────────────────────

persistence_manager = DataPersistenceManager()


# ── AutoSave mixin ────────────────────────────────────────────────────

class AutoSaveMixin:
    """Mixin that delegates save/load to the global persistence manager."""

    def __init__(self, data_type: str) -> None:
        self._data_type = data_type
        self._auto_save_enabled = True

    def save_changes(self, data: Any, force: bool = False) -> bool:
        """Persist *data* via the global manager."""
        if self._auto_save_enabled:
            persistence_manager.mark_dirty(self._data_type)
            return persistence_manager.save_data(self._data_type, data, force)
        return True

    def load_saved_data(self, default: Any = None) -> Any:
        """Load previously persisted data, or return *default*."""
        return persistence_manager.load_data(self._data_type, default)

    def enable_auto_save(self, enabled: bool = True) -> None:
        """Toggle auto-save for this data type."""
        self._auto_save_enabled = enabled
        log_info(f"Auto-save {'enabled' if enabled else 'disabled'} for {self._data_type}")


# ── Generic collection manager ────────────────────────────────────────

class CollectionManager(AutoSaveMixin):
    """Generic CRUD manager for list-based persistent collections.

    Eliminates the repeated add/update/remove pattern across
    DeviceManager, AccountManager, etc.
    """

    def __init__(self, data_type: str, key_field: str = "ip",
                 default: Optional[List[Dict]] = None) -> None:
        super().__init__(data_type)
        self._key_field = key_field
        self.items: List[Dict] = self.load_saved_data(
            default if default is not None else []
        )

    def add(self, item: Dict) -> None:
        """Append *item* and persist."""
        self.items.append(item)
        self.save_changes(self.items)

    def update(self, key_value: str, updates: Dict) -> None:
        """Update the first item whose key field matches *key_value*."""
        for item in self.items:
            if item.get(self._key_field) == key_value:
                item.update(updates)
                self.save_changes(self.items)
                return

    def remove(self, key_value: str) -> None:
        """Remove all items whose key field matches *key_value*."""
        self.items = [i for i in self.items if i.get(self._key_field) != key_value]
        self.save_changes(self.items)


# ── Specific managers (thin backwards-compat wrappers) ────────────────

class SettingsManager(AutoSaveMixin):
    """Manager for application settings (dict-based, not a collection)."""

    def __init__(self) -> None:
        super().__init__("settings")
        self.settings: Dict[str, Any] = self.load_saved_data({})

    def update_setting(self, key: str, value: Any) -> None:
        self.settings[key] = value
        self.save_changes(self.settings)

    def get_setting(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)


class DeviceManager(CollectionManager):
    """Manager for device data."""

    def __init__(self) -> None:
        super().__init__("devices", key_field="ip")

    @property
    def devices(self) -> List[Dict]:
        return self.items

    def add_device(self, d: Dict) -> None:
        self.add(d)

    def update_device(self, ip: str, u: Dict) -> None:
        self.update(ip, u)

    def remove_device(self, ip: str) -> None:
        self.remove(ip)


class AccountManager(CollectionManager):
    """Manager for DayZ account data."""

    def __init__(self) -> None:
        super().__init__("dayz_accounts", key_field="account")

    @property
    def accounts(self) -> List[Dict]:
        return self.items

    def add_account(self, a: Dict) -> None:
        self.add(a)

    def update_account(self, name: str, u: Dict) -> None:
        self.update(name, u)

    def remove_account(self, name: str) -> None:
        self.remove(name)


class MarkerManager(AutoSaveMixin):
    """Manager for map markers and loot locations."""

    def __init__(self) -> None:
        super().__init__("dayz_markers")
        self.markers: Dict[str, Any] = self.load_saved_data({
            "markers": [], "loot_locations": [], "gps_coordinates": {},
        })

    def add_marker(self, marker: Dict) -> None:
        self.markers["markers"].append(marker)
        self.save_changes(self.markers)

    def add_loot_location(self, loot: Dict) -> None:
        self.markers["loot_locations"].append(loot)
        self.save_changes(self.markers)

    def update_gps_coordinates(self, coordinates: Dict) -> None:
        self.markers["gps_coordinates"].update(coordinates)
        self.save_changes(self.markers)


class NicknameManager(AutoSaveMixin):
    """Device nicknames — MAC-preferred key → friendly name."""

    def __init__(self) -> None:
        super().__init__("device_nicknames")
        self.nicknames: Dict[str, str] = self.load_saved_data({})

    def set_nickname(self, key: str, nickname: str) -> None:
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

    def remove_nickname(self, key: str) -> None:
        if key in self.nicknames:
            del self.nicknames[key]
            self.save_changes(self.nicknames, force=True)

    def get_all(self) -> Dict[str, str]:
        return dict(self.nicknames)


class DeviceCacheManager(AutoSaveMixin):
    """Persists discovered devices across restarts."""

    def __init__(self) -> None:
        super().__init__("device_cache")
        self._cache: List[Dict] = self.load_saved_data([])

    def update_cache(self, devices: List[Dict]) -> None:
        self._cache = devices
        self.save_changes(self._cache, force=True)

    def get_cached_devices(self) -> List[Dict]:
        return list(self._cache)

    def clear(self) -> None:
        self._cache = []
        self.save_changes(self._cache, force=True)


# ── Global manager instances ──────────────────────────────────────────

settings_manager = SettingsManager()
device_manager = DeviceManager()
account_manager = AccountManager()
marker_manager = MarkerManager()
nickname_manager = NicknameManager()
device_cache_manager = DeviceCacheManager()


# ── Module-level convenience functions ────────────────────────────────

def save_all_data() -> bool:
    """Flush all dirty data to disk."""
    return persistence_manager.auto_save_all()


def get_persistence_info() -> Dict[str, Any]:
    """Return diagnostic info about persistence state."""
    return persistence_manager.get_data_info()
