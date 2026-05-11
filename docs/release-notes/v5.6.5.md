# DupeZ v5.6.5 — Self-Disrupt-By-Default: WiFi Lag That Actually Works

DupeZ exists to disrupt the operator's OWN connection (typically to a DayZ server) — not to attack other devices. v5.5.0 added a WiFi same-network ARP-spoof path under the wrong assumption that operators wanted to redirect a peer device's traffic. That premise was wrong for the actual use case AND fundamentally unreliable on modern consumer WiFi (AP client isolation drops the spoof on Eero, Google Nest, most ISP gateways, all public/guest networks). v5.6.5 collapses the WiFi same-network path to NETWORK-layer self-disrupt by default: the operator's own packets to/from the target get the disruption treatment. Works on every AP, every encryption mode, wired or wireless, immediately, no Npcap dependency.

## What this means for you

- **Hit DISRUPT on WiFi** → your own connection to the target lags / drops / does whatever the preset says. No more silent no-ops. No more "install Npcap" toast. No more 50/50 lottery on whether the AP forwards your ARP spoof.
- **Wired Ethernet** → unchanged. Same NETWORK-layer path as before.
- **Hotspot mode (PS5/Xbox via Windows ICS)** → unchanged. Still routes through NETWORK_FORWARD.
- **PC-LOCAL mode (DupeZ + DayZ on same box)** → unchanged. Already worked.

## Changed (the headline)

- **`wifi_same_net` targets default to NETWORK layer / self-disrupt (`app/firewall/target_profile.py`).** Old behavior: ARP-spoof + NETWORK_FORWARD layer (often a silent no-op on consumer WiFi). New behavior: NETWORK layer, filter on target_ip, disrupt operator's own traffic. No ARP spoof, no Npcap requirement, works on every AP.
- **`is_local` mapped from `_detection.layer` (`app/firewall/clumsy_network_disruptor.py`).** Pre-v5.6.5 the detection layer setting silently fell back to NETWORK_FORWARD because the controller didn't propagate it. Now wired correctly. Caller-override via `params["_network_local"]` still works.

## Added (defensive infrastructure for the rare opt-in case)

- **`app/network/wifi_probe.py`** — `IsolationWatchdog` class that samples spoofer/engine packet counters. Only arms when the operator explicitly opts into ARP spoof via `params["_force_arp_spoof"] = True`. Self-tested in 4 scenarios (WORKING / ISOLATION_DETECTED / INCONCLUSIVE / ABORTED).
- **Self-disrupt auto-fallback for the ARP opt-in path (`clumsy_network_disruptor.py`)** — `_arm_wifi_isolation_watchdog()` + `_fallback_to_self_disrupt()`. If a power user enables ARP and the AP drops the spoof, watchdog auto-falls-back to NETWORK layer.
- **One-command build pipeline (`packaging/build_variants.bat`)** — folds Inno Setup compilation + versionless `DupeZ_Setup.exe` alias emission into the variant build. Locates ISCC via PATH / `$env:DUPEZ_ISCC` / standard install paths. Falls back gracefully if Inno Setup is missing.

## Fixed

- **Inno Setup `Architecture identifier x64 is deprecated` warning (`packaging/installer.iss`).** Swapped `x64` → `x64compatible`. Same install behavior on native x64, additionally supports ARM64 Windows x64-emulation hosts.

## Downloads

- **`DupeZ_v5.6.5_Setup.exe`** — Inno Setup installer (recommended).
- **`DupeZ_Setup.exe`** — stable versionless alias.
- **`DupeZ-GPU.exe`** — portable, asInvoker manifest, split-mode architecture.
- **`DupeZ-Compat.exe`** — portable, requireAdministrator manifest, in-process engine.

## Test plan

- Build everything in one command: `packaging\build_variants.bat`. Verify four artifacts in `dist\`, all stamped 5.6.5.0.
- WiFi same-net target (any AP, any encryption — does NOT matter): fire Red Disconnect. Expected: log shows `target {ip} on same WiFi /24 → SELF-DISRUPT mode`, engine opens NETWORK layer, your ping to target drops/lags. No Npcap warning. No ARP toast.
- Wired Ethernet: behavior unchanged.
- Hotspot mode (PS5/Xbox on ICS): behavior unchanged.
- PC-LOCAL: behavior unchanged.
- Power-user opt-in: pass `_force_arp_spoof=True` → legacy ARP path executes, watchdog arms.
