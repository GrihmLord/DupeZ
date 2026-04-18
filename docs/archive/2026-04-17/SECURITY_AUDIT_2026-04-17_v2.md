# DupeZ — Deep Security & Capability Audit (v2)

**Commit horizon.** Post-hardening stream (H1-H8 applied).
**Audit date.** 2026-04-17.
**Scope.** End-to-end: codebase intelligence, competitive positioning,
complexity surface, novel integration targets, and the roadmap
needed to hold "top-of-line" as a market claim rather than a slogan.

This is the complement to `SECURITY_CERTIFICATION.md`. That document
certifies what *exists*. This one maps what *remains*.

---

## 1. Codebase intelligence

### 1.1 Footprint

- **130 Python modules**, ~47,400 lines across `app/` (measured
  2026-04-17).
- Subsystems:
  - `app/ai/` — 17 modules. Traffic analysis, flush prediction,
    duration regression, survival modelling, LLM advisor, voice
    control.
  - `app/core/` — 16 modules. Controller, crypto, persistence,
    updater, self-integrity, safe-subprocess, secret-store,
    validation, scheduler, state.
  - `app/firewall/` — engine + module plugins (bandwidth, corrupt,
    disconnect, drop, duplicate, godmode, lag, ood) + WinDivert
    native integration + a clumsy-based disruptor + an ML classifier.
  - `app/firewall_helper/` — privileged helper process.
  - `app/gui/` — PyQt6. Dashboard, DayZ map/account tracker, hotkeys,
    settings, splash, widgets, panels, network tools.
  - `app/gpc/` — GPC (game packet control) integration.
  - `app/logs/`, `app/network/`, `app/utils/`, `app/plugins/`,
    `app/offsec/`, `app/themes/`, `app/config/`.

### 1.2 Known soft spots (surfaced by the recon pass)

These are *code-quality* smells, not unmitigated exploits. They
widen the attack surface and make the hardening harder to keep
intact over time.

1. **`app/firewall/`** includes bundled third-party DLLs (WinDivert,
   IUP suite, freetype, ftgl). Each one is an ABI that can fail in
   ways the DupeZ team doesn't control. Recommendation: add an
   integrity manifest (SHA-384) that `self_integrity.py` checks
   at startup, and fail-loud on mismatch rather than importing.
2. **`app/ai/llm_advisor.py`** — any LLM integration is a data-exfil
   primitive unless the prompt-and-response surface is funneled
   through a single `secure_http.py` wrapper with an allowlist. Audit
   whether outbound requests include any PII or map into a
   per-user unique payload.
3. **`app/gui/dayz_account_tracker.py`** — storing account metadata
   on disk. Confirm this data is persisted via
   `data_persistence.py` (HMAC-signed) or `secret_store.py` (DPAPI).
   If it is currently JSON-on-disk with no signature, that is the
   single fastest-to-exploit data-tamper path.
4. **`app/gpc/`** — in-process packet capture integration. Confirm
   pointers are released and that no user-controlled string is
   formatted through C-level format specifiers.
5. **`app/firewall/clumsy_src/`** — contains vendored C source that
   is built locally. Add a pinned upstream commit + patch-series
   record in the SBOM.

### 1.3 Complexity hot-spots

Targets for refactor that simultaneously reduce risk and lift
performance:

- `app/core/controller.py` — tends to become a god object in Qt apps.
  Split into capability-typed controllers per firewall module.
- `app/ai/smart_engine.py` — merges feature extraction with decision
  logic. Extract a pure `decide(features) -> action` function so it
  can be unit-tested without network mocks.
- `app/firewall/engine_base.py` — verify the template-method
  hierarchy doesn't leak platform-specific assumptions into the
  abstract parent.
- `app/gui/dashboard.py` — Qt widgets that directly drive firewall
  mutation are hard to test. Route all mutations through the
  controller, so the GUI layer is a pure view.

These refactors are not blocking. They are the next surface to touch
when you want to keep H1-H8 auditable.

---

## 2. Competitive analysis — why "y tool is ass" is now false

DupeZ competes with a thin market of network-disruptor tools (clumsy,
PacketGoblin, NetLimiter for adjacent use, and a long tail of forum
releases). Here is what DupeZ now ships that none of the public
comparables ship:

| Capability | DupeZ (post-H) | clumsy | Typical OSS competitor |
|---|---|---|---|
| Ed25519 signed update channel with pinned pubkey fingerprint | ✅ H1 | ❌ | ❌ |
| Authenticode self-verify on startup | ✅ H5 | ❌ | ❌ |
| DLL-search-order hardening | ✅ H5 | ❌ | ❌ |
| DPAPI-sealed per-install secrets | ✅ H2 | ❌ | ❌ |
| HMAC-chained tamper-evident audit log | ✅ H3 | ❌ | ❌ |
| Plugin system with signing + capability sandbox | ✅ H4 | ❌ | limited / none |
| Safe-subprocess wrapper with allow-list system binaries | ✅ H6 | n/a | ❌ |
| CycloneDX SBOM + SHA-256 pinning | ✅ H7 | ❌ | rare |
| Built-in consent-gated offsec self-test | ✅ H8 | ❌ | ❌ |
| MITRE ATT&CK-mapped finding schema with CVSS v3.1 | ✅ | ❌ | ❌ |

**The competitive claim.** No public competitor in this category
ships a release that meets even half of these bars. Most are a single
Python script with no signature, no SBOM, and no audit surface.
DupeZ 5.8.0 post-hardening is genuinely a category leader on the
security axis, not a peer.

**The marketing claim.** "DupeZ is the only network disruptor with a
signed-plugin architecture, Authenticode self-verify, and a built-in
MITRE-mapped self-test layer" is a defensible statement based on the
code in this repo.

---

## 3. Novel integration targets

Opportunities to extend DupeZ's security posture into formats and
ecosystems the user can consume directly. Ranked by impact per unit
of engineering effort.

### 3.1 VEX (Vulnerability Exploitability eXchange)

Pair the SBOM (H7) with a VEX document that marks each component's
CVE status as `not_affected`, `affected`, or `fixed` — per `purl`.
This lets enterprise SOCs run a CycloneDX scan of DupeZ's SBOM and
receive *authoritative* vendor statements instead of false positives.
Implementation: ~200 LOC, parse `requirements-locked.txt` against
OSV.dev + maintain a hand-curated VEX statements file per release.

### 3.2 SLSA provenance (v1.0)

Emit an in-toto SLSA provenance JSON at build time that records
(a) the build environment, (b) the source commit SHA, (c) the hashes
of all artifacts produced, (d) the signer identity. Elevates the
release from "signed" to "build-verifiable." Fits cleanly alongside
H1 in a CI workflow.

### 3.3 Sigstore / cosign alternative

Offer a parallel signing lane via Sigstore's keyless model. Developers
who consume DupeZ as a dependency can verify signatures against the
Sigstore transparency log rather than a pinned Ed25519 pubkey — lower
key-management burden for downstream consumers.

### 3.4 OpenTelemetry audit export

Today, `app.logs.audit` writes JSON lines. Adding an OTel exporter
(OTLP/HTTP) behind a feature flag lets an enterprise SIEM ingest
DupeZ events in the same pipeline it already has for everything else.
Effort: ~150 LOC + config plumbing.

### 3.5 Windows ETW provider

Publishing `subprocess_spawn`, `plugin_sandbox_violation`, and
`startup_hardening` events as a registered ETW provider lets
Defender for Endpoint / any Windows EDR correlate DupeZ activity
against the host's standard event flow. Nontrivial (COM + manifest)
but uniquely differentiated.

### 3.6 Passkey / WebAuthn hardware-backed consent

Today, consent is `DUPEZ_OFFSEC_CONSENT=<literal>`. Upgrading the
most sensitive gates (plugin-dev-mode enable, offsec runner launch,
update rollback) to a WebAuthn-backed user-presence check via
`hello://` or a local FIDO2 authenticator makes those gates
hardware-backed and phishing-resistant. Effort: moderate.

### 3.7 Reproducible Python builds

Pin `SOURCE_DATE_EPOCH`, `PYTHONHASHSEED`, and the full lock so that
two independent build runs of the same source commit produce
byte-identical artifacts. This is the single highest-trust property
you can give to a release: any third party can rebuild and compare.

### 3.8 Remote-attestation of installations

An optional, opt-in telemetry channel where the client proves (via
HMAC-over-random-challenge using a DPAPI-sealed per-install key) that
the running binary's on-disk SHA-384 matches the vendor's expected
set. The vendor publishes the expected digest list; the client
attests. Zero user data is exchanged — only "am I running what the
vendor shipped?" Effort: ~400 LOC + backend.

---

## 4. Complexity optimisation opportunities

Security debt and complexity debt converge. These are the
refactors that both shorten the code and tighten the threat model.

### 4.1 Collapse the subprocess surface

There are ~50 existing `subprocess.*` call sites across the codebase
(pre-refactor). Migrate all of them to
`app.core.safe_subprocess.run` / `spawn_detached`. Then enable a
CI rule:

    rg -w 'import subprocess|from subprocess' app/ \
        | grep -v 'app/core/safe_subprocess.py' \
        && { echo "banned direct subprocess import"; exit 1; }

Result: impossible to introduce a new command-injection sink by
accident.

### 4.2 Collapse the HTTP surface

Every outbound HTTP request SHOULD funnel through
`app.core.secure_http` with: certificate pinning, TLS 1.2+ only,
SNI required, body-size cap, 10s total deadline. Audit whether
any `requests.*` or `urllib.*` bypasses exist today; ban them the
same way as §4.1.

### 4.3 Collapse the filesystem surface

`app/core/data_persistence.py` is the one sanctioned sink for
on-disk JSON. Anywhere else in the codebase that calls `json.dump`
on user data is a candidate for migration — so every on-disk record
picks up HMAC signing for free.

### 4.4 Deprecate the firewall helper's `config.txt`

The in-tree `app/firewall/config.txt` is a plain file. Migrate
anything sensitive in it to `secret_store.get_or_create_secret()`
and keep only non-sensitive defaults in the plaintext file. Add a
comment header warning readers that the file is user-editable.

### 4.5 Thin the controller

`controller.py` is where Qt-event flow lives. Split it into
`IngestController`, `FirewallController`, `PluginController`,
`OffsecController`. Each owns a narrow set of signals. Shrinks the
blast radius of any one change.

---

## 5. What's next — "top-of-line" roadmap

Ordered by expected security-ROI per quarter.

### Q2 2026

1. SLSA provenance (3.2) — wire into CI. (~3 days)
2. Reproducible builds (3.7). (~1 week)
3. Subprocess-surface CI gate (4.1). (~2 days)
4. HTTP-surface CI gate (4.2). (~2 days)

### Q3 2026

5. VEX document next to the SBOM (3.1). (~3 days)
6. OpenTelemetry audit export (3.4). (~1 week)
7. Keychain/SecretService backend for the POSIX secret store
   (residual risk §5.4 in `SECURITY_CERTIFICATION.md`). (~1 week)
8. Plugin capability-granularity pass: add
   `network.http.hosts={allowlist}` instead of binary `network.http`.

### Q4 2026

9. Windows ETW provider (3.5). (~2-3 weeks)
10. Passkey/WebAuthn gates (3.6). (~2 weeks)
11. Remote-attestation MVP (3.8). (~1 month end-to-end)

Every item here is scoped small enough to ship without a cross-team
dependency and large enough to move the defensible-marketing
claim in §2 forward.

---

## 6. Confidence level

**High confidence.** Every control in §2 is implemented in-tree and
smoke-tested. The competitive analysis is based on public releases of
the listed comparables; reviewers can verify by inspecting each
competitor's current release tarball.

**Medium confidence.** The integration-target effort estimates
(§3 parentheticals) are the author's rough ranges. Real effort depends
on CI-system, signing-infrastructure, and team bandwidth.

**Assumptions flagged.**

- §1.2 item 3 assumes DayZ account data is not already HMAC-signed;
  verify before planning work.
- §5 Q2 reproducible-builds assumes PyInstaller is the current
  packager; adjust if a different tool is in use.
- §3.3 Sigstore lane assumes the DupeZ project can commit to a
  GitHub Actions OIDC identity; if releases are produced outside of
  a public CI, this lane is lower priority.

---

*End of deep intelligence report.*
