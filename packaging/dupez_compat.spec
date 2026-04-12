# -*- mode: python ; coding: utf-8 -*-
"""DupeZ-Compat variant PyInstaller spec.

Output: dist/DupeZ-Compat.exe

Properties:
  * requireAdministrator manifest  (one UAC prompt on launch)
  * uac_admin = True               (embedded admin escalation)
  * DUPEZ_ARCH default  = inproc
  * Single-process build. WinDivert + netsh run directly in the GUI
    process, identical to shipping builds prior to ADR-0001.
  * Embedded iZurvive map falls through to software raster because
    Chromium's GPU process refuses to start under an admin token.
  * For users on blocklisted GPUs or who cannot tolerate the
    auto-spawn helper flow.

Build:
    pyinstaller dupez_compat.spec --noconfirm
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(SPEC)))

from build_common import build_variant  # noqa: E402

exe = build_variant(
    variant="compat",
    exe_name="DupeZ-Compat",
    manifest_path="dupez_compat.manifest",  # requireAdministrator
    uac_admin=True,
)
