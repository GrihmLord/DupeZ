#!/usr/bin/env python
# app/gui/map_host/renderer_tier.py
"""
QtWebEngine / Chromium renderer tier detection and flag resolution.

Decides which Chromium flags to set for the embedded iZurvive map based
on:

    1. The `DUPEZ_MAP_RENDERER` env var override (auto | gpu | software)
    2. The active architecture — under DUPEZ_ARCH=inproc the GUI still
       runs elevated and Chromium GPU init deadlocks, so force software.
    3. A best-effort hardware probe (Windows DXGI adapter LUID presence,
       GPU driver blocklist heuristics) to pick between hardware raster
       and SwiftShader.

Tier definitions (ADR-0001 §4.7):

    Tier 1 — Modern dGPU / recent iGPU, split arch → full hardware raster
             + GPU compositing. `--ignore-gpu-blocklist --enable-gpu-rasterization
             --enable-zero-copy --enable-features=Vulkan`.

    Tier 2 — Mid-tier or older iGPU, split arch → SwiftShader software GL.
             `--use-gl=swiftshader --enable-gpu-rasterization`. Keeps
             GPU compositing off to avoid buggy driver paths.

    Tier 3 — Any of: inproc mode (elevated), user forced software, or
             no usable GPU detected → pure CPU raster with no GPU
             processes. `--disable-gpu --disable-gpu-compositing
             --disable-software-rasterizer=false`. This is bit-for-bit
             the behavior we shipped before ADR-0001.

CRITICAL: this module must be imported and evaluated BEFORE any PyQt6
import, because QtWebEngine reads `QTWEBENGINE_CHROMIUM_FLAGS` exactly
once at Qt boot.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Literal, Tuple

log = logging.getLogger(__name__)

Tier = Literal["tier1_hw", "tier2_swiftshader", "tier3_cpu"]

TIER_FLAGS: dict[str, str] = {
    # tier1_hw uses ANGLE → D3D11 instead of native desktop OpenGL.
    # Chrome itself uses ANGLE on Windows by default: desktop GL on
    # Windows is a minefield because NV/AMD/Intel each report OpenGL
    # version strings in slightly different formats and Qt's parser
    # bails with "Unrecognized OpenGL version" on several of them.
    # ANGLE sidesteps the whole problem by translating GL → D3D11,
    # so we get hardware raster without touching driver OpenGL at all.
    # Vulkan is deliberately NOT enabled — it's still experimental in
    # Chromium on Windows and tends to regress on older drivers.
    "tier1_hw": (
        "--no-sandbox "
        "--ignore-gpu-blocklist "
        "--enable-gpu-rasterization "
        "--enable-zero-copy "
        "--use-gl=angle "
        "--use-angle=d3d11 "
        "--enable-features=CanvasOopRasterization"
    ),
    "tier2_swiftshader": (
        "--no-sandbox "
        "--use-gl=swiftshader "
        "--enable-gpu-rasterization "
        "--disable-features=Vulkan"
    ),
    "tier3_cpu": (
        "--no-sandbox "
        "--disable-gpu "
        "--disable-gpu-compositing"
    ),
}


def _is_split_mode() -> bool:
    arch = (os.environ.get("DUPEZ_ARCH") or "inproc").strip().lower()
    return arch == "split"


def _user_override() -> str:
    return (os.environ.get("DUPEZ_MAP_RENDERER") or "auto").strip().lower()


def _is_admin_token() -> bool:
    """Best-effort: return True if this process holds an admin token."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _probe_gpu_usable() -> Tuple[bool, str]:
    """Heuristic: does this machine have a GPU we'd trust for Chromium raster?

    Returns (usable, reason). We're deliberately conservative — a false
    negative just drops us to software raster, which is the same as the
    pre-ADR-0001 baseline. A false positive would mean SwiftShader or
    hardware raster on a blocklisted driver, which Chromium itself will
    then fall back from — so the cost of a wrong guess is bounded.

    Probe chain (stops at first conclusive answer):
      1. Pure-ctypes DXGI factory — fastest, no third-party deps.
      2. ``wmic`` subprocess — slower (~500ms) but universally available
         on Windows 10/11 (wmic deprecated but still ships).
      3. Give up → (False, reason).
    """
    if sys.platform != "win32":
        return (False, "non-windows")

    # ── Probe 1: Pure-ctypes DXGI ──────────────────────────────────
    # CreateDXGIFactory1 → EnumAdapters1 → GetDesc1.
    # Works without comtypes, win32com, or any third-party package.
    try:
        result = _probe_dxgi_ctypes()
        if result is not None:
            return result
    except Exception as e:
        log.debug("DXGI ctypes probe failed: %s", e)

    # ── Probe 2: wmic subprocess ───────────────────────────────────
    try:
        import subprocess
        out = subprocess.check_output(
            ["wmic", "path", "win32_videocontroller", "get",
             "name,AdapterRAM", "/format:csv"],
            timeout=5, stderr=subprocess.DEVNULL, text=True,
        )
        for line in out.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 3:
                continue
            name = parts[1].lower()
            if "microsoft basic" in name or "standard vga" in name:
                continue
            try:
                ram = int(parts[2])
            except (ValueError, IndexError):
                ram = 0
            if ram >= 256 * 1024 * 1024:  # 256 MB minimum
                return (True, f"wmic:{parts[1]} ram={ram}")
        return (False, "wmic:no-capable-adapter")
    except Exception as e:
        return (False, f"wmic-failed:{e}")


def _probe_dxgi_ctypes() -> "Tuple[bool, str] | None":
    """Pure-ctypes DXGI adapter enumeration.

    Returns ``(usable, reason)`` if we got a conclusive answer,
    or ``None`` if the probe couldn't run (missing DLL, etc.)
    so the caller should try the next strategy.
    """
    import ctypes
    import ctypes.wintypes as wt

    try:
        dxgi = ctypes.windll.dxgi  # type: ignore[attr-defined]
    except (OSError, AttributeError):
        return None

    # IID_IDXGIFactory1 = {770aae78-f26f-4dba-a829-253c83d1b387}
    IID_IDXGIFactory1 = (ctypes.c_byte * 16)(
        0x78, 0xAE, 0x0A, 0x77, 0x6F, 0xF2, 0xBA, 0x4D,
        0xA8, 0x29, 0x25, 0x3C, 0x83, 0xD1, 0xB3, 0x87,
    )

    factory_ptr = ctypes.c_void_p()
    hr = dxgi.CreateDXGIFactory1(
        ctypes.byref(IID_IDXGIFactory1),
        ctypes.byref(factory_ptr),
    )
    if hr != 0 or not factory_ptr.value:
        return None

    # IDXGIFactory1::EnumAdapters1 is vtable index 12.
    # IDXGIAdapter1::GetDesc1 is vtable index 10.
    # IDXGIAdapter1::Release is vtable index 2.
    # IDXGIFactory1::Release is vtable index 2.
    vtable = ctypes.cast(
        factory_ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
    )[0]

    # DXGI_ADAPTER_DESC1 layout (partial — we only need Description and
    # DedicatedVideoMemory):
    #   WCHAR Description[128]   offset 0    (256 bytes)
    #   UINT  VendorId           offset 256  (4 bytes)
    #   UINT  DeviceId           offset 260  (4 bytes)
    #   UINT  SubSysId           offset 264  (4 bytes)
    #   UINT  Revision           offset 268  (4 bytes)
    #   SIZE_T DedicatedVideoMemory   offset 272 (8 bytes on x64)
    #   SIZE_T DedicatedSystemMemory  offset 280
    #   SIZE_T SharedSystemMemory     offset 288
    #   LUID   AdapterLuid           offset 296
    #   UINT   Flags                 offset 304
    # Total: ~308 bytes. Allocate 320 for safety.
    DESC1_SIZE = 320

    best_name = ""
    best_ram = 0
    idx = 0

    while True:
        adapter_ptr = ctypes.c_void_p()
        # Call EnumAdapters1(factory, idx, &adapter)
        enum_fn = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p, ctypes.c_uint,
            ctypes.POINTER(ctypes.c_void_p),
        )(vtable[12])
        hr = enum_fn(factory_ptr, idx, ctypes.byref(adapter_ptr))
        if hr != 0 or not adapter_ptr.value:
            break
        idx += 1

        # GetDesc1
        desc_buf = (ctypes.c_byte * DESC1_SIZE)()
        adapter_vtable = ctypes.cast(
            adapter_ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
        )[0]
        get_desc1 = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_byte * DESC1_SIZE),
        )(adapter_vtable[10])
        hr_desc = get_desc1(adapter_ptr, ctypes.byref(desc_buf))

        # Release adapter
        release_fn = ctypes.WINFUNCTYPE(
            ctypes.c_ulong, ctypes.c_void_p
        )(adapter_vtable[2])
        release_fn(adapter_ptr)

        if hr_desc != 0:
            continue

        # Parse Description (WCHAR[128] at offset 0)
        raw_name = bytes(desc_buf[:256])
        try:
            name = raw_name.decode("utf-16-le").rstrip("\x00")
        except Exception:
            name = ""

        # Parse DedicatedVideoMemory (SIZE_T at offset 272)
        ram_bytes = bytes(desc_buf[272:280])
        ram = int.from_bytes(ram_bytes, byteorder="little", signed=False)

        # Parse Flags (UINT at offset 304)
        flags_bytes = bytes(desc_buf[304:308])
        flags = int.from_bytes(flags_bytes, byteorder="little", signed=False)
        DXGI_ADAPTER_FLAG_SOFTWARE = 2
        if flags & DXGI_ADAPTER_FLAG_SOFTWARE:
            continue  # Skip Microsoft Basic Render Driver / WARP

        name_lower = name.lower()
        if "microsoft basic" in name_lower or "standard vga" in name_lower:
            continue

        if ram > best_ram:
            best_ram = ram
            best_name = name

    # Release factory
    factory_vtable = vtable
    release_factory = ctypes.WINFUNCTYPE(
        ctypes.c_ulong, ctypes.c_void_p
    )(factory_vtable[2])
    release_factory(factory_ptr)

    if best_ram >= 256 * 1024 * 1024:  # 256 MB dedicated VRAM
        return (True, f"dxgi:{best_name} vram={best_ram}")
    if idx == 0:
        return None  # DXGI worked but no adapters — unusual, let next probe try
    return (False, f"dxgi:no-capable-adapter (best={best_name} vram={best_ram})")


def resolve_tier() -> Tier:
    """Pick the renderer tier for this launch."""
    override = _user_override()
    if override == "gpu":
        log.info("renderer tier: tier1_hw (forced by DUPEZ_MAP_RENDERER=gpu)")
        return "tier1_hw"
    if override == "swiftshader":
        log.info("renderer tier: tier2_swiftshader (forced by DUPEZ_MAP_RENDERER=swiftshader)")
        return "tier2_swiftshader"
    if override == "software":
        log.info("renderer tier: tier3_cpu (forced by DUPEZ_MAP_RENDERER=software)")
        return "tier3_cpu"

    # Auto mode.
    if not _is_split_mode():
        # Legacy elevated GUI — Chromium GPU init deadlocks. Shipped baseline.
        log.info("renderer tier: tier3_cpu (inproc mode forces software)")
        return "tier3_cpu"

    if _is_admin_token():
        # Belt-and-suspenders: even under split arch, if the GUI is somehow
        # still elevated (user ran the launcher elevated, or UAC broken),
        # fall back to CPU raster to avoid the deadlock.
        log.warning("renderer tier: tier3_cpu (split arch but GUI has admin token)")
        return "tier3_cpu"

    usable, reason = _probe_gpu_usable()
    if usable:
        log.info("renderer tier: tier1_hw (%s)", reason)
        return "tier1_hw"

    log.info("renderer tier: tier2_swiftshader (%s)", reason)
    return "tier2_swiftshader"


def apply_chromium_flags() -> Tier:
    """Set QTWEBENGINE_CHROMIUM_FLAGS + QT_OPENGL for the resolved tier.

    Call this BEFORE importing any PyQt6 module. Returns the tier so the
    caller can surface a one-time compatibility-mode toast in the GUI.
    """
    tier = resolve_tier()
    flags = TIER_FLAGS[tier]

    # Respect an existing override only if the user set it explicitly.
    # (`os.environ.setdefault` would not overwrite, which is what we want
    # for operator-provided overrides.)
    if "QTWEBENGINE_CHROMIUM_FLAGS" not in os.environ:
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = flags
        log.info("QTWEBENGINE_CHROMIUM_FLAGS=%s", flags)
    else:
        log.info("QTWEBENGINE_CHROMIUM_FLAGS already set, not overriding")

    # QT_OPENGL must be one of {"desktop", "software"} in Qt 6 — ANGLE was
    # removed as a Qt-side option in 6.0. Force "software" for ALL tiers:
    #
    #   * DupeZ's native Qt widgets don't use OpenGL for anything
    #     visually important (no QOpenGLWidget in the app), so software
    #     rendering of them is free.
    #   * It sidesteps Qt's "Unrecognized OpenGL version" parser crash
    #     seen on Grihm's NVIDIA driver under QT_OPENGL=desktop.
    #   * The heavy lifting — Chromium rendering the iZurvive tiles —
    #     is controlled by QTWEBENGINE_CHROMIUM_FLAGS above, which for
    #     tier1_hw uses "--use-gl=angle --use-angle=d3d11". Chromium
    #     bundles its own ANGLE → D3D11 GPU stack independently of
    #     whatever Qt picks for its widget surfaces, so we still get
    #     hardware D3D11 raster for the map while keeping Qt safe.
    os.environ.setdefault("QT_OPENGL", "software")

    # Make the tier visible to the rest of the app so the map widget can
    # display a one-time toast ("running in compatibility mode") without
    # re-running the probe.
    os.environ["DUPEZ_MAP_RENDERER_TIER"] = tier
    return tier
