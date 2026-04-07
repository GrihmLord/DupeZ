#!/usr/bin/env python3
"""
CronusZEN/MAX Device Bridge — detect and communicate with Cronus devices.

CronusZEN/MAX devices expose a USB HID interface and a virtual COM port
when connected.  There is no published serial protocol for remote control,
so this module focuses on:

  1. Device detection — find connected Cronus devices by USB VID/PID
  2. Connection status monitoring
  3. Script export path management (Zen Studio import folder)
  4. Future: if a community protocol is discovered, serial command layer

USB identifiers (from community research):
  - CronusZEN:  VID=0x2508, PID varies by firmware
  - CronusMAX:  VID=0x2508, PID varies
  - Generic HID: class 0x03

Dependencies:
  - pyserial>=3.5 (optional, for future serial comms)
  - No hard dependencies — device detection uses OS-level tools
"""

import os
import sys
import threading
import time
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass
from app.logs.logger import log_info, log_error

# Cronus USB Vendor ID (community-identified)
CRONUS_VID = "2508"

# Known device names
CRONUS_DEVICE_NAMES = [
    "cronus zen", "cronus max", "cronuszen", "cronusmax",
    "collective minds", "cm device",
]

@dataclass
class CronusDevice:
    """Represents a detected Cronus device."""
    name: str
    port: Optional[str] = None       # COM port if available
    vid: str = ""
    pid: str = ""
    serial_number: str = ""
    device_type: str = "unknown"     # "zen" or "max"
    connected: bool = False
    firmware_version: str = ""

# Device detection
class DeviceDetector:
    """Detect CronusZEN/MAX devices connected via USB."""

    def __init__(self):
        self._last_scan: List[CronusDevice] = []

    def scan(self) -> List[CronusDevice]:
        """Scan for connected Cronus devices. Returns list of found devices."""
        devices = []

        if sys.platform == "win32":
            devices = self._scan_windows()
        else:
            devices = self._scan_unix()

        self._last_scan = devices
        if devices:
            log_info(f"DeviceDetector: found {len(devices)} Cronus device(s)")
        return devices

    def get_last_scan(self) -> List[CronusDevice]:
        return self._last_scan

    def _scan_pyserial(self) -> List[CronusDevice]:
        """Scan for Cronus devices using pyserial's list_ports (cross-platform)."""
        devices = []
        try:
            from serial.tools import list_ports
            for port in list_ports.comports():
                desc_lower = (port.description or "").lower()
                mfr_lower = (getattr(port, 'manufacturer', None) or "").lower()
                vid = f"{port.vid:04X}" if port.vid else ""
                if (vid == CRONUS_VID
                        or any(n in desc_lower for n in CRONUS_DEVICE_NAMES)
                        or any(n in mfr_lower for n in CRONUS_DEVICE_NAMES)):
                    devices.append(CronusDevice(
                        name=port.description or "Cronus Device",
                        port=port.device, vid=vid,
                        pid=f"{port.pid:04X}" if port.pid else "",
                        serial_number=getattr(port, 'serial_number', '') or "",
                        device_type="zen" if "zen" in desc_lower else "max",
                        connected=True,
                    ))
        except ImportError:
            pass
        return devices

    def _scan_windows(self) -> List[CronusDevice]:
        """Scan for Cronus devices on Windows using pyserial + WMI fallback."""
        devices = self._scan_pyserial()
        if devices:
            return devices

        # WMI fallback via subprocess
        try:
            import subprocess
            result = subprocess.run(
                ["wmic", "path", "Win32_PnPEntity", "where",
                 f"DeviceID like '%VID_{CRONUS_VID}%'",
                 "get", "Name,DeviceID", "/format:csv"],
                capture_output=True, text=True, timeout=10,
                creationflags=0x08000000,
            )
            for line in result.stdout.strip().split('\n'):
                if CRONUS_VID.lower() in line.lower():
                    parts = line.split(',')
                    if len(parts) >= 3:
                        name = parts[-1].strip() or "Cronus Device"
                        devices.append(CronusDevice(
                            name=name, vid=CRONUS_VID, connected=True,
                            device_type="zen" if "zen" in name.lower() else "max",
                        ))
        except Exception as e:
            log_error(f"DeviceDetector: WMI scan failed: {e}")
        return devices

    def _scan_unix(self) -> List[CronusDevice]:
        """Scan for Cronus devices on Linux/Mac."""
        return self._scan_pyserial()

# Device Monitor — background polling for connect/disconnect events
class DeviceMonitor:
    """Monitor for Cronus device connect/disconnect events.

    Runs a background polling thread that detects USB device changes
    and fires callbacks on connect/disconnect events.  Thread-safe.
    """

    def __init__(self, on_connect: Callable[[CronusDevice], None] = None,
                 on_disconnect: Callable[[CronusDevice], None] = None,
                 poll_interval: float = 3.0):
        self._detector = DeviceDetector()
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect
        self._poll_interval = max(1.0, poll_interval)  # floor at 1s
        self._running = False
        self._thread = None
        self._known_devices: Dict[str, CronusDevice] = {}
        self._lock = threading.Lock()
        self._consecutive_errors = 0

    def start(self):
        """Start monitoring in background thread."""
        if self._running:
            return
        self._running = True
        self._consecutive_errors = 0
        self._thread = threading.Thread(target=self._poll_loop, daemon=True,
                                        name="CronusMonitor")
        self._thread.start()
        log_info("DeviceMonitor: started")

    def stop(self):
        """Stop monitoring."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        log_info("DeviceMonitor: stopped")

    def is_running(self) -> bool:
        return self._running

    def get_connected_devices(self) -> List[CronusDevice]:
        with self._lock:
            return list(self._known_devices.values())

    def _poll_loop(self):
        while self._running:
            try:
                current = self._detector.scan()
                current_keys = set()
                connect_events = []
                disconnect_events = []

                # Update state under lock, collect events for dispatch outside lock
                with self._lock:
                    for dev in current:
                        key = dev.port or dev.serial_number or dev.name
                        current_keys.add(key)
                        if key not in self._known_devices:
                            self._known_devices[key] = dev
                            connect_events.append(dev)

                    for key in list(self._known_devices.keys()):
                        if key not in current_keys:
                            dev = self._known_devices.pop(key)
                            dev.connected = False
                            disconnect_events.append(dev)

                # Fire callbacks outside lock to prevent deadlocks
                for dev in connect_events:
                    if self._on_connect:
                        try:
                            self._on_connect(dev)
                        except Exception as e:
                            log_error(f"DeviceMonitor: connect callback error: {e}")
                for dev in disconnect_events:
                    if self._on_disconnect:
                        try:
                            self._on_disconnect(dev)
                        except Exception as e:
                            log_error(f"DeviceMonitor: disconnect callback error: {e}")

                self._consecutive_errors = 0

            except Exception as e:
                self._consecutive_errors += 1
                log_error(f"DeviceMonitor: poll error ({self._consecutive_errors}): {e}")
                # Back off on repeated errors to avoid log spam
                if self._consecutive_errors >= 5:
                    backoff = min(30.0, self._poll_interval * self._consecutive_errors)
                    time.sleep(backoff)
                    continue

            time.sleep(self._poll_interval)

# Zen Studio integration — export path management
def find_zen_studio_library() -> Optional[str]:
    """Find the Zen Studio GPC library folder on the system.

    Zen Studio stores user scripts in:
      Windows: %USERPROFILE%/Documents/Zen Studio/Library/
      or:      %APPDATA%/Zen Studio/Library/
    """
    if sys.platform != "win32":
        return None

    candidates = []

    # Documents folder
    docs = os.path.join(os.path.expanduser("~"), "Documents",
                        "Zen Studio", "Library")
    candidates.append(docs)

    # AppData
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        candidates.append(os.path.join(appdata, "Zen Studio", "Library"))

    # Also check for CronusMAX Plus
    docs_cm = os.path.join(os.path.expanduser("~"), "Documents",
                           "CronusMAX Plus", "Library")
    candidates.append(docs_cm)

    for path in candidates:
        if os.path.isdir(path):
            log_info(f"Found Zen Studio library: {path}")
            return path

    return None

def get_default_export_path() -> str:
    """Get the best path to export .gpc files.
    Prefers Zen Studio library, falls back to user Documents."""
    zen_lib = find_zen_studio_library()
    if zen_lib:
        dupez_dir = os.path.join(zen_lib, "DupeZ")
        os.makedirs(dupez_dir, exist_ok=True)
        return dupez_dir

    # Fallback to Documents/DupeZ/GPC
    docs = os.path.join(os.path.expanduser("~"), "Documents", "DupeZ", "GPC")
    os.makedirs(docs, exist_ok=True)
    return docs

# Public API
def scan_devices() -> List[CronusDevice]:
    """Quick scan for connected Cronus devices."""
    return DeviceDetector().scan()

def is_device_connected() -> bool:
    """Check if any Cronus device is connected."""
    return len(scan_devices()) > 0

