# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for DupeZ — single-file Windows executable.

Build command:
    pyinstaller dupez.spec

Produces:  dist/dupez.exe
"""

import os, sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None
ROOT = os.path.abspath('.')

# ── hidden imports that PyInstaller often misses ────────────────────────
hidden = (
    collect_submodules('app') +
    [
        'PyQt6.QtWidgets', 'PyQt6.QtGui', 'PyQt6.QtCore',
        'PyQt6.QtWebEngineWidgets', 'PyQt6.QtWebEngineCore',
        'PyQt6.QtWebChannel',
        'pyqtgraph', 'psutil', 'keyboard', 'PIL',
        'scapy', 'scapy.all',
        'cryptography', 'numpy', 'pandas', 'openpyxl',
        # Voice control (optional) — whisper is EXCLUDED (see excludes below)
        # because it pulls in torch, which crashes PyInstaller's isolated
        # analyzer with WinError 1114 on c10.dll. voice_control.py gracefully
        # degrades when whisper is missing at runtime.
        'sounddevice',
        # GPC / CronusZEN (optional)
        'serial', 'serial.tools', 'serial.tools.list_ports',
    ]
)

# ── data files to bundle alongside the exe ──────────────────────────────
datas = [
    # Config JSONs
    (os.path.join(ROOT, 'app', 'config'),           os.path.join('app', 'config')),
    # Icons / assets
    (os.path.join(ROOT, 'app', 'resources'),         os.path.join('app', 'resources')),
    (os.path.join(ROOT, 'app', 'assets'),            os.path.join('app', 'assets')),
    # Themes
    (os.path.join(ROOT, 'app', 'themes'),            os.path.join('app', 'themes')),
]

# ── binary DLLs for WinDivert + Clumsy ──────────────────────────────────
binaries = []
firewall_dir = os.path.join(ROOT, 'app', 'firewall')
for fname in os.listdir(firewall_dir):
    fpath = os.path.join(firewall_dir, fname)
    if fname.endswith(('.dll', '.sys', '.exe')) and os.path.isfile(fpath):
        binaries.append((fpath, os.path.join('app', 'firewall')))

# ── analysis ────────────────────────────────────────────────────────────
a = Analysis(
    ['dupez.py'],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # ── ML / heavy libs not used ──
        # whisper excluded because it imports torch at module load time;
        # torch's c10.dll crashes PyInstaller's isolated analyzer with
        # WinError 1114 / access violation on Windows. voice_control.py
        # catches the missing dep and disables voice features gracefully.
        'tensorflow', 'torch', 'whisper', 'openai-whisper',
        'matplotlib', 'scipy',
        'Twisted', 'stem', 'PycURL', 'pymongo', 'redis',
        'logging-loki', 'prometheus-client',
        # ── Dev tools ──
        'pytest', 'black', 'flake8', 'mypy', 'Sphinx',
        # NOTE: QtWebEngine re-included — protected from UPX corruption
        # via upx_exclude list. Needed for DayZ interactive map.
        # ── Tcl/Tk — not used, pulls in _tcl_data/tzdata that fails ──
        'tkinter', '_tkinter', 'tcl',
        # ── Other unused stdlib that drags in large data ──
        'test', 'unittest', 'pydoc',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# ── Strip tcl/tk timezone data that sneaks in via stdlib ────────────────
# These cause "Failed to extract _tcl_data\tzdata\..." on low-spec machines
a.datas = [
    d for d in a.datas
    if not d[0].startswith(('_tcl_data', 'tcl', 'tk'))
]

# ── QtWebEngine binaries kept — protected from UPX via upx_exclude ──────

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='dupez',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    # ── Exclude large Qt DLLs from UPX compression ──────────────────
    # UPX can corrupt large DLLs during decompression, causing
    # "decompression resulted in return code -1" on extraction.
    upx_exclude=[
        # Qt core DLLs — UPX corrupts these large binaries
        'Qt6Core.dll',
        'Qt6Gui.dll',
        'Qt6Widgets.dll',
        'Qt6Network.dll',
        'Qt6Svg.dll',
        'Qt6OpenGL.dll',
        # QtWebEngine — largest DLLs (~200 MB), most prone to corruption
        'Qt6WebEngineCore.dll',
        'Qt6WebEngineWidgets.dll',
        'Qt6WebChannel.dll',
        'QtWebEngineProcess.exe',
        # System / runtime
        'python3*.dll',
        'vcruntime*.dll',
        'msvcp*.dll',
        'ucrtbase.dll',
        'libcrypto*.dll',
        'libssl*.dll',
        # WinDivert driver — must not be compressed
        'WinDivert.dll',
        'WinDivert64.sys',
    ],
    runtime_tmpdir=None,
    console=False,              # windowed (no terminal)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT, 'app', 'resources', 'dupez.ico'),
    version=os.path.join(ROOT, 'version_info.py'),       # embed VS_VERSION_INFO
    manifest=os.path.join(ROOT, 'dupez.manifest'),        # embed app manifest
    uac_admin=True,             # request admin on launch
)
