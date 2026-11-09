# -*- mode: python ; coding: utf-8 -*-
"""DupeZ-GPU variant PyInstaller spec.

Output: dist/DupeZ-GPU.exe

Properties:
  * asInvoker manifest  (GUI runs at Medium IL)
  * uac_admin = False   (no embedded admin escalation)
  * DUPEZ_ARCH default  = split
  * Embedded Chromium/QML payload is excluded; the Map tab presents the
    reviewed manual browser URL.
  * WinDivert + netsh live in the auto-spawned elevated helper
    (dupez_helper.py), not in this process.

Build:
    pyinstaller dupez_gpu.spec --noconfirm
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(SPEC)))

import build_common as shared_build  # noqa: E402

exe = shared_build.build_variant(
    variant="gpu",
    exe_name="DupeZ-GPU",
    manifest_path="dupez.manifest",        # asInvoker
    uac_admin=False,
)
