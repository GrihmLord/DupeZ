# ADR-0003 — v5.7.6 Maximum-Security Tier 1 Hardening

**Status:** Accepted
**Date:** 2026-05-27
**Owners:** Grihm
**Supersedes:** none
**Related:** ADR-0001 (split-elevation), ADR-0002 (key architectural decisions)

## Context

v5.7.5 closed the actionable findings of the WiFi-disrupt audit and shipped a defense-in-depth IP/MAC scrubber at the formatter layer. Across the wider security surface, six properties were already at "Strong":

| Property                            | Status (entering v5.7.6) | Mechanism |
|-------------------------------------|--------------------------|-----------|
| Update channel integrity            | Strong | Ed25519 signed manifest, pinned pubkey, fail-closed |
| Plugin trust                        | Strong | Signed bundles + capability sandbox + first-install consent |
| Crypto primitives                   | Strong | CNSA 2.0, AES-256-GCM, HMAC-SHA384, PBKDF2-SHA-512 600k |
| Audit integrity                     | Strong | Hash-chained JSONL under per-install HMAC key |
| PatchMonitor settings integrity     | Strong | HMAC sidecar, binary-mode write |
| Network egress                      | Strong | TLS 1.3, cert verify always on, URL scheme allowlist |

A post-v5.7.5 review identified **seven residual gaps** where a specific attacker model still won under v5.7.5, even with every other layer behaving as designed. v5.7.6 closes the five highest-ROI of those, plus three smaller tier-1.5 wins that piggy-back on the same release. The remaining four items need design work and are deferred to v5.8.x.

## Decisions

### Decision 1 — Add a monotonic version ledger to the auto-updater

**Gap:** Ed25519 signature verifies authenticity but not freshness. An attacker who can replay a valid-but-older signed manifest (a compromised CDN, a one-time signing-key compromise on a withdrawn release, a malicious mirror, a leaked pre-release) can force every client to "update" backwards into a vulnerable version. The pinned-pubkey check passes; the new install runs.

**Decision:** Introduce `app/core/update_state.py`, a small HMAC-protected ledger persisted at `app/data/update_state.json{,.hmac}` under the existing per-install `persistence.hmac` secret. Every successful `verify_manifest` call raises the floor. Any subsequent manifest whose semver is strictly older than the floor is refused with `DowngradeRefusedError`, even with a valid signature. Strict semver compare; pre-release / build metadata ignored so a re-signed-same-version manifest still compares equal.

**Rejected alternatives:**

* **Embed `not_before` timestamp in every manifest.** Solves freshness for *future* attacks but doesn't help an attacker replaying a manifest from before the clock was added; also burdens every release with another consistent field to sign.
* **TUF (The Update Framework).** Right answer for OS-scale fleets. Wrong answer for DupeZ's deploy surface — orders of magnitude more code and operational complexity than the threat justifies.
* **Server-side latest-version pinning only.** Doesn't help a client whose first call to the server is intercepted (initial install, post-reinstall). Client-side floor is the right primary.

**Trade-off:** A user who legitimately wants to roll back (rare — DupeZ has no LTS branches today) must edit `update_state.json` and re-sign the sidecar with their own HMAC key. We consider this acceptable: rollback is not a normal workflow, and the rare case can be operator-driven.

### Decision 2 — HMAC sidecar on `settings.json`

**Gap:** A local-file attacker (or backup-restore tool, or operator error) editing `settings.json` directly is silently accepted today. `"kill_switch": false` in a tampered file is loaded without complaint. PatchMonitor and `data_persistence.py` already do this right; settings was the exception.

**Decision:** `app/config/__init__.py` now writes `settings.json` + `settings.json.hmac` atomically (binary mode, tmp + fsync + os.replace) under the persistence HMAC key. On load: tag verify → accept; tag mismatch → quarantine the file as `settings.json.tampered.<ts>` and return `{}`. First-run migration (file exists, no sidecar) is one-shot accept-and-sign so v5.7.5 → v5.7.6 upgrades don't brick the operator's config.

**Rejected alternatives:**

* **Encrypt-at-rest with AES-GCM.** Confidentiality isn't the property we need — settings aren't secret. Integrity is. HMAC is the right primitive.
* **Sign with the same Ed25519 update key.** Asymmetric overkill; we have a symmetric key on the install already.

### Decision 3 — Audit log fails closed on tamper

**Gap:** Pre-v5.7.6, a broken hash chain logged ERROR and silently rotated aside. Silent recovery on the audit substrate (the record of truth) is the wrong default — if integrity is questionable, refusing to write is safer than continuing.

**Decision:** On any chain-break or corrupt-terminal signal, `AuditLogger._seal()` writes an `audit.TAMPERED` sentinel and refuses every subsequent `log()` call (one stderr warning per process, then silent drops). Sentinel persists across process restarts. Operator clears via `dupez --reset-audit`, which archives every `audit*.{jsonl,tampered.*}` to `audit-quarantine-<ts>/`, clears the sentinel, and writes a fresh `audit_chain_reset_by_operator` genesis event.

**Rejected alternatives:**

* **Refuse to boot when sealed.** Too brittle — a transient chain break (disk full mid-write) shouldn't lock the operator out of the app, only out of audit writes.
* **Auto-reset after N minutes.** Defeats the purpose. The whole point of the seal is the operator has to look.

### Decision 4 — Subprocess hardening (`SW_HIDE`, `close_fds=True`)

**Gap:** v5.7.5 already enforced `shell=False`, absolute-path executables, `CREATE_NO_WINDOW`, and per-spawn audit. Two residual issues: `spawn_detached` opted out of `close_fds` on Windows (a Python 3.6-era ternary that no longer applies on modern Python and was leaking parent handles into detached children), and neither path passed a `STARTUPINFO` with `SW_HIDE` — so a child process briefly flashing a window was possible even with `CREATE_NO_WINDOW`.

**Decision:** Both fixes mechanical. `subprocess.run` and `subprocess.Popen` now receive an explicit `close_fds=True` on every platform plus a Windows-only `STARTUPINFO` with `STARTF_USESHOWWINDOW | SW_HIDE`. Belt on top of the existing suspenders.

**Rejected alternatives:**

* **Migrate every direct `subprocess.*` call site to `safe_subprocess.run`.** Right answer eventually; out of scope for v5.7.6. The 16 direct-call sites identified during the survey are tracked for a v5.7.7 cleanup pass.

### Decision 5 — Webhook host allowlist

**Gap:** v5.7.3's scheme check kept `file://`/`ftp://` out, but allowed `https://attacker.example.com/x`. A hijacked-config or imported-bundle path could exfil cut/killswitch metadata to an attacker server. PII is already scrubbed but the metadata itself (frequency, timing) is operator-behavior signal.

**Decision:** `_validate_webhook_url` now requires the host to match (a) the default Discord canonical hosts, (b) an operator-extended entry in `app/config/audit_webhook_hosts.json` (HMAC-sidecar protected via Decision 2), or (c) be a loopback address. Off-allowlist hosts raise `WebhookURLError` at sink construction time. Tests use `DUPEZ_TEST_WEBHOOK_HOSTS` env var to add `example.invalid` etc. without touching production policy.

**Rejected alternatives:**

* **Allowlist via UI dialog at sink-add time.** Right answer for non-technical users but doesn't gate the programmatic path (config import, plugin-set sinks).
* **Allowlist by certificate fingerprint of the receiving server.** TLS pinning at the webhook layer is good but is overkill for the "block exfil to attacker.example.com" goal — host allowlist is the right blast radius.

### Decision 6 — `dupez --verify-self`

**Gap:** Ed25519 protects update *delivery*. Once `dupez.exe` is on disk, nothing checks whether it's the same binary the release engineer signed. A modded build can claim to be DupeZ; a malware-replaced exe is invisible.

**Decision:** Each frozen build ships a sidecar `dupez.exe.sig`: 72-byte envelope identical to the update manifest sig (8-byte fingerprint + 64-byte Ed25519 over SHA-256 of the exe). `--verify-self` reads the running exe, hashes, verifies. Returns exit 0 on match, 3 on tamper, 2 on operational failure. Dev/source-tree runs return ok=True with `skipped` so the dev workflow doesn't trip.

**Status:** Verify path implemented and tested. Sign-on-build wiring tracked for the next signing pipeline pass — until the sign step ships, `--verify-self` will report `missing-sidecar` on frozen builds (intentional: telling the operator the binary lacks a sidecar is itself useful).

### Decision 7 — `dupez --reset-audit`

Operator escape hatch for Decision 3. No architectural decision beyond "it's a CLI flag." Implementation: dispatched before elevation/GUI bootstrap so it works from any shell.

### Decision 8 — Cert-pinning infrastructure, audit-only in v5.7.6

**Gap:** The updater's GitHub HTTPS calls trust the Windows cert store. A compromised Windows CA (corporate MITM proxy, malware-installed root, state-actor sub-CA) can present a forged cert for github.com and TLS won't notice.

**Decision:** Ship `app/core/cert_pinning.py` with the full SPKI-pin enforcement path *and* an empty `PINS` map. Empty-set behavior is audit-only: every chain observed on an update call emits a `cert_chain_observed` audit event with the SPKI hashes seen. Release engineer populates `PINS` in v5.7.7 with values captured from production rather than guessed.

**Rejected alternative:**

* **Ship known-good pins from documentation.** Wrong values brick the updater for every user. CA chains do rotate, sometimes faster than DupeZ release cadence; we want to base the pin set on observed reality, not on a paper analysis. The cost of waiting one release is small; the cost of bricking the auto-updater is large.

`DUPEZ_DISABLE_CERT_PIN=1` is the explicit, audit-loud bypass for the operator recovery path when a CA rotation breaks the pin set in the future.

## Items deferred to v5.8.x

These are real gaps but need design proposals, not mechanical hardening. v5.8.x will have its own ADR:

### Deferred 1 — Real Windows AppContainer / Job Object for plugins

Today the plugin sandbox is declarative: the loader checks the manifest's claimed capabilities but the OS doesn't enforce them. v5.8.x: spawn plugins inside a Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` + `BREAKAWAY_OK = FALSE` + AppContainer SID restricting filesystem to the plugin sandbox dir. Plugin tries to touch `C:\Windows` → OS denies, not just the loader. Needs prototype work to understand WinDivert + plugin interaction under AppContainer.

### Deferred 2 — DPAPI scope audit

README claims "machine-bound KEK." Verify every secret hits DPAPI's `CryptProtectData` with `CRYPTPROTECT_LOCAL_MACHINE = 0` (per-user scope) rather than the wider machine scope. ~6 call sites in `secrets_manager.py`; needs a test guard that fails if any call site drifts.

### Deferred 3 — Memory-safe secret handling

Python's GC doesn't zero buffers. Anywhere a key, token, or password lives as `str`, switch to `cryptography.hazmat.primitives.secret.SecretBytes` (zeros on `__del__`). Limited blast radius (~6 sites) but reduces post-crash memory-dump exposure.

### Deferred 4 — WER opt-out for the elevated helper

Crash dumps from the elevated helper process can contain secrets. `WerAddExcludedApplication("dupez_helper.exe")` at install time. Trade-off: harder for us to diagnose helper crashes. Needs telemetry on helper crash rates first; not worth the diagnostic loss if helper crashes are common.

## Things intentionally NOT added

These were considered and rejected for v5.7.6 (and likely for v5.8.x too):

* **Anti-debugging tricks** (`IsDebuggerPresent`, timing checks). Legitimate users get hurt; real attackers strip them in five minutes.
* **Code obfuscation / packing.** Same problem, plus it triggers AV false positives that hurt distribution.
* **Anti-VM detection.** Customers run on VMs.
* **Custom crypto rolls.** CNSA 2.0 is the bar. Don't invent.
* **Network telemetry to "detect" tampering.** Violates ADR-0002 §4 (local-only telemetry). The point of DupeZ is no phone-home.

## Test posture

`tests/test_security_v576.py` adds seven test classes (one per item + helpers) with 23 test cases total. The cert-pinning tests run without network access by stubbing `chain_spki_hashes`. The downgrade-replay and settings-HMAC tests monkeypatch the data directory to a `tmp_path` so they don't touch the operator's real state. The audit-seal tests build a small `AuditLogger` instance in a temp directory and exercise the full seal → drop-writes → reset flow.

`tests/conftest.py` sets `DUPEZ_TEST_WEBHOOK_HOSTS` at session start so existing `test_audit_webhook.py` tests continue to pass without modification.

## Lockstep version bump

`app/__version__.py`, `packaging/version_info.py`, `packaging/dupez.manifest`, `packaging/dupez_compat.manifest`, `packaging/installer.iss`, `packaging/build.bat`, `packaging/build_variants.bat`, `README.md`, `CHANGELOG.md`.
