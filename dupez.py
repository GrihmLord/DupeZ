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
# and software rendering BEFORE any PyQt6 import or Qt picks up the
# default flags and the renderer crashes.
#
# NOTE: attempted to re-enable GPU rasterization for map perf
# (--disable-gpu-sandbox --ignore-gpu-blocklist --enable-gpu-rasterization)
# but it hung the splash at "Network scanner loaded" under an admin
# token — the GPU process init blocks the main thread when WebEngine
# tries to start the Chromium GPU process on an elevated token.
# Keeping software raster; map perf is addressed via the debounced
# MutationObserver and optimized AdBlockInterceptor instead.
os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    "--no-sandbox --disable-gpu --disable-gpu-compositing",
)
os.environ.setdefault("QT_OPENGL", "software")

# Ensure the project root is on sys.path so "app.*" imports resolve
_root = os.path.dirname(os.path.abspath(__file__))
if _root not in sys.path:
    sys.path.insert(0, _root)

from app.main import main

if __name__ == "__main__":
    main()
