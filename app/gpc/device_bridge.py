#!/usr/bin/env python3
"""
Game-Script Device Bridge — detect Cronus, Titan, and other GPC-compatible
controller-script devices.

v5.6.7 generalization: this module originally targeted CronusZEN/MAX only.
Titan One/Two from ConsoleTuner uses the same GPC scripting language (a
Cronus-derived dialect compiled in Gtuner IV), so the same generated .gpc
file can be dropped into their script library and run identically. The
detection layer is now VID-list-based and the export-path lookup
considers Cronus's Zen Studio library, Cronus's CronusMAX Plus library,
and Titan's Gtuner library in turn.

Supported devices (v5.6.7):

  CronusZEN     VID=0x2508, ConsoleTuner-derived firmware,  IDE = Zen Studio
  CronusMAX     VID=0x2508, original Collective Minds line,  IDE = Zen Studio / CronusMAX Plus
  Titan One     VID=0x2508 (pre-firmware shared) / 0x2F0A, IDE = Gtuner II / Gtuner IV
  Titan Two     VID=0x2508 (pre-firmware shared) / 0x2F0A, IDE = Gtuner IV

Note: Cronus and Titan both historically used VID 0x2508 because Titan
One predates the Console Tuner brand split. Modern Titan firmware ships
with its own VID. We accept both VIDs and disambiguate via the USB
description string.

Detection methods:

  1. pyserial list_ports — cross-platform, picks up VID/PID/description
  2. Windows WMI fallback via wmic — when pyserial is unavailable

Dependencies:
  - pyserial>=3.5 (optional, for VID/PID enumeration)
  - No hard dependencies — falls back to wmic on Windows

Future:
  - If a community serial protocol surfaces for either ecosystem,
    drop it in alongside :class:`DeviceDetector`.
"""

from __future__ import annotations

import os
import re
import sys
import threading
import time
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass
from app.logs.logger import log_info, log_error
from app.utils.helpers import _NO_WINDOW

__all__ = [
    "CRONUS_VID",
    "CRONUS_DEVICE_NAMES",
    "TITAN_VID",
    "TITAN_DEVICE_NAMES",
    "SUPPORTED_VIDS",
    "CronusDevice",
    "ScriptDevice",
    "DeviceDetector",
    "DeviceMonitor",
    "find_zen_studio_library",
    "find_gtuner_library",
    "find_cronusmax_library",
    "get_default_export_path",
    "scan_devices",
    "is_device_connected",
]

# ── USB vendor identifiers ─────────────────────────────────────────────
# Cronus (community-identified). Historically Titan One shared this VID
# because ConsoleTuner was the original firmware vendor for both lines.
CRONUS_VID = "2508"

# Titan VID after the Console Tuner brand split. Newer Titan firmware
# enumerates with this VID instead of the legacy 2508.
TITAN_VID = "2F0A"

#: Every VID we'll accept as a "GPC-compatible script device." Detection
#: scans for any of these; disambiguation between brands happens via the
#: USB description string.
SUPPORTED_VIDS = (CRONUS_VID, TITAN_VID)

# ── Known USB description substrings ───────────────────────────────────
CRONUS_DEVICE_NAMES = [
    "cronus zen", "cronus max", "cronuszen", "cronusmax",
    "collective minds", "cm device",
]

TITAN_DEVICE_NAMES = [
    "titan one", "titan two", "titanone", "titantwo", "t1", "t2",
    "consoletuner", "console tuner", "gtuner",
]

# ── Device data class ──────────────────────────────────────────────────
@dataclass
class ScriptDevice:
    """Represents a detected GPC-compatible script device.

    ``device_type`` is one of: ``"zen"``, ``"max"``, ``"titan1"``,
    ``"titan2"``, ``"cronus_other"``, ``"titan_other"``, ``"unknown"``.
    Callers should treat it as an informational tag — the script
    language (.gpc) and export workflow are identical across all of
    these, only the IDE / library path differs.
    """
    name: str
    port: Optional[str] = None       # COM port if available
    vid: str = ""
    pid: str = ""
    serial_number: str = ""
    device_type: str = "unknown"
    connected: bool = False
    firmware_version: str = ""


# v5.6.7: keep ``CronusDevice`` as a backward-compat alias so callers
# from the pre-Titan era continue to work without import changes.
CronusDevice = ScriptDevice


def _classify_device(desc: str, vid: str) -> str:
    """Return a ``device_type`` tag from USB description + VID.

    Description-first because Cronus and Titan One share VID 0x2508
    historically. Falls back to VID-only classification when the
    description is empty or unhelpful.
    """
    d = (desc or "").lower()
    if "titan two" in d or "titantwo" in d or " t2" in d:
        return "titan2"
    if "titan one" in d or "titanone" in d or " t1" in d:
        return "titan1"
    if "gtuner" in d or "consoletuner" in d or "console tuner" in d:
        # Generic Titan brand match when the model name isn't in the
        # description string.
        return "titan_other"
    if "zen" in d:
        return "zen"
    if "max" in d or "cronusmax" in d or "collective minds" in d:
        return "max"
    # VID-only fallback
    if vid.upper() == TITAN_VID:
        return "titan_other"
    if vid.upper() == CRONUS_VID:
        return "cronus_other"
    return "unknown"

# Device detection
class DeviceDetector:
    """Detect CronusZEN/MAX devices connected via USB."""

    def __init__(self) -> None:
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

    def _scan_pyserial(self) -> List[ScriptDevice]:
        """Scan for Cronus/Titan devices using pyserial's list_ports (cross-platform)."""
        devices = []
        all_names = CRONUS_DEVICE_NAMES + TITAN_DEVICE_NAMES
        try:
            from serial.tools import list_ports
            for port in list_ports.comports():
                desc_lower = (port.description or "").lower()
                mfr_lower = (getattr(port, 'manufacturer', None) or "").lower()
                vid = f"{port.vid:04X}" if port.vid else ""
                if (vid in SUPPORTED_VIDS
                        or any(n in desc_lower for n in all_names)
                        or any(n in mfr_lower for n in all_names)):
                    dtype = _classify_device(port.description or "", vid)
                    devices.append(ScriptDevice(
                        name=port.description or "GPC Script Device",
                        port=port.device, vid=vid,
                        pid=f"{port.pid:04X}" if port.pid else "",
                        serial_number=getattr(port, 'serial_number', '') or "",
                        device_type=dtype,
                        connected=True,
                    ))
        except ImportError:
            pass
        return devices

    def _scan_windows(self) -> List[ScriptDevice]:
        """Scan for Cronus/Titan devices on Windows: pyserial + WMI fallback."""
        devices = self._scan_pyserial()
        if devices:
            return devices

        # WMI fallback via subprocess — query for any of our supported VIDs.
        # We iterate VIDs rather than building a compound WHERE clause to
        # keep each wmic invocation simple and the resulting argv hard to
        # mis-parse if someone changes the VID constants downstream.
        try:
            import os as _os
            from app.core import safe_subprocess as _safe_sp
            sysroot = _os.environ.get("SystemRoot") or r"C:\Windows"
            wmic_path = _os.path.join(sysroot, "System32", "wbem", "wmic.exe")
            if not _os.path.isfile(wmic_path):
                return devices

            for vid in SUPPORTED_VIDS:
                # Defense in depth — argv whitelist would catch this
                # already, but guarding here makes the intent explicit.
                if not re.fullmatch(r"[0-9a-fA-F]{4}", vid):
                    log_error(f"DeviceDetector: rejecting non-hex VID {vid!r}")
                    continue
                result = _safe_sp.run(
                    [wmic_path, "path", "Win32_PnPEntity", "where",
                     f"DeviceID like '%VID_{vid}%'",
                     "get", "Name,DeviceID", "/format:csv"],
                    timeout=10.0,
                    expect_returncode=None,
                    intent="gpc.wmic_enumerate_script_device",
                )
                for line in result.stdout.strip().split('\n'):
                    if vid.lower() in line.lower():
                        parts = line.split(',')
                        if len(parts) >= 3:
                            name = parts[-1].strip() or "GPC Script Device"
                            devices.append(ScriptDevice(
                                name=name, vid=vid, connected=True,
                                device_type=_classify_device(name, vid),
                            ))
        except Exception as e:
            # Only log once — wmic is missing on many Windows installs.
            if not getattr(self, '_wmi_warned', False):
                log_error(f"DeviceDetector: WMI scan failed (suppressing repeats): {e}")
                self._wmi_warned = True
        return devices

    def _scan_unix(self) -> List[ScriptDevice]:
        """Scan for Cronus/Titan devices on Linux/Mac."""
        return self._scan_pyserial()

# Device Monitor — background polling for connect/disconnect events
class DeviceMonitor:
    """Monitor for Cronus device connect/disconnect events.

    Runs a background polling thread that detects USB device changes
    and fires callbacks on connect/disconnect events.  Thread-safe.
    """

    def __init__(self, on_connect: Callable[[CronusDevice], None] = None,
                 on_disconnect: Callable[[CronusDevice], None] = None,
                 poll_interval: float = 3.0) -> None:
        self._detector = DeviceDetector()
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect
        self._poll_interval = max(1.0, poll_interval)  # floor at 1s
        self._running = False
        self._thread = None
        self._known_devices: Dict[str, CronusDevice] = {}
        self._lock = threading.Lock()
        self._consecutive_errors = 0

    def start(self) -> None:
        """Start monitoring in background thread."""
        if self._running:
            return
        self._running = True
        self._consecutive_errors = 0
        self._thread = threading.Thread(target=self._poll_loop, daemon=True,
                                        name="CronusMonitor")
        self._thread.start()
        log_info("DeviceMonitor: started")

    def stop(self) -> None:
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

    def _poll_loop(self) -> None:
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

# ── IDE library discovery ─────────────────────────────────────────────
def _first_existing_dir(*candidates: str) -> Optional[str]:
    """Return the first path in *candidates* that exists as a directory."""
    for path in candidates:
        if path and os.path.isdir(path):
            return path
    return None


def find_zen_studio_library() -> Optional[str]:
    """Find the Zen Studio GPC library folder on the system.

    Zen Studio (the CronusZEN IDE) stores user scripts in:
      Windows: %USERPROFILE%/Documents/Zen Studio/Library/
      or:      %APPDATA%/Zen Studio/Library/
    """
    if sys.platform != "win32":
        return None
    home = os.path.expanduser("~")
    appdata = os.environ.get("APPDATA", "")
    found = _first_existing_dir(
        os.path.join(home, "Documents", "Zen Studio", "Library"),
        os.path.join(appdata, "Zen Studio", "Library") if appdata else "",
    )
    if found:
        log_info(f"Found Zen Studio library: {found}")
    return found


def find_cronusmax_library() -> Optional[str]:
    """Find the CronusMAX Plus IDE library folder (legacy MAX line)."""
    if sys.platform != "win32":
        return None
    home = os.path.expanduser("~")
    found = _first_existing_dir(
        os.path.join(home, "Documents", "CronusMAX Plus", "Library"),
    )
    if found:
        log_info(f"Found CronusMAX Plus library: {found}")
    return found


def find_gtuner_library() -> Optional[str]:
    """Find the Gtuner script library folder (Titan One / Titan Two IDE).

    Gtuner IV (current) and Gtuner II (legacy) both keep user scripts in
    a per-version library directory under Documents. We check both since
    operators on older Titan One setups may still be on Gtuner II.

    Typical locations on Windows:
      %USERPROFILE%/Documents/Gtuner IV/Scripts/
      %USERPROFILE%/Documents/Gtuner/Scripts/      (legacy Gtuner II)
      %USERPROFILE%/Documents/ConsoleTuner/Gtuner IV/Scripts/
    """
    if sys.platform != "win32":
        return None
    home = os.path.expanduser("~")
    found = _first_existing_dir(
        os.path.join(home, "Documents", "Gtuner IV", "Scripts"),
        os.path.join(home, "Documents", "Gtuner", "Scripts"),
        os.path.join(home, "Documents", "ConsoleTuner", "Gtuner IV", "Scripts"),
    )
    if found:
        log_info(f"Found Gtuner library: {found}")
    return found


def get_default_export_path(device_type: str = "") -> str:
    """Return the best directory to drop a generated .gpc file.

    Strategy:
      1. If *device_type* identifies a Titan device, prefer Gtuner's
         script folder (so the script appears in the Titan IDE on next
         refresh, ready to compile + push).
      2. If it identifies a CronusMAX, prefer the CronusMAX Plus library.
      3. For Cronus Zen or anything generic, prefer Zen Studio's library.
      4. Otherwise (no library found, or no specific device detected),
         fall back to Documents/DupeZ/GPC — operator imports manually.

    Either way, we create a per-tool ``DupeZ`` subfolder under the
    matched library so generated scripts don't pollute the user's own.
    Backward-compatible: callers that don't pass *device_type* (the
    pre-v5.6.7 signature) get the Zen-first behavior they had before.
    """
    dtype = (device_type or "").lower()

    if dtype in ("titan1", "titan2", "titan_other"):
        preferred = find_gtuner_library()
    elif dtype == "max":
        preferred = find_cronusmax_library() or find_zen_studio_library()
    else:
        # Zen, cronus_other, unknown, "" → Zen Studio first, then Gtuner
        # as a secondary on systems where only Titan IDE is installed.
        preferred = (
            find_zen_studio_library()
            or find_cronusmax_library()
            or find_gtuner_library()
        )

    if preferred:
        dupez_dir = os.path.join(preferred, "DupeZ")
        os.makedirs(dupez_dir, exist_ok=True)
        return dupez_dir

    # Final fallback: Documents/DupeZ/GPC — operator imports manually
    # from there into whichever IDE they actually use.
    docs = os.path.join(os.path.expanduser("~"), "Documents", "DupeZ", "GPC")
    os.makedirs(docs, exist_ok=True)
    return docs


# ── Public API ─────────────────────────────────────────────────────────
def scan_devices() -> List[ScriptDevice]:
    """Quick scan for connected Cronus/Titan script devices."""
    return DeviceDetector().scan()


def is_device_connected() -> bool:
    """Check if any supported script device is connected."""
    return len(scan_devices()) > 0

