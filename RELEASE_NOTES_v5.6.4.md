# DupeZ v5.6.4 — WiFi Honesty Pass: No More Silent No-Ops

Driven by a user report that disruption "works on Ethernet but not WiFi." Audit confirmed: when the target is on the same WiFi /24 (the `wifi_same_net` path added in v5.5.0), four failure branches in `clumsy_network_disruptor.disconnect_device_clumsy` silently degraded to "WinDivert NETWORK_FORWARD open, but no ARP spoof running" — which captures zero packets. The UI badged DISRUPTED while doing nothing. Combined with the 2026 reality that most consumer APs (Eero, Google Nest, ISP gateways, all public/guest WiFi) ship with client isolation default-on and refuse to forward station-to-station L2 frames, this looked like a randomly-broken feature when it was actually a deterministic silent failure plus an L2 attack the AP was correctly dropping.

## Fixed

- **Silent no-op when Npcap missing on WiFi same-net target (`app/firewall/clumsy_network_disruptor.py`).** Previously logged an error toast and *fell through* to open WinDivert on NETWORK_FORWARD with no spoofer running — zero packets captured, UI showed success. Now returns False so the GUI's "Partial Failure" dialog fires with install guidance.
- **Silent no-op when `ArpSpoofer.start()` fails on WiFi same-net target (same file).** Log line claimed "falling back to NETWORK layer (weak)" but the code did not actually flip `is_local` / `_network_local` back to True — it stayed on NETWORK_FORWARD with `_arp_spoofer=None`. NETWORK layer cannot affect a remote target anyway, so falling back was always a lie. Now returns False.
- **Silent no-op on `ImportError` for `arp_spoof` module (same file).** Was a toast-and-continue; now returns False.
- **Silent no-op on unexpected exception in ARP spoof startup (same file).** Was a toast-and-continue; now returns False.

## Added

- **Honest WiFi limitations section in the Help panel (`app/gui/panels/help_panel.py`).** Documents the three real reasons WiFi peer-targeting fails on modern consumer routers (AP client isolation, wireless L2 model, the v5.6.4 honesty fix itself) and clarifies that WinDivert-only PC-LOCAL modes work identically wired and WiFi.

## Audit findings (informational — no code change shipped)

- Eero (main + guest), Google Nest Wifi, and most ISP gateways have AP client isolation default-on with no user toggle. ARP spoof against a peer on these networks will reach the AP and stop there. There is no honest fix from the client side.
- WinDivert binds at the WFP layer above the NIC and is adapter-agnostic — works identically on wired and 802.11. The failure mode is the *targeting* layer (ARP), not WinDivert itself.
- Npcap monitor mode + injection for deauth-class attacks remains gated to a tiny set of chipsets in 2026; not shippable in a consumer tool.
- WPA3 + 802.11w MFP enforcement is still <10% of consumer auths globally as of Feb 2026, but doesn't matter — consumer APs already drop client-to-client L2 traffic by other means.
- **Planned for v5.6.5:** WiFi-aware pre-flight probe (`is_local_adapter_wifi()` via `GetIfTable2`, `probe_ap_isolation()` via warmup ARP + ICMP roundtrip), self-disrupt fallback mode when AP isolation is detected.

## Downloads

- **`DupeZ_v5.6.4_Setup.exe`** — Inno Setup installer (recommended).
- **`DupeZ_Setup.exe`** — stable versionless alias (same bytes as the versioned installer; targets `releases/latest/download/DupeZ_Setup.exe`).
- **`DupeZ-GPU.exe`** — portable, asInvoker manifest, split-mode architecture, GPU map. Default for most users.
- **`DupeZ-Compat.exe`** — portable, requireAdministrator manifest, in-process engine. For environments where Chromium's GPU process won't initialize (blocklisted GPUs, restricted desktops).

## Test plan

- Build both variants: `packaging\build_variants.bat`. Verify `dist\DupeZ-GPU.exe` and `dist\DupeZ-Compat.exe` show version 5.6.4.0.
- WiFi same-net target with Npcap **uninstalled**: fire Red Disconnect. Expected: "Partial Failure" dialog appears, log shows `[WiFi] Cannot ARP-spoof: ... Aborting disruption`. Previously: badge turned red, no packets intercepted.
- WiFi same-net target on a router with AP client isolation ON, Npcap **installed**: fire Red Disconnect. Expected: ArpSpoofer starts, but if the spoof can't land, target is unaffected. (Detection of isolation arrives in v5.6.5; v5.6.4 stops lying about the *cause* of silent failure but cannot yet detect AP isolation itself.)
- Wired Ethernet, same target as previous test: behaviour unchanged. Disruption lands.
- PC-LOCAL mode (target = own machine's connection to remote game server) over WiFi: behaviour unchanged. WinDivert intercepts local egress identically to wired.
