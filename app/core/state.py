# app/core/state.py
"""
Application state management for DupeZ.

Provides:
  - ``Device`` and ``AppSettings`` dataclasses
  - ``AppState`` — the central mutable state object with observer pattern
    and Qt thread marshaling for safe background → GUI notifications.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from app.logs.logger import log_error, log_info
from app.utils.helpers import mask_ip

__all__ = ["Device", "AppSettings", "AppState"]


def _is_main_thread() -> bool:
    """Return True when called from the main thread."""
    return threading.current_thread() is threading.main_thread()


# ── Data models ───────────────────────────────────────────────────────

@dataclass
class Device:
    """A single discovered network device."""

    ip: str
    mac: str
    vendor: str
    hostname: str
    local: bool
    traffic: int
    last_seen: str
    blocked: bool = False


@dataclass
class AppSettings:
    """Persisted application settings.

    ``whitelist`` uses a mutable default (``None`` → ``[]`` in
    ``__post_init__``) to avoid the shared-list pitfall.
    """

    # Core
    smart_mode: bool = False
    auto_scan: bool = True
    scan_interval: int = 60
    max_devices: int = 100
    log_level: str = "INFO"

    # Network
    ping_timeout: int = 2
    max_threads: int = 20
    quick_scan: bool = True
    auto_block: bool = False
    high_traffic_threshold: int = 1000
    connection_limit: int = 100
    suspicious_activity_threshold: int = 20
    block_duration: int = 30

    # UI
    theme: str = "dark"
    auto_refresh: bool = True
    refresh_interval: int = 120
    show_device_icons: bool = True
    show_status_indicators: bool = True
    compact_view: bool = False
    show_notifications: bool = True
    sound_alerts: bool = False

    # Advanced
    cache_duration: int = 60
    memory_limit: int = 200
    require_admin: bool = True
    encrypt_logs: bool = False
    debug_mode: bool = False
    verbose_logging: bool = False

    # Security
    whitelist: Optional[list] = None

    def __post_init__(self) -> None:
        if self.whitelist is None:
            self.whitelist = []


# ── Application state ─────────────────────────────────────────────────

class AppState:
    """Central mutable state with observer notifications.

    Observers are called on the Qt main thread when possible, falling
    back to direct dispatch when Qt is unavailable.
    """

    def __init__(self, config_file: str = "") -> None:
        if not config_file:
            import sys
            if getattr(sys, "frozen", False):
                base = os.path.dirname(sys.executable)
            else:
                base = os.path.dirname(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                )
            config_file = os.path.join(base, "app", "config", "settings.json")

        self.config_file: str = config_file
        self.devices: List[Device] = []
        self.selected_ip: Optional[str] = None
        self.blocking: bool = False
        self.settings: AppSettings = AppSettings()
        self.network_info: Dict[str, Any] = {}
        self.scan_in_progress: bool = False

        self._observers: List[Callable] = []
        self._lock = threading.Lock()

        self.load_settings()

    # ── Observer pattern ──────────────────────────────────────────

    def add_observer(self, callback: Callable) -> None:
        """Register *callback(event, data)* to be notified of state changes."""
        with self._lock:
            self._observers.append(callback)

    def notify_observers(self, event: str, data: Any = None) -> None:
        """Notify all observers of a state change.

        A snapshot of the observer list is taken under the lock, then
        dispatch happens outside the lock to avoid deadlocks in
        callbacks that touch state.  If called from a background
        thread, marshals to the Qt event loop via ``QTimer.singleShot``.
        """
        with self._lock:
            observers = list(self._observers)

        def _dispatch() -> None:
            for observer in observers:
                try:
                    observer(event, data)
                except Exception as e:
                    log_error(f"Observer notification failed: {e}")

        if _is_main_thread():
            _dispatch()
        else:
            try:
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(0, _dispatch)
            except (ImportError, RuntimeError):
                _dispatch()

    # ── Device management ─────────────────────────────────────────

    def update_devices(self, devices: List[Dict[str, Any]]) -> None:
        """Replace the device list from scan results.

        If a device dict arrives with a missing/blank/"Unknown" hostname
        — e.g. from a cache loaded before the hostname-enrichment pass
        landed, or from a third-party plugin that builds devices by
        hand — we synthesize a readable fallback here so the GUI column
        is never empty. The synthesis mirrors the scanner's fallback
        rules (vendor slug + MAC suffix).
        """
        new_devices = []
        for d in devices:
            ip = d.get("ip", "")
            mac = d.get("mac", "Unknown")
            vendor = d.get("vendor", "Unknown")
            hostname = d.get("hostname", "") or ""
            if not hostname or hostname == "Unknown":
                try:
                    from app.network.enhanced_scanner import _synthesize_hostname
                    hostname = _synthesize_hostname(ip, mac, vendor)
                except Exception:
                    hostname = f"device-{ip.replace('.', '-')}" if ip else "device-unknown"
            new_devices.append(Device(
                ip=ip,
                mac=mac,
                vendor=vendor,
                hostname=hostname,
                local=d.get("local", False),
                traffic=d.get("traffic", 0),
                last_seen=datetime.now().isoformat(),
                blocked=d.get("blocked", False),
            ))

        with self._lock:
            self.devices = new_devices

        self.notify_observers("devices_updated", self.devices)
        log_info(f"Updated device list: {len(self.devices)} devices")

    def select_device(self, ip: str) -> None:
        """Select a device by IP for subsequent operations."""
        self.selected_ip = ip
        self.notify_observers("device_selected", ip)
        log_info(f"Selected device: {mask_ip(ip)}")

    def get_selected_device(self) -> Optional[Device]:
        """Return the currently selected device, or None."""
        return self.get_device_by_ip(self.selected_ip) if self.selected_ip else None

    def get_device_by_ip(self, ip: str) -> Optional[Device]:
        """Return the device matching *ip*, or None."""
        with self._lock:
            for device in self.devices:
                if device.ip == ip:
                    return device
        return None

    def toggle_blocking(self, ip: Optional[str] = None) -> bool:
        """Toggle the blocked flag on a device.  Returns the new state."""
        target_ip = ip or self.selected_ip
        if not target_ip:
            log_error("No device selected to toggle blocking")
            return False

        with self._lock:
            for device in self.devices:
                if device.ip == target_ip:
                    device.blocked = not device.blocked
                    blocked = device.blocked
                    self.blocking = any(d.blocked for d in self.devices)
                    break
            else:
                log_error(f"Device {mask_ip(target_ip)} not found")
                return False

        self.notify_observers("blocking_toggled", {
            "ip": target_ip,
            "blocked": blocked,
        })
        log_info(f"Blocking {'enabled' if blocked else 'disabled'} for {mask_ip(target_ip)}")
        return blocked

    # ── Network info ──────────────────────────────────────────────

    def update_network_info(self, info: Dict[str, Any]) -> None:
        """Store latest network information and notify observers."""
        self.network_info = info
        self.notify_observers("network_updated", info)

    def set_scan_status(self, in_progress: bool) -> None:
        """Update scan-in-progress flag and notify observers."""
        self.scan_in_progress = in_progress
        self.notify_observers("scan_status_changed", in_progress)

    # ── Settings persistence ──────────────────────────────────────

    def load_settings(self) -> None:
        """Load settings from JSON file, resilient to corrupt/partial data."""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                known = {fld.name for fld in fields(AppSettings)}
                filtered = {k: v for k, v in data.items() if k in known}
                self.settings = AppSettings(**filtered)
                log_info("Settings loaded successfully")
        except (json.JSONDecodeError, TypeError) as e:
            log_error(f"Corrupt settings file, using defaults: {e}")
            self.settings = AppSettings()
            self.save_settings()
        except Exception as e:
            log_error(f"Failed to load settings: {e}")
            self.settings = AppSettings()

    def save_settings(self) -> None:
        """Persist settings via atomic write (tmp → fsync → replace)."""
        tmp_path = self.config_file + ".tmp"
        try:
            config_dir = os.path.dirname(self.config_file)
            if config_dir:
                os.makedirs(config_dir, exist_ok=True)

            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(asdict(self.settings), f, indent=2)
                f.flush()
                os.fsync(f.fileno())

            os.replace(tmp_path, self.config_file)
            log_info("Settings saved successfully")
        except Exception as e:
            log_error(f"Failed to save settings: {e}")
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def update_setting(self, key: str, value: Any) -> None:
        """Update a single setting by name and persist."""
        if hasattr(self.settings, key):
            old_value = getattr(self.settings, key)
            setattr(self.settings, key, value)
            self.save_settings()
            self.notify_observers("setting_updated", {key: value})
            log_info(f"Setting updated: {key} = {value}")
            # Audit trail for settings changes
            try:
                from app.logs.audit import audit_event
                audit_event("setting_changed", {
                    "key": key,
                    "old_value": str(old_value)[:100],
                    "new_value": str(value)[:100],
                })
            except Exception:
                pass
