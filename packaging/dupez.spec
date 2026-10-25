# -*- mode: python ; coding: utf-8 -*-
"""Non-release legacy portable, built from the reviewed Compat factory.

Output: ``dist/dupez.exe``. This entry point deliberately delegates all
dependency, release-data, native-binary, UPX, ASIO, and build-state policy to
``build_common`` so the non-release utility cannot drift behind the canonical
GPU and Compat builds.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(SPEC)))

import build_common as shared_build  # noqa: E402

exe = shared_build.build_variant(
    variant="compat",
    exe_name="dupez",
    manifest_path="dupez_compat.manifest",
    uac_admin=True,
)
