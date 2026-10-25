"""Platform GPU capability probing without GUI dependencies."""

from __future__ import annotations

import logging
import sys
from typing import Optional, Tuple

from app.core import safe_subprocess

__all__ = ["probe_gpu_usable"]

log = logging.getLogger(__name__)


def probe_gpu_usable() -> Tuple[bool, str]:
    """Return whether a hardware adapter is suitable for Chromium raster."""
    if sys.platform != "win32":
        return (False, "non-windows")

    try:
        result = _probe_dxgi_ctypes()
        if result is not None:
            return result
    except Exception as exc:
        log.debug("DXGI ctypes probe failed: %s", exc)

    try:
        wmic_path = safe_subprocess.resolve_system_binary(
            "wmic",
            subdirectory=("wbem",),
        )
        result = safe_subprocess.run(
            [
                wmic_path,
                "path",
                "win32_videocontroller",
                "get",
                "name,AdapterRAM",
                "/format:csv",
            ],
            timeout=5.0,
            expect_returncode=None,
            intent="gpu_probe.wmic",
        )
        for line in result.stdout.splitlines():
            parts = [part.strip() for part in line.split(",")]
            if len(parts) < 3:
                continue
            name = parts[1].lower()
            if "microsoft basic" in name or "standard vga" in name:
                continue
            try:
                ram = int(parts[2])
            except (ValueError, IndexError):
                ram = 0
            if ram >= 256 * 1024 * 1024:
                return (True, f"wmic:{parts[1]} ram={ram}")
        return (False, "wmic:no-capable-adapter")
    except Exception as exc:
        return (False, f"wmic-failed:{exc}")


def _probe_dxgi_ctypes() -> Optional[Tuple[bool, str]]:
    """Enumerate Windows DXGI adapters using ctypes."""
    import ctypes
    from ctypes import wintypes

    try:
        dxgi = ctypes.windll.dxgi  # type: ignore[attr-defined]
    except (OSError, AttributeError):
        return None

    iid_factory1 = (ctypes.c_ubyte * 16)(
        0x78, 0xAE, 0x0A, 0x77, 0x6F, 0xF2, 0xBA, 0x4D,
        0xA8, 0x29, 0x25, 0x3C, 0x83, 0xD1, 0xB3, 0x87,
    )

    class _Luid(ctypes.Structure):
        _fields_ = [
            ("LowPart", wintypes.DWORD),
            ("HighPart", wintypes.LONG),
        ]

    class _DxgiAdapterDesc1(ctypes.Structure):
        _fields_ = [
            ("Description", wintypes.WCHAR * 128),
            ("VendorId", wintypes.UINT),
            ("DeviceId", wintypes.UINT),
            ("SubSysId", wintypes.UINT),
            ("Revision", wintypes.UINT),
            ("DedicatedVideoMemory", ctypes.c_size_t),
            ("DedicatedSystemMemory", ctypes.c_size_t),
            ("SharedSystemMemory", ctypes.c_size_t),
            ("AdapterLuid", _Luid),
            ("Flags", wintypes.UINT),
        ]
    factory_ptr = ctypes.c_void_p()
    hr = dxgi.CreateDXGIFactory1(
        ctypes.byref(iid_factory1),
        ctypes.byref(factory_ptr),
    )
    if hr != 0 or not factory_ptr.value:
        return None

    vtable = ctypes.cast(
        factory_ptr,
        ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)),
    )[0]
    best_name = ""
    best_ram = 0
    adapter_count = 0

    try:
        while True:
            adapter_ptr = ctypes.c_void_p()
            enum_fn = ctypes.WINFUNCTYPE(
                ctypes.c_long,
                ctypes.c_void_p,
                ctypes.c_uint,
                ctypes.POINTER(ctypes.c_void_p),
            )(vtable[12])
            hr = enum_fn(factory_ptr, adapter_count, ctypes.byref(adapter_ptr))
            if hr != 0 or not adapter_ptr.value:
                break
            adapter_count += 1

            desc = _DxgiAdapterDesc1()
            adapter_vtable = ctypes.cast(
                adapter_ptr,
                ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)),
            )[0]
            try:
                get_desc = ctypes.WINFUNCTYPE(
                    ctypes.c_long,
                    ctypes.c_void_p,
                    ctypes.POINTER(_DxgiAdapterDesc1),
                )(adapter_vtable[10])
                hr_desc = get_desc(adapter_ptr, ctypes.byref(desc))
            finally:
                release_adapter = ctypes.WINFUNCTYPE(
                    ctypes.c_ulong,
                    ctypes.c_void_p,
                )(adapter_vtable[2])
                release_adapter(adapter_ptr)

            if hr_desc != 0:
                continue
            name = str(desc.Description).rstrip("\x00")
            ram = int(desc.DedicatedVideoMemory)
            flags = int(desc.Flags)
            if flags & 2:
                continue
            lowered = name.lower()
            if "microsoft basic" in lowered or "standard vga" in lowered:
                continue
            if ram > best_ram:
                best_ram = ram
                best_name = name
    finally:
        release_factory = ctypes.WINFUNCTYPE(
            ctypes.c_ulong,
            ctypes.c_void_p,
        )(vtable[2])
        release_factory(factory_ptr)

    if best_ram >= 256 * 1024 * 1024:
        return (True, f"dxgi:{best_name} vram={best_ram}")
    if adapter_count == 0:
        return None
    return (
        False,
        f"dxgi:no-capable-adapter (best={best_name} vram={best_ram})",
    )
