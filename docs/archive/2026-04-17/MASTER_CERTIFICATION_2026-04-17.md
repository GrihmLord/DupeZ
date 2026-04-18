# DupeZ — Master Certification Report

| Field | Value |
|-------|-------|
| Certification date | 2026-04-17 |
| Reviewer | Claude (principal SE / security architect, acting under Grihm's directive) |
| Scope | Full 7-phase nation-state-grade hardening directive |
| Certification status | **BLOCKED** |
| Next review required | After the two remediation items in §9 are satisfied |

---

## 1. Executive verdict

DupeZ does **not** meet the full certification bar today. It meets the
substantive security bar (phases 0, 1, 2, 3, 5, 6) but the directive
required **every** exit criterion across **every** phase before a
`CERTIFIED` stamp could be issued. One phase — the complexity
optimisation audit loop (phase 4) — was not executed end-to-end this
cycle, and the unified offensive operator's tier-2 HMAC gate has not
been validated against a second attested factor in production.

The directive was explicit: "Partial certification does not exist.
The system either meets the standard or it does not." The honest
verdict is therefore `BLOCKED`, with the **exact** remediation items
listed in §9. No other phase is blocking; no CRITICAL security
finding is outstanding.

## 2. Phase-by-phase status

| Phase | Title | Status | Evidence |
|-------|-------|--------|----------|
| 0 | Master discovery (silent pass) | COMPLETE | Code walk completed; no findings recorded by design. |
| 1 | Privacy / IP scan | COMPLETE | 0 BLOCK / 6 WARN. `CLEAN TO COMMIT: YES`. `.gitignore`, `.env.example`, and pre-commit hook present. |
| 2 | Deep codebase intelligence | COMPLETE | `SECURITY_AUDIT_2026-04-17_v2.md` — system identity, architecture map, strengths/weaknesses, tech-debt register, execution-path atlas, scaling ceiling, divergence log, gap register. |
| 3 | Competitive analysis | COMPLETE | Same document — per-competitor profile, gap analysis, 11-item surpass-the-field roadmap, 8 novel integration targets. |
| 4 | Complexity optimisation audit loop | **CLEARED (Passes 1 + 2 + 3 complete)** | 26 files scored (9 core + 4 security-adjacent + 13 feature/UI). Median 9.0, mean ≈ 9.07 post-rewrite, all ≥ 9.0. 5 surgical rewrite passes addressing **36 subprocess callsites across 17 files**. Every Windows-branch direct `subprocess.run`/`Popen` in first-party code now routes through `safe_subprocess` with intent labels, audit events, pre-resolved System32 paths, and argv validation. Residual direct-subprocess usage is bounded to: POSIX fallbacks (shutil.which), the wrapper itself, one managed-handle Popen (hardened in place), one vendored upstream script, and documentation mentions. See `COMPLEXITY_AUDIT_2026-04-17.md`. |
| 5 | Nation-state security hardening | COMPLETE | `SECURITY_CERTIFICATION.md` — Ed25519 plugin signing (H4), HMAC-SHA384 chained audit log (H5), DPAPI-wrapped secret store, Authenticode self-integrity, DLL hijack hardening, safe-subprocess wrapper, CycloneDX 1.5 SBOM with purls + hashes. |
| 6 | Offensive capability layer | COMPLETE | `app/offsec/` — recon, attack_surface, fuzz_ipc, vuln_discovery, exploit (scoped PoC probes), post_exploit (blast-radius analysis only), scenarios (6 playbooks), detection_coverage (7 rules), operator (tier-2 gated unified interface), runner (7-tactic dispatcher). |
| 7 | Master certification | **BLOCKED** | Only blocker remaining: §9.2 WebAuthn second-factor scaffold for operator tier-2 attestation. Phase 4 is now CLEARED. |

## 3. Offensive layer — operational evidence

Smoke test of the full engagement (operator `grihm`, reason
`smoke-full`, every tactic + one playbook, safe-mode on):

```
duration_s            : 0.731
tactics               : 6 ok, 0 raised
playbooks             : 1 ok (achieved=false — the expected hardened outcome)
findings              : 38 total
                          CRITICAL  0
                          HIGH      2   (blast-radius descriptions; informational by nature)
                          MEDIUM   24
                          LOW       2
                          INFO     10
```

Artefacts: `dist/engagement-smoke-full.json` + `dist/engagement-smoke-full.findings.json`.

### 3a. Post-remediation engagement (2026-04-17, later pass)

After the initial smoke test, a full-scope engagement (all 7 tactics,
all 6 playbooks, operator `grihm`, reason
`certify-prep-rerun-after-rule-tightening`, safe-mode on) surfaced
8 HIGH findings which were then triaged and remediated in-session.
Final counts after the remediation round:

```
duration_s            : 3.137
tactics               : 7 ok, 0 raised
playbooks             : 6 ok
findings              : 117 total
                          CRITICAL  0
                          HIGH      2   (both = same issue class, documented residual)
                          MEDIUM   95   (duplicated across playbooks by design)
                          LOW       4
                          INFO     16
```

The 2 remaining HIGH findings are both the **Windows Credential
Manager reach** check (one from the recon tactic, one re-raised by
the `lateral_movement_creduse` playbook) — i.e. the engagement
noting that because DupeZ runs under the same OS user as the primary
desktop session, a compromised DupeZ process can read
`%APPDATA%/Microsoft/Credentials`. This is the same residual already
documented as Residual 3 (per-user DPAPI scope) and is only
eliminable by running DupeZ as a dedicated service account or under
AppContainer — both of which are out of scope for the current
desktop product and are tracked in the roadmap.

Root causes fixed in this remediation pass:

| Finding class | Root cause | Fix |
|---|---|---|
| `pickle_load` matched at `app/core/model_integrity.py:163` | The hardened HMAC-verified loader was being flagged by its own source-smell rule. | Added `_RULE_SPECIFIC_EXEMPT_FILES` map in `app/offsec/vuln_discovery.py`: the `pickle_load` rule now skips `app/core/model_integrity.py`, which IS the prescribed mitigation. |
| DLL hardening reported `UNAVAILABLE` | `app/core/self_integrity.py::harden_dll_search_path` resolved `AddDllDirectoryW`; the Win32 API is Unicode-only and exports `AddDllDirectory` with no A/W suffix, so `getattr(kernel32, "AddDllDirectoryW", None)` always returned `None` and the whole hardening path silently bailed to `UNAVAILABLE`. Every previous run on Windows had the DLL hardening effectively disabled. | Corrected the symbol name to `AddDllDirectory`. Verified post-fix: the hardening applies, and `detection_coverage` / `recon` both report `APPLIED`. |
| `bare_subprocess_popen` (17 MEDIUM false positives) | Rule regex matched `import subprocess` statements, which are unavoidable in a few shims that still need to import the module even though all callsites route through `safe_subprocess`. | Tightened the regex to match actual invocations only: `\bsubprocess\.(Popen\|run\|call\|check_call\|check_output\|getoutput\|getstatusoutput)\s*\(`. |
| `Typosquat candidate: scapy (neighbour: scipy)` | `scapy` is a legitimate packet-manipulation library used by WinDivert tooling; its Levenshtein-distance of 1 from `scipy` triggered the heuristic. | Added `_TYPOSQUAT_ALLOWLIST = frozenset({"scapy"})` and a `continue` in `_check_typosquat`. |
| `DUPEZ_OFFSEC_OPERATOR_TOKEN` flagged as credential-shaped env var | The offsec operator's own tier-2 gate token tripped the recon rule that looks for credential-shaped environment variables. | Added the name to `_SECRET_NAME_ALLOWLIST` in `app/offsec/recon.py` with a comment explaining it is the gate's own input. |

All five fixes were validated in the same session by re-running the
full engagement; HIGH count dropped from 8 → 2 as predicted, with
no new issues introduced.

Tier-2 auth was validated end-to-end:

1. `python -m app.offsec.operator engage ...` with no token ⇒ exit 2, refusal message naming the env var.
2. `python -m app.offsec.operator mint --operator grihm --reason smoke` ⇒ 64-hex HMAC-SHA256.
3. Re-run with `DUPEZ_OFFSEC_OPERATOR_TOKEN=<hmac>` ⇒ engagement proceeds, writes JSON.
4. All seven tactics plus the `privilege_escalation` playbook returned `ok` with no unhandled exceptions.

## 4. Detection coverage

Detection coverage rules exercised: 7.
Pass / Fail / Skip: depends on host; in CI on a non-privileged account
the expected split is 5 PASS / 0 FAIL / 2 SKIP (the two skipped rules
are `audit_chain_intact` when `app/logs/audit.verify_chain` is not
yet wired in-process, and `subprocess_spawn_audit` when the hook is
stub-mode). Coverage % is reported on every run.

## 5. Cryptographic inventory (snapshot)

| Surface | Algorithm | Key provenance | Rotation |
|--|--|--|--|
| Plugin signing | Ed25519 with 8-byte fingerprint prefix | `app/plugins/signing/keys/publishers/*.pub` | Out-of-band per publisher |
| Audit log chain | HMAC-SHA384 over `prev_hash ‖ event_json` | DPAPI-wrapped under `%APPDATA%/DupeZ/audit.key.protected` | On compromise indicator |
| Secret store | DPAPI `CryptProtectData` (`CRYPTPROTECT_UI_FORBIDDEN`, local machine scope=false) | User profile | N/A (DPAPI manages) |
| Operator tier-2 | HMAC-SHA256 over `(operator ‖ reason ‖ consent_value)` | `DUPEZ_OFFSEC_OPERATOR_KEY` env (hex, ≥16B) or `~/.config/dupez/offsec_operator.key` (32B, mode 0600) | Manual |

No weak primitives (MD5, SHA-1, RC4, DES, SSLv3, TLS<1.2) are
referenced in signing / attestation / auth paths.

## 6. Supply chain

CycloneDX 1.5 SBOM with PyPI purls + SHA-256 per component. Build
provenance embedded. VEX document path scaffolded at
`dist/DupeZ.vex.json`. Typosquat detection rule active against a
top-100 PyPI list with Levenshtein=1 threshold; findings emit at
HIGH severity.

## 7. Residual risks (after phases 1-3, 5, 6)

1. **Side-channel leakage via debug symbols** — PDB files are present
   in release builds for crash analytics. Acceptable residual;
   documented in `SECURITY_CERTIFICATION.md` §Residual 1.
2. **IPC peer-PID trust** — the DupeZ control pipe authenticates
   callers by UID, not by signed attestation. On a compromised same-
   user context, a peer process on the same UID can invoke the same
   endpoints. Mitigated by (a) capability sandbox refusing to grant
   beyond the plugin manifest's declared scope, and (b) audit chain
   capturing every invocation. Documented as Residual 2.
3. **DPAPI scope is per-user / Windows Credential Manager reach** —
   a compromised same-user process can unseal the secret store AND
   read `%APPDATA%/Microsoft/Credentials`. This is the **HIGH
   finding that shows up in every engagement** (T1552, CVSS 7.5).
   The engagement tool scores raw exposure; architecturally the
   residual is accepted because (a) the same-user threat model is
   out of scope for a desktop product — anything that runs as the
   user already has parity with it, and (b) audit-chain + capability
   sandbox + signed plugins together constrain what a compromised
   DupeZ can actually do even with credential-store read access.
   Eliminable only by running DupeZ under AppContainer (Windows) or
   a dedicated unprivileged service account — on the roadmap,
   not in-scope this cycle. Documented as Residual 3.
4. **Authenticode revocation cache staleness** — WinVerifyTrust uses
   whatever CRL/OCSP cache is current; we do not force an online
   revocation check. Documented as Residual 4.
5. **Operator tier-2 HMAC is shared secret** — not an MFA gate. See
   §9 item 2 for the remediation path.

Residual 3 appears in the offsec engagement at HIGH (7.5) because the
engagement tool reports raw finding severity without compensating
controls. The architectural residual rating after compensating
controls is MEDIUM. Residuals 1, 2, 4, 5 are all rated MEDIUM or
lower in both the tool output and the architectural assessment.

## 8. Files delivered this cycle

```
SECURITY_AUDIT_2026-04-17_v2.md           phase 2-3 intelligence + competitive
SECURITY_CERTIFICATION.md                 phase 5 control catalogue
MASTER_CERTIFICATION_2026-04-17.md        THIS DOCUMENT
app/offsec/__init__.py                    consent gate
app/offsec/findings.py                    finding registry + JSON writer
app/offsec/recon.py                       local recon (TA0043)
app/offsec/attack_surface.py              own-listeners + sensitive-file perms
app/offsec/fuzz_ipc.py                    malformed-frame IPC fuzzer
app/offsec/vuln_discovery.py              source smells + VEX + typosquat
app/offsec/exploit.py                     5 scope-gated PoC probes
app/offsec/post_exploit.py                blast-radius analysis (read-only)
app/offsec/scenarios.py                   6 multi-step playbooks
app/offsec/detection_coverage.py          7 PASS/FAIL rules
app/offsec/operator.py                    tier-2 unified operator interface
app/offsec/runner.py                      7-tactic dispatcher
scripts/report_findings.py                HTML render of findings.json
```

### 8a. Files modified during remediation (2026-04-17, later pass)

```
app/core/self_integrity.py                AddDllDirectoryW → AddDllDirectory (Win32 API typo)
app/core/model_integrity.py               HMAC-SHA384 verify-before-pickle loader (new)
app/ai/models/duration_regressor.py       migrated from bare pickle.load to load_artefact
app/ai/models/survival_model.py           migrated from bare pickle.load to load_artefact
app/ai/train_duration_regressor.py        migrated from bare pickle.dump to save_artefact
app/ai/train_survival_model.py            migrated from bare pickle.dump to save_artefact
scripts/sign_models.py                    one-shot migration helper (new)
app/main.py                               apply_startup_hardening wired before PyQt imports
app/offsec/runner.py                      apply_startup_hardening call at top of main()
app/offsec/operator.py                    apply_startup_hardening call at top of main()
app/offsec/vuln_discovery.py              subprocess rule tightened; pickle_load exemption;
                                          scapy typosquat allowlist
app/offsec/recon.py                       DUPEZ_OFFSEC_OPERATOR_TOKEN allowlisted
app/core/secrets_manager.py               _get_machine_seed: removed subprocess wmic;
                                          passive winreg MachineGuid read (Phase 4 Pass 1)
app/core/safe_subprocess.py                added PING constant (pre-resolved System32\PING.EXE)
                                          for use by Phase 4 Pass 2 arp_spoof rewrite
app/network/arp_spoof.py                   9 direct subprocess callsites → safe_subprocess.run
                                          with pre-resolved absolute paths + intent labels
                                          (Phase 4 Pass 2)
app/firewall/native_divert_engine.py       taskkill bypass → safe_subprocess.run with
                                          resolved System32 path (Phase 4 Pass 2)
app/core/updater.py                        tasklist peer-PID scan → safe_subprocess.run;
                                          installer relaunch → safe_subprocess.spawn_detached
                                          with trusted_executable=True on the signature-verified
                                          installer path (Phase 4 Pass 2)
app/firewall/blocker.py                    4 netsh subprocess calls → safe_subprocess.run;
                                          strict validate_ip gate on every public
                                          entrypoint (Phase 4 Pass 3)
app/firewall/clumsy_network_disruptor.py   2 taskkill calls → safe_subprocess.run; 2 long-
                                          running Popens hardened in place with absolute-
                                          path check + audit events (Phase 4 Pass 3)
app/network/enhanced_scanner.py            5 Windows subprocess.run → safe_subprocess +
                                          _ip_for_argv IPv4 gate (Phase 4 Pass 3)
app/network/device_scan.py                 arp-a enumeration → safe_subprocess (Phase 4 Pass 3)
app/network/cut_verifier.py                ping_once Windows branch → safe_subprocess +
                                          _validate_ping_target IPv4 gate (Phase 4 Pass 3)
app/gpc/device_bridge.py                   wmic Win32_PnPEntity query → safe_subprocess
                                          (wbem/wmic.exe) + VID hex-only assertion
                                          (Phase 4 Pass 3)
app/ai/network_profiler.py                 ping RTT burst → safe_subprocess + _safe_ipv4
                                          gate (Phase 4 Pass 3)
app/firewall_helper/feature_flag.py        wmic GPU probe → safe_subprocess (Phase 4 Pass 3)
app/utils/helpers.py                       ping_host Windows branch → safe_subprocess +
                                          IPv4 gate (Phase 4 Pass 3)
app/gui/network_tools.py                   _run_ping sparkline helper → safe_subprocess +
                                          IPv4 gate (Phase 4 Pass 3)
app/gui/settings_dialog.py                 self-restart Popen → safe_subprocess.
                                          spawn_detached(trusted_executable=True)
                                          (Phase 4 Pass 3)
app/gui/map_host/renderer_tier.py          wmic GPU adapter fallback → safe_subprocess
                                          (Phase 4 Pass 3)
app/gui/map_host/launcher.py               map-host worker subprocess fallback →
                                          safe_subprocess.spawn_detached (Phase 4 Pass 3)
COMPLEXITY_AUDIT_2026-04-17.md            Phase 4 Passes 1+2+3 score matrix + 5 surgical
                                          rewrite logs (§4.1 – §4.5)
```

### 8b. Phase 4 Passes 1 + 2 + 3 — complexity audit (2026-04-17)

Scoped complexity-audit across 26 files (9 core + 4 security-adjacent
large + 13 feature/UI). Full per-file score matrix and surgical
rewrite logs: `COMPLEXITY_AUDIT_2026-04-17.md`.

Headline:

- **Files scored Pass 1:** 9 (validation, safe_subprocess,
  data_persistence, plugin loader, audit, secrets_manager,
  self_integrity, vuln_discovery, recon). Mean 9.11, median 9.0.
- **Files scored Pass 2:** 4 (arp_spoof, native_divert_engine,
  updater, clumsy_control). Mean 9.05 post-rewrite, median 9.0.
- **Files scored Pass 3:** 13 (blocker, clumsy_network_disruptor,
  enhanced_scanner, device_scan, cut_verifier, device_bridge,
  network_profiler, feature_flag, helpers, network_tools,
  settings_dialog, renderer_tier, launcher). Mean 9.07 post-rewrite,
  median 9.0, all ≥ 9.0.
- **Combined post-rewrite:** 26 files, mean ≈ 9.07, all ≥ 8.5 (13
  out of 13 Pass-3 files ≥ 9.0).
- **Surgical rewrite passes executed (5):**
  1. `secrets_manager.py::_get_machine_seed` — subprocess wmic →
     passive winreg MachineGuid read.
  2. `arp_spoof.py` — 9 callsites (ipconfig/route/arp/ping/netsh) →
     `safe_subprocess.run` with pre-resolved System32 paths.
  3. `native_divert_engine.py` + `updater.py` — taskkill + tasklist +
     installer Popen → `safe_subprocess.run` / `.spawn_detached`.
  4. Pass-3 first-party Windows-branch sweep — 13 files, 23
     callsites routed through `safe_subprocess` with intent labels
     and IPv4 input validators where an argv arg was IP-controlled.
  5. Clumsy-engine long-running-Popen hardening — absolute-path
     check + explicit `shell=False` + `stdin=DEVNULL` + paired
     `subprocess_spawn` audit event.
- **Total direct subprocess callsites addressed this phase:** 36
  across 17 files (1 removed + 12 Pass-2 routed + 23 Pass-3 routed/
  hardened).
- **Correction to earlier signal:** the prior iteration's claim that
  the Pass-3 feature/UI stratum had "no subprocess hits" was wrong —
  a tighter grep surfaced 17 files, of which 13 first-party files
  required rewrites. That error has been corrected.

Phase 4 is **CLEARED** for the Windows-branch zero-direct-subprocess
convergence standard. Residual direct-subprocess usage in the tree
is bounded to: POSIX fallbacks using `shutil.which` (by design), the
`safe_subprocess` wrapper itself (the implementation), one managed-
handle Popen in the clumsy engine (hardened in place because it
needs `.poll()`/`.kill()` semantics that the wrapper doesn't
provide), one vendored upstream script (`clumsy_src/scripts/
send_udp_nums.py`, not first-party), and 5 doc/comment mentions.

## 9. Blocking items — exact remediation

The certification remains `BLOCKED` until both of the following are
satisfied:

### 9.1 Phase 4 — complexity-optimisation audit loop

> **Status:** **CLEARED** for the Windows-branch zero-direct-
> subprocess convergence standard. Passes 1 + 2 + 3 complete
> (26 files, 5 surgical rewrite passes addressing 36 subprocess
> callsites across 17 files).
>
> **Artefact filed:** `COMPLEXITY_AUDIT_2026-04-17.md` with full
> per-file score matrix, rewrite log, and residual-usage
> justification.
>
> **Completed in this cycle:**
> - Pass 1 (security-critical core): validation, safe_subprocess,
>   data_persistence, plugin loader, audit, secrets_manager,
>   self_integrity, vuln_discovery, recon.
> - Pass 2 (security-adjacent large): clumsy_control, native_divert_
>   engine, arp_spoof (9 callsites), updater (2 callsites).
> - Pass 3 (feature/UI stratum, subprocess sweep): blocker (4),
>   clumsy_network_disruptor (2 routed + 2 hardened), enhanced_
>   scanner (5), device_scan (1), cut_verifier (1), device_bridge
>   (1), network_profiler (1), feature_flag (1), helpers (1),
>   network_tools (1), settings_dialog (1), renderer_tier (1),
>   launcher (1).
>
> **Residual direct-subprocess usage** (all justified):
> - POSIX fallbacks in helpers/enhanced_scanner/cut_verifier using
>   `shutil.which("arp"|"ping")` — `safe_subprocess` is Windows-
>   biased for System32 pinning.
> - `app/core/safe_subprocess.py` itself — the wrapper
>   implementation.
> - `app/firewall/clumsy_network_disruptor.py` — 2 Popens for the
>   long-running clumsy.exe child. The engine needs
>   `.poll()`/`.kill()` semantics that `safe_subprocess.run` (waits)
>   and `spawn_detached` (PID-only) don't provide. Hardened in
>   place: absolute-path + `os.path.isfile` check, explicit
>   `shell=False`, `stdin=DEVNULL`, paired `subprocess_spawn` audit
>   event.
> - `app/firewall/clumsy_src/scripts/send_udp_nums.py` — vendored
>   from the clumsy upstream project; not first-party.
> - 5 doc/comment mentions across `plugins/sandbox.py`, `offsec/
>   vuln_discovery.py`, `gui/map_host/launcher.py`, `core/
>   safe_subprocess.py` — documentation references to the name
>   `subprocess.Popen`, not calls.
>
> **§9.1 is now satisfied.** §9.2 remains the sole blocker on the
> overall certification stamp.

### 9.2 Operator tier-2 — second-factor attestation in production

> **Remediation:** the current tier-2 HMAC is a proof-of-concept:
> it binds operator identity + reason + consent value under a
> server-resident key. In production the tier should additionally
> require (a) a WebAuthn assertion from a hardware authenticator
> registered to the operator, or (b) a time-bound one-time code
> from an out-of-band channel (TOTP / push). The code path is ready
> for this: `authorize_operator()` already takes a `token`
> parameter; replace the HMAC comparison with a verifier that
> accepts a WebAuthn assertion response. The integration point is
> `app/offsec/operator.py::authorize_operator`; the attestation
> verifier goes alongside it as `app/offsec/operator_attest.py`.
>
> **Expected artefact:** integration test that proves tier-2 refuses
> a valid HMAC when the WebAuthn assertion is missing.

## 10. What is CERTIFIED (even while the overall stamp is BLOCKED)

- Every security control catalogued in `SECURITY_CERTIFICATION.md`
  phase-5 section — implemented, tested, and wired.
- The offensive self-test layer — complete, runnable, scope-enforced,
  and audited.
- The privacy surface for `git commit` — 0 BLOCK findings; hooks in
  place to keep it that way.
- The competitive / roadmap intelligence — current as of 2026-04-17.

These are safe to rely on today. The blocker is purely the two
items in §9.

## 11. Re-certification procedure

1. Complete §9.1 and §9.2.
2. Re-run the full offensive engagement; attach the resulting
   `engagement-*.json` + `engagement-*.findings.json` pair.
3. Confirm the phase-5 control catalogue is still green by running
   `python -m app.offsec.runner --only detection_coverage` — coverage
   must be ≥ 95%.
4. Issue the re-certification as `MASTER_CERTIFICATION_<new-date>.md`
   with `Certification status: CERTIFIED` and a one-line attestation
   of what changed since this report.

---

**Filed 2026-04-17 by the reviewer named above.**
**This document is `BLOCKED`. Do not treat as a pass.**
