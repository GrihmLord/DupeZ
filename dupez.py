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

# Kill hi-DPI pixel doubling — on a 1440p/4K monitor with Windows display
# scaling at 125-150%, QtWebEngine renders the iZurvive map at 1.25-1.5×
# the native pixel count. On software raster that's a 1.5-2.25× CPU
# multiplier on an already CPU-bound pipeline, and it's the single
# biggest remaining fluidity win after all the DOM-layer fixes. Force
# 1:1 DPR for the entire app — DupeZ's native Qt widgets look fine at
# 1× because they're drawn from vector assets.
os.environ.setdefault("QT_SCALE_FACTOR", "1")
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "0")

# Ensure the project root is on sys.path so "app.*" imports resolve
_root = os.path.dirname(os.path.abspath(__file__))
if _root not in sys.path:
    sys.path.insert(0, _root)

from app.main import main

if __name__ == "__main__":
    main()
