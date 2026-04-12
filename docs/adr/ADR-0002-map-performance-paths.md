# ADR-0002 — Map Performance Paths (Research)

Status: Research / decision pending
Date: 2026-04-11
Scope: Make the embedded iZurvive map smooth without regressing
duping, lagswitch, hotkeys, or packet-path latency.

## Hard constraint

The packet path is untouchable. Anything that risks WinDivert handle
ownership, disruption_manager thread timing, blocker netsh sequencing,
or GodMode hotkey latency is out of scope. The map can only change
what happens between Chromium and the screen.

## TL;DR

You already built the fix. It's called **DUPEZ_ARCH=split** and it's
latency-validated (get_status p999=568µs, hotkey_trigger p999=203µs
over the real Windows named pipe — 500x under the 100ms human floor).

The only reason the map is still laggy is that
`app/firewall_helper/feature_flag.py` still has `_DEFAULT_ARCH =
ARCH_INPROC`. The GUI boots elevated, Chromium's GPU process refuses
to start under an admin token, and `renderer_tier.py` correctly picks
`tier3_cpu` (software raster). That's the lag.

Flip the default to split and the map runs at `tier1_hw` or
`tier2_swiftshader`. Packet path is literally the same singleton —
just hosted in `dupez_helper.py` instead of `dupez.exe`. Bit-for-bit
identical WinDivert, bit-for-bit identical netsh, bit-for-bit
identical hotkeys. You already validated this on your own machine.

## Why the map is slow today

Stack of compounding CPU-raster penalties, all downstream of
"elevated parent token → Chromium GPU process refuses to start":

1. Chromium falls back to Skia software raster. Every Leaflet tile
   composite is a full-bitmap CPU blit.
2. Leaflet decorates map tiles with `will-change: transform` and
   `translate3d(...)` to force GPU layer promotion. Under software
   raster those become per-frame CPU work instead of free.
3. iZurvive runs at `devicePixelRatio >= 1.5` on most Windows
   installs. Quadruples fragment work on a pipeline that is already
   100% CPU.
4. Marker drag path hits the compositor twice per move event.
5. The tile network path occasionally stalls on SSL handshake
   failures to ad/analytics domains (`eyeota`, `googletag`,
   `appsignal`) — this is visible in your Qt WebEngine logs.

Items 1-4 all vanish the moment the GUI is at Medium IL. Item 5 is a
secondary improvement (local mirror / cache preload) worth doing
regardless.

## Options, ranked

### Option A — Ship split mode as the default (RECOMMENDED)

Effort: ~30 minutes
Risk to duping: zero (proved via latency_regression.py on real pipe)
Map impact: massive. Tier1 hardware raster on M1/M2-class machines,
  tier2 SwiftShader GL on mid-tier, tier3 CPU raster only on
  blocklisted-GPU machines — which is identical to today.

Changes required:
- `app/firewall_helper/feature_flag.py`: `_DEFAULT_ARCH = ARCH_SPLIT`
- `dupez.py` shim: already correct — skips self-elevation when
  DUPEZ_ARCH=split.
- `dupez.manifest`: already flipped to `asInvoker`.
- `app/firewall_helper/ipc_client.py`: already auto-spawns the helper
  via `ensure_helper_running()` on first call.
- `app/firewall_helper/elevation.py`: already handles B2a runas + B2b
  scheduled task.
- `renderer_tier.py`: already picks the right Chromium flag set.

What the user sees on a fresh launch:
1. Double-click dupez.exe. No UAC prompt (Medium IL asInvoker).
2. Splash screen boots instantly. No admin token = no GPU stall.
3. First control-plane call from the controller triggers helper
   auto-spawn. One UAC prompt for the helper (or zero if B2b
   scheduled task is registered).
4. Map renders with real GPU rasterization. Duping works
   unchanged.

Fallback path: if a user's machine has a blocklisted GPU,
`renderer_tier.resolve_tier()` returns `tier3_cpu` and the map is
identical to today's shipping build. Nothing regresses for anyone.

Escape hatch for paranoid users: `DUPEZ_ARCH=inproc` reverts to
today's single-process elevated behavior — nothing is removed, just
defaulted off.

### Option B — Fix the child-experimental HWND embed

Effort: ~1-2 days, Win32 spelunking
Risk to duping: zero (packet path never touched)
Map impact: medium — adds a second path to GPU rendering under
  inproc mode, useful as a backup for users who can't run split
  mode for any reason.

`app/gui/map_host/launcher.py` + `host.py` already implement the
Explorer COM spawn trick: `Shell.Application.ShellExecute()` routes
the child spawn through Explorer's Medium-IL token, bypassing the
parent's admin token inheritance. The child gets real GPU raster.
The current blocker is HWND reparenting across the IL boundary —
`SetParent` fails with `ERROR_INVALID_WINDOW_HANDLE` because UIPI
blocks cross-IL window manipulation from Medium → High.

Fix direction: the parent is the High-IL side. `SetParent` called
from the parent should work (High can manipulate Medium HWNDs).
Likely fix is ordering — parent must call `ChangeWindowMessageFilterEx`
with `MSGFLT_ALLOW` for `WM_COPYDATA`-style messages and make sure
the child HWND is fully realized (`WA_NativeWindow + create()` —
already done in host.py) before `SetParent` is invoked. The symptom
of "floating top-level flashes before reparent" is classic —
`SetWindowLongPtr` to strip `WS_POPUP` must happen before
`SetParent`, and `SetWindowPos SWP_FRAMECHANGED` must run after.

Why this is Option B not Option A: split mode makes this moot. B is
only worth chasing if you ever need a no-helper single-process mode
with GPU rendering, which you probably don't.

### Option C — Local iZurvive tile mirror + aggressive cache preload

Effort: ~1 day
Risk to duping: zero
Map impact: moderate. Removes network stalls and SSL handshake
  failures on pan/zoom. Mostly helps cold loads and first-tile
  render. Doesn't solve software-raster compositing cost.

Mechanism:
- Pre-download tile pyramids for Chernarus+, Livonia, Namalsk at
  zoom levels 2-6 to `%LOCALAPPDATA%/DupeZ/tile_cache/`.
- Serve them via an embedded `aiohttp`/`QHttpServer` on localhost.
- Inject a JS shim that rewrites `izurvive.com/...tile.png` URLs to
  `http://127.0.0.1:{port}/...tile.png`.
- Fall back to remote tiles on cache miss.

This is a real win under tier3_cpu (network hiccups disappear), and
a minor win under tier1_hw (same benefit but less visible because
GPU compositing is already fast). Worth doing after Option A ships
regardless of anything else.

### Option D — Replace QtWebEngine with WebView2 for the map

Effort: ~1 week
Risk to duping: zero
Map impact: similar to split + tier1_hw, but with a whole new
  dependency and none of your existing Chromium flag / ad blocker
  / inject_perf_tweaks code transfers.

Dismissed. Doesn't beat Option A and costs 20x more.

### Option E — Pre-rasterize iZurvive pages to static HTML

Effort: ~2-3 days
Risk to duping: zero
Map impact: high for static viewing, breaks marker drag and live
  overlays.

Dismissed. Breaks duping-adjacent workflows (marker placement for
PS5 target coordinates).

## Addendum — Dual-variant ship

Per Grihm's 2026-04-11 decision: ship BOTH variants so users pick.

| Variant | Manifest | Arch default | Helper | Map |
|---|---|---|---|---|
| `DupeZ-GPU.exe` | `asInvoker` | `split` | auto-spawn elevated | hardware raster |
| `DupeZ-Compat.exe` | `requireAdministrator` | `inproc` | none (in-process) | software raster |

Build infra changes (all landed):

- `app/firewall_helper/feature_flag.py` — resolves default from
  optional bundled `_build_default.py` (arch set at build time),
  env var override still wins.
- `app/firewall_helper/_build_default.py` — autogenerated per
  build, gitignored, written by `build_common._write_build_default`
  before `Analysis` runs.
- `dupez_compat.manifest` — new, requireAdministrator variant.
- `dupez.manifest` — unchanged, stays asInvoker (the GPU variant).
- `build_common.py` — shared Analysis/PYZ/EXE factory + variant
  writer. Both specs call `build_variant("gpu", ...)` or
  `build_variant("compat", ...)`.
- `dupez_gpu.spec` — thin wrapper, `uac_admin=False`.
- `dupez_compat.spec` — thin wrapper, `uac_admin=True`.
- `build_variants.bat` — orchestrator, builds both, strips MOTW.

Release-page copy:

> **DupeZ-GPU.exe** (recommended) — smooth hardware-accelerated map.
> Prompts UAC once for the firewall helper on first launch.
>
> **DupeZ-Compat.exe** — legacy single-process build. Software
> raster map (laggier). Use this if the GPU build won't launch on
> your machine or your antivirus flags the helper spawn.

## Recommendation

Do **A now**. Do **C next** regardless.

A is a one-line default change plus a rebuild. Everything it needs
is already merged and latency-validated. You could ship it this
afternoon.

C is a week of work on tile caching + local HTTP serving that
compounds with A — under A the map is fast, under A+C the map is
fast AND cold-load-insensitive AND ad-network-SSL-hiccup proof.

Skip B and D entirely.

## Validation plan for Option A

Before flipping the default, run the QA matrix from
`ADR-0001-QA-matrix.md` config 2 (split + runas + auto) on your dev
box:

1. Fresh launch → confirm one UAC prompt for helper, zero for GUI.
2. Load Chernarus+ Satellite → confirm smooth 60fps pan/zoom.
3. Run the scripted duping sequence (5-min warmup + 10 runs) →
   confirm success rate matches baseline.
4. Toggle F5/F9/F10/F11/F12 during live play → confirm every
   hotkey registers via GodMode recorder.
5. `python bench/latency_regression.py --path real-pipe
   --iters 10000` → confirm p999 numbers match your earlier
   validated run.
6. Kill helper mid-session → confirm GUI stays up and reconnects.
7. Kill GUI → confirm helper dies within 2s.

If all 7 pass, flip the default and ship.

## What you do NOT have to do

- Touch `app/firewall/*`
- Touch `app/core/controller.py`
- Touch GodMode hotkey timing
- Touch WinDivert handle lifecycle
- Touch netsh rule sequencing
- Touch the disruption_manager singleton semantics

All packet code is inherited verbatim by the helper process through
the same module imports. That's the whole point of split mode.
