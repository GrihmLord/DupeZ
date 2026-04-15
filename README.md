# DupeZ v5.6.1

Per-device network disruption toolkit. Scan your network, pick your targets, manipulate their packets. Direct WinDivert packet manipulation through a PyQt6 dashboard with AI auto-tuning, pulse-cycling god mode, precise dupe engine, tick-synchronized disruption, stealth patterns, and a plugin API.

Built for the DayZ community — scan your local network, target specific devices, and apply real-time packet disruption with granular control over lag, drops, throttling, duplication, corruption, directional freezing, and inventory duplication. Includes AI auto-tuning, voice commands, scheduled disruptions, macro chains, live traffic monitoring, and a plugin system for community extensions.

![Windows](https://img.shields.io/badge/platform-Windows%2010%2F11-blue) ![Python](https://img.shields.io/badge/python-3.10%2B-green) ![License](https://img.shields.io/badge/license-Proprietary-red)

---

## Features

### Disruption Engine

DupeZ uses a three-tier fallback for packet disruption:

1. **Native WinDivert Engine** — Pure Python, loads WinDivert.dll directly via ctypes. No GUI window, no external process. Batch API (RecvEx/SendEx) for up to 255 packets per syscall. Fastest startup, lowest overhead.
2. **Clumsy --silent** — Launches clumsy.exe with `--silent` flag (patched build). Hidden window, force-enables all modules.
3. **Clumsy GUI Automation** — Falls back to standard clumsy.exe with win32 automation.

**10 Disruption Modules:** Drop, Lag (with connection preservation), Throttle, Duplicate, Corrupt, RST Injection, Bandwidth Cap, Disconnect (stateful timed cut — primary dupe vector), Out-of-Order, God Mode (pulse cycling). Tick-synchronized burst/pulse modes layer on top via the tick-sync engine.

**Statistical Models:** Gilbert-Elliott bursty loss, Pareto heavy-tail jitter, Token Bucket rate limiting, Correlated drop with temporal autocorrelation. All produce patterns statistically indistinguishable from real network degradation.

**Stealth Layer:** Timing randomization (Gaussian jitter), 4 natural degradation patterns (wifi interference, congestion, ISP throttle, distance), session fingerprint rotation. Behavioral camouflage to avoid detection.

### God Mode (v5.2.0)

Asymmetric directional disruption with pulse-cycling for indefinite duration. Inbound packets (server → target) are managed by a block/flush cycle while outbound (target → server) always passes through untouched.

**Three modes:**

| Mode | Block | Flush | Effect |
|------|-------|-------|--------|
| Classic | Continuous delay | Timed release | Original behavior, subject to ~10s kick limit |
| Pulse (default) | 3000ms | 400ms | Indefinite red chain — quality monitor resets during flush windows |
| Infinite | 5000ms | 300ms | Maximum disruption — aggressive preset with 2s keepalive |

Pulse cycling keeps the sliding-window average below DayZ's kick threshold indefinitely. The target experiences freeze→micro-unfreeze→freeze cycles where the unfreeze window is too short to react but long enough to reset quality metrics.

**Packet classification:** Small inbound packets (<100 bytes) are identified as server keepalive probes and preferentially passed during NAT keepalive windows — maximum connection health signal with minimum game state leakage.

**Teleportation:** During extended block phases, your outbound movement reaches the server continuously. When the flush phase hits, the target's client reconciles the entire position delta at once — visual teleport from the target's perspective.

### Stateful Cut Disconnect (primary dupe vector)

The standalone Dupe Engine v1 was retired in v5.5.0. Dupe functionality now lives in the `disconnect` module as a stateful cut-with-timer — the same three-phase flow (arm → cut → release) exposed via three sliders: `Chance %`, `Arm Delay (ms)`, and `Duration (ms)`. Leaving duration at `0` preserves the legacy "drop until stopped" behavior; setting arm delay + duration arms a timed cut. Pair with the A2S Cut Verifier (see v5.6.0 below) for closed-loop severance confirmation.

### Extended Lag (v5.2.0)

Connection-preserving lag for durations beyond 5 seconds. Auto-activates when lag delay exceeds 5000ms. Periodically passes small keepalive-sized packets while holding large game state packets in the delay queue. Enables 30s+ lag without server timeout.

### Tick-Synchronized Disruption (v5.0.0)

Aligns disruption bursts with server tick boundaries for maximum impact with minimum total packet manipulation. TickEstimator detects server tick rate from packet inter-arrival times. PulseDisruptionModule implements burst/rest cycles that stay below DayZ's 1.27+ freeze system threshold.

### Packet Classification (v5.0.0)

Real-time packet classifier with UDP size/port heuristics, TCP flag analysis, and per-flow frequency tracking. Categories: KEEPALIVE, MOVEMENT, STATE, BULK, VOICE, CONNECTION, UNKNOWN. SelectiveDisruptionFilter wraps any module to target specific categories.

### Asymmetric Direction Presets (v5.0.0)

14 named presets across 5 families: God Mode (standard/stealth/aggressive), Ghost Mode (standard/soft), Desync (standard/heavy), Phantom (standard/aggressive), Combo (chaos/surgical). Independent inbound/outbound tuning per module.

### AI Smart Mode (v3.1.0+)

Network profiler + rule-based parameter optimizer. Profiles target connections in real-time (RTT, jitter, loss, bandwidth, device type, connection type) and generates optimal disruption configs. 7 goal strategies: Disconnect, Lag, Desync, Throttle, Chaos, God Mode, Auto. Optional LLM advisor via Ollama or any OpenAI-compatible API for natural-language disruption tuning.

### Voice Control (v3.4.0+)

Push-to-talk voice commands powered by OpenAI Whisper (local, offline). Speak a command like "heavy lag on the PS5" or "god mode" and the LLM advisor interprets it into a disruption config. Supports model selection (tiny/base/small) and mic selection.

### GPC / CronusZEN Support (v3.4.0+)

Native GPC script integration for CronusZEN and CronusMAX devices. Parse .gpc files, generate scripts synced with DupeZ disruption timing, export to Zen Studio. 4 built-in templates: Auto Dupe, Rapid Fire, God Mode Actions, Anti Recoil.

### Plugin API (v4.0.0+)

Lightweight plugin system for community-built extensions. Four plugin types: **DisruptionPlugin**, **ScannerPlugin**, **UIPanelPlugin**, **GenericPlugin**. JSON manifest + Python entry point in `plugins/`. Hot-reload via Tools menu or CLI.

### CLI Mode (v4.0.0+)

Run DupeZ headless from the terminal. Subcommands: `scan`, `disrupt`, `stop`, `status`, `devices`, `plugins`. Interactive REPL with `dupez-cli interactive`. Script disruptions with `--methods` and `--params` flags for automation pipelines.

### Network Tools (v3.3.0+)

Four-tab network intelligence toolkit: Live Traffic Monitor, Latency Overlay (floating transparent widget), Port Scanner, and Connection Mapper with gaming port detection and hostname resolution.

### iZurvive Map

Ad-free embedded iZurvive with two-layer ad blocking. Supports Chernarus+ (Satellite/Topographic), Livonia, Namalsk, Sakhal, Deer Isle, Esseker, and Takistan.

### Account Tracker (v5.4.0)

Multi-account DayZ manager with full CRUD, XLSX/CSV import and export, and per-account status tracking. Features include: notes field per account, multi-select with right-click context menu (edit, duplicate, set status, delete), quick-filter status chips, duplicate account with auto-increment, row numbering, editable dropdown fields, last-modified timestamps, scoped bulk operations (all/selected/filtered), and filtered subset export.

### Getting Started Guide (v5.2.0)

Built-in interactive guide with 10+ collapsible sections covering every feature: Clumsy Control, iZurvive Map, Account Tracker, Network Tools, Settings & Themes, Voice Control, GPC/Cronus, Troubleshooting, and Keyboard Shortcuts. Accessible from the sidebar rocket icon (🚀).

### Collapsible & Reorderable Sections (v5.2.0)

All control sections in Clumsy Control (Preset, Auto-Tune, Platform, Direction, Modules, Scheduler/Macros, Live Stats, Voice Control, GPC/Cronus) are wrapped in collapsible cards with ▶/▼ toggle headers and ▲/▼ reorder buttons. Collapse what you don't need, reorder to match your workflow.

### ARP Spoof + A2S Cut Verifier (v5.6.0)

Closed-loop cut verification for WiFi same-network targets. ARP poison writes three gateway-facing frames per cycle — opcode-2 reply with L2 source spoofed to the target's MAC, plus an opcode-1 request variant — defeating ASUS/Netgear/Ubiquiti anti-spoof heuristics and RFC 826 strict-mode routers. While a cut is active, the A2S probe polls the Source query port every second, captures a baseline player count on the first reachable poll, and emits `cut_verified` events with states `unknown → connected → degraded → severed`. Peak `max_cut_state` is written to `engine_stop` so the learning loop sees labeled severance data without operator input. `LearningLoop.cut_effectiveness(profile, goal)` surfaces per-bucket severance rates so the auto-tuner can switch presets when the current one can't sever a target class.

Vendor column now resolves against the full IEEE OUI database (~35k entries via scapy MANUFDB) instead of the 60-entry curated table — Ring, HUMAX, Murata, Texas Instruments, Chamberlain, HP, Samsung, Apple, and every other registered manufacturer populate correctly.

### Windows Installer & Auto-Update (v5.2.0)

Proper Inno Setup installer registers DupeZ in Add/Remove Programs with full uninstall support. Windows application manifest and VS_VERSION_INFO resource for SmartScreen trust. In-app auto-updater checks GitHub Releases and can download + silently install new versions with progress feedback.

---

## Presets

| Preset | Effect |
|--------|--------|
| Red Disconnect | 100% drop + 3000ms lag + 0 KB/s cap + full throttle + hard cut |
| Lag | Heavy sustained lag + drop — tune sliders after selecting (Light ~800/60 · Max ~5000/100) |
| God Mode | Bidirectional pulse-cycle — ghost teleport, invulnerable, hits land (3500ms block / 300ms flush / 100ms stagger) |
| Custom | Set your own parameters |

Platform-specific presets (`pc_local`, `ps5_hotspot`, `xbox_hotspot`) live in the game profile JSON and are auto-selected at disrupt time based on target subnet, MAC OUI, hostname, and device type — see `app/firewall/target_profile.py::resolve_target_profile`.

---

## Requirements

- Windows 10/11 (64-bit)
- Python 3.10+
- Administrator privileges (required for WinDivert kernel driver)

### Build Dependencies (optional)

- [Inno Setup 6+](https://jrsoftware.org/isinfo.php) — Required only to compile the installer (`iscc` must be on PATH)
- Code signing certificate — Optional; set `DUPEZ_SIGN_CERT` and `DUPEZ_SIGN_PASS` environment variables to enable signing in `build.bat`

### Firewall Binaries

The following must be present in `app/firewall/`:

- `WinDivert.dll` — Kernel packet interception library
- `WinDivert64.sys` — WinDivert kernel driver
- `clumsy.exe` — Packet manipulation engine (fallback only)

---

## Quick Start

```powershell
# Clone
git clone https://github.com/GrihmLord/DupeZ.git
cd DupeZ

# Install dependencies
pip install -r requirements.txt

# Run GUI (auto-elevates via UAC)
python dupez.py

# Run CLI (headless)
python -m app.cli scan
python -m app.cli interactive
```

### Build standalone exe

Run from the repo root. All build scripts and PyInstaller specs live in `packaging\` but write output to repo-root `dist\`.

```powershell
pip install pyinstaller

# Legacy single binary (requireAdministrator):
packaging\build.bat
# Output: dist\dupez.exe + dist\DupeZ_v5.6.1_Setup.exe (installer)

# Modern dual-variant build (RECOMMENDED):
packaging\build_variants.bat
# Output: dist\DupeZ-GPU.exe (asInvoker, split-arch, GPU map)
#         dist\DupeZ-Compat.exe (requireAdministrator, inproc, legacy fallback)
```

### Install via Installer (Recommended)

Download `DupeZ_v5.6.1_Setup.exe` from [Releases](https://github.com/GrihmLord/DupeZ/releases) (or use the stable [`DupeZ_Setup.exe`](https://github.com/GrihmLord/DupeZ/releases/latest/download/DupeZ_Setup.exe) alias which always points at the latest release). The installer:

1. Installs to `Program Files\DupeZ` — trusted path, no SmartScreen warnings after signing
2. Registers in **Add/Remove Programs** with version, publisher, and icon
3. Creates Start Menu and Desktop shortcuts
4. Strips Mark-of-the-Web (MOTW) from all files — prevents Windows Application Control blocking
5. Supports upgrade-in-place — re-run a newer installer without uninstalling first
6. **In-app auto-update** — DupeZ checks GitHub Releases on launch and can download + install updates directly

---

## Project Structure

```
dupez.py                             # Entry point (GUI mode)
dupez_helper.py                      # Elevated helper entry point (split-arch)
requirements.txt                     # Dependencies
requirements-locked.txt              # Pinned dependency versions

packaging/                           # All PyInstaller + Inno Setup build files
├── dupez.spec                       # Legacy single-binary PyInstaller spec
├── dupez_gpu.spec                   # DupeZ-GPU.exe spec (asInvoker, split)
├── dupez_compat.spec                # DupeZ-Compat.exe spec (requireAdmin, inproc)
├── build_common.py                  # Shared Analysis/PYZ/EXE factory
├── dupez.manifest                   # Windows app manifest (GPU + legacy)
├── dupez_compat.manifest            # Windows app manifest (Compat variant)
├── version_info.py                  # VS_VERSION_INFO resource for exe metadata
├── installer.iss                    # Inno Setup installer script
├── build.bat                        # 4-stage legacy pipeline (single binary)
└── build_variants.bat               # Modern dual-variant pipeline (RECOMMENDED)

app/
├── main.py                          # UAC elevation, crash handler, Qt init
├── cli.py                           # CLI mode — headless terminal interface + REPL
├── core/
│   ├── controller.py                # Scan, disrupt, block — main app logic
│   ├── state.py                     # Observable state + device model
│   ├── data_persistence.py          # Atomic JSON persistence
│   ├── scheduler.py                 # Disruption scheduler + macro engine
│   ├── profiles.py                  # Named disruption profile system
│   ├── updater.py                   # Auto-updater via GitHub Releases API
│   ├── crypto.py                    # CNSA 2.0 cryptographic primitives
│   ├── secrets_manager.py           # AES-256-GCM envelope encryption
│   ├── secure_http.py               # TLS 1.3 hardened HTTP client
│   ├── validation.py                # Strict allowlist input validation
│   └── patch_monitor.py             # DayZ patch monitoring with HMAC integrity
├── plugins/
│   ├── base.py                      # Plugin base classes (4 types)
│   └── loader.py                    # Plugin discovery + lifecycle management
├── ai/
│   ├── smart_engine.py              # ML-based disruption parameter optimizer
│   ├── network_profiler.py          # Target connection profiler
│   ├── llm_advisor.py               # Natural-language disruption tuning
│   ├── session_tracker.py           # Session history + HMAC-verified persistence
│   └── voice_control.py             # Push-to-talk voice commands via Whisper
├── gpc/
│   ├── gpc_parser.py                # CronusZEN .gpc script parser
│   ├── gpc_generator.py             # .gpc script generator (4 templates)
│   └── device_bridge.py             # Cronus USB device detection
├── firewall/
│   ├── native_divert_engine.py      # WinDivert packet engine (ctypes, batch API)
│   ├── clumsy_network_disruptor.py  # Dual-engine orchestrator (native + clumsy)
│   ├── engine_base.py               # DisruptionManagerBase ABC
│   ├── packet_classifier.py         # Real-time packet classification engine
│   ├── tick_sync.py                 # Tick-synchronized disruption + pulse mode
│   ├── statistical_models.py        # Gilbert-Elliott, Pareto, token bucket, correlated
│   ├── stealth.py                   # Behavioral stealth + natural patterns
│   ├── asymmetric_presets.py        # 14 named directional presets
│   ├── blocker.py                   # netsh firewall rules (fallback)
│   └── modules/                     # Extracted disruption modules
│       ├── godmode.py               # Pulse-cycling god mode (v5.2)
│       ├── lag.py                   # Connection-preserving lag (v5.2)
│       ├── drop.py                  # Random packet drop
│       ├── disconnect.py            # Stateful timed cut — primary dupe vector
│       ├── duplicate.py             # Packet flooding (N+1 copies)
│       ├── ood.py                   # Out-of-order reordering
│       ├── corrupt.py               # Payload bit-flip corruption
│       ├── bandwidth.py             # Token-bucket bandwidth cap
│       ├── throttle.py              # Time-gated packet flow
│       └── rst.py                   # TCP RST injection
├── gui/
│   ├── dashboard.py                 # Sidebar rail + view stack
│   ├── clumsy_control.py            # Device list + disruption controls
│   ├── network_tools.py             # Traffic monitor, latency, port scanner
│   ├── dayz_map_gui_new.py          # Ad-free iZurvive + map selector
│   ├── dayz_account_tracker.py      # Multi-account tracker
│   ├── hotkey.py                    # Global hotkey listener
│   ├── settings_dialog.py           # App settings
│   └── panels/                      # Modular UI panels
│       ├── help_panel.py            # Getting Started guide (collapsible sections)
│       ├── smart_mode_panel.py      # AI auto-tune panel
│       ├── stats_panel.py           # Live packet stats
│       ├── voice_panel.py           # Voice control panel
│       └── gpc_panel.py             # GPC/Cronus panel
├── network/
│   ├── device_scan.py               # ARP/TCP device discovery
│   └── enhanced_scanner.py          # Threaded scanner with signals
├── themes/                          # QSS stylesheets (dark, hacker, light, rainbow)
├── logs/                            # Rotating log files + tamper-evident audit trail
├── utils/                           # Helpers and system utilities
├── config/                          # JSON config + game profiles
│   └── game_profiles/               # Per-game tuning (ports, tick rates, defaults)
│       └── dayz.json
└── resources/                       # App icons

plugins/                             # Community plugins (each folder = one plugin)
└── example_ping_monitor/
tests/                               # Test suite (353 tests, 2 hardware-gated)
tools/                               # Operator CLI utilities (scan/lag smoketest, etc.)
bench/                               # Micro-benchmarks for hot paths
docs/
├── adr/                             # Architecture Decision Records
├── release-notes/                   # Per-version release notes + deploy checklists
├── user_guides/                     # End-user how-to docs
├── integration/                     # Integration and platform notes
└── reports/                         # Audit and research reports
logs/
└── archive/                         # Quarantined crash dumps and stale traces
```

---

## Architecture

DupeZ supports two runtime architectures, selectable at build time:

- **Split (GPU variant)** — Medium-integrity GUI process with an elevated helper subprocess for WinDivert operations. Launches via `asInvoker` manifest; UAC prompt only for the helper. Enables GPU-accelerated map rendering.
- **In-process (Compat variant)** — Single elevated process with `requireAdministrator` manifest. Legacy fallback for systems where split-arch IPC fails.

The active architecture is displayed in the About dialog as the ARCH field.

## Security Architecture

DupeZ v5.0.0+ implements defense-in-depth security hardening:

- **Cryptography:** AES-256-GCM envelope encryption with machine-bound KEK, HMAC-SHA384 data integrity, SHA-384/512 hashing, PBKDF2-SHA-512 key derivation (600K iterations). CNSA 2.0 compliant. No MD5/SHA-1/RC4.
- **Input Validation:** Strict allowlist validation at every trust boundary. WinDivert filter strings tokenized and checked against an allowlist. All parameters range-validated.
- **Network Hardening:** TLS 1.3 minimum for all outbound HTTP. Certificate verification always enabled. URL scheme/host validation.
- **Data Persistence:** Atomic writes (tmp → fsync → replace). HMAC companion files for integrity verification. Hash-chained JSONL audit logging (tamper-evident).
- **Secrets Management:** Encrypted at-rest storage with machine-bound keys. No plaintext secrets in config files.
- **IP Masking:** All target IPs masked via `mask_ip()` in every log statement. Zero raw IPs in any log output.

---

## Hotkeys

| Key | Action |
|-----|--------|
| Ctrl+S | Scan network |
| Ctrl+D | Stop all disruptions |
| Ctrl+1 / 2 / 3 / 4 | Switch views |
| Ctrl+, | Settings |
| Ctrl+E | Export device data |
| Ctrl+Q | Exit |
| Ctrl+Shift+D | Toggle tray visibility |

---

## Version History

See [CHANGELOG.md](CHANGELOG.md) for full details and [ROADMAP.md](ROADMAP.md) for what's coming next.

---

## Acknowledgments

- **[Clumsy](https://github.com/jagt/clumsy)** by [jagt (Chen Tao)](https://github.com/jagt) — The original network condition simulator for Windows using WinDivert.
- **[Clumsy Keybind Edition](https://github.com/kalirenegade-dev/clumsy)** (v0.3.4) by [Kalirenegade](https://github.com/kalirenegade-dev) — Fork with keybind support, timer, and disconnect modules.

## License

Proprietary. All rights reserved.

---

**Built by [GrihmLord](https://github.com/GrihmLord)**
