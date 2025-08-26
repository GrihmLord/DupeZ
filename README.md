# DupeZ – Professional Edition

## Overview
DupeZ is a professional-grade network control application with integrated DayZ mapping. It provides advanced device discovery, smart blocking, traffic manipulation, and a full iZurvive DayZ map experience – all wrapped in a modern, responsive UI.

## Key Features
- Network control: scanning, smart blocking, traffic manipulation, and real-time monitoring
- DayZ integration: iZurvive maps, markers, data import/export
- Gaming tools: DayZ dashboards, account tracking, performance optimization
- Modern UI: responsive layout, movable tabs, consolidated sidebar/content with splitter

## Quick Start
- Normal mode:
```bat
dupez.bat
```
- Admin mode (elevated):
```bat
dupez.bat --admin
```
Notes:
- The launcher prefers a packaged EXE in `dist/` if present and falls back to running from source (using `.venv` if available).
- Admin mode elevates via PowerShell.

## Build
1) Install dependencies
```bash
pip install -r requirements/requirements_webengine.txt
```
2) Build the packaged app (replace with your spec name if different)
```bash
pyinstaller YourRenamed.spec --noconfirm
```
3) Run packaged app
```bat
start "" .\dist\YourRenamed\YourRenamed.exe
```

Packaging notes:
- Theme and assets are bundled via the spec `datas` entries:
  - `app/themes/*.qss`, `app/assets/*`, `app/config/*.json`
- The theme manager resolves paths correctly in frozen builds (handles `sys._MEIPASS`).
- Source distributions are controlled by `MANIFEST.in` to include app code and resources, and prune development artifacts.

## Directory Structure (simplified)
```
DupeZ/
├── app/                    # Application code (gui, core, firewall, network, themes, config)
├── dist/                   # Packaged builds (after pyinstaller)
├── build/                  # Build artifacts (ignored)
├── docs/                   # Additional documentation (integration, guides)
├── development/            # Dev tools, tests, scripts
├── dupez.bat               # Unified launcher (normal/admin)
├── DupeZ_*.spec            # PyInstaller spec(s)
├── MANIFEST.in             # sdist contents
├── requirements/           # Requirements files
└── README.md               # This document
```

## UI and Theme
- Responsive theme: `responsive_dark.qss`. Parsing issues resolved for Qt style sheets.
- Movable tabs are enabled across the application (`QTabWidget.setMovable(True)`).
- Dashboard layout uses a `QSplitter` for sidebar/content for a cleaner, resizable admin experience.

## Troubleshooting
- Tabs not movable in admin build: ensure you are running the rebuilt EXE from `dist/` and that your spec bundles themes/assets. Rebuild with `pyinstaller YourRenamed.spec --noconfirm`.
- iZurvive maps not loading: verify internet access and try running in admin mode.
- Performance issues: close background apps; ensure GPU drivers are up to date.

## License
Proprietary software. All rights reserved.

## Acknowledgments
- iZurvive team (DayZ mapping)
- PyQt6 community
- DupeZ users and contributors
