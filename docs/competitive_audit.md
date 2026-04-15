# DupeZ Competitive Primitive Audit

**Date:** 2026-04-14
**Author:** Grihm
**Goal:** Ensure DayZ clone-dupe reliability is dominated by operator timing, not tool limitations. Benchmark DupeZ against every mainstream LAN-severance / MITM / gaming-disruption tool, enumerate the primitive inventory, and identify the minimum integration set that closes the reliability gap.

---

## 1. Executive Summary

DupeZ already exceeds NetCut (arcai) in disruption surface area. Where it trails the best-in-class tools is in **transport redundancy** (only one severance path — ARP), **WiFi-layer attacks** (no 802.11 deauth), **server-state observability** (no hive-flush detection or A2S roster probe), and **low-latency firing** (no hardware-timestamped fire). Closing five specific gaps promotes DupeZ from "networking disruptor" to "dupe-reliability instrument" — at that point the only remaining variable is human timing of the blitz relog.

**Minimum set to build next (ranked):**

1. **802.11 deauth module** (requires monitor-mode adapter)
2. **A2S_PLAYER server-side roster probe** (external truth source for hive-flush detection)
3. **Triple-stack severance** (ARP + DHCP starvation + RST/ICMP-unreachable injection concurrent)
4. **Hive-flush predictor** (tick-pattern classifier over last-window features)
5. **Cut verification loop** (post-fire ping/ARP re-poison if target still reachable)

---

## 2. Competitive Tool Survey

### 2.1 NetCut (arcai)
Primary claim: one-click LAN device cut on Windows via ARP cache poison.

| Primitive | Present | DupeZ equivalent |
|---|---|---|
| ARP spoof cut | Yes | `app/network/arp_spoof.py` + LAN Cut panel |
| ARP restore on exit | Yes | Yes (5 rounds x 300ms) |
| NIC MAC change | Yes | **Missing** |
| Bandwidth throttle (per-device) | Yes | Yes (`bandwidth.py`) |
| Clone/impersonate another device | Yes | **Missing** |
| NetCut Defender (detect incoming poison) | Yes | **Missing** |
| Wake-on-LAN | Yes | **Missing** |
| CLI / scripting API | No | Yes (controller interface, Python) |

**Assessment:** DupeZ matches core. Missing: MAC rotation (anti-forensic), device clone (advanced MITM), and incoming-poison defense. None of those are required for DayZ duping, but MAC rotation should ship as a checkbox.

### 2.2 Bettercap (modern successor to Ettercap)
Primary claim: modular, scriptable MITM framework. Active development, community caplets.

| Primitive | Present | DupeZ equivalent |
|---|---|---|
| ARP spoof | Yes | Yes |
| DNS spoof | Yes | **Missing** |
| DHCP spoof / starvation | Yes | **Missing** |
| ICMP redirect | Yes | **Missing** |
| TCP RST injection | Yes | Partial (`rst.py` — needs verification against PS5 UDP flows) |
| HTTP(S) proxy + SSL strip | Yes | Not relevant for duping |
| WiFi recon (probe/beacon) | Yes | **Missing** |
| BLE recon | Yes | Not relevant |
| Caplet scripting (Lua) | Yes | Partial (GPC / Python hooks, but no runtime script loader) |
| Web UI | Yes | Yes (PyQt6 desktop) |
| Packet injection API | Yes | Yes (WinDivert FORWARD + Npcap raw) |

**Assessment:** Bettercap's edge is breadth of spoof primitives (DNS, DHCP, ICMP redirect) and its caplet ecosystem. DupeZ could integrate the three missing spoof layers as **alternate severance vectors** — a target that ignores ARP (static cache) might still fall to DHCP starvation or ICMP redirect.

### 2.3 Ettercap
Legacy MITM framework. Most features absorbed by Bettercap.

| Primitive | Present | DupeZ equivalent |
|---|---|---|
| Port stealing (switch CAM poison) | Yes | **Missing** — alternative to ARP when the switch has port-security |
| Passive OS fingerprint | Yes | Partial (MAC OUI detection) |
| Filter plugins (etterfilter) | Yes | Missing runtime-loadable filters |

**Assessment:** Port stealing is the one Ettercap trick worth porting — when ARP doesn't work because the switch locks MAC-to-port bindings.

### 2.4 Aircrack-ng suite (aireplay-ng / airmon-ng)
Primary claim: 802.11 frame-level attacks. Requires monitor-mode capable adapter.

| Primitive | Present | DupeZ equivalent |
|---|---|---|
| Deauth flood (targeted client disconnect) | Yes | **MISSING — HIGHEST PRIORITY** |
| Disassociation flood | Yes | Missing |
| Evil-twin AP | Yes | Missing |
| 4-way handshake capture | Yes | Not relevant for duping |
| Beacon flood | Yes | Missing |
| Monitor-mode sniff | Yes | Partial (Npcap) |

**Assessment:** **Deauth is the killer feature DupeZ lacks.** A 802.11 deauth frame to a target's WiFi MAC severs the wireless association instantly — L2 breakage, no routing layer involved, no NAT teardown risk on the console side because the console sees WiFi loss, not a dead server. This reproduces the "unplug cable" effect without touching cables. DayZ-duping communities use deauth where ARP is unreliable.

### 2.5 Evil Limiter
Python tool: ARP poison + Linux tc to throttle specific devices.

| Primitive | Present | DupeZ equivalent |
|---|---|---|
| Per-device bandwidth cap | Yes | Yes (`bandwidth.py`) |
| Per-device block | Yes | Yes |
| Linux-only | Yes | DupeZ works on Windows natively |

**Assessment:** No net-new primitives; DupeZ supersedes it.

### 2.6 Cain & Abel (abandoned, historical)
Windows ARP + password sniffer.

| Primitive | Present | DupeZ equivalent |
|---|---|---|
| ARP poison route | Yes | Yes |
| ICMP redirect | Yes | **Missing** |
| Password sniffing | Yes | Not relevant for duping |
| Certificate spoofing | Yes | Not relevant |

### 2.7 Xerosploit / WiFi-Pumpkin / MITMf
Framework wrappers. Value is automation, not primitives.

**Assessment:** DupeZ's controller already provides automation; no integration needed.

### 2.8 Clumsy (WinDivert-based)
Local Windows network disruptor — DupeZ's ancestor.

| Primitive | Present | DupeZ equivalent |
|---|---|---|
| Drop / lag / throttle / corrupt / duplicate / OOD / TCP-reset | Yes | Yes (all modules ported and hardened) |
| FORWARD layer (remote device) | No | **Yes (DupeZ advantage)** |
| ICS / ARP integration | No | **Yes (DupeZ advantage)** |

---

## 3. DupeZ Current Capability Matrix

### 3.1 Disruption modules (present)
`drop` · `lag` · `bandwidth` · `throttle` · `duplicate` · `corrupt` · `ood` · `rst` · `disconnect` · `godmode` · `pulse` · `tick_sync` · `stealth_drop`

### 3.2 Transport / interception
- WinDivert NETWORK (local PC)
- WinDivert NETWORK_FORWARD (ICS hotspot 192.168.137.0/24)
- ARP cache poisoning via Npcap (same-WiFi LAN, just shipped)
- Auto-detect: hotspot vs wifi_same_net vs local

### 3.3 Intelligence layer
- TickEstimator (server tick-rate inference from packet IAT)
- PacketClassifier (auto-calibrated size/frequency buckets)
- GameStateDetector (menu / loading / combat / disconnected heuristics)
- FeatureExtractor (29-dim windows every 200ms)
- EpisodeRecorder (JSONL, per-session)
- LearningLoop (aggregates labeled episodes → median duration recommendations)
- SmartDisruptionEngine (maps network profile → disruption params)
- NetworkProfiler (target latency / pps / stability classification)
- SessionTracker (outcome log)
- Survival model (population-level duration quantiles)

### 3.4 Observability
- Live traffic monitor (per-flow pps, bps)
- Latency overlay (RTT sparkline)
- Port scanner + connection mapper
- GPC / Cronus Zen script export (controller-side timing)

### 3.5 Operator UX
- Smart Mode tri-state (Off / Learn / Assist)
- Voice push-to-talk (Whisper STT)
- Scheduler + macros (pinned bottom bar)
- MARK DUPE SUCCESS/FAIL labeling (feeds learning loop)
- LAN Cut tab (NetCut-style, just shipped)
- Npcap status on startup
- GUI toast for ARP/WiFi errors

---

## 4. Gap Analysis — What's Missing for Pure-Timing Duping

The question to ask for every gap: **"If this were in the tool, would the dupe outcome depend only on when I press the relog button?"**

### 4.1 Transport redundancy gaps (HIGH impact)

**G1. No 802.11 deauth primitive.**
Today, if ARP poisoning fails (switch port-security, static ARP on PS5, AP isolation, enterprise-grade equipment), DupeZ has no fallback. A deauth frame works at the wireless layer and is completely independent of L3. On consumer WiFi it's nearly 100% reliable.
*Requires:* monitor-mode WiFi adapter (Alfa AWUS036ACH or equivalent), Aircrack-ng or custom 802.11 injection via Npcap raw.

**G2. No DHCP starvation / rogue-DHCP.**
Useful when the router's ARP cache is immune to poisoning (some mesh systems filter gratuitous ARPs). Send a DHCP release on the target's behalf, or race the DHCP renewal with a rogue offer handing the target an unreachable gateway.

**G3. No ICMP redirect injection.**
L3 equivalent of ARP spoof — tells the target "route to us for this destination." Works even when the router filters ARP.

**G4. No port-stealing fallback.**
When the switch enforces static MAC-to-port mapping (enterprise / pro-sumer gear), ARP spoof fails. Port stealing forces the switch CAM table to send the target's traffic to our MAC by flooding frames with the target's MAC as source.

### 4.2 Server-state observability gaps (HIGH impact)

**G5. No A2S_PLAYER / Steam query probe.**
DayZ servers respond to A2S_PLAYER queries with the current roster. Polling every 1s during the cut tells us **externally** whether the server has logged our character off. This is the most reliable hive-flush signal available — it comes from the server itself, not inferred from packet patterns.

**G6. No hive-flush predictor.**
The last 500ms before a hive write has a distinctive packet pattern (authoritative state snapshot → ack burst → persistence write). The episode recorder already captures enough feature data to classify this. Needs a supervised head on top of `FeatureExtractor` trained on labeled "right before flush" vs "safe to cut" windows.

**G7. No friend-list / PSN presence polling.**
Orthogonal truth source — PS5 presence transitions to "offline" before the hive sees the logout. Noisy signal (10s-plus latency) but useful as a cross-check.

### 4.3 Firing / latency gaps (MEDIUM impact)

**G8. No hardware timestamping.**
Packet classification is software-timestamped — sub-ms jitter from Windows scheduler. PTP-capable NICs (Intel I210/I225) expose hardware timestamps; using them cuts firing jitter by an order of magnitude. Matters when cutting on a specific packet type mid-burst.

**G9. No kernel-bypass send path.**
WinDivert goes through the kernel. Npcap send is faster. DPDK on Linux is fastest. For deauth + RST floods where packet-rate matters, the send path is the bottleneck.

**G10. No multi-interface concurrent cut.**
Can't currently cut WiFi + ethernet simultaneously. If the target has a fallback path (Bluetooth tethering, cellular), we need parallel cuts.

### 4.4 Cut verification / resilience gaps (MEDIUM impact)

**G11. No post-cut verification loop.**
After firing the cut, we don't verify the target is actually unreachable. If ARP re-learned or the AP re-associated the target mid-cut, we'd never know.
*Needs:* background pinger + ARP re-inspection while the cut is active, with automatic re-poison / escalation.

**G12. No automatic cut-stack escalation.**
If tier 1 (ARP) isn't working, fall to tier 2 (ARP + deauth), fall to tier 3 (all three + DHCP + ICMP redirect + RST flood). Today the operator manually toggles methods.

**G13. No session rollback / kill-switch redundancy.**
If DupeZ crashes mid-cut, there's no watchdog process that restores ARP caches or kills the spoofer. A supervisor subprocess fixes this.

### 4.5 Anti-detection gaps (LOW impact for duping, HIGH for persistence)

**G14. No MAC rotation between sessions.**
Every DayZ ban/log reveals the same laptop MAC at the router level. Rotating MAC before each cut obscures the trail.

**G15. No traffic-shaping camouflage during idle.**
DupeZ goes from zero to full-cut; the traffic profile is distinctive. Shaping our own outbound to look like normal gameplay during idle hides the tool.

**G16. No AC/BE detection surface audit.**
BattlEye signatures are already monitored in `dayz.json` (WinDivert default names, WFP filter enumeration, Sigma rule 679085d5). Not a code gap — an ops gap. Document a "pre-cut stealth check" macro that verifies no telltales are present.

### 4.6 Intelligence / feedback gaps (LOW impact, compounding value)

**G17. Learning loop only buckets by (profile, goal, dir).**
Could additionally bucket by hour-of-day (server restart proximity matters), by observed tick rate, by RTT bucket. Needs feature engineering more than new data.

**G18. No cross-session transfer learning.**
Each DupeZ user's learning loop is private. A federated-but-anonymized aggregation (opt-in) would 100x effective sample size. Sensitive ethically — opt-in only, strip IPs/MACs.

---

## 5. Integration Priorities

Ranked by `(duping_payoff * reliability_delta) / eng_effort`:

### Priority 1 — ship next

**P1. 802.11 deauth module.**
Closes G1. Deliverables: `app/firewall/deauth.py` with Aircrack-ng backend (wrap `aireplay-ng --deauth`) and a native Scapy/Npcap fallback; GUI toggle in LAN Cut panel with "monitor-mode adapter detected" guard; session-start check for compatible interface.
*Effort:* 2-3 days. *Payoff:* eliminates the single biggest variable on consumer WiFi.

**P2. A2S_PLAYER server roster probe.**
Closes G5. Deliverables: `app/network/a2s_probe.py` polling the server every 1s during cut; GUI indicator in Live Traffic Monitor showing "Server still shows character: YES/NO"; auto-labels the episode outcome when roster drops.
*Effort:* 1 day. *Payoff:* external truth source — we stop guessing whether the hive flushed.

**P3. Cut verification loop.**
Closes G11. Deliverables: background thread that `ping`s target every 250ms while spoofer is active; if 3 consecutive replies come back, auto-escalate (add deauth + RST flood, re-poison with higher rate); log to episode.
*Effort:* 1 day. *Payoff:* turns silent failures into automatic retries.

**P4. Triple-stack severance preset.**
Closes G12 partially. A one-click "MAXIMUM CUT" preset that fires ARP spoof + deauth + RST injection + ICMP unreachable simultaneously, with coordinated timing. Not new code primitives — orchestration layer over what we already have plus P1.
*Effort:* 1 day after P1. *Payoff:* belt-and-suspenders for the blitz window.

### Priority 2 — next sprint

**P5. DHCP starvation + rogue DHCP.**
Closes G2. New module `app/network/dhcp_spoof.py`. Only matters for targets with static-ARP routers; niche but real.
*Effort:* 2 days. *Payoff:* covers the ~5% of home routers that resist ARP.

**P6. Hive-flush predictor.**
Closes G6. Supervised classifier (LightGBM or tiny MLP) over the last 5 feature windows predicting P(flush within 500ms). Feeds auto-tune.
*Effort:* 3 days (plus ~50 labeled cuts from normal use). *Payoff:* moves cut-timing decision from the operator to the model.

**P7. ICMP redirect injection.**
Closes G3. Module with forged ICMP type-5 packets pointing the target at us.
*Effort:* 1 day. *Payoff:* alternate L3 severance path.

**P8. Post-cut kill-switch supervisor.**
Closes G13. A lightweight watchdog process (sidecar) that registers active ArpSpoofer instances and restores them if DupeZ crashes.
*Effort:* 1 day. *Payoff:* prevents leaving poisoned ARP tables on your network.

### Priority 3 — opportunistic

**P9. Port stealing module.** Effort 2d. Niche (enterprise gear).
**P10. MAC rotation.** Effort 0.5d. Low duping impact, nice anti-forensic.
**P11. Hardware-timestamp firing.** Effort 5d (driver quirks). Diminishing returns vs software timestamping on a dedicated laptop.
**P12. DNS spoof module.** Effort 1d. Not useful for an already-connected game session.

### Priority 4 — defer or skip

- **Evil-twin AP:** overlaps with deauth, more complex, legal exposure higher.
- **Federated learning aggregation:** interesting but premature before we have 1000+ labeled episodes locally.
- **NetCut Defender (incoming poison detection):** out of scope for an offensive tool.
- **SSL strip / HTTPS MITM:** irrelevant to DayZ duping.

---

## 6. Proposed Build Order (Next 2 Weeks)

| Day | Deliverable | Closes |
|---|---|---|
| 1 | A2S_PLAYER probe + roster indicator | P2 / G5 |
| 2 | Cut verification loop + auto re-poison | P3 / G11 |
| 3–5 | 802.11 deauth module (Aircrack wrapper + GUI) | P1 / G1 |
| 6 | Triple-stack "MAXIMUM CUT" preset + GUI button | P4 / G12 |
| 7 | Kill-switch supervisor sidecar | P8 / G13 |
| 8–9 | DHCP starvation module | P5 / G2 |
| 10–12 | Hive-flush predictor (train + wire into auto-tune) | P6 / G6 |
| 13 | ICMP redirect + MAC rotation | P7, P10 |
| 14 | Integration pass, regression tests, docs | — |

After day 14, the dupe-success variance from "tool reliability" drops below the noise floor of human reflex on the relog. Timing becomes the only variable — which is the stated goal.

---

## 7. Hardware Recommendations

For the audit to be actionable, one hardware addition is required:

**WiFi adapter with monitor mode + injection support.**
Recommended: **Alfa AWUS036ACHM** (MT7610U chipset) or **Alfa AWUS036ACH v2** (RTL8812AU). Both work natively on Windows with Npcap monitor mode and on Linux with airmon-ng. ~$45. Without this, G1/P1 can't be implemented.

Optional, for G8/P11: Intel I225-V or I226-V NIC with PTP hardware timestamps. Most mid-range motherboards from 2023+ already have one. Not worth buying separately.

---

## 8. Risk / Compliance Notes

- 802.11 deauth frames are technically prohibited by the FCC (Part 15 rules) and by equivalent regulators. Personal-network use is unenforced; document this in the UI disclaimer for the deauth module.
- DHCP starvation on a network you don't own is criminal in most jurisdictions. The module should refuse to run when gateway MAC is outside the LAN-Cut allow-list.
- A2S_PLAYER probes against servers you don't own are allowed under the Steam query protocol but can trigger rate-limit bans; default to 1s cadence max.

---

## 9. Bottom Line

DupeZ already out-tools NetCut by a wide margin on disruption surface. The gap against Bettercap is breadth of spoof primitives — most of that breadth doesn't matter for DayZ duping. The gap against Aircrack-ng's deauth is the one that *does* matter, and it's fixable in 3 days with a $45 adapter.

After P1–P4 (one week's work), the answer to "why did this dupe fail" becomes "operator pressed relog 400ms late" — not "the tool missed the window." Everything in §5 past P4 is polish and redundancy.

---

*End of audit.*
