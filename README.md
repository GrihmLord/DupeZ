# DupeZ v5.7.9

DupeZ is a Windows network-condition testing and diagnostics workspace for
devices and local networks you own or are explicitly authorized to test. It
combines scoped packet impairment, dry-run previews, automatic stop deadlines,
crash-safe recovery, live diagnostics, and redacted support tooling in a PyQt6
desktop application.

The DayZ-oriented workflow focuses on reproducible connection testing:
latency, jitter, loss, bandwidth pressure, temporary disconnects, server
reachability, and local adapter/firewall health. The supported product boundary
is owned-lab diagnostics only: private servers, local devices, explicit
authorization, short automatic deadlines, and auditable rollback.

Installed builds keep mutable settings, histories, episodes, trained models,
logs, captures, reports, and crash dumps under `%LOCALAPPDATA%\DupeZ` rather
than beside binaries in `Program Files`. Upgrades perform a verified,
copy-only migration of recognized legacy files. Existing destination files win,
conflicts are reported, and legacy files are never deleted automatically.

![Windows](https://img.shields.io/badge/platform-Windows%2010%2F11-blue) ![Python](https://img.shields.io/badge/python-3.10%2B-green) ![License](https://img.shields.io/badge/license-Proprietary-red)

---

## Features

### Safe Network-Condition Engine

DupeZ selects and verifies the packet engine automatically:

1. **Verified Clumsy Compatibility** — The primary path for effects that the
   bundled Clumsy executable can represent exactly. DupeZ confirms the
   Local/Remote capture layer, enabled modules, numeric values, and Start
   state before hiding the Clumsy window.
2. **Native WinDivert Engine** — Used for native-only extensions, or as a
   bounded fallback for the small set of effects with matching semantics.
   Requests with known semantic differences fail closed instead of silently
   switching engines. Native mode exposes packet and per-module counters.

The engine supports bounded lab scenarios such as drop, lag, throttle,
bandwidth pressure, duplication, corruption, reordering, and temporary
disconnect. Every controller-started active operation is checked against local
CIDR policy and receives a hard automatic stop deadline.

Safety and support features include:

- First-run owned/authorized-network acknowledgement.
- Dry Run mode that validates and audits without loading the packet engine.
- Local-address and operator-defined CIDR scope checks.
- Crash-safe recovery of packet, firewall, and forwarding state.
- Redacted diagnostics, privacy inventory, and support-bundle exports.
- Stable CLI JSON schemas for support automation.

Statistical impairment models are available for reproducing burst loss,
heavy-tail jitter, rate limiting, and correlated loss in controlled tests.

### DayZ Connection Diagnostics

The DayZ workflow combines passive server reachability/query checks with
latency, jitter, loss, route, adapter, firewall, and driver diagnostics. It is
intended to help players and private-server operators reproduce and explain
connection problems without claiming to manipulate public-server game state.

### Plugin API (v4.0.0+)

Lightweight plugin system for community-built extensions. Four plugin types: **DisruptionPlugin**, **ScannerPlugin**, **UIPanelPlugin**, **GenericPlugin**. JSON manifest + Python entry point in `plugins/`. Hot-reload via Tools menu or CLI.

### CLI Mode (v4.0.0+)

Run DupeZ headless from the terminal. Subcommands: `scan`, `disrupt`, `stop`, `status`, `devices`, `plugins`. Interactive REPL with `dupez-cli interactive`. Script disruptions with `--methods` and `--params` flags for automation pipelines.

### Network Tools (v3.3.0+)

Network intelligence toolkit. Four core tabs — Live Traffic Monitor, Latency Overlay (floating transparent widget), Port Scanner, and Connection Mapper with gaming port detection and hostname resolution — plus AI / Smart Ops, GPC / Cronus Zen, and LAN Cut tabs that appear when their subsystems are available.

### iZurvive Map

Ad-free embedded iZurvive with two-layer ad blocking. Supports Chernarus+ (Satellite/Topographic), Livonia, Namalsk, Sakhal, Deer Isle, Esseker, and Takistan.

### Account Tracker (v5.4.0)

Multi-account DayZ manager with full CRUD, XLSX/CSV import and export, and per-account status tracking. Features include: notes field per account, multi-select with right-click context menu (edit, duplicate, set status, delete), quick-filter status chips, duplicate account with auto-increment, row numbering, editable dropdown fields, last-modified timestamps, scoped bulk operations (all/selected/filtered), and filtered subset export.

### Getting Started Guide (v5.2.0)

Built-in interactive guide with 10+ collapsible sections covering every feature: Clumsy Control, iZurvive Map, Account Tracker, Network Tools, Settings & Themes, Voice Control, GPC/Cronus, Troubleshooting, and Keyboard Shortcuts. Accessible from the sidebar rocket icon (🚀).

### Collapsible & Reorderable Sections (v5.2.0)

The Clumsy Control sections — Preset, Direction, Modules, and Live Stats — are wrapped in collapsible cards with ▶/▼ toggle headers and ▲/▼ reorder buttons. Engine and capture-layer selection are backend-owned: DupeZ resolves them from the requested effects and selected target. The scheduler/macro controls sit inline beneath the disrupt buttons; Smart Mode, Voice, and GPC/Cronus live in the Network Tools view.

### Local Forwarding + A2S Health Verification (v5.6.0)

Closed-loop lab verification for owned same-network devices and private DayZ
servers. The verifier samples Source-query reachability during a bounded
operation, records whether the private endpoint stayed healthy, degraded, or
temporarily disconnected, and writes that summarized state to the local
operation journal. The learning loop consumes only aggregate health outcomes so
operators can compare lab presets without storing raw targets or packet
payloads.

Vendor column now resolves against the full IEEE OUI database (~35k entries via scapy MANUFDB) instead of the 60-entry curated table — Ring, HUMAX, Murata, Texas Instruments, Chamberlain, HP, Samsung, Apple, and every other registered manufacturer populate correctly.

### WiFi Lab Path Reliability (v5.7.2)

Same-network lab workflows now fail visibly instead of presenting a successful
operation when client isolation or adapter policy prevents observation. v5.7.2
keeps the isolation watchdog, raises the grace window to avoid false positives,
and falls back to clearly announced self-diagnostics when the owned peer path is
not available. `params["_force_self_disrupt"]` remains an explicit opt-in for
operators who are intentionally testing only their own traffic.

### Tools-Menu Surfaces (v5.7.4)

Six feature backends that shipped backend-only in v5.7.0/v5.7.1 are now reachable from the UI:

- **Risk Score** — `Tools → Risk Score…` shows the live 0-100 score with the six-factor breakdown (active cuts, audit volume, kill-switch state, episode rate, server-integrity signal, network changes).
- **Diagnostics** — `Tools → Diagnostics…` (F2) runs all 8 self-checks (Npcap, WinDivert handle, IP forwarding, ARP table, audit log, episode store, signing key, update channel) with pass/warn/fail and per-check remediation hints.
- **Kill Switch — Panic Stop** — `Tools → Kill Switch` (Ctrl+Alt+X) immediately halts every active disruption. The manual half of the kill-switch feature; auto-triggers (server-integrity / risk threshold / packet rate) still pending a settings panel.
- **OBS Overlay Server** — `Tools → Toggle OBS Overlay Server` starts/stops the localhost-bound HTTP endpoint and shows the browser-source URL. Auto-starts on launch when `settings.obs_overlay_enabled` is set.
- **Audit Webhook Fan-Out** — `AuditLogger.log()` now actually emits configured Discord/generic webhook events after the canonical JSONL write. Best-effort, daemon-threaded, never raises into the audit hot path. Configure under Settings → Audit.
- **Episode Store Rotation** — 90-day / 5000-file retention now enforced once per launch; the JSONL episode store no longer grows unbounded.

### Security Hardening (v5.7.3)

Five post-audit fixes to the v5.6.9–v5.7.2 modules (added after the v5.6.2 nation-state cert sweep, never security-reviewed): backup restore path allowlist (`app/data` + `app/config` only — closed an arbitrary-code-execution path from hand-crafted bundles); decompression-bomb caps on backup restore; overlay server `/state` no longer ships wildcard CORS (was leaking live disruption state to any website the operator visited); webhook URL scheme allowlist (`https://` or loopback `http://` only — `file://`/`ftp://` blocked); preset `params` underscore-key allowlist + 16 KB size cap so a shared preset can't inject engine control flags. 15 new security regression tests in `tests/test_security_v573.py`.

### Windows Installer & Auto-Update (v5.2.0)

Proper Inno Setup installer registers DupeZ in Add/Remove Programs with full uninstall support. Windows application manifest and VS_VERSION_INFO resource for SmartScreen trust. In-app auto-updater checks GitHub Releases and can download + silently install new versions with progress feedback.

---

## Presets

| Preset | Effect |
|--------|--------|
| Automatic Connection Test | One click: lag long enough to release delayed traffic, then a bounded 5-second disconnect, then release |
| Red Disconnect | Pure stateful 100% cut with optional arm delay and duration |
| Lag | Pure sustained packet delay — tune the delay slider after selecting (Light ~800ms · Max ~5000ms) |
| Custom | Set your own parameters |

**Automatic Connection Test** is the default one-click workflow. It runs the
existing pure Lag and Red Disconnect presets as separate bounded stages, stops
cleanly between them, and always releases the final stage. On the native path,
it advances only after Lag has actually released delayed traffic and reports a
failure if either stage affects no packets. The Clumsy path verifies its
layer, controls, and requested values at startup, but is labeled
`runtime-unobservable` because standalone Clumsy exposes no packet counters.
Manual Lag, Red Disconnect, and Custom runs remain available for single-stage
diagnostics. There is no normal-user engine or capture-layer choice.

Platform-specific presets (`pc_local`, `ps5_hotspot`, `xbox_hotspot`) live in the game profile JSON and are auto-selected at disrupt time based on target subnet, MAC OUI, hostname, and device type — see `app/firewall/target_profile.py::resolve_target_profile`.

---

## Requirements

- Windows 10/11 (64-bit)
- Python 3.10+
- Administrator privileges (required for WinDivert kernel driver)

### Build Dependencies (optional)

- [Inno Setup 6+](https://jrsoftware.org/isinfo.php) — Required only to compile the installer (`iscc` must be on PATH)
- Code signing certificate — Optional for local builds, strongly recommended for releases. Set `DUPEZ_SIGN_CERT` and `DUPEZ_SIGN_PASS` to Authenticode-sign `build.bat` outputs and all `build_variants.bat` release executables with SHA-256 timestamping.

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

# Safe maintenance commands (no Administrator required)
python -m app.cli diagnostics
python -m app.cli diagnostics --json
python -m app.cli health
python -m app.cli health --json
python -m app.cli pktmon plan --port 2302 --protocol udp
python -m app.cli pktmon plan --port 2302 --protocol udp --json
python -m app.cli performance smoke
python -m app.cli performance smoke --json
python -m app.cli status --json
python -m app.cli report active --output-dir .\reports
python -m app.cli privacy scan
python -m app.cli privacy scan --json
python -m app.cli privacy retention
python -m app.cli privacy retention --max-age packet-capture=3 --json
python -m app.cli privacy scrub --apply
python -m app.cli recovery audit-status
python -m app.cli recovery audit-status --json
python -m app.cli recovery secret-store-status
python -m app.cli recovery secret-store-status --json
python -m app.cli recovery secret-store-repair-plan
python -m app.cli recovery secret-store-repair-plan --json
python -m app.cli safety status
python -m app.cli safety status --json
python -m app.cli safety acknowledge --owned-authorized-network
python -m app.cli storage status
python -m app.cli storage status --json
python -m app.cli support bundle
python -m app.cli support bundle --json
```

`diagnostics` runs the same health checks exposed in the GUI, including
secret-store access, persistence integrity key mode, audit-chain health, and a
passive WiFi adapter route check. The safe JSON commands redact user-specific
local filesystem roots and report classified error codes such as
`permission_denied` so support output is useful without exposing local paths.
`health` combines those checks with aggregate adapter readiness, default-route
type, Pktmon/PCAPNG capability, safety-policy state, recovery status, a health
score, and prioritized recommendations. It excludes adapter names, raw IPs,
MACs, and packet payloads.
`pktmon plan` previews a filter-required Windows Packet Monitor capture without
changing system state. Actual capture requires Administrator rights plus both
`--apply` and `--accept-sensitive-capture`. Captures are capped at 30 seconds,
32 MB circular storage, NIC components, and 64 bytes per packet. DupeZ refuses
to alter pre-existing global Pktmon filters and never uploads capture files.
ETL/PCAPNG artifacts are included in `privacy scan` and quarantine workflows.
`performance smoke` runs local no-engine benchmarks for storage status,
retention planning, and scenario-report generation against conservative support
budgets; add `--include-support-bundle` when you also want to measure full
redacted support-bundle creation.
`status --json` includes a privacy-preserving active-operation snapshot with
masked targets and remaining automatic-stop time. `report active` writes a
deterministic scenario report using UTC timestamps and IPPM metric terminology.
Raw targets and parameter values are excluded; parameter sets are represented
by stable fingerprints so repeated configurations can be compared safely.
`privacy scan` inventories ignored local runtime artifacts such as audit logs,
episode telemetry, support bundles, reports, managed backup archives, old
privacy quarantines, packet captures, logs, crash reports, and device caches.
`privacy retention` previews conservative age-based cleanup windows for local
artifacts; add `--apply` to quarantine only expired items, or repeat
`--max-age CATEGORY=DAYS` to override a category.
`privacy scrub --apply` quarantines the full inventory under
`app/data/privacy-quarantine-*`. Add `--include-account-data` only when you
also want account tracker/profile files to participate. `recovery
audit-status` reports whether the local tamper-evident audit chain is valid,
sealed, or running with a degraded key. `recovery secret-store-status` checks
whether the OS-backed key store is reachable and writable. Add `--json` to
safe maintenance commands when another tool needs parseable output. `support
bundle` writes a redacted JSON support artifact containing diagnostics,
secret-store health, and privacy inventory metadata without raw logs, secrets,
account contents, raw IPs, MACs, or user-specific local paths. It includes
privacy category counts and retention eligibility by default; add
`--include-file-list` only when support needs exact runtime filenames.
`safety status` reports the versioned authorized-use acknowledgement. Active
CLI operations require it unless `--dry-run` is used. `storage status` reports
managed runtime roots, migration marker health, and legacy-file candidate
counts with local paths redacted in JSON/support output.

### Build standalone exe

Run from the repo root. All build scripts and PyInstaller specs live in `packaging\` but write output to repo-root `dist\`.

```powershell
# Prerequisite: .venv uses 64-bit Python 3.11.9.
# Each script recreates an isolated .build-venv and installs only
# hash-pinned build/runtime dependencies.

# Legacy single binary (requireAdministrator):
packaging\build.bat
# Output: dist\dupez.exe + dist\DupeZ_v5.7.9_Setup.exe (installer)

# Modern dual-variant build (RECOMMENDED):
packaging\build_variants.bat
# Output: dist\DupeZ-GPU.exe (asInvoker, split-arch, GPU map)
#         dist\DupeZ-Compat.exe (requireAdministrator, inproc, legacy fallback)
```

Both build paths fail before signing if a PyInstaller archive contains
unfinished Group Finder packages or optional voice/scientific dependencies
that are outside the v5.7.9 production lock.

### Install via Installer (Recommended)

Download `DupeZ_v5.7.9_Setup.exe` from [Releases](https://github.com/GrihmLord/DupeZ/releases) (or use the stable [`DupeZ_Setup.exe`](https://github.com/GrihmLord/DupeZ/releases/latest/download/DupeZ_Setup.exe) alias which always points at the latest release). The installer:

1. Installs to `Program Files\DupeZ` — trusted path, no SmartScreen warnings after signing
2. Registers in **Add/Remove Programs** with version, publisher, and icon
3. Creates Start Menu and Desktop shortcuts
4. Preserves Windows trust metadata and relies on signatures/hashes instead of overriding SmartScreen or Windows Application Control
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
│   ├── gpc_generator.py             # Accessibility/diagnostic .gpc script generator
│   └── device_bridge.py             # Cronus USB device detection
├── firewall/
│   ├── native_divert_engine.py      # WinDivert packet engine (ctypes, batch API)
│   ├── clumsy_network_disruptor.py  # Dual-engine orchestrator (native + clumsy)
│   ├── engine_base.py               # DisruptionManagerBase ABC
│   ├── packet_classifier.py         # Real-time packet classification engine
│   ├── tick_sync.py                 # Legacy timing helper (not public-selectable)
│   ├── statistical_models.py        # Gilbert-Elliott, Pareto, token bucket, correlated
│   ├── asymmetric_presets.py        # 14 named directional presets
│   ├── blocker.py                   # netsh firewall rules (fallback)
│   └── modules/                     # Extracted disruption modules
│       ├── lag.py                   # Connection-preserving lag (v5.2)
│       ├── drop.py                  # Random packet drop
│       ├── disconnect.py            # Bounded temporary disconnect module
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
tests/                               # Broad unit/integration suite with hardware-gated checks
tools/                               # Operator CLI utilities (scan/lag smoketest, etc.)
bench/                               # Micro-benchmarks for hot paths
docs/
├── adr/                             # Architecture Decision Records
├── release-notes/                   # Per-version release notes + deploy checklists
├── audits/                          # Deep-audit reports (WiFi disrupt, etc.)
├── user_guides/                     # End-user how-to docs
├── integration/                     # Integration and platform notes
└── reports/                         # Audit and research reports (DOCX deliverables)
logs/
└── archive/                         # Quarantined crash dumps and stale traces
```

---

## Architecture

DupeZ supports two runtime architectures, selectable at build time:

- **Split (GPU variant)** — Medium-integrity GUI process with an elevated helper subprocess for WinDivert operations. Launches via `asInvoker` manifest; UAC prompt only for the helper. Enables GPU-accelerated map rendering.
- **In-process (Compat variant)** — Single elevated process with `requireAdministrator` manifest. Legacy fallback for systems where split-arch IPC fails.

The active architecture is displayed in the About dialog as the ARCH field.

### Package boundaries

- `app.gui` owns presentation and may depend on backend services.
- `app.core` owns orchestration, persistence, diagnostics, presets, and reusable
  platform capability probes. It must not import `app.gui`.
- `app.firewall_helper` owns the elevated split-process boundary and must not
  import `app.gui`.
- Built-in preset definitions live in `app.core.builtin_presets`; the GUI
  exposes a compatibility alias but does not own the data.
- GPU capability detection lives in `app.core.gpu_probe`, allowing the GUI and
  helper architecture selector to share the probe without crossing layers.
- `AppController` owns its service lifecycle explicitly. Dependencies can be
  injected, construction can be inert with `auto_start=False`, and startup,
  shutdown, scheduler, plugin, engine, and scan-thread ownership are
  idempotent.

These rules are enforced by `tests/test_architecture_boundaries.py`.

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

The Help → Hotkeys dialog (F1) self-generates from the live menu bar, so it can never drift from the table below.

| Key | Action |
|-----|--------|
| Ctrl+S | Scan network |
| Ctrl+D | Stop all disruptions |
| Ctrl+1 / 2 / 3 / 4 | Switch views (Clumsy Control / Map / Accounts / Network Tools) |
| Ctrl+, | Settings |
| Ctrl+E | Export device data |
| Ctrl+Q | Exit |
| Ctrl+Shift+D | Toggle tray visibility |
| Ctrl+Shift+P | Custom Preset Editor |
| Ctrl+Alt+A | Next account (multi-account quick-switch) |
| Ctrl+Alt+Shift+A | Previous account |
| F1 | Help → Hotkeys dialog |
| F2 | Diagnostics wizard (v5.7.5) |
| Ctrl+Alt+X | Kill Switch — Panic Stop (v5.7.5) |

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
