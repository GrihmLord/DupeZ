# DupeZ v3.5.0

Network disruption toolkit for DayZ. Wraps Clumsy + WinDivert for per-device packet manipulation through a clean PyQt6 dashboard.

Built for the DayZ community — scan your local network, target specific devices, and apply real-time packet disruption with granular control over lag, drops, throttling, duplication, corruption, and more. Includes AI auto-tuning, scheduled disruptions, macro chains, live traffic monitoring, and a connection mapper.

![Windows](https://img.shields.io/badge/platform-Windows%2010%2F11-blue) ![Python](https://img.shields.io/badge/python-3.10%2B-green) ![License](https://img.shields.io/badge/license-Proprietary-red)

---

## Features

### Clumsy Control (Main View)
ARP/TCP network scanner with per-device disruption controls. Select a device, pick your disruption methods, dial in parameters with sliders, and go. Includes preset profiles, session timers, live status feedback, multi-device targeting, scheduled disruptions, and macro chains.

**Disruption Methods:** Drop, Lag, Throttle, Duplicate, Corrupt, RST Injection, Bandwidth Cap, Full Disconnect, Out-of-Order, God Mode

**Presets:**

| Preset | Effect |
|--------|--------|
| Red Disconnect | 95% drop + 2000ms lag + 1KB/s cap + full throttle + disconnect |
| DupeZ Default | Disconnect + 95% drop + 1500ms lag + 1KB/s cap + throttle |
| Heavy Lag | 3000ms delay + 95% drop + 1KB/s cap |
| Light Lag | 800ms delay + 60% drop |
| God Mode | Directional lag — others freeze, you keep moving. 2000ms inbound lag |
| God Mode Aggressive | God Mode + 30% inbound drop for harder freeze |
| Desync | Duplicate flood + 800ms lag + out-of-order — massive server desync |
| Bandwidth Cap | Throttle to 1KB/s — near-zero bandwidth |
| Ghost Rush | Outbound-only freeze — enemies see you frozen while you move freely |
| Phantom Peek | Quick outbound burst — peek, shoot, vanish before they update |
| Total Chaos | All modules maxed — complete network destruction |
| Custom | Set your own parameters |

### AI Smart Mode (v3.1.0+)
Network profiler + ML-based parameter optimizer. Profiles target connections in real-time (RTT, jitter, loss, bandwidth, device type, connection type) and generates optimal disruption configs. 6 goal strategies: Disconnect, Lag, Desync, Throttle, Chaos, God Mode. Optional LLM advisor via Ollama or any OpenAI-compatible API for natural-language disruption tuning.

### God Mode (v3.4.0+)
Directional lag engine — inbound packets are delayed while outbound passes through untouched. The target's game client stops receiving your position updates (you freeze on their screen), but your actions register on the server in real time. Configurable inbound lag (0-5000ms) and optional inbound packet drop for harder freeze. Most effective on ICS/hotspot where your machine is the gateway.

### Voice Control (v3.4.0+)
Push-to-talk voice commands powered by OpenAI Whisper (local, offline). Hold the PTT button, speak a command like "heavy lag on the PS5" or "god mode", and the LLM advisor interprets it into a disruption config. Supports model selection (tiny/base/small), mic selection, and simple start/stop voice commands. Requires `sounddevice` and `openai-whisper` packages (optional — DupeZ runs without them).

### GPC / CronusZEN Support (v3.4.0+)
Native GPC script integration for CronusZEN and CronusMAX devices. Parse existing .gpc files, generate new scripts synced with DupeZ disruption timing, and export directly to Zen Studio's library folder. Built-in templates: DayZ Auto Dupe, Rapid Fire, God Mode Actions, Anti Recoil. Auto-detects connected Cronus devices via USB. Requires `pyserial` for device detection (optional).

### Network Tools (v3.3.0+)
Four-tab network intelligence toolkit: Live Traffic Monitor (per-interface bandwidth), Latency Overlay (floating transparent ping/jitter widget), Port Scanner (Common/Gaming/Web/Full presets), and Connection Mapper (real-time topology with gaming port detection and hostname resolution).

### iZurvive Map
Ad-free embedded iZurvive with map selector dropdown. MutationObserver-based ad blocker catches dynamically injected ads.

**Supported Maps:** Chernarus+ (Satellite), Chernarus+ (Topographic), Livonia, Namalsk, Sakhal, Deer Isle, Esseker, Takistan

### Account Tracker
Multi-account DayZ manager with full CRUD, XLSX/CSV import and export, search and filter, bulk operations, and per-account status tracking. Formatted XLSX export with status color-coding. Data persists across sessions via atomic JSON writes.

**Statuses:** Ready, Blood Infection, Storage, Dead, Offline

**Fields:** Account, Email, Location, Value, Status, Station, Gear, Holding, Loadout, Needs

---

## Requirements

- Windows 10/11 (64-bit)
- Python 3.10+
- Administrator privileges (required for WinDivert kernel driver)

### Firewall Binaries

The following must be present in `app/firewall/`:

- `clumsy.exe` — Packet manipulation engine
- `WinDivert.dll` — Kernel packet interception library
- `WinDivert64.sys` — WinDivert kernel driver

These are included in this repository. If missing, download Clumsy from [its official source](https://jagt.github.io/clumsy/) and place the binaries in `app/firewall/`.

---

## Quick Start

```powershell
# Clone
git clone https://github.com/GrihmLord/DupeZ.git
cd DupeZ

# Install dependencies
pip install -r requirements.txt

# Run (auto-elevates via UAC)
python dupez.py
```

### Build standalone exe

```powershell
pip install pyinstaller
build.bat
# Output: dist\dupez.exe
```

---

## Project Structure

```
dupez.py                             # Entry point — run this
dupez.spec                           # PyInstaller build spec
build.bat                            # One-click build script
app/
├── main.py                          # UAC elevation, crash handler, Qt init
├── core/
│   ├── controller.py                # Scan, disrupt, block — main app logic
│   ├── state.py                     # Observable state + device model
│   ├── data_persistence.py          # JSON persistence for accounts/settings
│   ├── scheduler.py                 # Disruption scheduler + macro engine
│   └── profiles.py                  # Named disruption profile system
├── ai/
│   ├── smart_engine.py              # ML-based disruption parameter optimizer
│   ├── network_profiler.py          # Target connection profiler (RTT/jitter/loss)
│   ├── llm_advisor.py               # Natural-language disruption tuning (Ollama/OpenAI)
│   ├── session_tracker.py           # Session history + feedback learning
│   └── voice_control.py             # Push-to-talk voice commands via Whisper STT
├── gpc/
│   ├── gpc_parser.py                # CronusZEN .gpc script tokenizer + parser
│   ├── gpc_generator.py             # Generate .gpc scripts synced with DupeZ
│   └── device_bridge.py             # Cronus USB device detection + Zen Studio export
├── firewall/
│   ├── clumsy_network_disruptor.py  # Clumsy.exe + native WinDivert engine
│   ├── native_divert_engine.py      # Pure Python WinDivert packet interception
│   ├── blocker.py                   # netsh firewall rules (fallback)
│   ├── clumsy.exe                   # Clumsy binary
│   ├── WinDivert.dll / .sys         # WinDivert driver
│   └── clumsy_src/                  # Clumsy C source (with --silent patch)
├── gui/
│   ├── dashboard.py                 # 4-view sidebar rail (Clumsy | Map | Accounts | Network)
│   ├── clumsy_control.py            # Device list + disruption controls + presets + AI panel
│   ├── network_tools.py             # Traffic monitor, latency overlay, port scanner, connection mapper
│   ├── dayz_map_gui_new.py          # Ad-free iZurvive + map selector
│   ├── dayz_account_tracker.py      # Multi-account tracker with XLSX support
│   ├── hotkey.py                    # Global hotkey listener
│   └── settings_dialog.py           # App settings
├── network/
│   ├── device_scan.py               # ARP/TCP device discovery
│   └── enhanced_scanner.py          # Threaded scanner with signals
├── themes/                          # QSS stylesheets (dark, hacker, light, rainbow)
├── logs/                            # Rotating log files (auto-managed)
├── utils/                           # Helpers and system utilities
├── resources/                       # App icons
└── config/                          # JSON config files
```

---

## Hotkeys

| Key | Action |
|-----|--------|
| Ctrl+S | Scan network |
| Ctrl+D | Stop all disruptions |
| Ctrl+1 / 2 / 3 | Switch views (Clumsy / Map / Accounts) |
| Ctrl+, | Settings |
| Ctrl+E | Export device data |
| Ctrl+Q | Exit |

---

## Settings

All settings persist to `app/config/settings.json` and can be configured via **Tools → Settings** (`Ctrl+,`). Reset to Defaults restores every field to its factory value.

### General

Controls automatic network scanning behavior and logging.

| Setting | Default | Description |
|---------|---------|-------------|
| Auto-Scan | On | Continuously scan the network on a timer |
| Scan Interval | 60s | Seconds between automatic scans (30–3600) |
| Max Devices | 100 | Maximum devices to track per scan (10–500) |
| Log Level | INFO | Logging verbosity: DEBUG, INFO, WARNING, ERROR |

### Network

Tunes the scanner's speed, parallelism, and timeout behavior.

| Setting | Default | Description |
|---------|---------|-------------|
| Ping Timeout | 2s | How long to wait for a device response (1–10) |
| Max Threads | 20 | Concurrent scan threads (5–50) |
| Quick Scan | On | Use fast ARP-only scanning mode |

### Smart Mode

Automated threat detection and blocking rules.

| Setting | Default | Description |
|---------|---------|-------------|
| Smart Mode | Off | Enable automatic traffic analysis |
| Auto-Block | Off | Automatically block suspicious devices |
| High Traffic Threshold | 1000 KB/s | Flag devices exceeding this rate (100–10000) |
| Connection Limit | 100 | Max connections before flagging (10–1000) |
| Suspicious Activity | 20 events/min | Threshold for suspicious event detection (5–100) |
| Block Duration | 30 min | How long auto-blocked devices stay blocked (1–1440) |
| Whitelist | Empty | IPs that are never auto-blocked (one per line) |

### Interface

Theme selection, rainbow mode, display preferences, and notifications.

| Setting | Default | Description |
|---------|---------|-------------|
| Theme | Dark | Visual theme: Dark, Light, Hacker, Rainbow |
| Rainbow Mode | Off | Animated HSV color cycling across the entire UI |
| Rainbow Speed | 2.0 | Animation speed for rainbow mode (0.1–10.0) |
| Auto-Refresh | On | Automatically refresh device list display |
| Refresh Interval | 120s | Seconds between UI refreshes (10–300) |
| Device Icons | On | Show device type icons in the device list |
| Status Indicators | On | Show connection status badges |
| Compact View | Off | Reduce row height for denser device list |
| Desktop Notifications | On | Show system tray notifications on events |
| Sound Alerts | Off | Play audio on scan/block events |

**Themes:** Dark (default cyber-dark), Light (clean light mode), Hacker (green-on-black terminal), Rainbow (animated color cycling). Quick-switch buttons or dropdown in the Interface tab. Rainbow mode runs at configurable speed with start/stop controls.

### Advanced

Performance tuning,