# -*- mode: python ; coding: utf-8 -*-
"""DupeZ-GPU variant PyInstaller spec.

Output: dist/DupeZ-GPU.exe

Properties:
  * asInvoker manifest  (GUI runs at Medium IL)
  * uac_admin = False   (no embedded admin escalation)
  * DUPEZ_ARCH default  = split
  * Chromium GPU process starts normally → embedded iZurvive map
    renders with hardware raster on any machine that isn't on the
    renderer_tier blocklist.
  * WinDivert + netsh live in the auto-spawned elevated helper
    (dupez_helper.py), not in this process.

Build:
    pyinstaller dupez_gpu.spec --noconfirm
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(SPEC)))

from build_common import build_variant  # noqa: E402

exe = build_variant(
    variant="gpu",
    exe_name="DupeZ-GPU",
    manifest_path="dupez.manifest",        # asInvoker
    uac_admin=False,
)
