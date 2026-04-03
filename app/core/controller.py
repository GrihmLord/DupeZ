# app/core/controller.py — DupeZ Controller (Stripped)

import socket
import threading
import time
import psutil
from typing import List, Dict, Optional
from app.network import device_scan
from app.firewall import blocker
from app.firewall.clumsy_network_disruptor import clumsy_network_disruptor
from app.logs.logger import log_info, log_error, log_performance, log_network_scan, log_blocking_event
from app.core.state import AppState, Device, AppSettings
from app.core.data_persistence import persistence_manager, settings_manager, device_manager, account_manager, marker_manager, save_all_data


class AppController:
    def __init__(self):
        self.state = AppState()
        self.scan_thread = None
        self.stop_scanning = False
        self.auto_scan_enabled = True

        # Initialize clumsy
        self._init_clumsy()

        # Start auto-scan if enabled
        if self.state.settings.auto_scan:
            self.start_auto_scan()

    # ------------------------------------------------------------------
    # Clumsy Integration
    # ------------------------------------------------------------------
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

    def disrupt_device(self, ip: str, methods: List[str] = None, params: Dict = None) -> bool:
        """Start clumsy disruption on a device"""
        return clumsy_network_disruptor.disconnect_device_clumsy(ip, methods, params)

    def stop_disruption(self, ip: str) -> bool:
        """Stop clumsy disruption on a device"""
        return clumsy_network_disruptor.reconnect_device_clumsy(ip)

    def stop_all_disruptions(self) -> bool:
        """Clear all active disruptions"""
        return clumsy_network_disruptor.clear_all_disruptions_clumsy()

    def get_disrupted_devices(self) -> List[str]:
        """Get list of currently disrupted IPs"""
        return clumsy_network_disruptor.get_disrupted_devices_clumsy()

    def get_disruption_status(self, ip: str) -> Dict:
        """Get disruption status for a specific device"""
        return clumsy_network_disruptor.get_device_status_clumsy(ip)

    def get_clumsy_status(self) -> Dict:
        """Get overall clumsy disruptor status"""
        return clumsy_network_disruptor.get_clumsy_status()

    # ------------------------------------------------------------------
    # Device Scanning
    # ------------------------------------------------------------------
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

            real_devices = []
            for d in devices:
                ip = d.get('ip')
                if not ip or ip == '127.0.0.1':
                    continue
                octets = ip.split('.')
                first_octet = int(octets[0])
                last_octet = int(octets[3])
                # Filter out multicast (224+), broadcast (.255), link-local (169.254.x.x)
                if first_octet >= 224:
                    continue
                if last_octet == 255:
                    continue
                if first_octet == 169 and int(octets[1]) == 254:
                    continue
                real_devices.append(d)
                log_info(f"Found device: {ip} — {d.get('hostname', 'Unknown')}")

            self.state.update_devices(real_devices)

            duration = time.time() - start_time
            log_network_scan(len(real_devices), duration)
            self.state.set_scan_status(False)
            return real_devices

        except Exception as e:
            log_error(f"Device scan failed: {e}")
            self.state.set_scan_status(False)
            return []

    def _on_scan_complete(self, devices: list):
        try:
            device_objects = []
            for d in devices:
                try:
                    device_objects.append(Device(
                        ip=d.get('ip', ''),
                        mac=d.get('mac', ''),
                        hostname=d.get('hostname', ''),
                        vendor=d.get('vendor', ''),
                        local=d.get('local', False),
                        traffic=d.get('traffic', 0),
                        last_seen=d.get('last_seen', ''),
                        blocked=d.get('blocked', False)
                    ))
                except Exception as e:
                    log_error(f"Error converting device: {e}")
            self.state.devices = device_objects
            self.state.notify_observers("devices_updated", device_objects)
        except Exception as e:
            log_error(f"Scan complete handler error: {e}")

    def _on_scan_error(self, error_msg: str):
        log_error(f"Scan error: {error_msg}")

    def _on_scan_status(self, status_msg: str):
        log_info(f"Scan status: {status_msg}")

    def _verify_device_exists(self, ip: str) -> bool:
        try:
            for port in [80, 443, 22, 53, 8080]:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(1.0)
                    result = sock.connect_ex((ip, port))
                    sock.close()
                    if result == 0:
                        return True
                except:
                    continue
            return False
        except:
            return False

    def quick_scan_devices(self) -> List[Dict]:
        return self.scan_devices(quick=True)

    def full_scan_devices(self) -> List[Dict]:
        return self.scan_devices(quick=False)

    # ------------------------------------------------------------------
    # Device Management
    # ------------------------------------------------------------------
    def select_device(self, ip: str):
        self.state.select_device(ip)

    def get_selected_device(self) -> Optional[Device]:
        return self.state.get_selected_device()

    def toggle_lag(self, ip: str = None) -> bool:
        """Toggle blocking for a device via netsh firewall.

        If no IP is provided, falls back to the currently selected device.
        """
        try:
            if not ip:
                ip = self.state.selected_ip
            if not ip:
                return False
            device = self.state.get_device_by_ip(ip)
            if device:
                if device.blocked:
                    success = blocker.unblock_device(ip)
                    if success:
                        device.blocked = False
                else:
                    success = blocker.block_device(ip)
                    if success:
                        device.blocked = True
                return device.blocked
            else:
                success = blocker.block_device(ip)
                return success
        except Exception as e:
            log_error(f"Toggle lag failed: {e}")
            return False

    def get_devices(self) -> List[Device]:
        return self.state.devices

    def get_blocked_devices(self) -> List[Device]:
        return [d for d in self.state.devices if d.blocked]

    def get_device_by_ip(self, ip: str) -> Optional[Device]:
        return self.state.get_device_by_ip(ip)

    def clear_devices(self):
        self.state.devices = []
        self.state.notify_observers("devices_updated", [])

    # ------------------------------------------------------------------
    # Auto-Scan
    # ------------------------------------------------------------------
    def start_auto_scan(self):
        self.auto_scan_enabled = True
        if not self.scan_thread or not self.scan_thread.is_alive():
            self.scan_thread = threading.Thread(target=self._auto_scan_loop, daemon=True)
            self.scan_thread.start()

    def stop_auto_scan(self):
        self.auto_scan_enabled = False
        self.stop_scanning = True

    def _auto_scan_loop(self):
        while self.auto_scan_enabled and not self.stop_scanning:
            try:
                self.quick_scan_devices()
                time.sleep(30)
            except Exception as e:
                log_error(f"Auto-scan error: {e}")
                time.sleep(60)

    # ------------------------------------------------------------------
    # Network Info
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------
    def update_settings(self, new_settings: AppSettings):
        self.state.settings = new_settings
        self.state.save_settings()

    def update_setting(self, key: str, value):
        if hasattr(self.state.settings, key):
            setattr(self.state.settings, key, value)
            self.state.save_settings()

    def get_settings(self):
        return self.state.settings

    def is_scanning(self) -> bool:
        return self.state.scan_in_progress

    def is_blocking(self) -> bool:
        return len(self.get_blocked_devices()) > 0

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------
    def shutdown(self):
        try:
            log_info("Controller shutting down...")
            self.stop_auto_scan()
            clumsy_network_disruptor.stop_clumsy()
            save_all_data()
            log_info("Controller shutdown complete")
        except Exception as e:
            log_error(f"Shutdown error: {e}")

