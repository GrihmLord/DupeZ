# app/core/controller.py — DupeZ Controller
"""
Central orchestrator for DupeZ: device scanning, disruption delegation,
auto-scan loop, plugin lifecycle, and settings management.
"""

from __future__ import annotations

import socket
import threading
import time
from typing import Any, Dict, List, Optional

import psutil

from app.core.data_persistence import device_cache_manager, save_all_data
from app.core.scheduler import DisruptionScheduler
from app.core.state import AppSettings, AppState, Device
from app.firewall import blocker
# ADR-0001: disruption_manager is now obtained via the feature-flag factory
# so that DUPEZ_ARCH=split can transparently swap in the IPC proxy without
# changing any downstream code. Under DUPEZ_ARCH=inproc (default) this
# returns the exact same singleton as a direct import — zero behavioural
# change on the hot path.
from app.firewall_helper.feature_flag import get_disruption_manager
disruption_manager = get_disruption_manager()
from app.logs.logger import log_error, log_info, log_network_scan
from app.network import device_scan
from app.plugins.loader import PluginLoader
from app.utils.helpers import mask_ip

__all__ = ["AppController"]


class AppController:
    """Top-level controller that ties together scanning, disruption,
    scheduling, plugins, and persistent state."""

    def __init__(self) -> None:
        self.state = AppState()
        self.scan_thread: Optional[threading.Thread] = None
        self.stop_scanning = False
        self.auto_scan_enabled = True
        self._scan_lock = threading.Lock()

        self._load_device_cache()
        self._init_engine()

        # Disruption scheduler + macro engine
        self.scheduler = DisruptionScheduler(
            disrupt_fn=self.disrupt_device,
            stop_fn=self.stop_disruption,
        )
        self.scheduler.start()

        # Plugin system
        self.plugin_loader = PluginLoader()
        self._init_plugins()

        if self.state.settings.auto_scan:
            self.start_auto_scan()

    # ── Disruption engine ───────────────────────────────────────

    def _init_engine(self) -> None:
        """Initialise the disruption engine (NativeWinDivert or clumsy.exe fallback)."""
        try:
            if disruption_manager.initialize():
                disruption_manager.start()
                log_info("Disruption engine initialized")
            else:
                log_error("Disruption engine init failed — check admin privileges and WinDivert files")
        except Exception as e:
            log_error(f"Disruption engine init error: {e}")

    # ── Disruption delegation ─────────────────────────────────────

    def disrupt_device(self, ip: str, methods: Optional[List[str]] = None,
                       params: Optional[Dict] = None, **kwargs: Any) -> bool:
        """Start disruption on *ip* with optional methods/params.

        Additional ``**kwargs`` (e.g. ``target_mac``, ``target_hostname``,
        ``target_device_type``) are forwarded to the underlying engine to
        enable auto-detection of the appropriate disruption profile.
        """
        return disruption_manager.disrupt_device(ip, methods, params, **kwargs)

    def stop_disruption(self, ip: str) -> bool:
        """Stop disruption on *ip*."""
        return disruption_manager.stop_device(ip)

    def stop_all_disruptions(self) -> bool:
        """Stop all active disruptions."""
        return disruption_manager.stop_all_devices()

    def get_disrupted_devices(self) -> List[str]:
        """Return list of currently disrupted IPs."""
        return disruption_manager.get_disrupted_devices()

    def get_disruption_status(self, ip: str) -> Dict:
        """Return disruption status for *ip*."""
        return disruption_manager.get_device_status(ip)

    def get_clumsy_status(self) -> Dict:
        """Return overall engine status."""
        return disruption_manager.get_status()

    def get_engine_stats(self) -> Dict:
        """Return packet processing stats from all engines."""
        return disruption_manager.get_engine_stats()

    # ── Device cache ──────────────────────────────────────────────

    _CACHE_FIELDS = ("ip", "mac", "hostname", "vendor", "local", "traffic", "last_seen")
    _CACHE_DEFAULTS: Dict[str, Any] = {
        "ip": "", "mac": "", "hostname": "", "vendor": "",
        "local": False, "traffic": 0, "last_seen": "",
    }

    def _load_device_cache(self) -> None:
        """Populate the device list from last session's cache."""
        try:
            cached = device_cache_manager.get_cached_devices()
            if cached:
                self.state.update_devices(cached)
                log_info(f"Loaded {len(cached)} cached devices from previous session")
        except Exception as e:
            log_error(f"Device cache load error: {e}")

    def _save_device_cache(self, devices: list) -> None:
        """Persist discovered devices for next launch."""
        try:
            serializable = [
                d if isinstance(d, dict)
                else {k: getattr(d, k, self._CACHE_DEFAULTS[k]) for k in self._CACHE_FIELDS}
                for d in devices
                if isinstance(d, dict) or hasattr(d, "__dict__")
            ]
            device_cache_manager.update_cache(serializable)
        except Exception as e:
            log_error(f"Device cache save error: {e}")

    # ── Device scanning ───────────────────────────────────────────

    def scan_devices(self, quick: bool = True) -> List[Dict]:
        """Scan for devices on the local network.

        Called from a background thread in the GUI, so we call
        ``scan_network()`` synchronously here.
        """
        start_time = time.time()
        try:
            self.state.set_scan_status(True)
            log_info(f"Starting device scan ({'quick' if quick else 'full'})...")

            network_info = device_scan.get_network_info()
            self.state.update_network_info(network_info)

            # Lazy import — EnhancedNetworkScanner is heavy and depends on Qt
            from app.network.enhanced_scanner import EnhancedNetworkScanner
            scanner = EnhancedNetworkScanner()
            devices = scanner.scan_network(quick_scan=quick)

            real_devices = [d for d in devices if self._is_real_device(d)]
            for d in real_devices:
                log_info(f"Found device: {mask_ip(d['ip'])} — {d.get('hostname', 'Unknown')}")

            self.state.update_devices(real_devices)
            self._save_device_cache(real_devices)

            duration = time.time() - start_time
            log_network_scan(len(real_devices), duration)
            return real_devices

        except Exception as e:
            log_error(f"Device scan failed: {e}")
            return []
        finally:
            self.state.set_scan_status(False)

    @staticmethod
    def _is_real_device(d: dict) -> bool:
        """Filter out loopback, multicast, broadcast, and link-local addresses."""
        ip = d.get("ip")
        if not ip or ip == "127.0.0.1":
            return False
        octets = ip.split(".")
        if len(octets) != 4:
            return False
        first, last = int(octets[0]), int(octets[3])
        return not (first >= 224 or last == 255 or (first == 169 and int(octets[1]) == 254))

    def quick_scan_devices(self) -> List[Dict]:
        """Convenience: run a quick scan."""
        return self.scan_devices(quick=True)

    # ── Device management ─────────────────────────────────────────

    def select_device(self, ip: str) -> None:
        """Select a device by IP for subsequent operations."""
        self.state.select_device(ip)

    def get_selected_device(self) -> Optional[Device]:
        """Return the currently selected device."""
        return self.state.get_selected_device()

    def toggle_lag(self, ip: Optional[str] = None) -> bool:
        """Toggle firewall blocking for a device.

        Despite the legacy name ('lag'), this uses netsh firewall
        rules for hard block/unblock, not packet manipulation.
        """
        if not ip:
            return False
        try:
            device = self.state.get_device_by_ip(ip)
            if not device:
                return blocker.block_device(ip)
            fn = blocker.unblock_device if device.blocked else blocker.block_device
            if fn(ip):
                device.blocked = not device.blocked
            return device.blocked
        except Exception as e:
            log_error(f"Toggle lag failed: {e}")
            return False

    def get_devices(self) -> List[Device]:
        """Return the current device list."""
        return self.state.devices

    def get_blocked_devices(self) -> List[Device]:
        """Return only devices with blocked=True."""
        return [d for d in self.state.devices if d.blocked]

    def get_device_by_ip(self, ip: str) -> Optional[Device]:
        """Look up a device by IP."""
        return self.state.get_device_by_ip(ip)

    def clear_devices(self) -> None:
        """Remove all devices from state."""
        with self.state._lock:
            self.state.devices = []
        self.state.notify_observers("devices_updated", [])

    # ── Auto-scan ─────────────────────────────────────────────────

    def start_auto_scan(self) -> None:
        """Start the background auto-scan loop."""
        with self._scan_lock:
            self.auto_scan_enabled = True
            self.stop_scanning = False
            if not self.scan_thread or not self.scan_thread.is_alive():
                self.scan_thread = threading.Thread(
                    target=self._auto_scan_loop, daemon=True,
                )
                self.scan_thread.start()

    def stop_auto_scan(self) -> None:
        """Signal the auto-scan loop to stop."""
        self.auto_scan_enabled = False
        self.stop_scanning = True

    def _auto_scan_loop(self) -> None:
        """Background loop that rescans at the configured interval."""
        while self.auto_scan_enabled and not self.stop_scanning:
            try:
                if not self.state.scan_in_progress:
                    self.quick_scan_devices()
                interval = max(10, self.state.settings.scan_interval)
                time.sleep(interval)
            except Exception as e:
                log_error(f"Auto-scan error: {e}")
                time.sleep(60)

    # ── Network info ──────────────────────────────────────────────

    def get_network_info(self) -> Dict[str, Any]:
        """Return active interfaces and I/O counters."""
        try:
            interfaces = psutil.net_if_addrs()
            active = [
                {"name": name, "ip": addr.address, "netmask": addr.netmask}
                for name, addrs in interfaces.items()
                for addr in addrs
                if addr.family == socket.AF_INET
            ]
            net_io = psutil.net_io_counters()
            return {
                "interfaces": active,
                "bytes_sent": net_io.bytes_sent,
                "bytes_recv": net_io.bytes_recv,
            }
        except Exception as e:
            log_error(f"Get network info failed: {e}")
            return {}

    # ── Settings ──────────────────────────────────────────────────

    def update_settings(self, new_settings: AppSettings) -> None:
        """Replace settings and persist."""
        self.state.settings = new_settings
        self.state.save_settings()

    def update_setting(self, key: str, value: Any) -> None:
        """Update a single setting by key."""
        if hasattr(self.state.settings, key):
            setattr(self.state.settings, key, value)
            self.state.save_settings()

    def get_settings(self) -> AppSettings:
        """Return current settings."""
        return self.state.settings

    def is_scanning(self) -> bool:
        """Return whether a scan is in progress."""
        return self.state.scan_in_progress

    def is_blocking(self) -> bool:
        """Return whether any devices are currently blocked."""
        return len(self.get_blocked_devices()) > 0

    # ── Plugin system ─────────────────────────────────────────────

    def _init_plugins(self) -> None:
        """Discover and load all plugins."""
        try:
            self.plugin_loader.discover()
            self.plugin_loader.load_all(self)
            active = self.plugin_loader.get_active_plugins()
            log_info(f"Plugin system initialized: {len(active)} active plugin(s)")
        except Exception as e:
            log_error(f"Plugin system init error: {e}")

    def get_plugin_info(self) -> List[Dict]:
        """Return metadata for all discovered plugins."""
        return self.plugin_loader.get_plugin_info()

    def reload_plugins(self) -> None:
        """Unload and re-discover all plugins."""
        self.plugin_loader.unload_all()
        self.plugin_loader.discover()
        self.plugin_loader.load_all(self)

    # ── Shutdown ──────────────────────────────────────────────────

    def shutdown(self) -> None:
        """Graceful shutdown: plugins → scan → scheduler → engine → save."""
        try:
            log_info("Controller shutting down...")
            self.plugin_loader.unload_all()
            self.stop_auto_scan()
            self.scheduler.stop()
            disruption_manager.stop()
            save_all_data()
            log_info("Controller shutdown complete")
        except Exception as e:
            log_error(f"Shutdown error: {e}")
