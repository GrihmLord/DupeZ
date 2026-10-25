# DupeZ v5.8.0

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

![Windows](https://img.shields.io/badge/platform-Windows%2011-blue) ![Python](https://img.shields.io/badge/python-3.12%20%7C%203.13-green) ![Release](https://img.shields.io/badge/v5.8.0-release%20gates%20pending-orange)

v5.8.0 is in preparation, not approved for public distribution. See the
[current launch plan](docs/release-notes/LAUNCH_PLAN_5.8.0.md) for remaining
owner, CI, native-runtime security, signing and exact-artifact gates. Older files in `dist` are not the
validated v5.8.0 release. Maintainers can inspect preparation status without
running binaries or advancing release phases:

```powershell
python scripts/release_readiness.py --version 5.8.0
```

---

## Features

### Safe Network-Condition Engine

DupeZ selects and verifies the packet engine automatically:

1. **Verified Clumsy Compatibility** — The primary path for effects that the
   bundled Clumsy executable can represent exactly. DupeZ confirms the
   Local/Remote capture layer, enabled modules, numeric values, and Start
   state before hiding the Clumsy window.
2. **Native WinDivert Extension Host** — Used only for explicitly namespaced
   DupeZ extensions such as the bounded Connection Resilience and experimental
   Pulse Resilience labs. A Clumsy startup failure remains failed; it never causes a
   silent Native substitution. Mixed standard/extension requests fail before
   launch. Native extensions expose packet and per-module counters.

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

Lightweight plugin loader for fully trusted extensions. Signed manifest-v2 bundles cover every Python helper, native module, and resource in the plugin directory; production rejects unsigned, legacy entry-only, modified, missing, or added files. The pinned publisher key—not in-process capability diagnostics—is the security boundary, because plugins run with the host user's authority. **UIPanelPlugin** and **GenericPlugin** have host integration today. **DisruptionPlugin** and **ScannerPlugin** remain typed extension contracts: the core disruption/scanner dispatch paths do not invoke them yet. Reload is an internal, fail-closed lifecycle operation and is not currently exposed through the Tools menu or CLI.

### CLI Mode (v4.0.0+)

Run DupeZ headless from the terminal. Subcommands: `scan`, `disrupt`, `stop`, `status`, `devices`, `plugins`. Interactive REPL with `dupez-cli interactive`. Script disruptions with `--methods` and `--params` flags for automation pipelines.

### Network Tools (v3.3.0+)

Network intelligence toolkit. Four core tabs — Live Traffic Monitor, Latency Overlay (floating transparent widget), Port Scanner, and Connection Mapper with gaming port detection and hostname resolution — plus AI / Smart Ops, GPC / Cronus Zen, and LAN Cut tabs that appear when their subsystems are available.

### iZurvive Map

The map selector provides reviewed iZurvive URLs for Chernarus+ (Satellite/Topographic), Livonia, Namalsk, Sakhal, Deer Isle, Esseker, and Takistan. Embedded browsing requires a verified non-elevated Windows process, sandboxing, and an admitted patched Qt/WebEngine runtime. The currently available Qt 6.11.2 wheels do not satisfy the 6.11.3 security floor, so this candidate shows a selectable URL to open manually in your normal browser instead. It does not launch a browser from an elevated or otherwise denied context.

When an admitted runtime is available, embedded navigation and resources are restricted to explicitly reviewed HTTPS hosts; popups, downloads, file selection, certificate overrides and permission requests are denied. Its browser profile is ephemeral. These controls do not replace exact-build security validation.

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

Vendor labels resolve from DupeZ's reviewed gaming/device OUI table. Unknown
prefixes remain explicitly `Unknown`; target selection still uses the observed
MAC and IP, so the informational label never controls network actions.

### WiFi Lab Path Reliability (v5.7.2)

Same-network lab workflows now fail visibly instead of presenting a successful
operation when client isolation or adapter policy prevents observation. v5.7.2
keeps the isolation watchdog, raises the grace window to avoid false positives,
and falls back to clearly announced self-diagnostics when the owned peer path is
not available. `params["_force_self_disrupt"]` remains an explicit opt-in for
operators who are intentionally testing only their own traffic.

### Tools-Menu Surfaces (v5.7.4, completed in v5.8.0)

Seven feature backends that shipped backend-only in v5.7.0/v5.7.1 are now reachable from the UI:

- **Risk Score** — `Tools → Risk Score…` shows the live 0-100 score with the six-factor breakdown (active cuts, audit volume, kill-switch state, episode rate, server-integrity signal, network changes).
- **Diagnostics** — `Tools → Diagnostics…` (F2) runs all 14 registered
  readiness and integrity checks (including admin status, WinDivert/Npcap,
  Wi-Fi and Clumsy availability, secret/persistence stores, audit and
  operation journals, runtime storage, firewall posture, and update/episode
  state) with pass/warn/fail remediation hints. Copy and Save Support Bundle
  export only the redacted results currently shown.
- **Cut-Chain Configurator** — `Tools → Cut-Chain Configurator…`
  (`Ctrl+Shift+C`) builds a bounded sequence of known presets with time,
  severed, connected, or packet-count gates. It supports atomic JSON
  save/load, requires an owned-or-authorized private target acknowledgement,
  and is revalidated against the current controller safety scope before use.
- **Kill Switch** — `Tools → Kill Switch — Panic Stop` (`Ctrl+Alt+X`)
  immediately halts every active disruption. `Settings → Network → Automatic
  Kill Switch` configures the process-watch, risk-score, sustained packet-rate,
  polling, and cooldown triggers; malformed persisted trigger settings block
  new network mutations until corrected while the manual panic stop remains
  available.
- **OBS Overlay Server** — `Tools → Toggle OBS Overlay Server` starts/stops the localhost-bound HTTP endpoint and shows the browser-source URL. Auto-starts on launch when `settings.obs_overlay_enabled` is set.
- **Audit Webhook Fan-Out** — `Tools → Audit Webhook…` provisions, enables,
  disables, or removes a Discord/generic webhook without displaying a stored
  URL. `AuditLogger.log()` emits best-effort events after the canonical JSONL
  write and never raises into the audit hot path. The CLI's hidden-input
  `python -m app.cli webhook provision --apply` remains available for
  automation; only non-secret metadata is kept in settings. See [audit webhook
  credential storage](docs/WEBHOOK_SECRET_STORAGE.md).
- **Episode Store Rotation** — 90-day / 5000-file retention now enforced once per launch; the JSONL episode store no longer grows unbounded.

### Security Hardening (v5.7.3)

Five post-audit fixes to the v5.6.9–v5.7.2 modules (added after the v5.6.2 nation-state cert sweep, never security-reviewed): backup restore path allowlist (`app/data` + `app/config` only — closed an arbitrary-code-execution path from hand-crafted bundles); decompression-bomb caps on backup restore; overlay server `/state` no longer ships wildcard CORS (was leaking live disruption state to any website the operator visited); webhook URL scheme allowlist (`https://` or loopback `http://` only — `file://`/`ftp://` blocked); preset `params` underscore-key allowlist + 16 KB size cap so a shared preset can't inject engine control flags. 15 new security regression tests in `tests/test_security_v573.py`.

### Windows Installer & Auto-Update (v5.2.0)

Proper Inno Setup installer registers DupeZ in Add/Remove Programs with full uninstall support. Windows application manifest and VS_VERSION_INFO resource for SmartScreen trust. The in-app updater checks GitHub Releases and can download + silently install a newer installer only when its Ed25519-signed metadata binds a Windows-trusted Authenticode publisher. Explicitly unsigned releases remain manual download/install only and are never auto-executed.

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

- Windows 11 (64-bit), or a Windows 10 LTSC/ESU edition still receiving
  Microsoft security updates
- Python 3.12 or 3.13 for source use; release artifacts use Python 3.13.17 x64
- Administrator privileges (required for WinDivert kernel driver)

### Build Dependencies (optional)

- [Inno Setup 6.7.1](https://jrsoftware.org/isinfo.php) — required only to
  compile the installer. Release builds accept the exact Program Files path,
  SHA-256, and Authenticode signer pinned in `packaging/release-tools.json`;
  ambient `PATH` discovery is rejected.
- Code signing certificate — Optional for local builds and mandatory for
  releases. Set `DUPEZ_SIGN_CERT`, `DUPEZ_SIGN_PASS` when required, and
  `DUPEZ_SIGN_PRIVKEY` for updater metadata. The release finalizer accepts only
  the exact Windows SDK x64 SignTool path, SHA-256, version, and Authenticode
  signer pinned in `packaging/release-tools.json`; release artifacts use
  SHA-256 with RFC3161 timestamping.

### Firewall Binaries

The following must be present in `app/firewall/`:

- `WinDivert.dll` — Kernel packet interception library
- `WinDivert64.sys` — WinDivert kernel driver
- `clumsy.exe` — Canonical engine for standard packet effects (pinned v0.3.4)

---

## Quick Start

```powershell
# Clone
git clone https://github.com/GrihmLord/DupeZ.git
cd DupeZ

# Install the reviewed, hash-pinned runtime graph
python -m pip install --require-hashes -r requirements-locked.txt

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
safe maintenance commands when another tool needs parseable output. `webhook
status` reports URL-free configuration state, while `webhook provision
--apply` stores the endpoint in the OS-backed secret store instead of settings
or backups. Historical pre-migration archives may still contain the old bearer
URL; revoke or rotate that provider token as described in
[the credential migration note](docs/WEBHOOK_SECRET_STORAGE.md). `support
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
# Prerequisite: .venv uses 64-bit Python 3.13.17.
# Each script recreates an isolated .release-venv and installs only
# hash-pinned build/runtime dependencies.

# Local legacy portable (requireAdministrator, non-release):
packaging\build.bat
# Output: dist\dupez.exe only

# Canonical release/installer build:
packaging\build_variants.bat
# Output: dist\DupeZ-GPU.exe (asInvoker, split-arch, GPU map)
#         dist\DupeZ-Compat.exe (requireAdministrator, inproc, legacy fallback)
#         dist\DupeZ_v5.8.0_Setup.exe + dist\DupeZ_Setup.exe
#         dist\LICENSE.txt + dist\SOURCE_AND_RELINK.txt
#         dist\THIRD_PARTY_NOTICES.txt + dist\license-payload.json
```

`packaging\build.bat` is retained for local compatibility testing and never
invokes Inno Setup or creates installer aliases. It is not a public-release
entry point. All installer and release artifacts must come from
`packaging\build_variants.bat` through the protected finalization flow.
The finalizer also creates `dist\DupeZ-v5.8.0-source.zip` with `git archive`
from the exact clean commit. Its hash is bound into the release checksum list
and attestation.

Both executable build paths fail before signing if a PyInstaller archive contains
unfinished Group Finder packages or optional voice/scientific dependencies
that are outside the v5.8.0 production lock. Packaged config, icons, and
themes must also match `packaging/release-data.json`; generated HMACs,
bytecode caches, and untracked local files are rejected.
Distribution builds additionally fail unless the owner-controlled license/IP
policy is fully evidenced. The installer displays the project license and
installs the deterministic, exact-lock third-party notices and source/relink
record beside the executables.

### Install via Installer (Recommended)

v5.8.0 remains a release candidate until every exact-artifact gate in the
[roadmap](ROADMAP.md) passes. Until it is published, use the current public
build from [Releases](https://github.com/GrihmLord/DupeZ/releases); do not infer
availability from the source version. Once v5.8.0 is released, its versioned
installer and the stable [`DupeZ_Setup.exe`](https://github.com/GrihmLord/DupeZ/releases/latest/download/DupeZ_Setup.exe)
alias will be available there. The installer:

1. Installs to `Program Files\DupeZ`; standard distribution builds copy the
   provenance-pinned native payload into an ignored stage, Authenticode-sign
   only the staged `clumsy.exe`, and prove that it differs from the reviewed
   unsigned source only by valid PE signing structures. Both PyInstaller
   variants and the installer consume that verified stage; final preflight
   remeasures the nested bytes and requires the updater-bound signer.
   Tracked upstream binaries are never modified. Windows reputation and Smart
   App Control decisions remain under Microsoft's policy; explicitly
   authorized unsigned releases must disclose the resulting warnings.
2. Registers in **Add/Remove Programs** with version, publisher, and icon
3. Creates Start Menu and Desktop shortcuts
4. Release policy relies on Authenticode plus signed updater metadata and does not promise to bypass SmartScreen or Windows Application Control
5. Supports upgrade-in-place — re-run a newer installer without uninstalling first
6. **In-app auto-update** — DupeZ checks GitHub Releases on launch and can
   download + install an update directly only when the installer has the
   trusted Authenticode identity bound by its signed updater manifest. An
   explicitly unsigned release requires manual download and installation.

---

## Project Structure

```
dupez.py                             # Entry point (GUI mode)
dupez_helper.py                      # Elevated helper entry point (split-arch)
requirements.in                      # Human-edited dependency constraints
requirements.txt                     # Compatibility shim to the exact lock
requirements-locked.txt              # Reviewed, hash-pinned runtime graph

packaging/                           # All PyInstaller + Inno Setup build files
├── dupez.spec                       # Legacy single-binary PyInstaller spec
├── dupez_gpu.spec                   # DupeZ-GPU.exe spec (asInvoker, split)
├── dupez_compat.spec                # DupeZ-Compat.exe spec (requireAdmin, inproc)
├── build_common.py                  # Shared Analysis/PYZ/EXE factory
├── dupez.manifest                   # Windows app manifest (GPU/asInvoker)
├── dupez_compat.manifest            # Windows manifest (Compat + legacy/admin)
├── version_info.py                  # VS_VERSION_INFO resource for exe metadata
├── installer.iss                    # Inno Setup installer script
├── build.bat                        # 3-step local legacy portable (non-release)
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

- **Split (GPU variant)** — Medium-integrity GUI process with an elevated helper subprocess for WinDivert operations. Launches via `asInvoker` manifest; UAC prompt only for the helper. Embedded map rendering additionally requires native-browser security admission; it is currently unavailable with the pinned Qt 6.11.2 wheels.
- **In-process (Compat variant)** — Single elevated process with `requireAdministrator` manifest. Legacy fallback for systems where split-arch IPC fails. Remote embedded browsing is blocked; use the displayed map URL manually in a normal non-administrator browser.

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

Help → Hotkeys (F1) lists live window shortcuts separately from global hook
registration status. The table below shows window defaults, except the optional
global tray binding. A window shortcut is not an OS-wide emergency binding.

Settings → Hotkeys adds opt-in global Stop All/Panic Stop and a separate opt-in
Start. Defaults: Ctrl+Alt+F8 (Start), Ctrl+Alt+F9 (Stop All), Ctrl+Alt+X (Panic).
Global actions fire on key release. Start requires both emergency hooks and uses
the normal selected-target checks. F1 shows actual armed keys and failures;
registration does not guarantee that another app will pass through the keys.

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
| Ctrl+Shift+C | Cut-Chain Configurator |
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

The owner selected **GPL-3.0-only** for original DupeZ code, with corresponding
source. See [LICENSE.txt](LICENSE.txt) and the
[dated selection record](packaging/license-evidence/project-distribution-terms-2026-10-24.txt).
Third-party components retain their own licenses; this choice does not relicense them.

Release evidence remains incomplete in `packaging/license-policy.json`:
contribution-rights confirmation, exact dependency obligations, delivered notices
and a verified corresponding-source/rebuild route are still required. The
[owner checklist](docs/release-notes/BLOCKED_RELEASE_GATES_RUNBOOK_5.8.0.md#owner-action-checklist-2026-10-24)
separates remaining owner decisions from engineering validation. A license
selection is not approval to publish unvalidated v5.8.0 binaries.

---

**Built by [GrihmLord](https://github.com/GrihmLord)**
