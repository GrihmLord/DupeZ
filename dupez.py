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
# Chromium GPU init deadlocks under an admin token. Confirmed twice:
#  * Attempt #1: --no-sandbox --disable-gpu-sandbox --ignore-gpu-blocklist
#    --enable-gpu-rasterization --enable-zero-copy → splash hung.
#  * Attempt #2: --no-sandbox alone → splash hung.
#
# Conclusion: any code path that lets the Chromium GPU process start
# under our elevated token blocks the main thread during init. The
# only fix that keeps the embedded map is moving WebEngine out of the
# elevated process entirely (child-process architecture, tracked
# separately). Until then, force software raster and never touch it.
os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    "--no-sandbox --disable-gpu --disable-gpu-compositing",
)
os.environ.setdefault("QT_OPENGL", "software")

# NOTE: we previously tried QT_SCALE_FACTOR=1 to kill hi-DPI pixel
# doubling in the WebEngine, but it also shrunk the native Qt widgets
# to an unusable size on high-DPI displays. Hi-DPI is now killed only
# at the web page level (via the devicePixelRatio override in
# app/gui/dayz_map_gui_new.py) so the rest of the app keeps its
# normal scaling.

# Ensure the project root is on sys.path so "app.*" imports resolve
_root = os.path.dirname(os.path.abspath(__file__))
if _root not in sys.path:
    sys.path.insert(0, _root)

from app.main import main

if __name__ == "__main__":
    main()
