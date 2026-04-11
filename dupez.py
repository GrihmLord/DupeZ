#!/usr/bin/env python3
"""
DupeZ — Single root launcher.
Run this file to start DupeZ.  Works both as a script and as PyInstaller entry.
"""
import sys, os

# ── QtWebEngine bootstrap ──────────────────────────────────────────
# DupeZ runs elevated (required by WinDivert). Chromium's sandbox refuses
# to initialize under an admin token, which causes the render process to
# die silently and the iZurvive map tab shows blank. Force --no-sandbox
# BEFORE any PyQt6 import or Qt picks up the default flags and the
# renderer crashes.
#
# GPU rendering is re-enabled (hardware accel is critical for iZurvive's
# Leaflet tile map — software raster makes pan/zoom unusably laggy).
# Under an admin token the GPU *process* sandbox is what fails, not GPU
# itself; --no-sandbox already disables all sandbox layers, and
# --disable-gpu-sandbox + --ignore-gpu-blocklist forces the GPU process
# to start cleanly. --in-process-gpu is the fallback if the GPU process
# still refuses (runs the GPU on the main thread).
#
# If the map tab goes blank again, revert to:
#   "--no-sandbox --disable-gpu --disable-gpu-compositing"
# and set QT_OPENGL=software.
os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    "--no-sandbox --disable-gpu-sandbox --ignore-gpu-blocklist "
    "--enable-gpu-rasterization --enable-zero-copy",
)

# Ensure the project root is on sys.path so "app.*" imports resolve
_root = os.path.dirname(os.path.abspath(__file__))
if _root not in sys.path:
    sys.path.insert(0, _root)

from app.main import main

if __name__ == "__main__":
    main()
