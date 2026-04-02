# Changelog

All notable changes to DupeZ are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/).

---

## v3.0.1 — 2026-04-01

Production hardening pass for public community release.

### Added
- `.gitattributes` — Cross-platform line ending normalization. Binary files (DLLs, .sys, .exe, .ico) marked binary to prevent git corruption.
- Atomic file writes for `settings.json` — writes to `.tmp`, fsyncs, then `os.replace()` to prevent mid-write corruption.
- Settings resilience — `load_settings()` auto-recovers to clean defaults on corrupt/partial JSON.
- Self-contained settings dialog stylesheet (`SETTINGS_STYLE`) — immune to app-level theme changes.
- Complete QSS coverage in `dark.qss` — QSlider, QTextEdit, QDialog, QMenuBar, QMenu, QSpinBox buttons, QComboBox dropdown.
- Missing QSS rules in `light.qss` — QSpinBox, QTextEdit, QDialog.
- Full settings documentation in README — all 5 tabs with every field, default, and range.

### Changed
- Settings dialog completely rewritten — 5-tab layout (General, Network, Smart Mode, Interface, Advanced), all 28 `AppSettings` fields wired end-to-end.
- Settings dialog styled to match cyber HUD theme — glassmorphism background, cyan accents, color-coded buttons.
- `state.py` — Hardened `load_settings()` filters unknown keys, catches `JSONDecodeError`/`TypeError`, auto-regenerates on corruption.
- `state.py` — `save_settings()` uses atomic write pattern (tmp + fsync + os.replace).
- `profiles.json` — Stripped PS5/XBOX device-specific profiles, replaced with generic defaults.
- `logger.py` — Renamed `ps5_detection()` → `device_detection()`, `log_ps5_detection()` → `log_device_detection()` (backward-compat aliases kept).
- All documentation IPs replaced with RFC 5737 addresses (198.51.100.x).

### Removed
- 14,800+ lines of dead code: `development/` test suites, PS5-specific scripts and GUI (`ps5_gui.py`), launcher batch files, maintenance scripts, `strip_dead_code.ps1`.
- Dead UI controls from settings: `log_to_file_checkbox`, `interface_combo`, `custom_network_edit`.
- Unused imports from settings dialog: `QLineEdit`, `QProgressBar`, `QFileDialog`, `QColorDialog`, `QFontDialog`, `QColor`, `Dict`, `Any`.

### Fixed
- Corrupted `settings.json` — was truncated mid-write (missing closing brace, partial field). Rebuilt with clean defaults.
- Settings dialog stylesheet overwritten by theme changes — now re-applies `SETTINGS_STYLE` in `apply_theme()`, `start_rainbow_mode()`, `stop_rainbow_mode()`.
- Qt combo box feedback loops — `blockSignals()` guards prevent recursive signal firing during programmatic updates.

### Security
- Zero personal IPs, emails, debug artifacts, or secrets in tracked code.
- All example IPs use RFC 5737 documentation ranges.

---

## v3.0.0 — 2026-03-30 (The Strip)

Complete architectural overhaul. Stripped 90+ dead files (~40,000 lines). Rebuilt from 5-view bloated dashboard to clean 3-view tool.

### Added
- `clumsy_control.py` — New main view. Device scanner + per-device disruption controls with sliders, presets, method checkboxes, session timers.
- Disruption presets: Light Lag, Heavy Lag, Full Disconnect, Desync, Bandwidth Cap, Custom.
- Per-method parameter sliders: Drop %, Lag ms, Throttle %, Duplicate %, Corrupt %, RST %.
- Map selector dropdown: 8 maps (Chernarus+ sat/topo, Livonia, Namalsk, Sakhal, Deer Isle, Esseker, Takistan).
- MutationObserver-based ad blocker for iZurvive (catches dynamically injected ads).
- Account tracker dark theme with status-colored statistics bar.

### Removed
- ML module (MoE engine, inference, embeddings, anomaly detection, threat classifier, report generator — 11 files, ~5,200 lines)
- Surveillance module (DPI, network intelligence, behavioral profiler — 3 files, ~1,600 lines)
- Counter-surveillance module (anomaly detector, deception engine, anti-MITM, TSCM — 4 files, ~1,600 lines)
- Security module (crypto engine, anti-forensics, integrity monitor, encrypted DB, auth, audit logger — 8 files, ~3,500 lines)
- Research module (OSINT engine, threat intel — 2 files, ~1,060 lines)
- Plugin system (advanced plugin system, plugin manager, secure executor, gaming control — 6 files, ~3,000 lines)
- Privacy module, health module, PS5 module
- Mesh networking (gossip protocol, node discovery, distributed tasks)
- 17 orphaned GUI files (old map, gaming dashboard, tips/tricks, topology views, duplicate device lists, etc.)
- 7 redundant firewall modules (enterprise disruptor, network disruptor, netcut, internet dropper, UDP interrupter, etc.)
- 8 redundant core modules (smart mode, stability optimizer, traffic analyzer, data pipeline, etc.)
- 9 redundant network modules (gaming optimizer, duping optimizer, server discovery, multi-protocol scanner, etc.)
- TipsTicker footer, stability optimizer integration, CPU monitoring timers, animation timers
- All root-level debug artifacts (crash logs, one-off scripts, enhancement blueprint)

### Changed
- `main.py` — Stripped to clean startup. Only clumsy disruptor in shutdown path. Version bumped to 3.0.0.
- `controller.py` — Gutted from 742 to 285 lines. Direct clumsy integration. Removed smart mode, plugin manager, traffic analyzer, enterprise disruptor.
- `dashboard.py` — Complete rewrite. 3-view sidebar rail (Clumsy | Map | Accounts). 1,732 → 348 lines.
- `dayz_map_gui_new.py` — Enhanced from 75 to 137 lines. Map selector + improved ad blocker.
- `dayz_account_tracker.py` — Injected cascading dark theme. Fixed 23 empty `setStyleSheet("")` calls. Status-colored statistics.

### Stats
- Before: 110+ files, ~60,800 lines
- After: 14 files, ~6,600 lines
- Reduction: 89%

---

## v2.0.0 — Previous

Major UI optimization. 5-view dashboard with sidebar rail. iZurvive map integration. Account tracker. Multiple network disruptors.

## v1.0.0 — Initial

Basic network scanner with device blocking.
