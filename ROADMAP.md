# DupeZ Roadmap

What's coming next. Priorities shift based on community feedback — open an issue or PR if something here matters to you.

---

## v5.7.0 — GUI Integration & Live Visualization

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

## v6.0.0 — Stealth & Platform

**Status:** Future

Reduce detection surface and expand platform support.

- **WinDivert Alternative Research** — NDIS filter driver or WFP callout driver to reduce signature exposure.
- **Overlapped I/O** — Async packet processing with OVERLAPPED structures. Full batch pipeline.
- **Custom Filter Compilation** — Optimized WinDivert filter bytecode for game traffic patterns.
- **Linux Support** — `tc`/`iptables` backend implementing DisruptionEngineBase. Same PyQt6 GUI.
- **BattlEye Monitoring** — Track detection rule updates. Automated behavioral pattern rotation.
- **Packet Capture Pipeline** — Record labeled packet traces during controlled DayZ sessions. Export as training datasets.
- **ML Packet Classifier** — Replace rule-based heuristics with a lightweight trained model. Online learning.
- **Disruption Effectiveness Database** — Systematic mapping of [params] → [desync duration, invulnerability window, freeze threshold]. Per-DayZ-version tracking.
- **Server Behavior Catalog** — Document freeze system trigger thresholds, kick thresholds, modded vs official tolerance.

---

## Stretch Goals (No Timeline)

- **Steam Integration** — Pull player names from Steam for friendlier device identification.
- **DayZ Server Browser** — Embedded server list with one-click connect and per-server disruption profiles.
- **Replay System** — Record and replay disruption sessions for testing and consistency.
- **Mobile Companion** — Lightweight mobile app for monitoring active disruptions and triggering presets remotely.
- **Community Hub** — In-app feed for shared disruption profiles, presets, and configs.
- **Voice Macro Chains** — Chain voice commands into multi-step disruption sequences.

---

## Released

### v5.6.0 — MAC-Spoof Spike + A2S Cut Verification + Learning-Loop Closure ✅

**Released:** 2026-04-14

Three-frontier release closing the observability loop on cut effectiveness, hardening ARP poison against consumer-router anti-spoof heuristics, and filling in the vendor column for every IEEE-registered OUI.

- ~~**MAC-spoof spike** — Gateway-facing poison now emits opcode-2 reply with L2 source spoofed to target MAC + opcode-1 request variant. Defeats ASUS/Netgear/Ubiquiti anti-spoof and RFC 826 strict-mode routers.~~ ✅ Done
- ~~**A2S cut verifier → episode recorder** — `CutVerifier` writes `cut_verified` events on every state transition. `engine_stop` carries peak `max_cut_state`.~~ ✅ Done
- ~~**`LearningLoop.cut_effectiveness`** — Per-bucket severance aggregation distinct from recommend(). Enables auto-tuner preset switching when current preset can't sever.~~ ✅ Done
- ~~**Full scapy MANUFDB vendor fallback** — `lookup_vendor()` chains to ~35k-entry IEEE OUI database on curated-table miss.~~ ✅ Done
- ~~**Smoketest tool** — `tools/smoketest_scan_and_lag.py` end-to-end pipeline validator with distinct exit codes per failure class.~~ ✅ Done

---

### v5.5.0 — WiFi ARP Spoof + Audit Cleanup ✅

**Released:** 2026-04-12

WiFi same-network interception and technical debt cleanup from the Phase C codebase audit.

- ~~**WiFi Same-Network Mode** — ARP cache poisoning for targets on the same WiFi (not behind hotspot). Auto-detected by `target_profile.py`, managed by `arp_spoof.py`.~~ ✅ Done
- ~~**V1 Dupe Engine Removed** — Deprecated module deleted; mechanics docstring preserved in v2. `DupeMethod.LEGACY` is self-contained.~~ ✅ Done
- ~~**Shared Widget Extraction** — `CollapsibleCard` moved to `app/gui/widgets/` for cross-panel reuse.~~ ✅ Done
- ~~**Type Annotation & PRNG Fixes** — `_finalize_calibration` return type, `_LCG` class replacing module-level mutable state.~~ ✅ Done

---

### v5.4.0 — Account Tracker Overhaul + UI Polish + Bug Fixes ✅

**Released:** 2026-04-12

Feature release focused on the Account Tracker, theme stability, and overall UI polish. Tracker is now a full-featured multi-account management tool. Six bugs from v5.3.0 are fixed; Help panel and About dialog rewritten.

- ~~**Account Tracker overhaul** — Notes field, multi-select, right-click context menu, quick-filter status chips, duplicate account, row numbering, last-modified display, editable dropdowns, upgraded bulk operations with scope (All/Selected/Filtered) and export-subset.~~ ✅ Done
- ~~**GPU auto-detection fallback** — `feature_flag.get_arch()` probes for a discrete GPU and selects `split` or `inproc` when no env var or compiled default is set.~~ ✅ Done
- ~~**About dialog rewrite** — Broader tagline, dynamic ARCH row (Split vs In-process), condensed credits, GitHub + Close button pair.~~ ✅ Done
- ~~**Help panel rewrite** — All 11 sections updated to match actual codebase — shortcuts, troubleshooting, feature descriptions.~~ ✅ Done
- ~~**Nav button layout hardening** — `#nav_btn` object-name selector + explicit re-application after theme switch; fixes theme-switch sidebar breakage.~~ ✅ Done
- ~~**Rainbow theme auto-animate** — `apply_theme("rainbow")` now starts the animation timer.~~ ✅ Done
- ~~**v5.3.0 regression fixes** — "Engine unavailable no admin" false banner, slow map despite GPU (both root-caused to `_BUILD_DEFAULT_ARCH` wrong in GPU variant), overlapping Clumsy Control sections, settings dialog return-type typo, Account Tracker duplicate-import + signal-stacking + reference-sharing mutations.~~ ✅ Done

---

### v5.3.0 — Split-Elevation Architecture + Hardware Map + Preset Collapse ✅

**Released:** 2026-04-11

First release shipping **two user-facing binaries from one codebase**: `DupeZ-GPU.exe` (asInvoker, split-arch, hardware-rasterized map) and `DupeZ-Compat.exe` (requireAdministrator, legacy inproc, CPU-raster fallback). Lands the ADR-0001 split-elevation architecture end-to-end, collapses the preset taxonomy from 8 entries to 5, reorganizes packaging files into a dedicated `packaging/` subtree, and beefs up hostname resolution in the scanner with a 4-stage fallback chain including bundled zeroconf mDNS.

- ~~**Split-elevation architecture (ADR-0001)** — GUI runs at Medium IL for Chromium GPU init; firewall/WinDivert ops forwarded to an elevated helper (`dupez_helper.py`) over IPC. Helper is the same frozen exe re-invoked with `--role helper --parent-pid N`, dispatched before any `app.*` import so it never boots the GUI.~~ ✅ Done
- ~~**Dual-variant PyInstaller build pipeline** — `packaging/build_variants.bat` drives both specs (`dupez_gpu.spec` + `dupez_compat.spec`) through a shared `build_common.py` factory that writes a per-variant `_build_default.py` before Analysis, baking in the compiled-in `DUPEZ_ARCH` default.~~ ✅ Done
- ~~**Hardware raster tier resolver** — `app/gui/map_host/renderer_tier.py` picks tier1_hw / tier2_swiftshader / tier3_cpu based on env + GPU probe and applies the matching Chromium flags before any PyQt6 import. Embedded iZurvive map now runs GPU-accelerated under split mode.~~ ✅ Done
- ~~**Preset taxonomy collapse 8 → 5** — Merged Heavy/Light Lag into a single `Lag` preset tuned by sliders; removed `God Mode Aggressive` and `Desync` as redundant. Final set: Red Disconnect, Lag, God Mode, Dupe Mode, Custom.~~ ✅ Done
- ~~**4-stage hostname resolution chain** — `gethostbyaddr` → `getfqdn` → NetBIOS → mDNS (zeroconf) → synthesized `<vendor>-<mac_suffix>` fallback. Hostname column in the GUI is never blank. zeroconf is now a hard runtime dep and bundled into hiddenimports.~~ ✅ Done
- ~~**Packaging reorganization** — All build artifacts moved under `packaging/`. Spec files use `HERE` / `ROOT` path split; Inno Setup uses `SourceDir=..`; batch drivers `pushd "%~dp0.."`. Cleaner repo root, existing `Source:` paths unchanged.~~ ✅ Done
- ~~**Root cleanup + AA_ShareOpenGLContexts** — Deleted transient crash dumps / cache dirs; `.gitignore` covers them now. `AA_ShareOpenGLContexts` set on `QCoreApplication` before `QApplication` so Qt 6 WebEngine + GL-adjacent widgets coexist cleanly.~~ ✅ Done

---

### v5.2.0 — Indefinite God Mode + Dupe Engine + Hardening ✅

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

### v5.0.0 — God Mode Engineering ✅

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

### v4.0.0 — Platform & Extensibility ✅

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
- **Linux Support** — Replace WinDivert dependency with `tc`/`iptables` backend for Linux. *(Deferred to v6.0.0)*

---

### v3.5.0 — Live Stats + Distribution Polish ✅

**Released:** 2026-04-03

- ~~**Live Stats Dashboard** — Real-time packet counters (processed, dropped, passed, inbound, outbound) with auto-refresh. Drop rate bar, active engine count, per-device breakdown table.~~ ✅ Done
- ~~**Engine Stats API** — `get_stats()` on NativeDisruptEngine, `get_all_engine_stats()` aggregator on ClumsyNetworkDisruptor, `get_engine_stats()` on AppController.~~ ✅ Done
- ~~**PyInstaller Spec Update** — Hidden imports for optional voice and GPC dependencies so frozen exe bundles correctly.~~ ✅ Done
- ~~**Version Bump** — 3.3.0 → 3.5.0 across all modules, title bar, about dialog, and AppUserModelID.~~ ✅ Done

---

### v3.4.0 — God Mode + Voice + GPC ✅

**Released:** 2026-04-02

- ~~**God Mode / Directional Lag** — Inbound packets delayed while outbound passes untouched. Target freezes on others' screens while your actions register in real time. Configurable inbound lag (0–5000ms) and optional inbound drop.~~ ✅ Done
- ~~**100% Drop Fidelity** — Drop module uses packet discard instead of re-inject. True 100% when configured.~~ ✅ Done
- ~~**Direction-Aware Filtering** — All disruption modules implement `matches_direction()`. WinDivert outbound bit detection for per-packet direction classification.~~ ✅ Done
- ~~**Voice Control** — Push-to-talk voice commands via OpenAI Whisper (local, offline). Speak disruption commands, LLM advisor interprets into configs. Model selection (tiny/base/small), mic selection.~~ ✅ Done
- ~~**GPC / CronusZEN Support** — Parse .gpc files, generate scripts synced with DupeZ timing, export to Zen Studio. 4 built-in templates (Auto Dupe, Rapid Fire, God Mode Actions, Anti Recoil). USB device detection.~~ ✅ Done
- ~~**Smart Engine God Mode Strategy** — 6th goal strategy with hotspot-aware tuning.~~ ✅ Done
- ~~**LLM Advisor God Mode Fallback** — Keyword-based godmode interpretation when no LLM available.~~ ✅ Done

---

### v3.3.0 — Network Intelligence ✅

**Released:** 2026-04-02

- ~~**Live Traffic Monitor** — Real-time per-interface bandwidth table with rate calculation and total throughput bar.~~ ✅ Done
- ~~**Connection Mapper** — Visual topology showing which devices are talking to which external IPs. Live-updating table + text topology, filter by TCP/UDP/Established/Gaming.~~ ✅ Done
- ~~**Latency Overlay** — Floating transparent always-on-top ping/jitter widget with sparkline graph. Draggable.~~ ✅ Done
- ~~**Port Scanner Integration** — Standalone port scanner with Common/Gaming/Web/Full port sets and service identification.~~ ✅ Done

---

### v3.2.0 — Multi-Target & Scheduling ✅

**Released:** 2026-04-02

- ~~**Multi-Device Disruption** — MULTI toggle enables simultaneous disruption of multiple selected devices.~~ ✅ Done
- ~~**Scheduled Disruptions** — Timed Disrupt button with configurable duration and delay. Auto-stop after timer expires.~~ ✅ Done
- ~~**Disruption Macros** — Chain disruption steps in sequence with Quick Macro and saved macro support.~~ ✅ Done
- ~~**Import/Export Profiles** — IMPORT/EXPORT buttons in profile panel. Share profiles as standalone JSON files.~~ ✅ Done

---

### v3.1.0 — Smart Mode + Quality of Life ✅

**Released:** 2026-04-02

- ~~**Profile System** — Save/load named disruption profiles per game or scenario.~~ ✅ Done
- ~~**Session History** — Log of past disruption sessions with timestamps, targets, methods, and durations.~~ ✅ Done
- ~~**AI Auto-Tune Engine** — Network profiler + ML-based parameter optimizer + LLM advisor.~~ ✅ Done
- ~~**Tray Mode** — Minimize to system tray with hotkey toggle. Ctrl+Shift+D global hotkey.~~ ✅ Done
- ~~**Device Nicknames** — Assign friendly names to scanned devices via right-click context menu.~~ ✅ Done
- ~~**Scan Result Caching** — Persist discovered devices across restarts.~~ ✅ Done

---

## Completed Release Index

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
- [x] **v5.3.0** — Split-elevation architecture + hardware-rasterized map + preset collapse. Dual-variant builds (`DupeZ-GPU.exe` + `DupeZ-Compat.exe`). ADR-0001 helper-role dispatch, feature-flag routing in blocker, renderer tier resolver, 4-stage hostname chain with bundled zeroconf, packaging subtree reorganization, preset taxonomy 8 → 5.
- [x] **v5.4.0** — Account Tracker overhaul (multi-select, context menu, filter chips, notes, bulk ops with scope, export-subset), GPU auto-detection fallback, About/Help rewrites, nav-button theme-switch hardening, rainbow auto-animate, six v5.3.0 regression fixes.
- [x] **v5.5.0** — WiFi same-network ARP-spoof mode, `CollapsibleCard` extraction, `ml_classifier` PRNG refactor, deprecated Dupe Engine v1 removal.
- [x] **v5.6.0** — MAC-spoof spike (gateway-facing opcode 1+2 with L2 target-MAC impersonation), A2S cut verifier plumbed into episode recorder (`cut_verified` events + `max_cut_state` on `engine_stop`), `LearningLoop.cut_effectiveness` severance aggregation, full scapy MANUFDB vendor fallback (~35k OUI), end-to-end smoketest tool.
- [x] **v5.6.1** — Updater stability: equal-tag short-circuit in `UpdateChecker.check_sync` to suppress spurious re-prompts; `installer_url` pinned to the stable versionless `releases/latest/download/DupeZ_Setup.exe` alias; `dupez.manifest` / `dupez_compat.manifest` versions resynced from stale `5.5.0.0`.
- [x] **v5.6.2** — Nation-state hardening. Closed §9.2 with the SP 800-63B / CNSA 2.0 second-factor gate (`app/core/second_factor.py`) wired into elevation, plugin loader, and offsec runner. Auto-update fail-closed behind pinned Ed25519 signed-manifest verification (`app/core/update_verify.py` + `scripts/sign-release.py`). Fixed DayZ tracker CSV/XLSX import (BOM, delimiter sniffing, header synonyms, off-by-one). Routed offsec CLI INFO chatter to stderr. New pytest suite + Windows CI matrix. Cert: **CERTIFIED — Nation-State Grade**.
- [x] **v5.6.3** — Crash-safety + duping audit hardening. `faulthandler` enabled at process entry so C-extension segfaults (WinDivert, Qt, Chromium GPU) leave a usable traceback. Pipe-disconnect recovery in `DisruptionManagerProxy._call` — helper death is now recoverable instead of requiring a GUI restart. `_shutdown_cleanup` routed through `get_disruption_manager()` so split-mode tears down the elevated helper over IPC instead of no-op'ing the in-process singleton. Doc drift fixes (Red Disconnect 95% → 100% drop in help panel) and dead `taskkill dupez_helper.exe` removed from the variant build script.

---

Got a feature request? [Open an issue](https://github.com/GrihmLord/DupeZ/issues).
