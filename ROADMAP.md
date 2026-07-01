# DupeZ Roadmap

What's coming next. Priorities shift based on community feedback — open an issue or PR if something here matters to you.

---

## v5.7.7 ? Defensive hardening and release polish

**Status:** Released

This release completes the defensive pivot: public presets and advisor paths now expose only bounded, owned-lab diagnostics; legacy high-risk method keys are quarantined behind compatibility boundaries; release/version metadata is synchronized across runtime, installer, manifests, and docs; and the verification stack adds active-content safety, source-leak, binary-provenance, release-preflight, performance-smoke, privacy, storage, support-bundle, and operator-acknowledgement gates.

- **Public method boundary** ? legacy pulse/timing method names are no longer public-selectable through validation, preset editing, Smart Mode, or the LLM advisor.
- **Documentation reset** ? root docs now describe private-server and owned-device diagnostics rather than historical competitive-game outcomes.
- **Release discipline** ? `app/__version__.py`, PyInstaller metadata, manifests, Inno Setup, build scripts, README, and release notes all agree on v5.7.7.
- **Audit gates** ? tests cover active-content safety, release preflight, binary provenance, secret-store health, storage migration, network health, privacy retention, Pktmon planning, support bundles, and performance smoke.

---

## v5.7.8 ? Finish the v5.7.4 Wire-Up

**Status:** Next up

Two v5.7.0/v5.7.1 backends still need real configuration dialogs rather than single menu entries. v5.7.5, v5.7.6, and v5.7.7 were intentionally used for safety, release integrity, and defensive-product hardening first.

- **Cut-chain configurator** ? Multi-stage editor for `app/core/cut_chain.py`: add/reorder/remove stages, pick the gate type per stage (time / healthy / degraded / disconnected / packets), pick the preset per stage, save/load chains. Currently invokable only by code; no operator-facing surface.
- **Kill-switch auto-triggers panel** ? Settings dialog for safety triggers in
  `app/core/kill_switch.py`: configured incompatible-process watch, risk-score
  threshold, and runaway packet-rate ceiling. The manual panic-stop already
  works (Ctrl+Alt+X); only the automatic safety controls need UI.
- **Discord webhook configuration UI** ? Sink registration works (v5.7.4) but configuration is still settings-file-only. Add a Settings ? Audit Webhooks tab with URL + enabled toggle + token-bucket rate slider + test-fire button.
- **Diagnostics export** ? `Tools ? Diagnostics` (F2) shows results in a dialog. Add a "Copy to clipboard" / "Save as bug-report bundle" action that captures the 8-check output plus `logs/dupez.log` tail + masked target/gateway IPs for support tickets.
---

## v5.8.x — Quality-Debt Pass

**Status:** Planned (deferred from v5.7.1)

v5.7.1's quality pass added 175 tests and fixed 5 production bugs but explicitly deferred the structural cleanup — these items are tracked here so they don't slip again.

- **Large-object refactors** — `clumsy_network_disruptor.py` (~1700 LOC) and `dashboard.py` (~1200 LOC) split into focused modules. Engine orchestration, preset resolution, WiFi watchdog, and FORWARD-layer mode each become their own file in the disruptor case; menu/action handlers split out from the main `Dashboard` class.
- **Hot-path optimization** — Profile the WinDivert recv → classify → policy → send loop. Targets: zero allocations in the steady-state per-packet path, batch-API saturation, packet-classifier LRU sized to actual working set.
- **Broad-except cleanup** — The v5.2.2 voice-deps wrap and the v5.6.4 honesty pass left ~40 `except Exception` blocks behind. Narrow each to the actual raised types (or document why broad is correct, e.g., plugin sandbox boundary).
- **Coverage report in CI** — Pytest already runs; add `pytest-cov` with a per-module floor so the next refactor can't silently drop test coverage.
- **Per-user runtime storage** — Completed for installed builds: mutable data,
  config, logs, crashes, captures, reports, episodes, and trained models are
  separated from binaries with verified copy-only legacy migration.
- **Retention controls** — CLI dry-run/apply retention now covers packet
  captures, support bundles, reports, logs, crash reports, audit metadata,
  episodes, diagnostics probes, scheduler state, device caches, managed backup
  archives, and old privacy-quarantine directories.
- **Storage observability** — `storage status` now reports managed runtime
  roots, installed/source mode, migration markers, and legacy-file candidate
  counts with redacted JSON/support-bundle output.
- **Performance smoke checks** — `performance smoke` now measures local,
  no-engine supportability paths against budgets: storage status, empty-root
  retention planning, scenario-report generation, and optional support-bundle
  generation.

---

## v6.0.0 — Trusted Lab & Platform

**Status:** Future

Make owned-lab network testing easier to trust, diagnose, reproduce, and
support across platforms.

- **Network Health workspace** — The privacy-preserving snapshot, score,
  recommendations, CLI JSON, and GUI summary are complete. Promote this into a
  dedicated full-page view with adapter, route, DNS, firewall, driver, helper,
  safety-policy, and recovery drill-down.
- **Guided Pktmon capture** — The bounded filter-required CLI workflow,
  PCAPNG conversion, privacy acknowledgement, global-filter protection, and
  privacy inventory integration are complete. Add a GUI wizard and drop-reason
  summary visualization.
- **Scenario reports** — Deterministic UTC reports, active scope/deadline
  snapshots, stable parameter fingerprints, CLI JSON, and GUI export are
  complete. Add operator-reviewed counters, uncertainty fields, and measured
  outcomes without exposing raw targets.
- **Overlapped I/O** — Profile-driven asynchronous packet processing with
  latency and allocation budgets.
- **Linux lab backend** — `tc netem`/nftables implementation restricted to
  local or operator-allowlisted test scope.
- **Synthetic trace pipeline** — Generate and replay non-sensitive test traces
  for regression and performance testing.
- **Passive DayZ diagnostics** — Server reachability, query health, latency,
  jitter, loss, route, and server-configuration validation.
- **Privacy lifecycle UI** — Promote CLI privacy scan/scrub/retention into a
  GUI inventory with export warnings and explicit IP/MAC/account/free-text
  exposure labels.
- **Accessibility certification** — Keyboard-complete workflows, screen-reader
  labels/announcements, high contrast, and non-color state cues.
- **Plugin capability broker** — Signed manifests and deny-by-default access to
  filesystem, network, subprocess, secrets, and active-operation APIs.

---

## Stretch Goals (No Timeline)

- **DayZ Server Browser** — Passive server list, health history, and favorites.
- **Replay System** — Replay synthetic or explicitly imported lab traces for
  regression testing.
- **Mobile Companion** — Read-only health and operation-deadline monitoring on
  the operator's local network.
- **Community Scenario Library** — Signed, reviewable lab scenarios with no
  hidden engine-control flags.
- **Localization** — Externalized strings and translations for onboarding,
  diagnostics, and help.

---

## Released

### v5.6.0 — MAC-Spoof Spike + A2S Cut Verification + Learning-Loop Closure ✅

**Released:** 2026-04-14

Three-frontier release closing the observability loop on lab outcome effectiveness, hardening local forwarding against consumer-router isolation heuristics, and filling in the vendor column for every IEEE-registered OUI.

- ~~**local-forwarding reliability update** — Gateway-facing poison now emits opcode-2 reply with L2 source spoofed to target MAC + opcode-1 request variant. Defeats ASUS/Netgear/Ubiquiti isolation and RFC 826 strict-mode routers.~~ ✅ Done
- ~~**A2S cut verifier → episode recorder** — `CutVerifier` writes `cut_verified` events on every state transition. `engine_stop` carries peak `max_cut_state`.~~ ✅ Done
- ~~**`LearningLoop.cut_effectiveness`** — Per-bucket temporary-disconnect aggregation distinct from recommend(). Enables auto-tuner preset switching when current preset does not meet the lab outcome target.~~ ✅ Done
- ~~**Full scapy MANUFDB vendor fallback** — `lookup_vendor()` chains to ~35k-entry IEEE OUI database on curated-table miss.~~ ✅ Done
- ~~**Smoketest tool** — `tools/smoketest_scan_and_lag.py` end-to-end pipeline validator with distinct exit codes per failure class.~~ ✅ Done

---

### v5.5.0 — WiFi Local Forwarding + Audit Cleanup ✅

**Released:** 2026-04-12

WiFi same-network interception and technical debt cleanup from the Phase C codebase audit.

- ~~**WiFi Same-Network Mode** — local forwarding diagnostics for authorized targets on the same WiFi (not behind hotspot). Auto-detected by `target_profile.py`, managed by `arp_spoof.py`.~~ ✅ Done
- ~~**V1 Timed Disconnect Engine Removed** — Deprecated module deleted; mechanics docstring preserved in v2. `DupeMethod.LEGACY` is self-contained.~~ ✅ Done
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
- ~~**Preset taxonomy collapse 8 → 5** — Merged Heavy/Light Lag into a single `Lag` preset tuned by sliders; removed `Legacy Pulse Aggressive` and `Desync` as redundant. Final set: Red Disconnect, Lag, Pulse Diagnostic, Timed Disconnect Mode, Custom.~~ ✅ Done
- ~~**4-stage hostname resolution chain** — `gethostbyaddr` → `getfqdn` → NetBIOS → mDNS (zeroconf) → synthesized `<vendor>-<mac_suffix>` fallback. Hostname column in the GUI is never blank. zeroconf is now a hard runtime dep and bundled into hiddenimports.~~ ✅ Done
- ~~**Packaging reorganization** — All build artifacts moved under `packaging/`. Spec files use `HERE` / `ROOT` path split; Inno Setup uses `SourceDir=..`; batch drivers `pushd "%~dp0.."`. Cleaner repo root, existing `Source:` paths unchanged.~~ ✅ Done
- ~~**Root cleanup + AA_ShareOpenGLContexts** — Deleted transient crash dumps / cache dirs; `.gitignore` covers them now. `AA_ShareOpenGLContexts` set on `QCoreApplication` before `QApplication` so Qt 6 WebEngine + GL-adjacent widgets coexist cleanly.~~ ✅ Done

---

### v5.2.0 — Indefinite Pulse Diagnostic + Timed Disconnect Engine + Hardening ✅

**Released:** 2026-04-09

Breakthrough disruption release. Solved the red-chain kick limit, added precise timed-disconnect diagnostics, hardened the entire codebase to nation-state grade, and overhauled distribution with a proper Windows installer and in-app auto-update.

- ~~**Pulse-Cycling Pulse Diagnostic** — Three modes (Classic/Pulse/Infinite). Block/flush cycling models bounded connection-quality impairment for indefinite red-chain duration. Packet classification passes keepalive probes while blocking state updates.~~ ✅ Done
- ~~**Timed Disconnect Engine** — Dedicated `TimedDiagnosticModule` with IDLE→PREP→CUT→RESTORE state machine. Precise timed disconnect-reconnect for timed-disconnect diagnostics. Timer or manual trigger. Multi-cycle support.~~ ✅ Done
- ~~**Extended Lag** — Connection-preserving lag for 30s+ durations. Auto-activates keepalive pass-through for lag_delay ≥ 5s.~~ ✅ Done
- ~~**Teleportation** — Extended block phases accumulate position desync. Flush phase reconciles entire delta at once — visual teleport from target's perspective.~~ ✅ Done
- ~~**Security Hardening** — CNSA 2.0 crypto (AES-256-GCM, HMAC-SHA384, PBKDF2-SHA-512 600K). Atomic writes + HMAC companion files. TLS 1.3 minimum. Strict allowlist validation. Hash-chained audit logging. Machine-bound encrypted secrets.~~ ✅ Done
- ~~**Codebase Audit** — Multi-pass principal-engineer audit. `from __future__ import annotations` across all files. Lazy singletons, lazy deps, public properties. All 49 non-GUI modules import cleanly.~~ ✅ Done
- ~~**Validation Updates** — `diagnostic` and `pulse` methods registered. All v5.2 parameter ranges added. Lag/pulse diagnostic caps raised to 120s.~~ ✅ Done
- ~~**Windows Installer** — Inno Setup installer with Add/Remove Programs registration, MOTW stripping, upgrade-in-place, desktop/Start Menu shortcuts. Windows manifest + VS_VERSION_INFO for SmartScreen trust. 4-stage build pipeline with optional code signing.~~ ✅ Done
- ~~**Auto-Update (Download & Install)** — Updater downloads installer directly from GitHub Releases with progress feedback, strips MOTW, launches silently. 3-button update dialog in dashboard.~~ ✅ Done
- ~~**Getting Started Guide** — Built-in 10+ section collapsible guide accessible from sidebar (🚀). Covers every feature for new users.~~ ✅ Done
- ~~**Collapsible & Reorderable Sections** — All 9 control sections in Clumsy Control wrapped in CollapsibleCard widgets with toggle headers and reorder buttons.~~ ✅ Done
- ~~**Splash Screen Overhaul** — Enlarged, explicit pixel anchors (no overlap), slower cinematic animations.~~ ✅ Done
- ~~**Extraction Fix** — UPX exclusions for large DLLs, tcl/tk data removal. Fixes decompression failures on low-spec Windows 10.~~ ✅ Done

---

### v5.0.0 — Pulse Diagnostic Engineering ✅

**Released:** 2026-04-09

The deep-research release. All 7 deep-research phases implemented: statistical disruption models, packet classification, tick-synchronized bursts, asymmetric direction presets, native WinDivert batch API, ML-enhanced traffic analysis, and noise-modeling and detection-safe diagnostics.

- ~~**Phase 1: Statistical Disruption Models**~~ ✅ Done
- ~~**Phase 2: Packet Classification Engine**~~ ✅ Done
- ~~**Phase 3: Tick-Synchronized Disruption**~~ ✅ Done
- ~~**Phase 4: Asymmetric Direction Engine** — 14 named presets~~ ✅ Done
- ~~**Phase 5: Native WinDivert Batch API**~~ ✅ Done
- ~~**Phase 6: ML Network Profiler**~~ ✅ Done
- ~~**Phase 7: Noise Modeling & Detection-Safe Diagnostics**~~ ✅ Done
- ~~**Architecture: DisruptionManagerBase ABC + Module Extraction**~~ ✅ Done
- ~~**Code Quality Audit + Test Suite (216 tests)**~~ ✅ Done

---

### v4.0.0 — Platform & Extensibility ✅

**Released:** 2026-04-06

- ~~**Plugin API** — Lightweight plugin system for community-built disruption modules, scanners, and UI panels. JSON manifest + Python entry point. Auto-discovery from `plugins/` directory. Hot-reload support. sys.path/sys.modules leak-safe loading.~~ ✅ Done
- ~~**CLI Mode** — Run DupeZ headless from the terminal. Script disruptions, pipe output, integrate into automation. Interactive REPL mode.~~ ✅ Done
- ~~**Auto-Updater** — In-app update checker with one-click download from GitHub releases.~~ ✅ Done
- ~~**Pulse Diagnostic Overhaul** — NAT keepalive system (1 packet/800ms) prevents Windows ICS NAT table timeout during long freeze cycles. Burst-controlled flush on deactivation (50 packets/5ms burst). Full WinDivert NETWORK_FORWARD documentation.~~ ✅ Done
- ~~**Desync Engine Rewrite** — Lag module passthrough mode auto-enables when stacked with duplicate/ood. Lag queues delayed copies while originals flow to downstream modules. True lag+diagnostic+ood stacking for maximum desync.~~ ✅ Done
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

### v3.4.0 — Pulse Diagnostic + Voice + GPC ✅

**Released:** 2026-04-02

- ~~**Pulse Diagnostic / Directional Lag** — Inbound packets delayed while outbound passes untouched. Target freezes on others' screens while your actions register in real time. Configurable inbound lag (0–5000ms) and optional inbound drop.~~ ✅ Done
- ~~**100% Drop Fidelity** — Drop module uses packet discard instead of re-inject. True 100% when configured.~~ ✅ Done
- ~~**Direction-Aware Filtering** — All disruption modules implement `matches_direction()`. WinDivert outbound bit detection for per-packet direction classification.~~ ✅ Done
- ~~**Voice Control** — Push-to-talk voice commands via OpenAI Whisper (local, offline). Speak disruption commands, LLM advisor interprets into configs. Model selection (tiny/base/small), mic selection.~~ ✅ Done
- ~~**GPC / CronusZEN Support** — Parse .gpc files, generate scripts synced with DupeZ timing, export to Zen Studio. Shipped templates now focus on accessibility helpers, hold-toggle support, diagnostic markers, and stick-rest calibration. USB device detection.~~ ✅ Done
- ~~**Smart Engine Pulse Diagnostic Strategy** — 6th goal strategy with hotspot-aware tuning.~~ ✅ Done
- ~~**LLM Advisor Pulse Diagnostic Fallback** — Keyword-based pulse diagnostic interpretation when no LLM available.~~ ✅ Done

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
- [x] **v3.4.0** — Pulse Diagnostic + Voice + GPC. Directional lag. Whisper STT. CronusZEN integration.
- [x] **v3.5.0** — Live Stats Dashboard. Real-time packet counters. Engine stats API.
- [x] **v4.0.0** — Platform & Extensibility. Plugin API. CLI mode. Auto-updater.
- [x] **v5.0.0** — Pulse Diagnostic Engineering. 7 deep-research phases. Statistical models. Packet classification. Tick sync. 14 asymmetric presets. Batch API. ML traffic analysis. Natural impairment patterns. 216 tests.
- [x] **v5.2.0** — Indefinite Pulse Diagnostic + Timed Disconnect Engine + Hardening. Pulse-cycling pulse diagnostic. timed diagnostic state machine. Extended lag. CNSA 2.0 security. Full codebase audit. Windows installer + auto-update. Getting Started guide. Collapsible/reorderable sections. Splash screen overhaul. Extraction fix for low-spec machines.
- [x] **v5.2.1** — Map fix + resilient optional deps. iZurvive QtWebEngine loads under admin token via `--no-sandbox` Chromium flag. Optional dep imports (whisper, sounddevice) wrapped in broad exception handlers so missing/broken bindings no longer crash startup.
- [x] **v5.2.2** — Build hardening: torch/whisper isolation. PyInstaller isolated analyzer no longer crashes on `torch\lib\c10.dll` (WinError 1114 / access violation) every build. `whisper` and `openai-whisper` added to `dupez.spec` excludes alongside `torch`. `is_voice_available()` probes in `voice_panel.py` and `clumsy_control.py` deferred from module import to first view instantiation, wrapped in broad exception handlers.
- [x] **v5.2.3** — Version display fix + single source of truth. Dashboard title bar and HTTP `User-Agent` header now report the actual build version. `app/core/updater.py` and `app/core/secure_http.py` both had `"5.2.0"` hardcoded — fixed by pointing at a new `app/__version__.py` single-source-of-truth module. Hardcoding versions anywhere under `app/` is now explicitly forbidden.
- [x] **v5.2.4** — Installer architecture fix + manifest sync. Installer now lands in `C:\Program Files\DupeZ` on 64-bit Windows instead of `C:\Program Files (x86)\DupeZ` — added missing `ArchitecturesInstallIn64BitMode=x64` / `ArchitecturesAllowed=x64` directives to `installer.iss`. `dupez.manifest` `assemblyIdentity` version bumped from the stale `5.2.0.0` it had been stuck at since v5.2.0, now tracked in the per-release bump checklist.
- [x] **v5.3.0** — Split-elevation architecture + hardware-rasterized map + preset collapse. Dual-variant builds (`DupeZ-GPU.exe` + `DupeZ-Compat.exe`). ADR-0001 helper-role dispatch, feature-flag routing in blocker, renderer tier resolver, 4-stage hostname chain with bundled zeroconf, packaging subtree reorganization, preset taxonomy 8 → 5.
- [x] **v5.4.0** — Account Tracker overhaul (multi-select, context menu, filter chips, notes, bulk ops with scope, export-subset), GPU auto-detection fallback, About/Help rewrites, nav-button theme-switch hardening, rainbow auto-animate, six v5.3.0 regression fixes.
- [x] **v5.5.0** — WiFi same-network ARP-spoof mode, `CollapsibleCard` extraction, `ml_classifier` PRNG refactor, deprecated Timed Disconnect Engine v1 removal.
- [x] **v5.6.0** — local-forwarding reliability update (bounded local-forwarding health instrumentation), A2S cut verifier plumbed into episode recorder (`cut_verified` events + `max_cut_state` on `engine_stop`), `LearningLoop.cut_effectiveness` temporary-disconnect aggregation, full scapy MANUFDB vendor fallback (~35k OUI), end-to-end smoketest tool.
- [x] **v5.6.1** — Updater stability: equal-tag short-circuit in `UpdateChecker.check_sync` to suppress spurious re-prompts; `installer_url` pinned to the stable versionless `releases/latest/download/DupeZ_Setup.exe` alias; `dupez.manifest` / `dupez_compat.manifest` versions resynced from stale `5.5.0.0`.
- [x] **v5.6.2** — Nation-state hardening. Closed §9.2 with the SP 800-63B / CNSA 2.0 second-factor gate (`app/core/second_factor.py`) wired into elevation, plugin loader, and offsec runner. Auto-update fail-closed behind pinned Ed25519 signed-manifest verification (`app/core/update_verify.py` + `scripts/sign-release.py`). Fixed DayZ tracker CSV/XLSX import (BOM, delimiter sniffing, header synonyms, off-by-one). Routed offsec CLI INFO chatter to stderr. New pytest suite + Windows CI matrix. Cert: **CERTIFIED — Nation-State Grade**.
- [x] **v5.6.3** — Crash-safety + audit hardening. `faulthandler` enabled at process entry so C-extension segfaults (WinDivert, Qt, Chromium GPU) leave a usable traceback. Pipe-disconnect recovery in `DisruptionManagerProxy._call` — helper death is now recoverable instead of requiring a GUI restart. `_shutdown_cleanup` routed through `get_disruption_manager()` so split-mode tears down the elevated helper over IPC instead of no-op'ing the in-process singleton. Doc drift fixes (Red Disconnect 95% → 100% drop in help panel) and dead `taskkill dupez_helper.exe` removed from the variant build script.
- [x] **v5.6.4** — WiFi honesty pass. Four silent-no-op branches in the `wifi_same_net` path (Npcap missing, `ArpSpoofer.start()` failed, ImportError, generic exception) now return False so the GUI surfaces "Partial Failure" with actionable guidance instead of badging DISRUPTED on a useless WinDivert handle. Honest WiFi limitations section added to Help panel documenting AP client isolation (Eero/Google Nest/ISP gateways default-on with no toggle), wireless L2 forwarding behavior, and the WinDivert vs ARP layer split. WiFi-aware pre-flight probe + self-disrupt fallback deferred to v5.6.5.
- [x] **v5.6.5** — WiFi isolation watchdog + self-disrupt fallback. New `app/network/wifi_probe.py` module with `IsolationWatchdog` that samples ArpSpoofer/WinDivert packet counters after a 5s grace window; when `_packets_sent > 0 ∧ _packets_processed == 0`, declares AP isolation and triggers automatic fallback to NETWORK-layer self-disrupt mode (operator's own traffic to/from target only — the only thing that can work behind AP client isolation). Inno Setup compilation + versionless installer alias emission folded into `packaging\build_variants.bat` so the release pipeline is now one command instead of three. Inno Setup `x64` → `x64compatible` to suppress deprecation warning and additionally support ARM64 Windows x64-emulation hosts. Help panel updated with the v5.6.5 watchdog explanation + operator decision tree.
- [x] **v5.6.6** — Auto-update fix. Provisioned the Ed25519 release keypair and embedded the pinned pubkey in `app/core/update_verify.TRUSTED_PUBKEYS_PEM` (empty since v5.6.2 — auto-update fail-closed on every check since then). Folded `scripts/sign-release.py` into `packaging/build_variants.bat`: build now emits `dist/DupeZ_Setup.exe.manifest.json` + `dist/DupeZ_Setup.exe.manifest.sig` automatically when `DUPEZ_SIGN_PRIVKEY` env var points at the offline-held privkey. Root cleanup: moved `RELEASE_NOTES_v5.6.{3,4,5}.md` to `docs/release-notes/`. Users on v5.6.3-v5.6.5 must manually upgrade once to v5.6.6; from then on auto-update works.
- [x] **v5.6.7** — Account-tracker XLSX import fix + multi-script-device support. (1) XLSX importer now infers the account-name column when the header cell above it is blank but the data rows contain text — fixes the case where workbooks with the account name in column A and headers starting at column B silently imported 0/N rows. (2) GPC panel renamed "GPC / CRONUS" → "GAME SCRIPTS", now detects Cronus Zen, Cronus Max, Titan One, Titan Two; export-path routing picks Zen Studio for Cronus, Gtuner for Titan, with Documents/DupeZ/GPC fallback. `CronusDevice` aliased to new `ScriptDevice` for backward compat.
- [x] **v5.6.8** — Account-tracker save-state bug fix + episode-history backend API + v6.x roadmap doc. Critical fix: `_load_accounts` no longer overwrites the on-disk JSON with the starter template when load returns empty for transient reasons (HMAC mismatch, corrupt file, I/O error). Template now only seeds on true first launch (no data file present). New `LearningLoop.recent_episodes()` + `LearningLoop.session_summary()` surface the existing episode store to GUI consumers — backend infrastructure for the v5.6.9 episode-history panel. `docs/ROADMAP_v6.md` lays out concrete plans for hotkey macros, safety telemetry, cross-game profiles, plugin marketplace, and mobile companion.
- [x] **v5.6.9** — Engine extensions (4 features): custom preset editor with JSON-validated store + import/export sidecars + Qt dialog; per-port WinDivert filter targeting via preset `_ports` param so cuts can be scoped to game ports only; process-scoped disruption via preset `_process_scope: auto|dayz` driving a `processId` filter clause from psutil-enumerated DayZ PIDs, with a foreground-watch thread for auto-mode; one-click backup/restore bundling all `app/data` + `app/config` JSON into a manifest-signed ZIP with optional DPAPI encryption.
- [x] **v5.7.0** — Telemetry + safety + polish (7 features bundled): risk score aggregator (six-factor weighted 0-100 with GREEN/AMBER/RED bands over existing episode + audit telemetry); kill switch orchestrator with four trigger types (server-integrity process watch, risk threshold, runaway packet rate, manual fire); diagnostic wizard backend (8 self-checks consolidated into a registry with per-check remediation hints); Discord/generic webhook audit sink with token-bucket rate limiting + IP scrubbing; cut chaining orchestrator (N-stage preset sequencer with time/health/packets gates); multi-account quick-switch (persistent active-account marker with tracker validation); OBS overlay HTTP endpoint (localhost-bound JSON + HTML/JS browser source for stream graphics).
- [x] **v5.7.1** — Codebase quality pass. 175 new unit tests across 10 modules (test suite grew 386 → 569 passing). Audit uncovered three real production bugs: `_TokenBucket` starting empty (audit sinks dropped first ~1s of events silently), preset name regex rejecting auto-rename suffix `(2)` (every duplicate-import crashed), and overlay handler class-attribute leak between multi-instance servers. All three fixed. New `rotate_episodes()` with 90-day + 5000-file retention policy. ADR-0002 consolidates the major architectural decisions (WiFi self-disrupt, fail-closed auto-update, split elevation, local-only telemetry, plugin trust model). Quality-debt items remaining (large-object refactors, hot-path optimization, broad-except cleanup) documented for v5.8.x.
- [x] **v5.7.2** — Regression fix: WiFi disruption of peer devices. A user reported that after updating to v5.7, DISRUPT had no effect on WiFi targets (Xbox) where it disconnected/lagged before. Root cause: the v5.6.5 "self-disrupt by default" decision turned same-WiFi peer disruption into a no-op — it only affected the operator's own traffic. Reverted `target_profile.resolve_target_profile` so `wifi_same_net` routes through local forwarding + FORWARD layer again, disrupting the target device directly. The v5.6.5 isolation watchdog is retained and now runs by default — auto-falls-back to self-disrupt only when AP client isolation genuinely drops the spoof. Watchdog grace window raised 5s → 8s to avoid false-positive fallback on a briefly-idle target. `params["_force_self_disrupt"]` added as the explicit opt-in for operators who want self-disrupt. Regression test locks the corrected behavior.
- [x] **v5.7.3** — Security hardening of the v5.6.9-v5.7.2 modules (added after the v5.6.2 nation-state cert sweep, never security-reviewed). Five findings, one critical: backup restore could overwrite source code from a hand-crafted bundle → arbitrary code execution (fixed with an `app/data` + `app/config` restore path allowlist); decompression-bomb caps on backup restore; overlay server `/state` no longer sends wildcard CORS (was leaking live disruption state to any website the operator visits); webhook URLs scheme-validated to `https://` (or loopback `http://`) so `file://`/`ftp://` are blocked; preset `params` underscore-key allowlist so a shared preset can't inject engine control flags, plus a 16 KB params size cap. 15 new security regression tests (`tests/test_security_v573.py`); suite 570 → 585.
- [x] **v5.7.4** — Wire-up release. A deep audit found seven feature backends from v5.7.0/v5.7.1 had zero invocation points — tested, CHANGELOG-documented, but unreachable by a user (~2000 LOC of dead code). Root cause: v5.7.0 deferred UI wiring to v5.7.1, v5.7.1 was re-scoped to a quality pass, the wiring was dropped. Fixed: audit-webhook fan-out hooked into `AuditLogger.log()`; `rotate_episodes()` called at startup; webhook sinks registered from settings; OBS overlay auto-starts + Tools-menu toggle; risk score, diagnostics (F2), and kill-switch panic-stop (Ctrl+Alt+X) added as Tools-menu entries. Still backend-only and honestly documented as such: cut-chain configurator and the kill-switch auto-trigger orchestrator (both need real settings dialogs).
- [x] **v5.7.5** — WiFi disrupt audit closure. Closed M1 (atexit ARP cache restore on uncaught exceptions / Ctrl+C / sys.exit — kill -9 / SIGSEGV still need the v5.8.x hot-reload guard), M2 (read real interface netmask via psutil instead of /24 hardcode — fixes silent no-op disrupts on /23 and /22 LANs like Eero mesh and business APs), M6 (NpcapSender context manager + defensive `__del__` — closes the pcap-handle leak on partial-init failure), L2 (ArpSpoofer constructor validates `target_ip`/`gateway_ip`), L3 (forwarding setup loop self-terminates after 5 consecutive send failures — removes the spin-forever-while-reporting-ACTIVE silent fail). Defense in depth: new `mask_macs_in_text` helper wired into the logger's `ScrubbingFormatter` so a forgotten call-site `mask_mac()` still cannot leak a device-unique identifier into log files. `tests/test_ip_leak_guard.py` extended with `TestMacScrubber`, `TestTargetProfileNetmask`, `TestArpSpooferValidatesIp`. Audit M3/M4/M5 race conditions + L1/L4/L5 nits deferred to v5.8.x because they need the `WifiDisruptSession` orchestration refactor to close cleanly.
- [x] **v5.7.6** — Maximum Security Tier 1. Closed the five highest-ROI residual attack paths from the post-v5.7.5 security review: downgrade-replay protection on the update channel (HMAC-protected monotonic version ledger refuses signed-but-older manifests), HMAC sidecars on `settings.json` (tampered files quarantined), audit log fails closed on a broken hash chain (seals until `dupez --reset-audit`), subprocess hardening (`SW_HIDE` STARTUPINFO + `close_fds=True` everywhere), and a webhook host allowlist (Discord + operator-pinned + loopback only). Three tier-1.5 wins rode along: `dupez --verify-self` Ed25519 binary integrity check, `--reset-audit` operator escape hatch, and cert-pinning infrastructure (audit-only; pins populate in v5.7.7). Security-only — no behavior change on the normal path. `tests/test_security_v576.py` adds seven test classes; see ADR-0003. Build hotfix (PR #25) repaired a `version_info.py` paren slip that broke the PyInstaller build and defined the `_POISON_FAILURE_THRESHOLD` constant the v5.7.5 poison-loop guard referenced.
- [x] **v5.7.7** ? Defensive hardening and release polish. Removed legacy high-risk methods from public validation, preset editing, Smart Mode, and advisor paths; refreshed root/docs to an owned-lab diagnostic posture; synchronized runtime/installer/manifest/build metadata; added release notes; and verified with active-content safety, release-preflight, binary-provenance, privacy, storage, support-bundle, source-leak, performance-smoke, ruff, compile, and pytest gates.

---

Got a feature request? [Open an issue](https://github.com/GrihmLord/DupeZ/issues).
