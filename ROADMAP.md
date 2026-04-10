# DupeZ Roadmap

What's coming next. Priorities shift based on community feedback — open an issue or PR if something here matters to you.

---

## v3.1.0 — Smart Mode + Quality of Life ✅

**Released:** 2026-04-02

- ~~**Profile System** — Save/load named disruption profiles per game or scenario.~~ ✅ Done
- ~~**Session History** — Log of past disruption sessions with timestamps, targets, methods, and durations.~~ ✅ Done
- ~~**AI Auto-Tune Engine** — Network profiler + ML-based parameter optimizer + LLM advisor.~~ ✅ Done
- ~~**Tray Mode** — Minimize to system tray with hotkey toggle. Ctrl+Shift+D global hotkey.~~ ✅ Done
- ~~**Device Nicknames** — Assign friendly names to scanned devices via right-click context menu.~~ ✅ Done
- ~~**Scan Result Caching** — Persist discovered devices across restarts.~~ ✅ Done

---

## v3.2.0 — Multi-Target & Scheduling ✅

**Released:** 2026-04-02

- ~~**Multi-Device Disruption** — MULTI toggle enables simultaneous disruption of multiple selected devices.~~ ✅ Done
- ~~**Scheduled Disruptions** — Timed Disrupt button with configurable duration and delay. Auto-stop after timer expires.~~ ✅ Done
- ~~**Disruption Macros** — Chain disruption steps in sequence with Quick Macro and saved macro support.~~ ✅ Done
- ~~**Import/Export Profiles** — IMPORT/EXPORT buttons in profile panel. Share profiles as standalone JSON files.~~ ✅ Done

---

## v3.3.0 — Network Intelligence ✅

**Released:** 2026-04-02

- ~~**Live Traffic Monitor** — Real-time per-interface bandwidth table with rate calculation and total throughput bar.~~ ✅ Done
- ~~**Connection Mapper** — Visual topology showing which devices are talking to which external IPs. Live-updating table + text topology, filter by TCP/UDP/Established/Gaming.~~ ✅ Done
- ~~**Latency Overlay** — Floating transparent always-on-top ping/jitter widget with sparkline graph. Draggable.~~ ✅ Done
- ~~**Port Scanner Integration** — Standalone port scanner with Common/Gaming/Web/Full port sets and service identification.~~ ✅ Done

---

## v3.4.0 — God Mode + Voice + GPC ✅

**Released:** 2026-04-02

- ~~**God Mode / Directional Lag** — Inbound packets delayed while outbound passes untouched. Target freezes on others' screens while your actions register in real time. Configurable inbound lag (0–5000ms) and optional inbound drop.~~ ✅ Done
- ~~**100% Drop Fidelity** — Drop module uses packet discard instead of re-inject. True 100% when configured.~~ ✅ Done
- ~~**Direction-Aware Filtering** — All disruption modules implement `matches_direction()`. WinDivert outbound bit detection for per-packet direction classification.~~ ✅ Done
- ~~**Voice Control** — Push-to-talk voice commands via OpenAI Whisper (local, offline). Speak disruption commands, LLM advisor interprets into configs. Model selection (tiny/base/small), mic selection.~~ ✅ Done
- ~~**GPC / CronusZEN Support** — Parse .gpc files, generate scripts synced with DupeZ timing, export to Zen Studio. 4 built-in templates (Auto Dupe, Rapid Fire, God Mode Actions, Anti Recoil). USB device detection.~~ ✅ Done
- ~~**Smart Engine God Mode Strategy** — 6th goal strategy with hotspot-aware tuning.~~ ✅ Done
- ~~**LLM Advisor God Mode Fallback** — Keyword-based godmode interpretation when no LLM available.~~ ✅ Done

---

## v3.5.0 — Live Stats + Distribution Polish ✅

**Released:** 2026-04-03

- ~~**Live Stats Dashboard** — Real-time packet counters (processed, dropped, passed, inbound, outbound) with auto-refresh. Drop rate bar, active engine count, per-device breakdown table.~~ ✅ Done
- ~~**Engine Stats API** — `get_stats()` on NativeDisruptEngine, `get_all_engine_stats()` aggregator on ClumsyNetworkDisruptor, `get_engine_stats()` on AppController.~~ ✅ Done
- ~~**PyInstaller Spec Update** — Hidden imports for optional voice and GPC dependencies so frozen exe bundles correctly.~~ ✅ Done
- ~~**Version Bump** — 3.3.0 → 3.5.0 across all modules, title bar, about dialog, and AppUserModelID.~~ ✅ Done

---

## v4.0.0 — Platform & Extensibility ✅

**Released:** 2026-04-06

- ~~**Plugin API** — Lightweight plugin system for community-built disruption modules, scanners, and UI panels. JSON manifest + Python entry point. Auto-discovery from `plugins/` directory. Hot-reload support. sys.path/sys.modules leak-safe loading.~~ ✅ Done
- ~~**CLI Mode** — Run DupeZ headless from the terminal. Script disruptions, pipe output, integrate into automation. Interactive REPL mode.~~ ✅ Done
- ~~**Auto-Updater** — In-app update checker with one-click download from GitHub releases.~~ ✅ Done
- ~~**God Mode Overhaul** — NAT keepalive system (1 packet/800ms) prevents Windows ICS NAT table timeout during long freeze cycles. Burst-controlled flush on deactivation (50 packets/5ms burst). Full WinDivert NETWORK_FORWARD documentation.~~ ✅ Done
- ~~**Desync Engine Rewrite** — Lag module passthrough mode auto-enables when stacked with duplicate/ood. Lag queues delayed copies while originals flow to downstream modules. True lag+dupe+ood stacking for maximum desync.~~ ✅ Done
- ~~**Fixed Duplicate Count** — DuplicateModule now sends 1 original + N copies = N+1 total deliveries (was N, missing the original).~~ ✅ Done
- ~~**Thread-Safe LLM Advisor** — Conversation history protected by lock for ask_async concurrency. Error handling on get_explanation.~~ ✅ Done
- ~~**Full Opsec Audit** — All target IPs masked via mask_ip() in every log statement across the codebase (7 files, 12 call sites). No personal data in tracked files.~~ ✅ Done
- ~~**iZurvive Ad Blocker v2** — Two-layer: network-level QWebEngineUrlRequestInterceptor blocks ~28 ad domains + DOM-level CSS/JS cleanup. OAuth login preserved.~~ ✅ Done
- ~~**Scheduler/Macro Fixes** — Repeat-only rule first-fire bug. Epoch-based delayed start. QTimer.singleShot for auto-stop (was threading.Thread race). Macro step callback for GUI timer sync.~~ ✅ Done
- ~~**Thread Safety Pass** — Data persistence lock, network scanner executor lock, state observer Qt thread marshalling, GPC bridge callback-outside-lock pattern, enhanced scanner threading.Event.~~ ✅ Done
- ~~**Custom Menu Bar** — Embedded QMenuBar below frameless title bar with dark theme styling. ADMIN badge repositioned before version string.~~ ✅ Done
- **Linux Support** — Replace WinDivert dependency with `tc`/`iptables` backend for Linux. Same GUI via PyQt6. *(Deferred)*

---

## v5.0.0 — God Mode Engineering ✅

**Released:** 2026-04-09

The deep-research release. All 7 deep-research phases implemented: statistical disruption models, packet classification, tick-synchronized bursts, asymmetric direction presets, native WinDivert batch API, ML-enhanced traffic analysis, and stealth/detection avoidance.

- ~~**Phase 1: Statistical Disruption Models**~~ ✅ Done
- ~~**Phase 2: Packet Classification Engine**~~ ✅ Done
- ~~**Phase 3: Tick-Synchronized Disruption**~~ ✅ Done
- ~~**Phase 4: Asymmetric Direction Engine** — 14 named presets~~ ✅ Done
- ~~**Phase 5: Native WinDivert Batch API**~~ ✅ Done
- ~~**Phase 6: ML Network Profiler**~~ ✅ Done
- ~~**Phase 7: Stealth & Detection Avoidance**~~ ✅ Done
- ~~**Architecture: DisruptionManagerBase ABC + Module Extraction**~~ ✅ Done
- ~~**Code Quality Audit + Test Suite (216 tests)**~~ ✅ Done

---

## v5.2.0 — Indefinite God Mode + Dupe Engine + Hardening ✅

**Released:** 2026-04-09

Breakthrough disruption release. Solved the red-chain kick limit, added precise inventory duplication, hardened the entire codebase to nation-state grade, and overhauled distribution with a proper Windows installer and in-app auto-update.

- ~~**Pulse-Cycling God Mode** — Three modes (Classic/Pulse/Infinite). Block/flush cycling bypasses DayZ's connection quality monitor for indefinite red-chain duration. Packet classification passes keepalive probes while blocking state updates.~~ ✅ Done
- ~~**Dupe Engine** — Dedicated `DupeEngineModule` with IDLE→PREP→CUT→RESTORE state machine. Precise timed disconnect-reconnect for inventory duplication. Timer or manual trigger. Multi-cycle support.~~ ✅ Done
- ~~**Extended Lag** — Connection-preserving lag for 30s+ durations. Auto-activates keepalive pass-through for lag_delay ≥ 5s.~~ ✅ Done
- ~~**Teleportation** — Extended block phases accumulate position desync. Flush phase reconciles entire delta at once — visual teleport from target's perspective.~~ ✅ Done
- ~~**Security Hardening** — CNSA 2.0 crypto (AES-256-GCM, HMAC-SHA384, PBKDF2-SHA-512 600K). Atomic writes + HMAC companion files. TLS 1.3 minimum. Strict allowlist validation. Hash-chained audit logging. Machine-bound encrypted secrets.~~ ✅ Done
- ~~**Codebase Audit** — Multi-pass principal-engineer audit. `from __future__ import annotations` across all files. Lazy singletons, lazy deps, public properties. All 49 non-GUI modules import cleanly.~~ ✅ Done
- ~~**Validation Updates** — `dupe` and `pulse` methods registered. All v5.2 parameter ranges added. Lag/godmode caps raised to 120s.~~ ✅ Done
- ~~**Windows Installer** — Inno Setup installer with Add/Remove Programs registration, MOTW stripping, upgrade-in-place, desktop/Start Menu shortcuts. Windows manifest + VS_VERSION_INFO for SmartScreen trust. 4-stage build pipeline with optional code signing.~~ ✅ Done
- ~~**Auto-Update (Download & Install)** — Updater downloads installer directly from GitHub Releases with progress feedback, strips MOTW, launches silently. 3-button update dialog in dashboard.~~ ✅ Done
- ~~**Getting Started Guide** — Built-in 10+ section collapsible guide accessible from sidebar (🚀). Covers every feature for new users.~~ ✅ Done
- ~~**Collapsible & Reorderable Sections** — All 9 control sections in Clumsy Control wrapped in CollapsibleCard widgets with toggle headers and reorder buttons.~~ ✅ Done
- ~~**Splash Screen Overhaul** — Enlarged, explicit pixel anchors (no overlap), slower cinematic animations.~~ ✅ Done
- ~~**Extraction Fix** — UPX exclusions for large DLLs, tcl/tk data removal. Fixes decompression failures on low-spec Windows 10.~~ ✅ Done

---

## v5.3.0 — GUI Integration & Live Visualization

**Status:** Next up

Wire the v5.x engine features into the UI so users can use God Mode Pulse, Dupe Engine, and extended lag without hand-editing params. Plus code signing and distribution polish.

- **God Mode Pulse UI** — Block/flush timing sliders, mode selector (Classic/Pulse/Infinite), live cycle visualization showing block/flush phases.
- **Dupe Engine UI** — PREP/CUT/RESTORE button with phase indicator, cut duration slider, cycle count spinner, manual trigger button.
- **Extended Lag UI** — Connection preservation toggle, keepalive interval slider, queue depth indicator.
- **Statistical Model UI** — Sliders and distribution preview graphs for Gilbert-Elliott, Pareto, token bucket, correlation.
- **Packet Classifier Dashboard** — Live packet category breakdown. Per-category disruption rule editor.
- **Tick Rate Visualizer** — Real-time tick estimation display with confidence indicator.
- **Asymmetric Preset Selector** — Dropdown/card UI for the 14 named presets with effectiveness ratings.
- **Game State Indicator** — Live GameStateDetector output (MENU, LOADING, IN_GAME_IDLE, COMBAT, DISCONNECTED).
- **Stealth Pattern Selector** — Natural pattern chooser with preview waveform.
- **Code Signing** — Obtain EV code signing certificate, sign exe + installer for instant SmartScreen trust. Wire into `build.bat` Stage 2.
- **Installer UX** — Custom installer banner/wizard images, license agreement page, optional portable mode checkbox.

---

## v5.4.0 — Data Collection & ML Training

**Status:** Planned

Build the infrastructure to collect real-world packet data and train the classifier beyond heuristics.

- **Packet Capture Pipeline** — Record labeled packet traces during controlled DayZ sessions. Export as training datasets.
- **ML Packet Classifier** — Replace rule-based heuristics with a lightweight trained model. Online learning.
- **Disruption Effectiveness Database** — Systematic mapping of [params] → [desync duration, invulnerability window, freeze threshold]. Per-DayZ-version tracking.
- **Server Behavior Catalog** — Document freeze system trigger thresholds, kick thresholds, modded vs official tolerance.
- **Auto-Optimize Engine** — SessionLearner feeds back into SmartDisruptionEngine. Per-server/scenario preset recommendations.

---

## v6.0.0 — Stealth & Platform

**Status:** Future

Reduce detection surface and expand platform support.

- **WinDivert Alternative Research** — NDIS filter driver or WFP callout driver to reduce signature exposure.
- **Overlapped I/O** — Async packet processing with OVERLAPPED structures. Full batch pipeline.
- **Custom Filter Compilation** — Optimized WinDivert filter bytecode for game traffic patterns.
- **Linux Support** — `tc`/`iptables` backend implementing DisruptionEngineBase. Same PyQt6 GUI.
- **BattlEye Monitoring** — Track detection rule updates. Automated behavioral pattern rotation.

---

## Stretch Goals (No Timeline)

- **Steam Integration** — Pull player names from Steam for friendlier device identification.
- **DayZ Server Browser** — Embedded server list with one-click connect and per-server disruption profiles.
- **Replay System** — Record and replay disruption sessions for testing and consistency.
- **Mobile Companion** — Lightweight mobile app for monitoring active disruptions and triggering presets remotely.
- **Community Hub** — In-app feed for shared disruption profiles, presets, and configs.
- **Voice Macro Chains** — Chain voice commands into multi-step disruption sequences.

---

## Completed

- [x] **v3.0.0** — The Strip. 89% code reduction. 3-view dashboard. Native WinDivert engine.
- [x] **v3.0.1** — Production hardening. Atomic settings writes. Full QSS coverage. IP sanitization.
- [x] **v3.1.0** — Smart Mode. AI auto-tune. Network profiler. LLM advisor. Session tracking. Profile system. Tray mode.
- [x] **v3.2.0** — Multi-target. Scheduled disruptions. Macro chains. Profile import/export.
- [x] **v3.3.0** — Network Intelligence. Traffic monitor. Latency overlay. Port scanner.
- [x] **v3.3.1** — Hardening pass. 11 fixes across thread safety, atomic writes, frozen-exe paths.
- [x] **v3.4.0** — God Mode + Voice + GPC. Directional lag. Whisper STT. CronusZEN integration.
- [x] **v3.5.0** — Live Stats Dashboard. Real-time packet counters. Engine stats API.
- [x] **v4.0.0** — Platform & Extensibility. Plugin API. CLI mode. Auto-updater.
- [x] **v5.0.0** — God Mode Engineering. 7 deep-research phases. Statistical models. Packet classification. Tick sync. 14 asymmetric presets. Batch API. ML traffic analysis. Stealth patterns. 216 tests.
- [x] **v5.2.0** — Indefinite God Mode + Dupe Engine + Hardening. Pulse-cycling god mode. Dupe engine state machine. Extended lag. CNSA 2.0 security. Full codebase audit. Windows installer + auto-update. Getting Started guide. Collapsible/reorderable sections. Splash screen overhaul. Extraction fix for low-spec machines.
- [x] **v5.2.1** — Map fix + resilient optional deps. iZurvive QtWebEngine loads under admin token via `--no-sandbox` Chromium flag. Optional dep imports (whisper, sounddevice) wrapped in broad exception handlers so missing/broken bindings no longer crash startup.
- [x] **v5.2.2** — Build hardening: torch/whisper isolation. PyInstaller isolated analyzer no longer crashes on `torch\lib\c10.dll` (WinError 1114 / access violation) every build. `whisper` and `openai-whisper` added to `dupez.spec` excludes alongside `torch`. `is_voice_available()` probes in `voice_panel.py` and `clumsy_control.py` deferred from module import to first view instantiation, wrapped in broad exception handlers.
- [x] **v5.2.3** — Version display fix + single source of truth. Dashboard title bar and HTTP `User-Agent` header now report the actual build version. `app/core/updater.py` and `app/core/secure_http.py` both had `"5.2.0"` hardcoded — fixed by pointing at a new `app/__version__.py` single-source-of-truth module. Hardcoding versions anywhere under `app/` is now explicitly forbidden.
- [x] **v5.2.4** — Installer architecture fix + manifest sync. Installer now lands in `C:\Program Files\DupeZ` on 64-bit Windows instead of `C:\Program Files (x86)\DupeZ` — added missing `ArchitecturesInstallIn64BitMode=x64` / `ArchitecturesAllowed=x64` directives to `installer.iss`. `dupez.manifest` `assemblyIdentity` version bumped from the stale `5.2.0.0` it had been stuck at since v5.2.0, now tracked in the per-release bump checklist.

---

Got a feature request? [Open an issue](https://github.com/GrihmLord/DupeZ/issues).
