# app/core/controller.py — DupeZ Controller (Stripped)

import threading
import time
import psutil
from typing import List, Dict
from app.network import device_scan
from app.firewall import blocker
from app.firewall.clumsy_network_disruptor import clumsy_network_disruptor
from app.logs.logger import log_info, log_error, log_network_scan
from app.core.state import AppState, AppSettings
from app.core.data_persistence import device_cache_manager, save_all_data
from app.core.scheduler import DisruptionScheduler
from app.plugins.loader import PluginLoader

class AppController:
    def __init__(self):
        self.state = AppState()
        self.scan_thread = None
        self.stop_scanning = False
        self.auto_scan_enabled = True
        self._scan_lock = threading.Lock()  # protects scan_thread lifecycle

        self._load_device_cache()

        self._init_clumsy()

        # Disruption scheduler + macro engine
        self.scheduler = DisruptionScheduler(
            disrupt_fn=self.disrupt_device,
            stop_fn=self.stop_disruption
        )
        self.scheduler.start()

        # Plugin system
        self.plugin_loader = PluginLoader()
        self._init_plugins()

        # Start auto-scan if enabled
        if self.state.settings.auto_scan:
            self.start_auto_scan()

    # Clumsy Integration
    def _init_clumsy(self):
        """Initialize the clumsy network disruptor"""
        try:
            if clumsy_network_disruptor.initialize():
                clumsy_network_disruptor.start_clumsy()
                log_info("Clumsy network disruptor initialized")
            else:
                log_error("Clumsy initialization failed — check admin privileges and WinDivert files")
        except Exception as e:
            log_error(f"Clumsy init error: {e}")

    # Clumsy disruption delegation — thin wrappers for GUI/plugin use
    def disrupt_device(self, ip, methods=None, params=None):
        return clumsy_network_disruptor.disconnect_device_clumsy(ip, methods, params)
    def stop_disruption(self, ip):
        return clumsy_network_disruptor.reconnect_device_clumsy(ip)
    def stop_all_disruptions(self):
        return clumsy_network_disruptor.clear_all_disruptions_clumsy()
    def get_disrupted_devices(self):
        return clumsy_network_disruptor.get_disrupted_devices_clumsy()
    def get_disruption_status(self, ip):
        return clumsy_network_disruptor.get_device_status_clumsy(ip)
    def get_clumsy_status(self):
        return clumsy_network_disruptor.get_clumsy_status()
    def get_engine_stats(self):
        return clumsy_network_disruptor.get_all_engine_stats()

    # Device Cache
    def _load_device_cache(self):
        """Load cached devices from last session so list isn't empty on launch."""
        try:
            cached = device_cache_manager.get_cached_devices()
            if cached:
                self.state.update_devices(cached)
                log_info(f"Loaded {len(cached)} cached devices from previous session")
        except Exception as e:
            log_error(f"Device cache load error: {e}")

    _CACHE_FIELDS = ('ip', 'mac', 'hostname', 'vendor', 'local', 'traffic', 'last_seen')
    _CACHE_DEFAULTS = {'ip': '', 'mac': '', 'hostname': '', 'vendor': '',
                       'local': False, 'traffic': 0, 'last_seen': ''}

    def _save_device_cache(self, devices: list):
        """Persist discovered devices for next launch."""
        try:
            serializable = [
                d if isinstance(d, dict)
                else {k: getattr(d, k, self._CACHE_DEFAULTS[k]) for k in self._CACHE_FIELDS}
                for d in devices if isinstance(d, dict) or hasattr(d, '__dict__')
            ]
            device_cache_manager.update_cache(serializable)
        except Exception as e:
            log_error(f"Device cache save error: {e}")

    # Device Scanning
    def scan_devices(self, quick: bool = True) -> List[Dict]:
        """Scan for devices on the network.

        NOTE: This is called from a background thread in the GUI,
        so we call scan_network() synchronously here — no need for
        the async start()/wait() pattern.
        """
        start_time = time.time()
        try:
            self.state.set_scan_status(True)
            log_info(f"Starting device scan ({'quick' if quick else 'full'})...")

            network_info = device_scan.get_network_info()
            self.state.update_network_info(network_info)

            from app.network.enhanced_scanner import EnhancedNetworkScanner
            scanner = EnhancedNetworkScanner()

            # Call synchronously — we're already in a background thread
            devices = scanner.scan_network(quick_scan=quick)

            real_devices = [d for d in devices if self._is_real_device(d)]
            for d in real_devices:
                log_info(f"Found device: {d['ip']} — {d.get('hostname', 'Unknown')}")

            self.state.update_devices(real_devices)
            self._save_device_cache(real_devices)

            duration = time.time() - start_time
            log_network_scan(len(real_devices), duration)
            self.state.set_scan_status(False)
            return real_devices

        except Exception as e:
            log_error(f"Device scan failed: {e}")
            self.state.set_scan_status(False)
            return []

    @staticmethod
    def _is_real_device(d: dict) -> bool:
        """Filter out loopback, multicast, broadcast, and link-local addresses."""
        ip = d.get('ip')
        if not ip or ip == '127.0.0.1':
            return False
        octets = ip.split('.')
        first, last = int(octets[0]), int(octets[3])
        # Multicast (224+), broadcast (.255), link-local (169.254.x.x)
        return not (first >= 224 or last == 255 or (first == 169 and int(octets[1]) == 254))

    def quick_scan_devices(self) -> List[Dict]:
        return self.scan_devices(quick=True)

    # Device Management
    def select_device(self, ip): self.state.select_device(ip)
    def get_selected_device(self): return self.state.get_selected_device()

    def toggle_lag(self, ip: str = None) -> bool:
        """Toggle blocking for a device via netsh firewall."""
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

    def get_devices(self): return self.state.devices
    def get_blocked_devices(self): return [d for d in self.state.devices if d.blocked]
    def get_device_by_ip(self, ip): return self.state.get_device_by_ip(ip)

    def clear_devices(self):
        self.state.devices = []
        self.state.notify_observers("devices_updated", [])

    # Auto-Scan
    def start_auto_scan(self):
        with self._scan_lock:
            self.auto_scan_enabled = True
            self.stop_scanning = False  # Reset so the loop can run again
            if not self.scan_thread or not self.scan_thread.is_alive():
                self.scan_thread = threading.Thread(target=self._auto_scan_loop, daemon=True)
                self.scan_thread.start()

    def stop_auto_scan(self):
        self.auto_scan_enabled = False
        self.stop_scanning = True

    def _auto_scan_loop(self):
        while self.auto_scan_enabled and not self.stop_scanning:
            try:
                # Skip if a scan is already in progress (e.g. manual scan from GUI)
                if not self.state.scan_in_progress:
                    self.quick_scan_devices()
                time.sleep(30)
            except Exception as e:
                log_error(f"Auto-scan error: {e}")
                time.sleep(60)

    # Network Info
    def get_network_info(self) -> Dict:
        try:
            info = {}
            interfaces = psutil.net_if_addrs()
            active = []
            for name, addrs in interfaces.items():
                for addr in addrs:
                    if addr.family == 2:
                        active.append({"name": name, "ip": addr.address, "netmask": addr.netmask})
            info["interfaces"] = active
            net_io = psutil.net_io_counters()
            info["bytes_sent"] = net_io.bytes_sent
            info["bytes_recv"] = net_io.bytes_recv
            return info
        except Exception as e:
            log_error(f"Get network info failed: {e}")
            return {}

    # Settings
    def update_settings(self, new_settings: AppSettings):
        self.state.settings = new_settings
        self.state.save_settings()

    def update_setting(self, key, value):
        if hasattr(self.state.settings, key):
            setattr(self.state.settings, key, value)
            self.state.save_settings()
    def get_settings(self): return self.state.settings
    def is_scanning(self): return self.state.scan_in_progress
    def is_blocking(self): return len(self.get_blocked_devices()) > 0

    # Plugin System
    def _init_plugins(self):
        """Discover and load all plugins from the plugins directory."""
        try:
            self.plugin_loader.discover()
            self.plugin_loader.load_all(self)
            active = self.plugin_loader.get_active_plugins()
            log_info(f"Plugin system initialized: {len(active)} active plugin(s)")
        except Exception as e:
            log_error(f"Plugin system init error: {e}")

    def get_plugin_info(self): return self.plugin_loader.get_plugin_info()
    def reload_plugins(self):
        self.plugin_loader.unload_all()
        self.plugin_loader.discover()
        self.plugin_loader.load_all(self)

    # Shutdown
    def shutdown(self):
        try:
            log_info("Controller shutting down...")
            self.plugin_loader.unload_all()
            self.stop_auto_scan()
            self.scheduler.stop()
            clumsy_network_disruptor.stop_clumsy()
            save_all_data()
            log_info("Controller shutdown complete")
        except Exception as e:
            log_error(f"Shutdown error: {e}")

