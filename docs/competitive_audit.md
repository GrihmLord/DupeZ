# DupeZ Defensive Product and Competitive Audit

**Date:** 2026-06-25
**Scope:** Windows network-condition testing and diagnostics for owned or
explicitly authorized local networks, with a DayZ-oriented workflow.

## Executive conclusion

DupeZ should not compete by accumulating increasingly invasive network attack
primitives. That creates legal, safety, support, and server-integrity risk without
making the product easier to trust.

The credible market position is:

> A Windows desktop lab for reproducing poor network conditions, validating
> DayZ connectivity, and recovering safely from interrupted tests—with
> per-device scope, dry-run previews, explicit deadlines, auditability, and
> support-grade diagnostics.

Clumsy remains a useful benchmark for simple local impairment. NetCut is a
benchmark for approachable device discovery and scheduling. Windows Packet
Monitor is the benchmark for explainable, low-level diagnostics. DupeZ can
surpass their combined product experience through safer scope controls,
crash-safe recovery, guided diagnostics, and an integrated DayZ workflow.

## Evidence reviewed

- **Clumsy:** controlled and interactive poor-network simulation on Windows,
  built on WinDivert, with no proxy or application changes required.
- **NetCut:** device identification, speed control, unknown-device visibility,
  schedules, history, and one-click controls.
- **Microsoft Packet Monitor (Pktmon):** in-box cross-component packet
  diagnostics, counters, drop detection/reasons, ETW logging, filtering, and
  PCAPNG export.
- **WinDivert 2.2:** user-mode packet capture/filter/drop/modify/reinject,
  network and forward layers, IPv6/loopback support, and administrator
  requirements.

## Competitive matrix

| Product | Strongest quality | Important limitation | DupeZ opportunity |
|---|---|---|---|
| Clumsy | Fast, portable, understandable local impairment | Primarily local/system-wide; limited recovery and support workflow | Per-device authorized scope, guided presets, deadlines, dry run, recovery journal |
| NetCut | Device-centric UI, schedules, history, recognizable controls | Peer-control orientation creates trust and authorization concerns | Owned-lab inventory, CIDR allowlists, transparent audit trail, safer terminology |
| Pktmon | Root-cause visibility and native Windows diagnostics | Command-line complexity and no scenario-oriented UX | Guided capture, counters, drop reasons, redacted export, DayZ-focused explanation |
| DupeZ | Broad integrated workflow and mature local tooling | Complexity, legacy offensive language, uneven accessibility, steep trust barrier | Consolidate around a polished defensive lab and diagnostics experience |

## Differentiators DupeZ should own

1. **Scope before action**
   - Owned/authorized-use acknowledgement.
   - Local-address and operator CIDR allowlists.
   - Dry-run validation before packet-engine initialization.
   - Hard operation deadlines and bounded scheduling.

2. **Recovery as a first-class feature**
   - Crash-safe operation journal.
   - Exact restoration of the previous forwarding state.
   - Elevated helper lifetime bound to the parent process.
   - Startup recovery with honest status reporting.

3. **Explainable diagnostics**
   - A health dashboard using plain language.
   - Optional Pktmon-assisted collection with visible filters and duration.
   - Packet/drop counters and root-cause summaries.
   - Redacted support bundles with an explicit manifest.

4. **DayZ-specific, passive insight**
   - Server reachability and query health.
   - Latency, jitter, loss, route, NAT/firewall, and adapter diagnostics.
   - Server configuration validation for operators who own the server.
   - No claims about inventory duplication, server-integrity bypass, or public-server
     manipulation.

5. **Professional release trust**
   - Signed installer and update manifest.
   - Bundled-binary provenance verification.
   - Reproducible release preflight.
   - SBOM, dependency review, CodeQL, and documented vulnerability intake.

6. **Accessible operation**
   - Keyboard-complete navigation.
   - Accessible names/descriptions for icon-only controls.
   - High-contrast themes and non-color status cues.
   - Screen-reader announcements for operation state changes.

## Highest-value remaining gaps

### P0 — release blockers

- Remove exploit/evasion positioning from current user-facing documentation.
- Complete keyboard and screen-reader testing across every active-operation
  control.
- Make every active state show target scope, remaining deadline, and an
  immediate stop action.
- Add signed-installer verification to the release checklist and publish
  hashes/provenance.

### P1 — market-leading polish

- Completed baseline: a unified Network Health snapshot now combines
  diagnostics, aggregate adapter readiness, default-route type, Pktmon
  capability, safety policy, recovery state, scoring, and prioritized
  recommendations in GUI and CLI. A dedicated full-page workspace remains.
- Completed CLI baseline: guided Pktmon planning/capture requires a TCP/UDP
  port filter, caps duration at 30 seconds and storage at 32 MB circular,
  truncates packets to 64 bytes, refuses pre-existing global filters, requires
  two explicit capture confirmations, and never uploads files. A GUI capture
  wizard remains.
- Add scenario templates for owned-lab testing: latency, jitter, loss,
  bandwidth pressure, reorder, and temporary disconnect.
- Completed baseline: active-operation snapshots now show masked scope,
  elapsed time, remaining automatic-stop time, process state, methods, and
  parameter fingerprints. Deterministic UTC scenario reports are available
  through CLI and GUI using IPPM terminology. Future work should attach
  operator-reviewed counters and measured outcomes.
- Add first-run onboarding that defaults to Dry Run and explains local scope.

### P2 — support and scale

- Localize visible UI strings.
- Add benchmark tests for packet-loop overhead and UI responsiveness.
- Split dashboard and engine god objects into testable services.
- Add plugin capability declarations and a brokered, deny-by-default API.
- Add privacy controls for retention, export, and one-click local-data reset.

## Storage and upgrade hardening completed

- Installed binaries and mutable state now use separate trust locations.
- Runtime data, configuration, logs, crashes, captures, reports, episodes, and
  trained models resolve beneath the current user's local application-data
  folder.
- Legacy migration is allowlisted, copy-only, SHA-256 verified, conflict-aware,
  retryable after failures, and leaves source files untouched.
- Backup archives retain stable logical paths while restore maps them to the
  current runtime roots with atomic post-write verification.

## Explicit non-goals

DupeZ should not implement or market:

- Wi-Fi deauthentication or disassociation.
- DHCP starvation, rogue DHCP, port stealing, or unauthorized neighbor-cache
  interference.
- Credential interception, identity impersonation, or MAC rotation for
  forensic weakening.
- Server-integrity bypass, behavioral rotation, detection-rule tracking, or
  concealed modes.
- Unauthorized public-server use or game-state manipulation.

These features increase harm and support burden while undermining the product's
defensible value proposition.

## Success metrics

- 100% of active operations pass scope validation and have an automatic stop.
- 100% of icon-only controls have accessible names.
- Zero raw target identifiers in default logs and support bundles.
- Startup recovery restores all journaled host-network changes.
- A new user can run a dry scenario and export a report in under five minutes.
- Release artifacts pass provenance, signature, dependency, and security
  preflight checks before publication.

## Primary sources

- Clumsy: https://github.com/jagt/clumsy
- NetCut: https://arcai.com/netCut/s/
- Microsoft Packet Monitor:
  https://learn.microsoft.com/windows-server/networking/technologies/pktmon/pktmon
- WinDivert documentation: https://reqrypt.org/windivert-doc.html
