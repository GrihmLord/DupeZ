# NetCut Architecture Analysis & DupeZ L2 MITM Proposal

**Branch:** `feature/netcut-research`
**Author:** Grihm
**Date:** 2026-04-10
**Status:** Research / Design Proposal — not yet implemented

---

## TL;DR

1. **You do not need to write a custom kernel driver.** NetCut doesn't have one. It rides on **Npcap** (the same NDIS 6 Lightweight Filter driver used by Wireshark, nmap, Bettercap, and Scapy). Writing a WDK kernel driver is a 6–12 month project with WHQL signing overhead and a massive BSOD surface — and it would only duplicate what Npcap already ships.
2. **NetCut's entire trick is ARP cache poisoning over Layer 2**, executed from userspace on top of Npcap. It's ~300 lines of logic wrapped in a polished GUI.
3. **DupeZ today is host-local only.** WinDivert hooks WFP at L3/L4 on *this* machine. It cannot touch another LAN device's traffic. That is the gap.
4. **The correct architecture is dual-stack**: keep WinDivert for host-local stack surgery (drop, lag, throttle, duplicate, corrupt, RST) *and* add an Npcap-backed L2 engine for LAN-wide ARP MITM. They are complementary, not competing.
5. **Strategic payoff for duping:** an L2 MITM mode lets DupeZ cut or freeze *other* players' traffic mid-trade on shared LANs (duo sessions, LAN parties, split-household duos), which opens new duplication trigger windows that host-local filtering cannot reach.
6. **Recommended milestone:** v6.0. This is a major architectural expansion, not a patch. v5.x stays WinDivert-only.

---

## 1. NetCut Architecture Primer

### 1.1 What NetCut actually does

NetCut is a Windows LAN control tool from arcai.com. Despite the marketing ("cut any device off your network in one click"), the core mechanism is classical **ARP cache poisoning**:

1. Scan the local subnet via ARP requests to build a device table (MAC ↔ IP ↔ vendor OUI).
2. To "cut" a target device, forge gratuitous ARP replies telling the target that *the gateway's IP* maps to NetCut's MAC — and telling the gateway that *the target's IP* maps to NetCut's MAC.
3. All traffic between the target and the gateway now routes through the NetCut host.
4. NetCut drops those frames instead of forwarding them. The target appears to lose internet.
5. "Restore" simply stops sending poisoned ARPs and optionally sends corrective ARPs. Caches re-learn within seconds to a few minutes.

That's it. That's the whole product. Every additional NetCut feature is a UX wrapper around this primitive.

### 1.2 What NetCut Pro adds (the feature set worth studying)

| Feature | Mechanism | DupeZ equivalent today |
|---|---|---|
| Per-device bandwidth limit | Forwards frames after a token-bucket delay instead of dropping | Partial — `throttle` in `native_divert_engine.py` (host-local only) |
| Protect mode | Detects inbound ARP poisoning by watching for gateway MAC changes, alerts/auto-corrects | None |
| Scheduled on/off | Cron-style timers toggling cut state | None |
| WIFI lock | Continuously kicks unknown MACs until they leave the AP | None |
| Device history | Persists seen MAC/hostname pairs across sessions | Partial — `enhanced_scanner.py` scans but doesn't persist history |
| Vendor identification | OUI lookup from IEEE prefix DB | Likely present in `enhanced_scanner.py` |

### 1.3 Driver stack

NetCut depends on **WinPcap** (legacy) or **Npcap** (modern). Both are NDIS 6 Lightweight Filter drivers — they sit between the Windows TCP/IP stack and the physical NIC and expose a userspace libpcap API (`pcap_open_live`, `pcap_sendpacket`, `pcap_next_ex`). NetCut ships the Npcap installer as a prerequisite; it does not ship its own `.sys` file.

This is the critical insight: **the driver is commodity infrastructure.** NetCut is not special because of its driver. It is special because of its targeting + UX layer on top of Npcap.

---

## 2. DupeZ Current State (Baseline)

### 2.1 What DupeZ does today

DupeZ operates at L3/L4 on the local Windows host using **WinDivert** (`WinDivert64.sys`), which hooks the Windows Filtering Platform. The engine (`app/firewall/native_divert_engine.py`, ~1063 LOC) exposes nine primitives:

- `drop` — kill packets matching a filter
- `lag` — introduce jitter/latency
- `throttle` — bandwidth cap
- `duplicate` — reinject copies
- `ood` — out-of-order delivery
- `corrupt` — flip bits in payload
- `bandwidth` — token bucket
- `disconnect` — hard cut all matching flows
- `rst` — forge TCP RST to tear down sessions

All of these act on **packets that enter or leave this machine's TCP/IP stack**. WinDivert runs at `WINDIVERT_LAYER_NETWORK` (0) and `WINDIVERT_LAYER_NETWORK_FORWARD` (1). The forward layer only sees traffic when the host is routing, i.e. acting as a gateway — which it isn't, by default.

### 2.2 The gap

DupeZ cannot affect another machine on the LAN. If Grihm and his duo partner are both playing DayZ from the same house, DupeZ can cut Grihm's own connection (triggering rollback-style dupes on his client/server sync) but cannot cut the partner's connection independently. That's a fundamental limitation of the WinDivert-only stack.

NetCut closes that gap by moving to L2: once you ARP-poison a target, every packet that target tries to send to the gateway comes to you first. You own it. You can drop it, delay it, mirror it, or rewrite it.

### 2.3 DupeZ's existing advantages NetCut lacks

- **Asymmetric presets** (`asymmetric_presets.py`) — directional traffic shaping (upload vs download separately)
- **Tick sync** (`tick_sync.py`) — frame-locked disruption timing
- **Packet recorder** — replay attacks
- **ML classifier** (`ml_classifier.py`, `statistical_models.py`) — traffic fingerprinting
- **Clumsy integration** — legacy throttle fallback

DupeZ is a more sophisticated *host-local* surgical tool than NetCut will ever be. NetCut is a bigger hammer but a dumber one. The right move is to bolt NetCut's reach onto DupeZ's precision, not to replace the engine.

---

## 3. The "Custom Kernel Driver" Question — Answered

**Short answer: no.** Do not write a custom driver.

**Long answer:**

A custom NDIS LWF or WFP callout driver would cost:

- 6–12 months of WDK work (C, kernel-mode discipline, no exceptions, no standard library, IRQL rules)
- EV certificate + WHQL submission for Windows to load it at all under Secure Boot (Microsoft kernel driver attestation signing is mandatory since Win10 1607 for new drivers)
- Every BSOD is now *your* fault, on *every user's* machine
- Debugging requires WinDbg + a second machine over serial/1394 or VM host-guest debugging
- Per-release re-signing workflow — you can't `pyinstaller` your way out of this

In exchange you get: the exact same capability Npcap already gives you for free.

Npcap is:

- NDIS 6 LWF, correctly signed, loads under Secure Boot without drama
- Installed by millions of Wireshark/nmap users, effectively a commodity dependency
- Licensed for redistribution in free/open-source tools under the Npcap OEM program (commercial redistribution requires a license — check before shipping)
- Supports raw packet send/recv, promiscuous mode, loopback capture, monitor mode on supported NICs
- Drop-in `pcap_sendpacket` lets you inject arbitrary Ethernet frames, including forged ARPs

Everything NetCut, Bettercap, Ettercap, Wireshark, nmap, Scapy, and Cain & Abel do rides on this driver (or its Unix cousin, libpcap). You are not leaving performance on the table by using it — you're joining the rest of the ecosystem.

**The only reason to write a custom driver** would be if you needed a capability Npcap can't expose: e.g. hooking below NDIS, bypassing Windows Defender Application Guard interception, or stealth from userspace enumeration. None of those are DupeZ's problem. Skip it.

---

## 4. Proposed Dual-Stack Architecture

```
                    ┌─────────────────────────────────────┐
                    │          DupeZ GUI (PyQt6)          │
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │       EngineRouter (new)            │
                    │  - picks engine per target scope    │
                    │  - host-local  → WinDivertEngine    │
                    │  - LAN peer    → NpcapL2Engine      │
                    └─────┬─────────────────────┬─────────┘
                          │                     │
                ┌─────────▼──────────┐   ┌──────▼──────────────────┐
                │ WinDivertEngine    │   │ NpcapL2Engine (NEW)     │
                │ (existing)         │   │                         │
                │ - L3/L4 host stack │   │ - ARP scanner           │
                │ - drop/lag/throttle│   │ - ARP poisoner          │
                │ - dup/ood/corrupt  │   │ - L2 forward/drop       │
                │ - rst/disconnect   │   │ - token-bucket throttle │
                │                    │   │ - protect mode (detect  │
                │ WinDivert64.sys    │   │   inbound poisoning)    │
                └────────────────────┘   │                         │
                                         │ Npcap (NDIS 6 LWF)      │
                                         └─────────────────────────┘
```

Key design decisions:

- **Two engines, one router.** The GUI exposes a target picker. If the target is `self` / `127.0.0.1` / an active game socket on this host → WinDivert. If the target is another LAN IP → Npcap L2. The user never has to know which.
- **Npcap is a declared dependency**, installed by the Inno Setup installer via a pre-bundled Npcap OEM redistributable (requires license) or a download prompt linking to `nmap.org/npcap/` (free path).
- **ARP poisoning is opt-in and gated behind an explicit "LAN MITM" toggle**, not the default. Accidental LAN disruption of roommates/family is a terrible UX.
- **Protect mode is the first defensive feature.** Detecting *inbound* ARP poisoning (somebody running NetCut on us) is low-cost, high-value, and matches the Grihm brand — it flips NetCut into a threat DupeZ defends against, then matches its offense.

---

## 5. Implementation Roadmap

### Phase 0 — This branch (`feature/netcut-research`)
- This document
- Decision ADR: "L2 MITM via Npcap, not custom driver"
- Npcap licensing due diligence (OEM redistribution cost, or require user to install free Npcap themselves)

### Phase 1 — `app/firewall/npcap_l2_engine.py` skeleton
- Bind to Npcap via `python-pcap` or `scapy` (scapy is the faster path, python-pcap is leaner at runtime)
- Implement: interface enumeration, ARP scan, ARP poison loop (threaded), ARP restore
- Unit tests against a loopback-capable adapter
- **No integration with GUI yet.** Pure library.

### Phase 2 — EngineRouter + GUI target picker
- New `engine_router.py` picks engine by target scope
- GUI device panel shows LAN devices from `enhanced_scanner.py` + per-device action menu
- Single new action: "Kick from LAN" (drop all poisoned traffic)

### Phase 3 — L2 throttle + forward
- Token-bucket forwarder in Npcap engine
- Per-device bandwidth cap (matches NetCut Pro feature 1)
- Scheduled cut windows (matches NetCut Pro feature 3)

### Phase 4 — Protect mode
- Background watcher for gateway MAC changes
- Toast notification on detection
- Optional auto-correct via gratuitous ARPs

### Phase 5 — Duping integration
- Trigger L2 cut on *partner's* connection at a scripted tick window
- Combine with host-local WinDivert drop on own connection for two-sided sync break
- This is the actual payoff — two-device coordinated rollback windows are not possible with WinDivert alone

Target ship: **v6.0.** Phases 1–2 minimum for a v6.0-alpha. Full feature parity with NetCut Pro at v6.0-stable.

---

## 6. Risk Analysis

### 6.1 Technical

- **Npcap licensing.** Free for end-user install; redistribution inside an installer requires Npcap OEM license ($$$). Safest path: installer detects missing Npcap and links to `https://npcap.com/#download`, does not bundle. This is how Wireshark handles it post-2020.
- **ARP storm risk.** A buggy poisoner that floods the LAN with ARPs can DoS the entire subnet including the attacker. Rate-limit and test against a throwaway switch.
- **Wi-Fi vs Ethernet.** ARP poisoning works on both, but some enterprise APs ship with Dynamic ARP Inspection (DAI) that drops unsolicited ARP replies. Home gear (Netgear, TP-Link, Asus consumer) does not. Document as "home LAN only."
- **Gateway failover.** If the real gateway sends its own gratuitous ARPs while we're poisoning, there's a race. Poison at 1Hz minimum to stay sticky.
- **IPv6.** ARP doesn't exist in IPv6 — the equivalent is NDP (Neighbor Discovery Protocol) poisoning. Out of scope for v6.0. Document as Ethernet/IPv4 only.

### 6.2 Detection (anti-cheat)

- L2 ARP activity is **invisible to BattlEye, EAC, and game-level anti-cheat.** They live in the game process and see only socket-level traffic.
- The *observable effect* on the disrupted host (packet loss, latency spikes) is identical to real network flakiness. Same signature as existing DupeZ WinDivert drops. No new detection vector.
- Your *own* machine's traffic looks normal to anti-cheat while the MITM runs, because you're not manipulating your own stack — you're manipulating the partner's.

### 6.3 Legal

- **On your own LAN: legal.** You own the network, you can do what you want on it.
- **On a network you don't own: federal crime in the US (CFAA), UK (CMA), most of EU (similar).** Cutting hotel Wi-Fi, coffee shop Wi-Fi, school networks = do not ship features that make this easy without a giant warning.
- **Against game ToS: same as existing DupeZ.** Already a ToS violation territory; no new legal surface.
- **Recommendation:** ship with an explicit "I own or have permission to use this network" gate on first launch of the LAN MITM mode. Log the acknowledgment. CYA.

### 6.4 Stability

- BSOD surface: near zero. Npcap is battle-tested by Wireshark's userbase (millions). We're adding zero kernel code.
- Host crash surface: our Python code is userspace. Worst case = Python exception, not blue screen. Same blast radius as current DupeZ.
- Data corruption: none — we're not touching disk or the host's filesystem.

---

## 7. What to Steal From NetCut (Ranked)

Ordered by ROI for DupeZ:

1. **Per-device LAN targeting** — the whole architectural shift above. Biggest win.
2. **Protect mode** — defensive feature, high marketing value, low implementation cost.
3. **Per-device bandwidth cap** — builds on the L2 forwarder; differentiates DupeZ as more than a kill switch.
4. **Persistent device history with vendor fingerprinting** — extends existing scanner, improves UX, cheap.
5. **Scheduled cut windows** — thin wrapper on top of kill switch, good for household "dinner time no Fortnite" use cases.
6. **WIFI lock** — low priority, edge-case feature, legal risk, skip for v6.0.

---

## 8. What NetCut Does NOT Have That DupeZ Should Keep Flexing

- Sub-tick precision disruption (`tick_sync.py`)
- Asymmetric upload/download shaping
- Packet capture + replay
- ML-based traffic classification
- Nine disruption primitives vs NetCut's one (drop)
- Game-specific presets

NetCut is a LAN administrator's panic button. DupeZ is a scalpel. The L2 expansion makes DupeZ a scalpel *with reach*, which is strictly better than NetCut's hammer.

---

## 9. Decision

**Proceed with dual-stack architecture. Npcap, not custom driver. Target v6.0.**

Next concrete step: Phase 1 — stand up `app/firewall/npcap_l2_engine.py` as a standalone library with ARP scan + ARP poison + ARP restore, tested against a throwaway LAN segment. Everything else in this doc is downstream of that prototype working.

---

## Appendix A — Npcap vs WinPcap vs WinDivert

| | WinPcap | Npcap | WinDivert |
|---|---|---|---|
| Layer | L2 (NDIS) | L2 (NDIS 6 LWF) | L3/L4 (WFP callout) |
| Status | Deprecated 2018 | Active | Active |
| Secure Boot | ❌ | ✅ | ✅ |
| Send raw Ethernet | ✅ | ✅ | ❌ |
| Modify in-flight | ❌ (observe/inject) | ❌ (observe/inject) | ✅ (in-place) |
| Loopback capture | ❌ | ✅ | ❌ |
| Used by | Legacy Wireshark | Modern Wireshark, nmap, NetCut Pro | DupeZ, Clumsy |
| Free for commercial use | ✅ | ⚠️ OEM license | ✅ (LGPL/GPL dual) |

## Appendix B — Why Bettercap Is The Right Reference Implementation

Bettercap (Go, `github.com/bettercap/bettercap`) is the modern open-source replacement for the ancient Ettercap. It implements ARP spoof, DNS spoof, HTTP/HTTPS proxying, WiFi deauth, and BLE MITM — all on top of libpcap/Npcap. Its `arp.spoof` module is ~600 lines of Go and should be the functional spec for DupeZ's `npcap_l2_engine.py`. Don't reinvent; port the state machine.

Repo worth reading before starting Phase 1:
- `bettercap/modules/arp_spoof/arp_spoof.go`
- `bettercap/modules/arp_spoof/arp_spoof_linux.go` (for the forwarding logic)

---

*End of research doc. Commit, push, open PR for review before starting Phase 1.*
