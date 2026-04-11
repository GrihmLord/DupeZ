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
    """
    if sys.platform != "win32":
        return (False, "non-windows")
    try:
        import ctypes
        from ctypes import wintypes

        # Query DXGI for adapter count via EnumAdapters1. If there's at
        # least one non-software adapter with >= 512 MB dedicated video
        # memory, call it usable.
        try:
            import comtypes  # type: ignore  # noqa: F401
        except Exception:
            # No comtypes — fall back to the CIM_VideoController WMI check,
            # which is slower but widely available. Skip WMI if pywin32 is
            # missing to keep startup fast.
            try:
                import win32com.client  # type: ignore
                wmi = win32com.client.GetObject("winmgmts:")
                adapters = wmi.InstancesOf("Win32_VideoController")
                for a in adapters:
                    try:
                        name = str(a.Name or "").lower()
                        ram = int(getattr(a, "AdapterRAM", 0) or 0)
                    except Exception:
                        continue
                    if "microsoft basic" in name or "standard vga" in name:
                        continue
                    if ram >= 512 * 1024 * 1024:
                        return (True, f"wmi:{name} ram={ram}")
                return (False, "wmi:no-capable-adapter")
            except Exception as e:
                return (False, f"wmi-failed:{e}")

        # comtypes path — but this is heavy. Skip it by default; WMI is
        # enough for a startup heuristic.
        return (False, "dxgi-unimplemented")
    except Exception as e:
        return (False, f"probe-error:{e}")


def resolve_tier() -> Tier:
    """Pick the renderer tier for this launch."""
    override = _user_override()
    if override == "gpu":
        log.info("renderer tier: tier1_hw (forced by DUPEZ_MAP_RENDERER=gpu)")
        return "tier1_hw"
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
