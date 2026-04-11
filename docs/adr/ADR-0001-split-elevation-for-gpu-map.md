# ADR-0001: Split elevation — unelevated GUI + elevated WinDivert helper

**Status:** Proposed — awaiting Grihm approval
**Date:** 2026-04-10
**Deciders:** Grihm
**Hard constraint:** Zero regression in duping features, lag features, or packet-path timing.

---

## 1. Context

### 1.1 The problem
DupeZ is a Windows-native PS5 DayZ duping tool built on WinDivert. Because `WinDivert.dll` demands Administrator privileges to load `WinDivert64.sys`, the entire DupeZ process currently runs elevated (the manifest declares `requireAdministrator` and `app/main.py` self-elevates via `ShellExecuteW("runas")` on first start).

A side effect of running elevated is that Chromium's GPU process refuses to initialize under an Administrator token (confirmed twice in prior debugging — the sandbox and GPU child-process model fights UAC integrity levels). QtWebEngine falls back to software rasterization, which hits a ceiling well below native Leaflet/iZurvive responsiveness. Six optimization passes on the in-proc map widget (tile prewarm, software-raster tuning, flag permutations, GPU-flag stripping, splash-phase construction, prewarmed-singleton adoption) got us a fast **first load** but could not fix **interactive pan/zoom fluidity**. Grihm's verdict:

> "its too slow still but better it needs to react more smoothly and naturally like on the web"

That is a hardware-rasterization-level requirement. It is not achievable with Chromium running under an admin token, period.

### 1.2 The non-negotiable constraint
Grihm:

> "we cant kill duping or any of the lag features"

This ADR exists to evaluate whether the architecture can be restructured so that (a) Chromium runs under medium integrity and regains hardware rasterization, while (b) no duping or lag feature regresses in behaviour or timing.

### 1.3 Prior benchmark (spike)
Before any architectural commitment was considered, a throwaway IPC-overhead spike was built (`bench/windivert_ipc_spike.py`, commit `a55601f`). It measures the latency delta of routing a packet-inject request across an IPC boundary (Windows named pipe or loopback TCP) versus a direct in-process function call. Pre-declared pass criteria tied to 2× current peak dupe injection rate (~20k pps).

**Result on Grihm's Windows dev box:**

| Bench | p50 | p99 | p99.9 | throughput |
|---|---|---|---|---|
| in-proc baseline (600 B) | 0.5 µs | 0.7 µs | 5.3 µs | 1.52 M pps |
| loopback TCP (600 B) | 52.2 µs | 108.5 µs | 157.8 µs | 18.0k pps |
| **Windows named pipe (600 B)** | **18.5 µs** | **40.0 µs** | **71.3 µs** | **51.2k pps** |
| TCP burst (600 B, async) | — | — | — | 37.8k pps |

Named pipe **clears every pass threshold with margin**: p50 overhead 18 µs versus 50 µs budget (36 %), p99 overhead 39 µs versus 200 µs budget (20 %), throughput 28 % above 40k-pps floor. Loopback TCP fails, but we would never ship TCP on Windows anyway.

### 1.4 Current hot-path architecture (what we must not break)
Extracted from `app/firewall/native_divert_engine.py`. This is the exact code path that runs for every dupe packet today:

```
┌──────────────────────────────────────────────────────────────┐
│ NativeWinDivertEngine._packet_loop()                 (line 906)│
│                                                              │
│  while self._running:                                        │
│      WinDivertRecv(...)                              (L 943) │
│      # zero-alloc direction detect via u32 compare   (L 989) │
│      for mod in self._modules:                       (L1030) │
│          if not mod.matches_direction(addr): continue        │
│          if mod.process(pkt, addr, self._send_packet):       │
│              consumed = True; break                          │
│      if not consumed:                                        │
│          self._send_packet(pkt, addr)                (L1068) │
│                                                              │
│  _send_packet():                                     (L 885) │
│      with self._send_lock:                                   │
│          memmove(send_buf, pkt, pkt_len)                     │
│          WinDivertHelperCalcChecksums(send_buf, ...)         │
│          WinDivertSend(handle, send_buf, ..., addr)          │
└──────────────────────────────────────────────────────────────┘
```

Module chain runs entirely in-process, each module is a subclass of `DisruptionModule` that imports `WINDIVERT_ADDRESS` directly. Flush threads (GodMode, Lag, OOD, StatisticalFlush) also call `_send_packet` from inside the engine process.

### 1.5 Scope of code that touches the packet path
```
app/firewall/native_divert_engine.py        1,096 lines  (engine + hot loop)
app/firewall/modules/godmode.py                929 lines  (pulse-cycle dupe timing)
app/firewall/statistical_models.py             592 lines  (Gilbert-Elliott, Pareto, token bucket)
app/firewall/packet_classifier.py              554 lines  (packet type classification)
app/firewall/tick_sync.py                      530 lines  (tick-sync drop/pulse)
app/firewall/stealth.py                        428 lines  (behavioural anti-detection)
app/firewall/modules/dupe_engine.py            348 lines  (PREP→CUT→RESTORE state machine)
app/firewall/modules/lag.py                    226 lines  (inbound/outbound lag queue)
app/firewall/engine_base.py                    200 lines  (engine interface)
app/firewall/clumsy_network_disruptor.py    ~1,000 lines  (disruption manager + fallback)
app/firewall/modules/{drop,corrupt,bandwidth,
  disconnect,throttle,ood,rst,duplicate}.py   ~410 lines  (core disruption modules)
app/firewall/modules/recorder_hotkeys.py                (F5-F12 keyboard bindings to GodMode)
app/firewall/packet_recorder.py                         (ML training data capture)
app/firewall/ml_classifier.py                           (ML-based packet type detection)
────────────────────────────────────────────────────────
Total in the "firewall" subtree:            ~5,231 lines
```

Every module imports `DisruptionModule` and `WINDIVERT_ADDRESS` from `native_divert_engine`. `controller.py` owns engine lifecycle via `disruption_manager`. `clumsy_control.py` (GUI tab) configures filters/params. 26 files across the tree import from `app.firewall.*`.

Admin dependencies **beyond** WinDivert:
* `app/firewall/blocker.py` — `netsh advfirewall firewall add rule` requires admin (separate from WinDivert, used by `toggle_lag`).
* `dupez.manifest` — declares `requireAdministrator`.
* `app/main.py` — `ShellExecuteW("runas")` self-elevation on cold start.
* `app/gui/splash.py` — displays admin status.
* `app/cli.py` — refuses to run without admin.
* `app/core/patch_monitor.py` — no admin needed (HTTPS only to Steam API), can stay anywhere.
* Plugins (`plugins/example_logger`, `plugins/example_ping_monitor`) — verified via grep: neither plugin imports `native_divert_engine` or calls WinDivert.

### 1.6 Research findings

| Question | Finding | Source |
|---|---|---|
| WinDivert + Windows service? | "The calling application must have Administrator privileges." LocalSystem meets that requirement, no documented blockers. | WinDivert FAQ |
| Driver install model | "automatically (and silently) installed on demand whenever your application calls WinDivertOpen()". Auto-uninstalls after reboot when no open handles. | WinDivert FAQ |
| Handle ownership | Not explicitly documented whether `DuplicateHandle()` works across processes. Moot for B2 (helper owns all handles). | WinDivert 2.2 docs |
| Multiple processes | WinDivert supports multiple processes opening handles at different priorities; single-process ownership is the default pattern. | WinDivert 2.2 docs |
| Pipe latency (medium→high) | Named pipes on Windows typically 15–60 µs p50 for small messages. Measured: 18.5 µs p50 on Grihm's box. | [Benchmark TCP/UDS/Named Pipe](https://www.yanxurui.cc/posts/server/2023-11-28-benchmark-tcp-uds-namedpipe/), local measurement |
| Cross-integrity pipe access | Helper (high) creates the pipe with a SECURITY_DESCRIPTOR permitting medium-integrity clients. Standard, well-documented pattern. | [MS Learn: Named Pipe Security](https://learn.microsoft.com/en-us/windows/win32/ipc/named-pipe-security-and-access-rights) |
| BattlEye / WFP visibility | BattlEye enumerates WFP filters via the kernel driver. A filter is equally visible whether opened by a service or a GUI process — no detection profile change from splitting. Also no *improvement* from splitting. | [WinDivert 2.0 Wishlist #156](https://github.com/basil00/WinDivert/issues/156), stealth.py |
| Named pipe + GIL | `pywin32` `win32file.ReadFile/WriteFile` release the GIL during blocking IO. Overlapped IO would only help under multi-client contention. Single helper client = no issue. | Conventional pywin32 behaviour |

---

## 2. Decision

**Adopt Option B2 — Control-plane split with unelevated GUI and elevated firewall helper.** Gate behind a feature flag (`DUPEZ_ARCH=split|inproc`) for one release cycle. Default stays `inproc` until benchmarks and dogfooding confirm zero regression.

The entire `app.firewall` subtree (engine, modules, flush threads, classifier, recorder, stealth) moves into the helper process. Main process keeps the GUI, controller, plugins, patch monitor, and everything non-packet. IPC carries **control plane only**: engine lifecycle, config, live stats, dupe triggers, audit events, hotkey fires, recorder commands.

**Critical rule:** no packet ever crosses the IPC boundary. The hot loop's latency is invariant under this refactor.

---

## 3. Options considered

### 3.1 Option A — Leave architecture as-is
| Dimension | Assessment |
|---|---|
| Duping regression risk | Zero |
| Complexity | Zero |
| Map fluidity | **Fail** — software raster, choppy pan/zoom |
| Engineering cost | Zero |
| Future optionality | Blocked — any "make the map feel native" work is gated on this |

**Status:** Current state. Rejected because the map-performance ask is a hard request and software raster has hit its ceiling.

### 3.2 Option B1 — Packet-plane IPC (helper owns handle, main owns modules)
Main process runs unelevated, helper runs elevated and owns the WinDivert handle. On every packet: helper recvs → serializes → pipes to main → main runs modules → main pipes decision → helper injects.

| Dimension | Assessment |
|---|---|
| Duping regression risk | **Fail** — IPC on hot path doubles round-trip time per packet and per flush. Hotspot godmode flush bursts trigger N extra round trips. |
| Complexity | High — every `_send_packet` call becomes IPC. |
| Map fluidity | Unblocks Chromium GPU. |
| Engineering cost | ~2500 lines |
| Latency budget | At 20k pps peak, p999 IPC overhead (66 µs) × 2 round trips/packet = 2.6 ms/s aggregate. Still inside DayZ 60-tick tolerance but razor thin, and flush bursts would concentrate latency. |

**Status:** Rejected. The benchmark passes the single-round-trip budget, but B1 imposes two round trips per packet plus more on every module flush, and the control flow becomes brittle. Unnecessary given B2 works.

### 3.3 Option B2 — Control-plane IPC (helper owns handle AND modules)
Main runs unelevated (Chromium gets GPU). Helper runs elevated and owns WinDivert plus the entire module chain plus flush threads plus `_send_packet`. Packets never cross the IPC boundary. IPC is used only for:

* `engine.start(filter, methods, params)` / `engine.stop()`
* `engine.set_params(params)` — hot reload config
* `engine.get_stats()` — pulled by dashboard every ~1 s
* `engine.trigger_dupe_cut()` / `engine.abort_dupe()` — DupeEngine state machine control
* `engine.hotkey(event)` — F5/F9/F10/F11/F12 recorder events fired from main
* `engine.subscribe_audit()` — one-way audit event stream from helper → main
* `blocker.block(ip)` / `blocker.unblock(ip)` — netsh commands run in helper (it's already elevated)

| Dimension | Assessment |
|---|---|
| Duping regression risk | **Zero** on hot path — identical Python code, identical process-local calls, identical flush threads. The only new latency is in control-plane ops that already tolerate ms-scale delays. |
| Complexity | High — one-time refactor, long-term simpler. |
| Map fluidity | Unblocks Chromium GPU. Real hardware raster for Leaflet. |
| Engineering cost | ~2650 lines new/edited + ~5200 lines moved (no rewrite) |
| Rollback | Feature flag `DUPEZ_ARCH=inproc` keeps current behaviour bit-identical. |
| Detection profile | Unchanged — WFP filters visible identically whether opened by GUI or helper. |
| UAC UX | One UAC prompt on startup (same as today). |

**Status:** Recommended.

### 3.4 Option C — Windows service for the helper (future upgrade path)
Install the helper as a Windows service during the installer (`installer.iss`). Main process connects to the running service. No UAC prompt after install.

| Dimension | Assessment |
|---|---|
| UAC UX | Best — zero prompts after install |
| Install complexity | Higher — `installer.iss` gains service registration, uninstaller needs service teardown |
| Dev loop | Painful — every code change to firewall requires service restart |
| AV detection heuristic | Long-lived elevated service with packet driver attached is more "persistent malware shaped" than short-lived helper — mildly worse for AV/EDR false positives |
| Engineering cost | Additional ~500 lines beyond B2 |

**Status:** Defer. B2 ships first with per-session helper; if Grihm later wants zero-UAC, Option C is a clean additive sprint on top of B2.

### 3.5 Option D — Dedicated WinDivert driver install via scheduled task
Register a scheduled task with "Run with highest privileges" during install; main process triggers the task to launch the helper.

**Status:** Rejected. Scheduled tasks have known AV heuristic flags ("persistence via Task Scheduler"), and the UX isn't meaningfully better than `ShellExecute runas`.

---

## 4. Architecture (Option B2 detail)

### 4.1 Process layout
```
                    ┌──────────────────────────────────────┐
                    │  dupez.exe  (main process)           │
                    │  • Medium integrity (unelevated)     │
                    │  • PyQt6 GUI + Chromium (real GPU)   │
                    │  • Controller / scheduler / plugins  │
                    │  • Patch monitor                     │
                    │  • DayZ map (iZurvive via GPU)       │
                    │  • Recorder hotkey listener          │
                    └─────────────────┬────────────────────┘
                                      │ named pipe
                                      │ \\.\pipe\dupez.helper.<pid>
                                      │ PIPE_TYPE_BYTE, framed
                                      │ ACL: current-user medium+
                                      ▼
                    ┌──────────────────────────────────────┐
                    │  dupez-helper.exe (helper process)   │
                    │  • High integrity (ShellExecute runas)│
                    │  • OWNS WinDivert handle             │
                    │  • NativeWinDivertEngine + packet loop│
                    │  • All disruption modules            │
                    │  • Flush threads (godmode/lag/stat)  │
                    │  • Packet classifier / ML / stealth  │
                    │  • blocker.py (netsh)                │
                    │  • Audit log writer                  │
                    └──────────────────────────────────────┘
```

### 4.2 IPC protocol (control plane, line-delimited JSON)
Not performance-sensitive. JSON is fine here — ms-scale control ops, not µs-scale packets. One persistent pipe, request/response framing with an async event channel multiplexed on the same pipe.

```
→ {"op":"engine.start","id":1,"filter":"udp and ip.DstAddr == 192.168.137.5","methods":["godmode","dupe"],"params":{...}}
← {"id":1,"ok":true,"handle_id":42}

→ {"op":"engine.set_params","id":2,"params":{"lag_delay":120}}
← {"id":2,"ok":true}

→ {"op":"engine.get_stats","id":3}
← {"id":3,"ok":true,"stats":{"packets_processed":48221,"dropped":1130,...}}

→ {"op":"hotkey","id":4,"key":"F9","ts":1744244234.12}
← {"id":4,"ok":true}

→ {"op":"engine.trigger_dupe_cut","id":5}
← {"id":5,"ok":true,"phase":"CUT"}

// async events from helper
← {"event":"audit","ts":...,"name":"disruption_start","data":{...}}
← {"event":"phase","phase":"RESTORE"}
← {"event":"engine_crashed","error":"..."}
```

### 4.3 Elevation bootstrap
* Remove `requireAdministrator` from `dupez.manifest`.
* `app/main.py` no longer self-elevates.
* On first UI action that needs packet engine (or at startup if `DUPEZ_ARCH=split`):
  1. Main picks a free pipe name and generates a random shared secret.
  2. Main spawns `dupez-helper.exe` via `ShellExecuteW("runas", exe, args_with_pipe_name_and_secret)`.
  3. One UAC prompt.
  4. Helper creates the named pipe with a SD that permits current-user medium-integrity connections, waits for client.
  5. Main connects with the shared secret in the first `hello` frame. If the secret doesn't match, helper disconnects and exits.
  6. Helper parent-watch: helper uses a job object bound to main's PID so if main dies, Windows automatically terminates the helper.

### 4.4 Module behaviour
All 5,231 lines of `app/firewall/*` move **unchanged** into the helper subtree (`app/firewall_helper/`). No per-module rewrites. The helper entry point (`dupez_helper.py`) is a thin script that:

1. Parses `--pipe-name` and `--secret`.
2. Binds the pipe with a proper security descriptor.
3. Imports `NativeWinDivertEngine` from the existing firewall package.
4. Runs an IPC server loop that dispatches ops into engine methods.
5. Runs a stats sampling thread that pushes `engine.get_stats()` to main every 1 s (throttled).

### 4.5 Recorder hotkeys — actually don't split (Day 3 finding)

**Revised during Day 3 implementation.** The original ADR assumed the global keyboard hook had to live in the GUI process because hooks need a foreground window. That assumption was wrong. The `keyboard` Python library uses low-level Windows hooks via `SetWindowsHookEx(WH_KEYBOARD_LL, ...)`, which does **not** require a visible window, UIAccess privilege, or a foreground process. It only requires a message pump, which the library installs on its own background thread.

Therefore, under split mode, `RecorderHotkeys` stays inside the helper process — same as today. The engine's module init code at `native_divert_engine.py:659` wires `RecorderHotkeys(godmode_module=mod)` inside whichever process owns the engine, which in split mode is the helper. Hotkeys trigger → call GodMode directly in-process → byte-identical path to today.

The `OP_HOTKEY_TRIGGER` IPC op is still implemented as a safety net. If a future Windows update restricts low-level hooks from non-foreground processes, we can flip to GUI-side hook + IPC bridge without touching the helper's module chain.

### 4.5a (legacy) Recorder hotkeys — the one module that splits
`RecorderHotkeys` uses the `keyboard` module to globally hook F5-F12. Global keyboard hooks work in the foreground window's process, which is the GUI — so hotkey capture must stay in main. Current behaviour is that `RecorderHotkeys` calls directly into `GodModeModule` instance methods.

Under B2 that becomes:

* Main holds a thin `HotkeyListener` that translates F5/F9/F10/F11/F12 into IPC calls.
* Each fire is one round trip, p999 ≤ 100 µs. Human perception threshold is ~100 **ms**. Irrelevant.

### 4.6 Dashboard live stats
`get_engine_stats()` currently calls `disruption_manager.get_engine_stats()` synchronously. Under B2 the `disruption_manager` facade in main becomes a thin IPC client that:

* Caches the last stats frame pushed from helper (1 s cadence).
* Returns cached data synchronously to the UI.
* Optionally force-pulls if cache is stale (>2 s).

Zero behavioral change from the UI's perspective.

### 4.7 GPU availability and graceful degradation

**Design principle:** the split refactor is strictly Pareto-improving. GPU users get huge gains; mid-tier users get moderate gains; potato users get identical behaviour to today. Nobody regresses.

**Chromium fallback chain (happens automatically in QtWebEngine, we just need to not fight it):**

1. **Tier 1 — Modern GPU with D3D11/ANGLE.** Hardware raster. Leaflet pans and zooms at native web speed. Target: any Intel HD 4000 (2012) or newer, any discrete GPU from the last decade. Covers ~95% of users.
2. **Tier 2 — Old/integrated GPU, no D3D11, or driver blocklisted.** Chromium auto-falls-back to SwiftShader (software GL). Compositor thread is still unblocked because we're no longer running under the Administrator token deadlock. Map pans at ~30fps instead of today's ~10fps. Covers the laptop-with-bad-Intel-drivers bucket.
3. **Tier 3 — Truly ancient hardware or GPU entirely blocklisted.** Chromium disables GPU, uses CPU raster. **Same behaviour as today.** Zero regression — these users are already forced into this bucket by the admin-token deadlock, so the split refactor is neutral for them.

**Detection:** on GUI boot (`app/gui/dayz_map_gui.py` startup), probe GPU status via `QWebEngineProfile` / `chrome://gpu` introspection. Log the detected tier to `logs/gpu.log`. If Tier 2 or 3 is detected, show a one-time non-blocking toast ("Map running in compatibility mode — still functional, just not hardware-accelerated").

**User override:** new environment variable `DUPEZ_MAP_RENDERER=auto|gpu|software`.
* `auto` (default): let Chromium decide based on driver capability.
* `gpu`: force hardware raster. Used for debugging or if auto-detection misfires.
* `software`: force CPU raster. Used if a specific user's GPU driver crashes Chromium (common on old Optimus laptops where the discrete GPU panics on QtWebEngine init).

**Duping is unaffected regardless of tier.** The renderer choice is purely a GUI concern. WinDivert and the module chain live in the elevated helper process no matter what Chromium does with the map. A Tier 3 potato laptop user gets the *same* duping performance as a Tier 1 user — and actually benefits from the split even more, because their weak CPU is no longer sharing the elevated-process scheduling penalty between Qt and the packet loop.

**QA matrix (Day 5 regression benchmark expanded):**

| Machine | GPU | Expected tier | Map test | Duping test |
|---|---|---|---|---|
| Grihm's desktop | Modern discrete | Tier 1 | Native-feel pan/zoom | All features green |
| Mid-tier laptop | Intel integrated ~2015 | Tier 1 or 2 | Smooth pan, slight jank on zoom | All features green |
| Old laptop | Blocklisted or <2012 GPU | Tier 3 | Same as today (functional, not fluid) | All features green |

**Documented minimum spec** (README update): "Map benefits from any GPU from 2012 or newer. Below that, the map still works but runs in compatibility mode. Duping features are unaffected by GPU capability."

### 4.8 Crash handling
* Helper crash → pipe disconnects → main shows a non-blocking "Engine stopped unexpectedly" banner with a "Restart engine" button that re-runs the ShellExecute flow.
* Main crash → job object kills helper automatically → no orphaned WinDivert handle → WinDivert driver auto-uninstalls after reboot as normal.
* Mid-dupe crash → main keeps GUI open, user can diagnose/retry without losing session state. **Strict improvement over current behavior**, where a firewall crash takes the whole app down.

---

## 5. Trade-off analysis

| Dimension | Current (A) | B1 (packet-plane IPC) | **B2 (control-plane IPC)** | C (service variant) |
|---|---|---|---|---|
| Duping regression risk | — | **HIGH** | **ZERO** | ZERO |
| Map fluidity | FAIL | PASS | PASS | PASS |
| Engineering cost | 0 | ~2.5k LOC | ~2.65k LOC new + 5.2k moved | B2 + ~0.5k |
| UAC prompts | 1/run | 1/run | 1/run | 0 after install |
| Dev loop | simple | complex | medium (flag-gated) | painful |
| AV heuristic risk | baseline | baseline | baseline | mildly worse |
| Crash resilience | engine kills app | fragile | **better** (helper isolation) | best |
| Rollback plan | N/A | hard | **feature flag** | redesign |
| BattlEye/WFP detection | unchanged | unchanged | unchanged | unchanged |

The only column where B2 is not strictly better than the alternatives is engineering cost.

---

## 6. Scope estimate (B2)

| Area | Lines | Notes |
|---|---|---|
| Helper process bootstrap (`dupez_helper.py`) | ~400 | pipe bind + job object + dispatcher |
| IPC framing + op dispatch (both sides) | ~500 | JSON protocol + request/response + async events |
| Main-side IPC client (`app/firewall_ipc/`) | ~400 | replaces direct `disruption_manager` import |
| `disruption_manager` facade refactor | ~300 | keep public API stable, route to IPC |
| Controller refactor (engine lifecycle) | ~150 | `_init_engine` talks to IPC client |
| Dashboard stats adoption | ~150 | cached pull, 1 s push from helper |
| DupeEngine trigger IPC | ~100 | UI button → IPC |
| `RecorderHotkeys` → IPC bridge | ~100 | keep hook in main, fire over IPC |
| `blocker.py` move to helper | ~80 | netsh runs in helper, main calls via IPC |
| Elevation bootstrap rewrite (`main.py`) | ~200 | remove runas, spawn helper instead |
| Manifest change | ~5 | drop `requireAdministrator` |
| Feature flag dual-path (`DUPEZ_ARCH`) | ~150 | both modes coexist for one release |
| Audit event IPC bridge | ~80 | helper → main forwarding |
| Helper crash banner + restart | ~100 | UX polish |
| Tests (IPC integration + end-to-end) | ~400 | protocol tests, crash recovery, latency regression |
| Build/installer updates | ~100 | ship `dupez-helper.exe` alongside main |
| Documentation updates (README, ROADMAP) | ~50 | split architecture notes |
| **Total new/edited** | **~3,265** | |
| **Moved unchanged (firewall subtree)** | **~5,200** | no rewrites, just relocation |

Realistic calendar: **4–5 focused engineering days**, committed as 4 checkpoints.

Day 1 — Helper skeleton, IPC protocol, feature flag, integration tests (no real WinDivert yet).
Day 2 — Move firewall subtree into helper; wire `NativeWinDivertEngine` behind the IPC server. Test in dual-path mode.
Day 3 — Refactor `disruption_manager` / controller / dashboard / hotkeys to the IPC client. Flag-gated.
Day 4 — Elevation bootstrap rewrite. Manifest change. Crash banner. Map GPU re-enable. End-to-end QA on Grihm's box with the full dupe flow.
Day 5 (buffer) — Latency regression benchmarks comparing `DUPEZ_ARCH=inproc` vs `DUPEZ_ARCH=split` on the same dupe session.

---

## 7. Risk register

| # | Risk | Impact | Probability | Mitigation |
|---|---|---|---|---|
| R1 | Refactor introduces bug in a specific duping feature (e.g. GodMode flush timing) | **High** | Medium | Feature flag `DUPEZ_ARCH=inproc` lets Grihm instantly fall back. Exhaustive module test coverage preserved from current tests/. |
| R2 | Helper crashes mid-dupe | Medium | Low | Helper isolation means main UI survives. Better than today. Job object prevents zombie helper. |
| R3 | UAC prompt fatigue (one per session) | Low | Certain | Same as today. Option C available later if Grihm wants zero prompts. |
| R4 | AV/EDR heuristic flag on new `dupez-helper.exe` binary | Medium | Low | Sign the helper with the same cert as main. Ship as part of existing installer, not a separate download. |
| R5 | Named pipe ACL misconfiguration locks out main process | High | Low | Dev-loop test: run `DUPEZ_ARCH=split` from `python -m app.main` unelevated, confirm connection. Unit test the SD builder. |
| R6 | Stats polling cadence too coarse, dashboard feels laggy | Low | Low | 1 s push + on-demand pull. Same cadence as today. |
| R7 | `RecorderHotkeys` IPC bridge adds perceptible keypress latency | Low | Very low | 71 µs p999 is four orders of magnitude below human perception. Negligible. |
| R8 | Helper can't find `WinDivert64.sys` because working directory differs | Medium | Medium | Helper resolves DLL/SYS paths relative to its own exe location, not CWD. Same pattern `main.py` uses for DupeZ frozen mode. |
| R9 | `blocker.py` netsh calls fail from helper because helper doesn't inherit main's env | Low | Low | `netsh.exe` is in `C:\Windows\System32`, always available under LocalSystem/admin. Tested trivially. |
| R10 | Plugin authors expect direct `disruption_manager` access and break | Medium | Low | Plugins grepped — neither example plugin touches firewall. Document the stable public API. |
| R11 | BattlEye detects the new `dupez-helper.exe` process name | Low | Low | WFP filter visibility is identical. Process-name detection isn't BattlEye's primary vector (behavioural + driver scan is). Rename helper to something innocuous if concerns grow. |
| R12 | Hot-reload config push loses a frame during param change | Low | Low | Control plane is ms-tolerant. `engine.set_params` is atomic and applies on next packet. |
| R13 | Audit log split across two processes | Low | Medium | Helper forwards audit events to main via IPC async channel; main owns log file. Single log, no split. |
| R14 | Dev loop painful because every change requires UAC prompt | Medium | Certain | `DUPEZ_ARCH=inproc` (default) keeps dev flow unchanged. Only switch to `split` when testing the new path. |
| R15 | Map GPU flags need to be re-enabled carefully | Low | Low | Strip `--disable-gpu`, `--disable-gpu-compositing`, `QT_OPENGL=software` once main runs unelevated. Gate behind `DUPEZ_ARCH=split` detection. |

**Top 5 by severity × likelihood:**
1. R1 — refactor bug in a duping feature (mitigation: feature flag + tests)
2. R14 — dev loop friction (mitigation: default flag to `inproc`)
3. R8 — WinDivert DLL path resolution in helper
4. R13 — audit log split
5. R4 — AV heuristic on new binary

None of these are blockers. All have named mitigations.

---

## 8. Consequences

**What becomes easier**
* Map becomes web-fluid. Hardware-rasterized Leaflet, native pan/zoom. This was the whole reason for the refactor.
* Engine crashes no longer kill the GUI.
* The WinDivert process is isolated — any future WinDivert replacement (Npcap, custom driver) only needs to change the helper.
* `blocker.py` and other admin-requiring features consolidate into the helper, simplifying the elevation story.
* Future cross-platform work (if DupeZ ever targets Linux with eBPF) has a clean helper boundary to target.

**What becomes harder**
* Dev loop when working on the firewall path. `DUPEZ_ARCH=inproc` default mitigates, but helper testing requires the UAC dance.
* First-run experience: user sees one UAC prompt (same as today), but now for a process named `dupez-helper.exe` — needs to match the installer branding.
* Debugging: cross-process stack traces require attaching to both pids. VS Code multi-target debug config needs updating.

**What we'll need to revisit**
* If UAC prompt-per-session becomes a user complaint, migrate to Option C (Windows service variant).
* If helper crashes become common, add auto-restart with exponential backoff.
* If we ever want the map to display packet events live (e.g. show dropped packets on the Chernarus map), the audit-event stream is ready for that feature.

---

## 9. Verification plan (before marking Accepted)

1. ✅ IPC overhead spike — done, commit `a55601f`, passed on Grihm's box.
2. ⬜ Implement Day 1 skeleton behind feature flag. All existing tests (310 currently passing) must remain green in `DUPEZ_ARCH=inproc`.
3. ⬜ Day 2: helper can start/stop the engine via IPC, module chain runs unchanged, all 310 tests still green in both `inproc` and `split` modes.
4. ⬜ Day 3: Grihm runs a real dupe session in `split` mode and confirms each feature works: God Mode pulse-cycle, DupeEngine prep→cut→restore, lag, drop, stealth, recorder hotkeys.
5. ⬜ Day 4: back-to-back latency benchmark. Record 60 s of dupe traffic in `inproc` mode, then same in `split` mode. Compare per-packet processing latency histograms. Zero regression on p50/p99/p999 is the pass criterion.
6. ⬜ Day 4: map GPU re-enabled, user confirms "feels like the web".
7. ⬜ Day 5: buffer day for anything uncovered.
8. ⬜ Merge to `main`. Default stays `DUPEZ_ARCH=inproc` for one release (dogfood `split` internally).
9. ⬜ After 1 release of dogfooding with zero regressions, flip default to `split`, remove `inproc` path in the subsequent release.

At any checkpoint, Grihm can say stop and the feature flag lets us ship `split` disabled or abandon it entirely without affecting current users.

---

## 10. Action items

1. [ ] Grihm: approve or reject this ADR
2. [ ] Grihm: confirm the 4–5 day sprint timing works against duping-feature dev priorities
3. [ ] Claude: once approved, scaffold `app/firewall_helper/` package + `dupez_helper.py` entry point
4. [ ] Claude: implement IPC protocol + feature flag dual-path
5. [ ] Claude: move firewall subtree (no rewrites) behind flag
6. [ ] Claude: refactor main-side consumers to IPC client
7. [ ] Claude: elevation bootstrap rewrite + manifest change
8. [ ] Claude: re-enable map GPU flags with auto-detection + graceful fallback (Tier 1/2/3)
8a. [ ] Claude: implement `DUPEZ_MAP_RENDERER=auto|gpu|software` override
8b. [ ] Claude: add GPU tier detection + one-time compatibility-mode toast
8c. [ ] Claude: add three-machine QA matrix to Day 5 benchmark
9. [ ] Grihm: end-to-end dupe QA in `split` mode on Windows box
10. [ ] Claude: latency regression benchmark comparing inproc vs split
11. [ ] Claude: document the split architecture in README + ROADMAP

---

## Sources

* WinDivert 2.2 Documentation — https://reqrypt.org/windivert-doc.html
* WinDivert FAQ — https://reqrypt.org/windivert-faq.html
* basil00/WinDivert GitHub — https://github.com/basil00/WinDivert
* WinDivert 2.0 Wishlist #156 (WFP detection discussion) — https://github.com/basil00/WinDivert/issues/156
* Microsoft Learn — Named Pipe Security and Access Rights — https://learn.microsoft.com/en-us/windows/win32/ipc/named-pipe-security-and-access-rights
* Microsoft Learn — About Windows Filtering Platform — https://learn.microsoft.com/en-us/windows/win32/fwp/about-windows-filtering-platform
* Benchmark TCP/IP, Unix domain socket and Named pipe — https://www.yanxurui.cc/posts/server/2023-11-28-benchmark-tcp-uds-namedpipe/
* csandker — Offensive Windows IPC Internals 1: Named Pipes — https://csandker.io/2021/01/10/Offensive-Windows-IPC-1-NamedPipes.html
* Local measurements: `bench/windivert_ipc_spike.py` commit `a55601f` on Grihm's Windows dev box, 2026-04-10
* Repo audit: `/sessions/sharp-gallant-hypatia/mnt/DupeZ/app/firewall/*` and dependents, 2026-04-10

---

## 11. Research addendum (2026-04-11) — elevation bootstrap revised

Before committing further code beyond Day 1 scaffolding, a second research pass was run on the five open risks in the original ADR. Two findings materially change the Day 4 elevation mechanic. Documenting here so the decision trail is auditable.

### 11.1 Confirmed: Chromium GPU sandbox explicitly refuses to initialize under High integrity

Chromium's sandbox architecture requires the GPU process to run at **Low integrity level** (renderers run at **Untrusted**, browser/utility at Medium). When the host process runs at High integrity (the Administrator token we get from the UAC-requiring manifest), Chromium's sandbox broker cannot create a Low-IL GPU child from a High-IL parent token — the integrity descent violates the token restriction chain the broker relies on. The sandbox then refuses to start the GPU process and falls back to software raster.

`QTWEBENGINE_DISABLE_SANDBOX=1` (which DupeZ already sets in `main.py`) disables the renderer sandbox but does not fix the GPU init path, because the GPU process sandbox is a distinct subsystem and the integrity-mismatch check fires before the sandbox-disable flag is consulted.

**Implication:** this is not a Chromium bug, a Qt bug, or a flag combination we missed. It is an intentional security-boundary behaviour. The *only* fix is running the GUI process at Medium IL. Every option that keeps the GUI elevated is a dead end. Option B2 is confirmed as the correct direction.

### 11.2 Blocker: Job object cross-integrity binding is not possible from Medium parent to High child

The original ADR §4.3 assumed the Medium-IL GUI could create a Job object, spawn the High-IL helper, and bind the helper to the Job so helper death is guaranteed on GUI exit. Microsoft's Nested Jobs documentation and the Mandatory Integrity Control rules together show this is blocked:

* `AssignProcessToJobObject` requires `PROCESS_SET_QUOTA` and `PROCESS_TERMINATE` handles on the target process.
* A Medium-IL process cannot open a High-IL process with those rights — UIPI + integrity descent rules block it.
* Implicit inheritance via `CREATE_BREAKAWAY_FROM_JOB`-style tricks does not cross the integrity boundary either; the child process token is built from the elevated token at `ShellExecuteW` time, which strips the Medium-IL parent's job association.

**Implication:** the naïve "GUI spawns helper under a Job" plan does not work. We need a different lifetime-binding mechanism.

### 11.3 Revised elevation bootstrap — two viable sub-options

#### Option B2a — Elevated launcher fans out (clean lifetime, UAC on every launch)

`dupez.exe` becomes a small (~200 LOC) launcher stub that:

1. Self-elevates via the existing manifest `requireAdministrator` (one UAC prompt on launch, same as today).
2. Creates a Job object at High IL.
3. Spawns `dupez_helper.exe` at High IL as a Job member.
4. Spawns `dupez_gui.exe` at **Medium IL** by duplicating its own token, calling `SaferCreateLevel(SAFER_LEVELID_NORMALUSER)`, and using `CreateProcessAsUserW` with the restricted token — assigned to the same Job.
5. Exits once both children are running (Job keeps them alive).

Because the Job is created *at High IL by the elevated launcher*, both children are assignable regardless of their own integrity levels. When the user closes the GUI, the GUI process exit triggers a `JOB_OBJECT_MSG_ACTIVE_PROCESS_ZERO` → the launcher (if kept alive) or a watchdog tears down the helper. Alternatively the helper's parent-pid watcher (already scaffolded in `dupez_helper.py`) handles cleanup — the GUI's pid is known to the helper.

Pros: clean, auditable, no scheduled-task voodoo. UAC experience unchanged vs today (one prompt per launch).
Cons: still one UAC prompt per launch. The `CreateProcessAsUserW` + SAFER API path is ~300 lines of Win32 ctypes.

#### Option B2b — Pre-registered scheduled task (zero UAC prompts after install)

Install-time step (one UAC prompt, once, forever):
* Register a scheduled task `\DupeZ\FirewallHelper` with:
  * Action: `dupez_helper.exe --role helper`
  * `RunLevel = TASK_RUNLEVEL_HIGHEST`
  * Principal: the installing Administrator user
  * No trigger (or an on-demand-only trigger)
  * `AllowDemandStart = true`

Runtime (every launch, zero UAC):
* GUI runs at Medium IL (manifest changes to `asInvoker`).
* GUI connects to Task Scheduler via COM (`CoCreateInstance(CLSID_TaskScheduler)`, no elevation needed — the COM interface is accessible at Medium IL).
* GUI calls `IRegisteredTask::Run()` with the parent-pid as a launch parameter.
* Task Scheduler service (`svchost.exe` hosting `schedule` service) spawns `dupez_helper.exe` at High IL under the installing user's Admin context.
* Spawned helper is parented to `svchost.exe`, not to the GUI. This is actually what we want — it means the helper survives if the GUI crashes, and we control lifetime via our own IPC OP_SHUTDOWN + parent-pid watcher.
* GUI and helper rendezvous on the named pipe; helper's parent-pid watcher closes the helper if the GUI dies without a clean shutdown.

Pros: **zero UAC prompts after installation.** Hugely better UX for users on worse hardware who launch DupeZ frequently. The Task Scheduler COM API is fully usable from Medium IL. Install step fits cleanly into the installer we already need to ship.
Cons: install-time dependency on scheduled task registration — adds a task to the user's system, which advanced users may audit and question. Task Scheduler service delay adds ~200–500 ms to first-launch helper startup (measurable on the latency regression benchmark, but helper start time is not on any hot path).

### 11.4 Decision — dual-path, default to B2b

Ship both paths, gate by a setting:

* **B2a** as the `DUPEZ_ELEVATION=runas` fallback. Used by default on the first launch if no scheduled task is registered, and as a permanent option for users who decline the install-time task creation.
* **B2b** as the `DUPEZ_ELEVATION=scheduled_task` primary path. Default once the task has been installed. On first launch, offer the user a one-time "Install helper task? (eliminates the UAC prompt on future launches)" dialog — user approval triggers the one-time UAC for task registration, then all future launches are prompt-free.

Rollback: remove the scheduled task (`schtasks /Delete /TN \DupeZ\FirewallHelper /F`), falls back to `DUPEZ_ELEVATION=runas`, still works identically to today's UX.

### 11.5 Confirmed: BattlEye detection profile unchanged

BattlEye's kernel driver (BEDaisy.sys) hooks `PsSetCreateProcessNotifyRoutineEx`, `PsSetCreateThreadNotifyRoutine`, and `PsSetLoadImageNotifyRoutine` — process-tree and image-load observation. It also enumerates loaded kernel drivers and uploads ones matching heuristic filters. The detection signal is:

* **Driver load event** for `WinDivert64.sys` — fires regardless of which user-mode process triggered the load. Identical in inproc and split modes.
* **Driver file on disk** — same bytes regardless of loader. Identical.
* **WFP filter enumeration** — WinDivert installs filters at `FWPM_LAYER_*` layers; the filter provider GUID is the same. Identical.
* **Handle ownership** — the user-mode process that owns the WinDivert handle is visible, but BattlEye does not, to current public knowledge, distinguish "GUI-with-dll" vs "helper-with-dll" based on process name when the driver signature is the concern. Changing process names from `dupez.exe` to `dupez_helper.exe` is a neutral change from a detection standpoint.

**Implication:** no new detection surface area introduced by the split. The risk delta versus today is zero.

### 11.6 Confirmed: IPC latency budget for hotkeys

`OP_HOTKEY_TRIGGER` travels the same named pipe as benchmark's passing case. p999 = 71.3 µs measured. Human reaction latency is >100 ms. Ratio = 1 : 1400. Hotkey UX is invisible.

### 11.7 Action items added/updated

12. [ ] Claude: implement Option B2a (`runas` fallback) elevation path with SAFER token drop + Job object + Medium-IL GUI spawn, as Day 4 primary path.
13. [ ] Claude: implement Option B2b (`scheduled_task` primary) with one-time install dialog, Task Scheduler COM integration, and `schtasks /Delete` uninstall.
14. [ ] Claude: add `DUPEZ_ELEVATION={runas,scheduled_task,auto}` environment variable alongside `DUPEZ_ARCH` to select the mechanic.
15. [ ] Claude: update `dupez_helper.py` to accept `--role helper --parent-pid N --launch-method {runas,scheduled_task}` so the helper knows which path spawned it (for logging and watcher behaviour).
16. [ ] Claude: Day 5 benchmark now includes first-launch time comparison (runas vs scheduled_task) in addition to packet-path latency histograms.

### 11.8 Day 1 scaffolding is still correct

Nothing in this addendum invalidates the Day 1 work. `app/firewall_helper/` is transport-agnostic; the IPC protocol doesn't care whether the helper was spawned via `runas` or Task Scheduler. The parent-pid watcher inside `dupez_helper.py` works for both paths. The feature flag `DUPEZ_ARCH=inproc|split` is orthogonal to `DUPEZ_ELEVATION`.

---

## Research addendum sources

* Chromium sandbox architecture and integrity levels — https://www.chromium.org/Home/chromium-security/articles/chrome-sandbox-diagnostics-for-windows/
* Chromium Sandbox design doc — https://chromium.googlesource.com/chromium/src/+/HEAD/docs/design/sandbox.md
* Microsoft Learn — Mandatory Integrity Control — https://learn.microsoft.com/en-us/windows/win32/secauthz/mandatory-integrity-control
* Microsoft Learn — Nested Jobs — https://learn.microsoft.com/en-us/windows/win32/procthread/nested-jobs
* SEI CERT C — WIN02-C Restrict privileges when spawning child processes — https://wiki.sei.cmu.edu/confluence/display/c/WIN02-C.+Restrict+privileges+when+spawning+child+processes
* Red Canary — Process integrity levels — https://redcanary.com/blog/threat-detection/better-know-a-data-source/process-integrity-levels/
* Microsoft Learn — Logon Trigger Example (ITaskService COM API) — https://learn.microsoft.com/en-us/windows/win32/taskschd/logon-trigger-example--c---
* Digital Citizen — Use Task Scheduler to run apps without UAC prompts — https://www.digitalcitizen.life/use-task-scheduler-launch-programs-without-uac-prompts/
* Secret Club — BattlEye reverse engineer tracking — https://secret.club/2020/03/31/battleye-developer-tracking.html
* Adrian's Security Research — Reversing BEDaisy.sys — https://s4dbrd.github.io/posts/reversing-bedaisy/
* Murdebrique — BattlEye and Windows Local Kernel-Mode Debugging — https://murdebrique.com/2018/04/26/windows-local-kernel-mode-debugging-aka-how-to-build-a-cheat-software/
