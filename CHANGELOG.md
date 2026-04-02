# Changelog

All notable changes to DupeZ are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/).

---

## v3.3.0 — 2026-04-02 (Network Intelligence)

Network intelligence toolkit. Live traffic monitoring, latency overlay for gameplay, and standalone port scanner.

### Added
- **`app/gui/network_tools.py`** — New Network Tools module with 3 tab views:
  - `TrafficMonitorWidget` — Real-time per-interface bandwidth table. Shows bytes sent/recv, rate in KB/s with color-coded thresholds, total throughput bar.
  - `LatencyOverlayWidget` — Continuous ping monitor with sparkline graph. Floating always-on-top transparent overlay mode for gameplay (draggable, right-click to close).
  - `PortScannerWidget` — TCP port scanner with preset port sets (Common 100, Gaming, Web, All 1-1024, Full 1-65535). Threaded scanning with progress bar, service identification for 25+ known ports.
- **Network Tools view** — 4th sidebar nav button (📡) in dashboard. Accessible via Ctrl+4.

### Changed
- `dashboard.py` — Expanded from 3-view to 4-view architecture (Clumsy | Map | Accounts | Network Tools).

---

## v3.2.0 — 2026-04-02 (Multi-Target & Scheduling)

Multi-device disruption, timed disruptions, macro chains, and profile sharing.

### Added
- **Multi-Device Disruption** — MULTI toggle in device list enables selecting multiple targets. DISRUPT/STOP buttons operate on all selected devices simultaneously.
- **`app/core/scheduler.py`** — Disruption scheduler + macro engine (~280 lines):
  - `ScheduledRule` — Timer-based disruption rules with HH:MM triggers, duration, and repeat intervals.
  - `DisruptionMacro` / `MacroStep` — Named sequences of disruption steps with per-step timing and repeat control.
  - `DisruptionScheduler` — Background thread scheduler with atomic JSON persistence.
- **Scheduler UI** in Clumsy Control view:
  - Duration/Delay spinboxes for timed disruptions
  - TIMED DISRUPT button — disrupt for N seconds, then auto-stop
  - RUN MACRO — execute saved macros or generate Quick Macros (3-step: light → current → heavy)
  - STOP MACRO — halt active macro execution
- **Import/Export Profiles** — IMPORT and EXPORT buttons in profile panel. Export profiles as standalone JSON, import from file.

### Changed
- `clumsy_control.py` — Device checkboxes now support multi-select mode. Target label shows count when multiple selected. DISRUPT iterates all targets.
- `controller.py` — Scheduler integrated into controller lifecycle (start on init, stop on shutdown).

---

## v3.1.0 — 2026-04-02 (Smart Mode + QoL)

AI-powered auto-tuning, system tray mode, device nicknames, and scan caching.

### Added
- **`app/ai/` module** — Complete AI auto-tune subsystem (4 new files, ~1,500 lines):
  - `network_profiler.py` — Probes target IP in real-time: RTT, jitter, packet loss, bandwidth estimation, hop count, port fingerprinting, device type inference, connection quality scoring (0-100).
  - `smart_engine.py` — Maps network profiles to optimal disruption parameters. 5 goal strategies (disconnect, lag, desync, throttle, chaos) with connection-type adjustments (hotspot/LAN/WAN) and device-type tuning (console/PC/mobile). Intensity slider (0-100%) scales all parameters.
  - `llm_advisor.py` — Natural-language disruption tuning via Ollama (local Mistral 7B) or any OpenAI-compatible API. Describe what you want in plain English → get a tuned preset. Falls back to keyword-based interpretation when no LLM is available.
  - `session_tracker.py` — Logs every disruption session (profile snapshot, config used, duration, user rating). Feeds back into the engine to improve future recommendations. Atomic JSON persistence.
- **AI Auto-Tune UI panel** in Clumsy Control view:
  - Goal selector (Auto, Disconnect, Lag, Desync, Throttle, Chaos)
  - Intensity slider with purple accent theme
  - "ASK AI" text input for natural language requests
  - PROFILE button (analyze target without disrupting)
  - SMART DISRUPT button (profile + auto-tune + disrupt in one click)
  - Live recommendation display with reasoning, confidence bar, and estimated effectiveness
- **`app/core/profiles.py`** — Profile system for saving/loading/sharing named disruption configs. JSON-based, supports import/export, tracks usage count and timestamps.
- **Session history** — Persistent log of past disruptions with target profiles, configs used, and effectiveness ratings. Enables the engine to learn from past sessions.
- **Tray Mode** — System tray icon with context menu (Show/Hide, disruption status, Stop All, Quit). Minimize-to-tray on window close. Ctrl+Shift+D global hotkey to toggle visibility.
- **Device Nicknames** — Right-click any device in the table to set/rename/clear a friendly nickname. Nicknames persist across sessions (stored in `device_nicknames.json`). Shown in gold (#fbbf24) in the Nickname column.
- **Scan Result Caching** — `DeviceCacheManager` persists last scan results to `device_cache.json`. Device list pre-populated on launch from cache.

### Changed
- `dashboard.py` — Version bumped to 3.1.0. System tray icon with tooltip showing active disruption count. Hotkey manager integration. Close event minimizes to tray by default (Quit via tray menu or Ctrl+Q). Hotkeys help dialog updated.
- `clumsy_control.py` — Device table expanded to 7 columns (added Nickname). Integrated Smart Mode panel between Preset selector and Direction toggle. Session tracking wired to stop/stop-all buttons. Context menu for nickname management.
- `controller.py` — Device cache loaded on init, saved after each scan.
- `data_persistence.py` — Added `NicknameManager` and `DeviceCacheManager` with global instances.
- Smart Mode now defaults to AI-recommended settings when enabled, automatically populating all module checkboxes and sliders.

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
