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

## v4.0.0 — Platform & Extensibility

**Target:** 2027

- **Plugin API** — Lightweight plugin system for community-built disruption modules, scanners, and UI panels. JSON manifest + Python entry point.
- **CLI Mode** — Run DupeZ headless from the terminal. Script disruptions, pipe output, integrate into automation.
- **Linux Support** — Replace WinDivert dependency with `tc`/`iptables` backend for Linux. Same GUI via PyQt6.
- **Auto-Updater** — In-app update checker with one-click download from GitHub releases.

---

## Stretch Goals (No Timeline)

These are ideas worth exploring but not committed to a release.

- **Steam Integration** — Pull player names from Steam for friendlier device identification.
- **DayZ Server Browser** — Embedded server list with one-click connect and per-server disruption profiles.
- **Replay System** — Record and replay disruption sessions for testing and consistency.
- **Mobile Companion** — Lightweight mobile app for monitoring active disruptions and triggering presets remotely.
- **Community Hub** — In-app feed for shared disruption profiles, presets, and configs.
- **Voice Macro Chains** — Chain voice commands into multi-step disruption sequences.

---

## Completed

- [x] **v3.0.0** — The Strip. 89% code reduction. 3-view dashboard. Clumsy Control with presets and sliders. Map selector. Account tracker. Native WinDivert engine.
- [x] **v3.0.1** — Production hardening. Atomic settings writes. Settings dialog overhaul. Full QSS coverage. Dead code purge. IP sanitization. Cross-platform line endings.
- [x] **v3.1.0** — Smart Mode. AI auto-tune engine. Network profiler. LLM advisor (Ollama/Mistral). Session tracking with feedback learning. Profile system. Tray mode. Device nicknames. Scan caching.
- [x] **v3.2.0** — Multi-target simultaneous disruption. Scheduled/timed disruptions. Disruption macros. Profile import/export.
- [x] **v3.3.0** — Network Intelligence. Live traffic monitor. Latency overlay. Port scanner. 4-view dashboard.
- [x] **v3.3.1** — Hardening pass. 11 fixes across thread safety, atomic writes, frozen-exe paths, RFC1918 validation, OOD buffer bounds.
- [x] **v3.4.0** — God Mode + Voice + GPC. Directional lag engine. Push-to-talk voice control via Whisper. CronusZEN/MAX GPC integration. 100% drop fidelity. Direction-aware filtering. 6th smart engine strategy.
- [x] **v3.5.0** — Live Stats Dashboard. Real-time packet counters with per-device breakdown. Engine stats API. PyInstaller spec update for optional deps. Version bump.

---

Got a feature request? [Open an issue](https://github.com/GrihmLord/DupeZ/issues).
