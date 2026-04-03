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
        'PyQt6.QtWebEngineWidgets', 'PyQt6.QtWebChannel',
        'pyqtgraph', 'psutil', 'keyboard', 'PIL',
        'scapy', 'scapy.all',
        'cryptography', 'numpy', 'pandas', 'openpyxl',
        # Voice control (optional)
        'sounddevice', 'whisper',
        # GPC / CronusZEN (optional)
        'serial', 'serial.tools', 'serial.tools.list_ports',
    ]
)

# ── data files to bundle alongside the exe ──────────────────────────────
datas = [
    # Config JSONs
    (os.path.join(ROOT, 'app', 'config'),           os.path.join('app', 'config')),
    (os.path.join(ROOT, 'config'),                   'config'),
    # Icons / assets
    (os.path.join(ROOT, 'app', 'resources'),         os.path.join('app', 'resources')),
    (os.path.join(ROOT, 'app', 'assets'),            os.path.join('app', 'assets')),
    # Themes
    (os.path.join(ROOT, 'app', 'themes'),            os.path.join('app', 'themes')),
    # Data files
    (os.path.join(ROOT, 'data'),                     'data'),
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
        'tensorflow', 'torch', 'matplotlib', 'scipy',
        'Twisted', 'stem', 'PycURL', 'pymongo', 'redis',
        'logging-loki', 'prometheus-client',
        'pytest', 'black', 'flake8', 'mypy', 'Sphinx',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

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
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,              # windowed (no terminal)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT, 'app', 'resources', 'dupez.ico'),
    uac_admin=True,             # request admin on launch
)
