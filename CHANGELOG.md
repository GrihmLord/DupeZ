# Changelog

All notable changes to DupeZ are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/).

---

## v4.0.0 — 2026-04-06 (Platform & Extensibility)

Major platform release. Plugin API, CLI mode, auto-updater, desync engine rewrite, God Mode overhaul with NAT keepalive, full opsec audit, and thread safety pass across the entire codebase.

### Added — Plugin API
- **`app/plugins/base.py`** — Base classes for all plugin types: `DisruptionPlugin`, `ScannerPlugin`, `UIPanelPlugin`, `GenericPlugin`. Each receives a reference to `AppController` on activation.
- **`app/plugins/loader.py`** — `PluginLoader` with full lifecycle: discovery, manifest validation, dynamic import, activation, deactivation, and hot-reload. Plugins live in `plugins/` with a `manifest.json` + Python entry point. Leak-safe loading cleans `sys.path` and `sys.modules` on unload.
- **`manifest.json` schema** — Declares name, version, description, type, entry_point, author, dependencies, and min DupeZ version. Validated on discovery.
- **Dashboard integration** — UI panel plugins automatically get a sidebar nav button and view stack entry. Loaded after core views during `setup_ui()`.
- **Controller integration** — `AppController._init_plugins()`, `get_plugin_info()`, `reload_plugins()`. Plugins unloaded cleanly on shutdown.
- **Example plugin: Ping Monitor** — Live latency panel showing real-time ping to all discovered devices. Demonstrates the full `UIPanelPlugin` lifecycle with thread-safe Qt signals.

### Added — CLI Mode
- **`app/cli.py`** — Full headless terminal interface. Subcommands: `scan`, `disrupt`, `stop`, `status`, `devices`, `plugins`. Interactive REPL mode with `dupez-cli interactive`.
- **Scriptable disruptions** — `dupez-cli disrupt <ip> --methods drop,lag --params '{"drop_chance":50}'`. Pipe-friendly output for automation.

### Added — Auto-Updater
- **`app/core/updater.py`** — `UpdateChecker` queries GitHub Releases API for latest version. Compares semver, offers one-click download via browser. Sync and async check modes.
- **Dashboard menu** — Help > Check for Updates triggers update check with dialog.

### Added — iZurvive Ad Blocker v2
- **Two-layer blocking** — Network-level `QWebEngineUrlRequestInterceptor` blocks ~28 known ad domains before requests leave the browser. DOM-level CSS/JS cleanup removes residual ad containers and iframes after page load.
- **OAuth login preserved** — Google/Steam login domains whitelisted so authentication flows are unaffected by ad blocking.

### Changed — Desync Engine Rewrite
- **Lag passthrough mode** — `LagModule` auto-enables passthrough when stacked with duplicate or out-of-order modules. In passthrough mode, lag queues a delayed *copy* of each packet but returns `False`, allowing the original to continue to downstream modules. This enables true lag+dupe+ood stacking for maximum desync. Previously lag consumed all packets (`return True`), silently preventing dupe/ood from ever firing.
- **`_init_modules()` auto-detection** — Engine inspects active method set on startup; if `{"duplicate", "ood"}` intersects active methods, `lag_passthrough` is enabled automatically with a log message.

### Changed — God Mode Overhaul
- **NAT keepalive system** — Periodically lets 1 inbound packet through unlagged (default every 800ms) to refresh Windows ICS NAT table mappings. Prevents silent packet drops during long freeze cycles caused by stale NAT entries. Configurable via `godmode_keepalive_interval_ms` (0 = disabled, used at intensity ≥ 0.95).
- **Burst-controlled flush on deactivation** — Queued inbound packets released in bursts of 50 with 5ms pauses between bursts to prevent packet storms that crash the target's network stack.
- **Full WinDivert NETWORK_FORWARD documentation** — `Outbound=True` means leaving gateway toward internet, `Outbound=False` means arriving from internet to be forwarded to target.
- **God Mode stats** — `stop()` logs inbound lagged/dropped/keepalive and outbound passed counters.

### Fixed — Duplicate Count
- **`DuplicateModule.process()`** — Now sends 1 original + N copies = N+1 total deliveries. Previously sent only N copies and consumed the original, so the target received N instead of N+1.

### Fixed — Thread Safety Pass
- **`data_persistence.py`** — All persistence operations protected by lock. Corrupt file recovery with atomic tmp → fsync → replace pattern.
- **`network_scanner.py`** — Executor access guarded by lock. Cache race condition resolved.
- **`state.py`** — Observer notifications marshalled to Qt thread. IP leak in `toggle_device_blocking()` fixed (2 call sites wrapped in `mask_ip()`).
- **`llm_advisor.py`** — `_conversation_history` reads/writes protected by `_history_lock`. `get_explanation()` wrapped in try/except with `_fallback_explanation` recovery. IP leak on line 156 fixed (`mask_ip()` applied before sending target IP to remote LLM API).
- **`gpc/device_bridge.py`** — Callback-outside-lock pattern prevents deadlock in device monitor.
- **`network_scanner.py`** — Enhanced `threading.Event` for lock-free thread-safe scan cancellation.

### Fixed — Scheduler / Macro
- **Repeat-only rule first-fire bug** — Rules with only a repeat interval now fire immediately on first tick instead of waiting one full interval.
- **Epoch-based delayed start** — Scheduled rules use epoch timestamps for delay calculation, eliminating clock drift on long-running sessions.
- **`QTimer.singleShot` for auto-stop** — Replaced `threading.Thread` sleep-then-stop pattern with Qt timer, eliminating race conditions between background thread and GUI thread.
- **Macro step callback** — `MacroStep` emits callback on completion for GUI timer synchronization.

### Security — Full Opsec Audit
- **`mask_ip()` everywhere** — All target IPs masked via `mask_ip()` in every log statement across the codebase (7 files, 12 call sites). Zero raw IPs in any log output.
- **LLM advisor IP leak closed** — Target IP was sent unmasked to remote LLM API in profile context. Now masked before transmission.
- **State.py IP leaks closed** — 2 log statements in `toggle_device_blocking()` logged raw target IP. Now masked.
- **No personal data in tracked files** — `dist/`, build artifacts, and user data files excluded via `.gitignore`.

### Changed — LLM Advisor
- **Complete system prompt rewrite** — Documents module chain order, passthrough mode, NAT keepalive mechanics, and 6 proven DayZ disruption scenarios with exact parameter values.
- **`godmode_keepalive_interval_ms`** added to `_PARAM_RANGES` (0–5000).
- **`_fallback_godmode` updated** — Includes keepalive interval scaled by intensity. Disabled (0ms) at intensity ≥ 0.95 for maximum freeze.
- **`_fallback_explanation` updated** — God Mode explanation includes NAT keepalive and burst flush details.

### Changed — Smart Engine
- **`_strategy_godmode` updated** — Generates `godmode_keepalive_interval_ms` scaled from 800ms (low intensity) to 0ms (max intensity). Hotspot connection type reduces lag by 20%.

### Changed — UI
- **Custom menu bar** — Embedded `QMenuBar` below frameless title bar with dark theme styling. ADMIN badge repositioned before version string.

### Changed
- **Version bump** — 3.5.0 → 4.0.0 across all modules, title bar, about dialog, AppUserModelID, and PyInstaller spec.
- **`dupez.spec`** — Plugin loader hidden imports added. `sys.path` cleanup modules included.
- **`clumsy_network_disruptor.py`** — Default params include `godmode_keepalive_interval_ms: 800`.

---

## v3.5.0 — 2026-04-03 (Live Stats + Distribution Polish)

Quality-of-life release: real-time packet stats dashboard, PyInstaller packaging improvements, and version bump.

### Added
- **Live Stats Dashboard** in Clumsy Control view — real-time packet counters (processed, dropped, passed, inbound, outbound) with auto-refresh every 1.5s. Includes drop rate progress bar, active engine count, and per-device breakdown table with method labels.
- **`NativeDisruptEngine.get_stats()`** — returns live packet counters dict from each engine instance.
- **`ClumsyNetworkDisruptor.get_all_engine_stats()`** — aggregates stats across all active disruption engines with per-device breakdown.
- **`AppController.get_engine_stats()`** — exposes aggregated engine stats to the GUI layer.
- **`_format_count()` helper** — human-readable packet counts (1.2K, 3.4M).

### Changed
- **`dupez.spec`** — Added hidden imports for voice (`sounddevice`, `whisper`) and GPC (`serial`, `serial.tools`, `serial.tools.list_ports`) so PyInstaller bundles optional dependencies correctly.
- **Version bump** — 3.3.0 → 3.5.0 across `main.py`, `dashboard.py`, `network_tools.py`, AppUserModelID.

---

## v3.4.0 — 2026-04-02 (God Mode + Voice + GPC)

Major feature release. Directional lag engine (God Mode), push-to-talk voice control via Whisper, and native CronusZEN/MAX GPC script integration.

### Added — God Mode
- **`native_divert_engine.py` → `GodModeModule`** — Directional lag engine using WinDivert packet direction detection. Delays inbound packets (server → target) while passing outbound untouched. Target freezes on other players' screens while your actions register in real time. Configurable inbound lag (0–5000ms) and optional inbound packet drop percentage.
- **Direction-aware filtering** — All disruption modules now implement `matches_direction()`. WinDivert `Outbound` bit (position 17 in addr bitfield) used for per-packet direction classification.
- **`NETWORK_FORWARD` layer support** — Enables God Mode on ICS/hotspot setups where the machine is the gateway.
- **God Mode preset** — 2000ms inbound lag, outbound untouched. One-click activation.
- **God Mode Aggressive preset** — God Mode + 30% inbound drop for harder freeze effect.
- **Smart Engine godmode strategy** — 6th goal strategy in AI auto-tune. Connection-type adjustments (hotspot reduces lag by 20%).
- **LLM Advisor godmode fallback** — Keyword-based God Mode interpretation with intensity scaling and hotspot detection when no LLM is available.

### Added — Voice Control
- **`app/ai/voice_control.py`** — Complete push-to-talk voice command module (~480 lines):
  - `VoiceEngine` — Audio capture via `sounddevice` InputStream callback (16kHz, mono, float32). Silence detection (RMS threshold), minimum length validation, max duration cap.
  - `VoiceController` — Wires VoiceEngine → OpenAI Whisper STT → LLMAdvisor → disruption config. Thread-safe callback marshaling to Qt main thread.
  - `VoiceConfig` dataclass — sample rate, channels, dtype, model name (tiny/base/small), language, silence threshold, min/max duration.
  - Lazy dependency checks — DupeZ runs without `sounddevice` or `openai-whisper` installed.
  - Simple voice commands: "stop"/"off" → stop disruption, "start"/"on" → start.
  - Input device listing and selection.
- **Voice Control UI panel** in Clumsy Control — INIT button, PUSH TO TALK button, model selector (tiny/base/small), mic selector, status label.

### Added — GPC / CronusZEN Support
- **`app/gpc/gpc_parser.py`** — GPC script tokenizer + recursive descent parser (~350 lines). Parses preprocessor directives, variables, main blocks, combo blocks, and functions into structured `GPCScript` objects.
- **`app/gpc/gpc_generator.py`** — GPC script generator (~350 lines). 4 built-in templates: DayZ Auto Dupe, Rapid Fire, God Mode Actions, Anti Recoil. Generates complete .gpc source synced with DupeZ disruption timing. Atomic file export.
- **`app/gpc/device_bridge.py`** — Cronus USB device detection + Zen Studio integration (~250 lines). Scans for VID 0x2508 via pyserial (WMI fallback on Windows). Background `DeviceMonitor` thread for connect/disconnect events. Auto-discovers Zen Studio library folder for direct .gpc export.
- **`app/gpc/__init__.py`** — Package init with full public API exports.
- **GPC UI panel** in Clumsy Control — Device status, template selector, description label, GENERATE/EXPORT/SYNC TIMING buttons, script preview.

### Fixed
- **100% drop fidelity** — Drop module now uses `continue` (discard packet) instead of re-injecting, guaranteeing true 100% drop when configured.
- **`llm_advisor.py`** — Missing `_fallback_godmode()` method caused `AttributeError` when godmode keywords matched without LLM. Added complete implementation with intensity scaling and hotspot detection.
- **`llm_advisor.py`** — False positive on bare "god" keyword (matched "good"). Removed; kept specific patterns ("god mode", "godmode", "freeze them", etc.).
- **`smart_engine.py`** — Goal key mismatch: GUI sent "god mode" (with space) but strategy map keyed on "godmode". Added `goal.replace(" ", "")` normalization.
- **`smart_engine.py`** — Hotspot adjustment never touched `godmode_lag_ms`. Added `*= 0.8` reduction in hotspot branch.
- **`clumsy_control.py`** — Voice command callback ran on background thread, modifying Qt widgets unsafely. Split into thread-safe marshal (`QMetaObject.invokeMethod`) + main-thread `@pyqtSlot` handler.
- **`clumsy_control.py`** — `_voice_controller` AttributeError when voice dependencies unavailable. Added `None` initialization in `__init__`.
- **`voice_control.py`** — Audio buffer appended from sounddevice callback thread without lock. Added `with self._lock:` guard on both append and read paths.
- **`llm_advisor.py`** — Removed unused `import os`.
- **`app/ai/__init__.py`** — Added voice control exports with `ImportError` fallback.

### Changed
- `smart_engine.py` — Goal strategies expanded from 5 to 6 (added godmode).
- `clumsy_control.py` — Smart Mode goal selector includes "God Mode". Voice and GPC panels added to control layout.
- `requirements.txt` — Added optional dependencies: `sounddevice>=0.4.6`, `openai-whisper>=20231117`, `pyserial>=3.5`.

---

## v3.3.1 — 2026-04-02 (Hardening Pass)

Full codebase audit — 11 fixes across 11 files targeting thread safety, crash resilience, frozen-exe compatibility, and correctness.

### Fixed — Critical
- **`blocker.py`** — Missing `log_warning` import crashed `clear_all_dupez_blocks()` at runtime.
- **`blocker.py`** — `is_active()` method shadowed `self.is_active` bool attribute; renamed to `get_active()`.

### Fixed — High
- **`data_persistence.py`** — `save_data()` used bare `json.dump`; crash mid-write corrupted file. Now uses atomic tmp → fsync → replace pattern.
- **`smart_engine.py`** — Hardcoded `"app/data/session_history.json"` broke in PyInstaller builds. Now uses `_resolve_data_directory()`.
- **`logger.py`** — Relative `"logs"` directory resolved to `System32\logs` in frozen exe. Added `_resolve_log_directory()` with `sys.frozen` detection.

### Fixed — Medium
- **`state.py`** — `_observers` list had no thread protection. Added `threading.Lock` to `add_observer()` and `notify_observers()`.
- **`controller.py`** — `start_auto_scan()` never reset `stop_scanning` flag, preventing auto-scan restart after manual stop.
- **`network_profiler.py`** — `ip.startswith("172.2")` incorrectly matched public IPs 172.200-255.x.x. Added proper RFC1918 172.16.0.0/12 range check.
- **`session_tracker.py`** — `_active_sessions` dict mutations in `start_session()`/`end_session()` were unprotected. Now guarded by `self._lock`.

### Fixed — Low
- **`native_divert_engine.py`** — Out-of-Order module had unbounded packet buffer. Added `MAX_BUFFER=64` safety valve.
- **`helpers.py`** — 350-entry duplicate emoji replacement dict replaced with single `encode('ascii', errors='replace')` call.

### Changed
- **`main.py`** — Version log updated to 3.3.0. AppUserModelID updated to `com.dupez.app.3.3`.
- **`dashboard.py`** — Window title updated to "DupeZ v3.3.0".

---

## v3.3.0 — 2026-04-02 (Network Intelligence)

Network intelligence toolkit. Live traffic monitoring, latency overlay for gameplay, and standalone port scanner.

### Added
- **`app/gui/network_tools.py`** — New Network Tools module with 4 tab views:
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

## v2.0.0 — Previous (Legacy)

Major UI optimization. 5-view dashboard with sidebar rail. iZurvive map integration. Account tracker. Multiple network disruptors.

## v1.0.0 — Initial

Basic network scanner with device blocking.
