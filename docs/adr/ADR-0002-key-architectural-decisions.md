# ADR-0002: Key Architectural Decisions (Consolidated)

**Status:** accepted
**Date:** 2026-05-13
**Supersedes:** scattered code comments and CHANGELOG entries

This ADR consolidates the major architectural decisions baked into DupeZ between v5.5 and v5.7. Each decision is captured with the problem it solved, the option chosen, the alternatives considered, and the trade-off accepted. New contributors and Future Grihm should read this first.

---

## §1 — WiFi disruption of same-network peer targets

**Status: this decision was made in v5.6.5, REVERSED in v5.7.2 after a user-reported regression. The current behavior is the v5.7.2 one. The v5.6.5 history is preserved below as a lesson.**

**Problem.** v5.5.0 added a `wifi_same_net` path that ARP-spoofs peer devices and routes their traffic through the operator's machine via the NETWORK_FORWARD layer, so the target device gets disrupted. This is unreliable on consumer WiFi where AP client isolation drops the spoof.

**v5.6.5 decision (WRONG — reversed).** v5.6.5 collapsed the default to NETWORK layer / self-disrupt — only the operator's own traffic to/from the target was disrupted. The stated reasoning: AP isolation makes ARP unreliable, and "the canonical use case is lagging your own connection to a server."

**Why it was wrong.** That reasoning mis-identified the primary workflow. DupeZ's core loop is: scan the network → see the devices (Xbox, PS5, other PCs) → pick one → click DISRUPT. The operator is unambiguously asking to disrupt *that device*. Self-disrupt does nothing they asked for. v5.6.5 silently turned the tool's headline function into a no-op for every peer target. A user (Discord, "PUTKASKANU") reported it directly: "scan finds all devices including xbox, but disruptions has no effect now after update."

**v5.7.2 decision (current).** `wifi_same_net` targets route through ARP spoof + FORWARD layer again — the target device is disrupted directly. The v5.6.5 isolation watchdog is retained but now runs by default: when the AP genuinely drops the spoof (zero forwarded packets after an 8-second grace window), it auto-falls-back to self-disrupt mode with a toast. Users without AP isolation get the working cut; users with it get an honest, announced degraded mode. `params["_force_self_disrupt"]` is the explicit opt-in for operators who really do want self-disrupt.

**Lesson.** Do not infer the "canonical use case" from one's own assumptions. The tool's actual primary workflow is whatever the UI most directly invites — here, "pick a device, disrupt it." When a design decision makes the most obvious UI action do nothing, the decision is wrong regardless of how defensible the edge-case reasoning sounds. Validate against a real user before collapsing a default.

---

## §2 — Auto-update fail-closed by pinned Ed25519 (v5.6.2 → v5.6.6)

**Problem.** Without signature verification, a compromise of the GitHub account / CDN / DNS translates one-for-one into silent installer-grade RCE on every user who clicks "Install update."

**Decision.** v5.6.2 added the verifier (`app/core/update_verify.py`) and pinned-pubkey trust model. v5.6.6 provisioned the actual Ed25519 key and folded signing into `packaging/build_variants.bat`. Without a valid `.manifest.json` + `.manifest.sig` sidecar signed by a pinned pubkey, the updater refuses the install.

**Bootstrapping note.** Trust cannot be bootstrapped from nothing. Users on v5.6.3-v5.6.5 carry an empty `TRUSTED_PUBKEYS_PEM` and require one manual download of v5.6.6. From v5.6.6 onward, auto-update works correctly. This is intentional; we will not retro-add a permissive path to old clients.

**Trade-off accepted.** A maintainer-side key-management cost (offline-held private key, rotation procedure documented in `update_verify.py` docstring) in exchange for elimination of installer-grade RCE via any single point of compromise.

---

## §3 — Split-elevation architecture for the GPU map (ADR-0001)

**Problem.** GPU-accelerated map rendering (Chromium WebEngine) refuses to spawn child processes under High-IL on Windows. But WinDivert requires admin / High-IL for packet interception. These two requirements are at war.

**Decision.** Split the process tree: a Medium-IL GUI process owns the WebEngine, and an elevated helper child handles WinDivert calls over a named-pipe IPC. The helper is the same binary (`DupeZ-GPU.exe`) re-invoked with `--role helper`. The Compat variant (`DupeZ-Compat.exe`) keeps the legacy single-process model with `requireAdministrator` manifest, for users on blocklisted GPUs.

**Trade-off accepted.** Two release artifacts, one IPC layer, one feature-flag factory (`get_disruption_manager`). Mitigated by v5.6.3's pipe-disconnect recovery (helper death no longer requires a GUI restart) and v5.6.5's WiFi-aware orchestration that works identically across both variants.

---

## §4 — Telemetry stays local, opt-in only (continuous)

**Decision.** DupeZ records per-cut episodes to `app/data/episodes/*.jsonl` on the local machine only. There is no cloud telemetry. The Discord webhook sink (v5.7.0) only forwards what the operator explicitly configures, and only after the canonical JSONL write succeeds.

**Trade-off accepted.** Maintainer has no aggregate usage data. Future product decisions rely on direct user feedback rather than analytics. Strong privacy posture is worth more than the lost signal.

---

## §5 — Plugin trust model: signed bundles + capability sandbox (v5.5)

**Decision.** Plugins ship as Ed25519-signed ZIP bundles. The loader verifies the signature against a pinned trust list (currently project key only). Plugins run in a capability sandbox limiting filesystem + network access. Future plugin marketplace (v5.8+) will extend the trust list to community authors with first-install consent.

**Trade-off accepted.** Higher contributor friction (must sign + cap-declare) in exchange for elimination of arbitrary-RCE plugins. Same threat-model logic as §2.

---

## §6 — Fail-closed posture everywhere (continuous)

**Decision.** When a safety check fails or input is suspect, refuse the action rather than degrade silently. Examples:

- v5.6.4 WiFi honesty pass: 4 silent-no-op branches in the ARP path now return False → surface "Partial Failure" dialog instead of badging DISRUPTED on a useless WinDivert handle.
- v5.6.6 auto-update: empty pubkey list → refuse every update rather than allow unsigned.
- v5.6.8 tracker save-state: failed load → preserve disk, log error rather than overwrite with template.
- v5.6.9 process_scope: zero DayZ PIDs → fall back to unscoped filter with loud warning rather than silently capture zero packets (this is the exception that proves the rule: silent capture-nothing was deemed strictly worse than capture-everything for a process-scope failure).

**Trade-off accepted.** More toasts / dialogs / error messages in the UX in exchange for never silently lying to the operator about what's working.

---

## §7 — Test coverage policy (v5.7.1)

**Decision.** Every new module shipped in v5.6.9+ requires a `tests/test_<module>.py` covering happy-path + critical edge cases. Backfilled in v5.7.1 with 175 new test cases across 10 modules — surfaced 3 real production bugs (token-bucket starting empty, preset regex rejecting auto-rename suffix, overlay handler class-attribute leak) that the previous test suite never caught.

**Trade-off accepted.** ~500 LOC of test code per feature batch, in exchange for regression resistance on every future refactor. The v5.6.x release cycle had multiple recovery passes that better tests would have prevented.

---

## §8 — When NOT to add a feature

Feature creep is the failure mode that ends the project. These categories of requests have been explicitly declined:

- **Active anti-cheat evasion / process injection.** Changes the threat model. Current product is "network shaping" — that's a clean line.
- **Cloud profile sync / account system.** Adds a backend you don't have, maintenance cost forever. Local-only stays the rule.
- **Cross-game support beyond the network primitives.** Loot route planners, server browsers, etc. are different apps — not duping tools.

When a request lands, ask: "does this extend what DupeZ IS, or does it make DupeZ INTO something else?" Extensions ship. Conversions get added to this list.
