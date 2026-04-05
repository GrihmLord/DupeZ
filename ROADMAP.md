# DupeZ Roadmap

What's coming next. Priorities shift based on community feedback — open an issue or PR if something here matters to you.

---

## v3.1.0 — Quality of Life

**Target:** Q2 2026

- **Profile System** — Save/load named disruption profiles per game or scenario. Quick-switch between configs without re-dialing sliders every time.
- **Tray Mode** — Minimize to system tray with hotkey toggle. Run disruptions in background without the window in the way.
- **Session History** — Log of past disruption sessions with timestamps, targets, methods, and durations. Exportable for review.
- **Device Nicknames** — Assign friendly names to scanned devices so you're not squinting at MACs every time.
- **Scan Result Caching** — Persist discovered devices across restarts so the device list isn't empty on every launch.

---

## v3.2.0 — Multi-Target & Scheduling

**Target:** Q3 2026

- **Multi-Device Disruption** — Select and disrupt multiple devices simultaneously with independent parameters per target.
- **Scheduled Disruptions** — Timer-based rules: start disruption at X, stop at Y, repeat on interval. Useful for timed PvP scenarios.
- **Disruption Macros** — Chain multiple disruption profiles in sequence (e.g., light lag for 30s → heavy lag for 10s → disconnect for 5s → repeat).
- **Import/Export Profiles** — Share disruption profiles as JSON files with the community.

---

## v3.3.0 — Network Intelligence

**Target:** Q4 2026

- **Live Traffic Monitor** — Real-time bandwidth graph per device. See who's actually eating your network.
- **Connection Mapper** — Visual topology showing which devices are talking to which external IPs.
- **Latency Overlay** — Floating transparent widget showing current ping/jitter to a target IP. Stays on top during gameplay.
- **Port Scanner Integration** — Quick scan open ports on discovered devices for identification.

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

---

## Completed

- [x] **v3.0.0** — The Strip. 89% code reduction. 3-view dashboard. Clumsy Control with presets and sliders. Map selector. Account tracker. Native WinDivert engine.
- [x] **v3.0.1** — Production hardening. Atomic settings writes. Settings dialog overhaul. Full QSS coverage. Dead code purge. IP sanitization. Cross-platform line endings.
- [x] **v3.0.2** — Ghost Rush + Phantom Peek outbound-only PvP presets. 7 bug fixes (5 core + 2 account tracker). 14 regression tests. Version consistency cleanup.

---

Got a feature request? [Open an issue](https://github.com/GrihmLord/DupeZ/issues).
