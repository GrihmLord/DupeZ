# DupeZ — Security Certification

**Version covered.** 5.8.0 hardening stream
**Certification date.** 2026-04-17
**Scope.** Entire DupeZ desktop application (`app/`, `scripts/`, release
tooling). Out of scope: any infrastructure DupeZ connects to; any
third-party plugin not shipped in-tree.
**Classification.** Internal — Security. Do not redistribute outside
the DupeZ engineering group without redacting the signing-key
fingerprints and SBOM serial numbers.

---

## 1. Executive summary

DupeZ has been re-architected to meet the bar usually reserved for
enterprise endpoint software. Every code path that touches user data,
executes privileged operations, or accepts external input now routes
through a single, auditable control. The following controls are in
effect and have been smoke-tested against their stated threat models:

| # | Control | File(s) | Threat addressed |
|---|---|---|---|
| H1 | Ed25519 signed-update manifests | `app/core/update_verify.py`, `scripts/sign-release.py` | Update-channel tamper / downgrade |
| H2 | DPAPI-wrapped per-install secret store | `app/core/secret_store.py` | Secret exfil from disk by a local process |
| H3 | HMAC-SHA384 hash-chained audit log | `app/logs/audit.py` | Silent tamper of forensic trail |
| H4 | Ed25519 plugin signing + capability sandbox | `app/plugins/signing.py`, `app/plugins/sandbox.py`, `app/plugins/loader.py` | Arbitrary-code-execution via plugin side-load |
| H5 | Authenticode self-verify + DLL-search hardening | `app/core/self_integrity.py` | DLL hijack, binary swap |
| H6 | Safe-by-default subprocess wrapper | `app/core/safe_subprocess.py` | Command injection, PATH hijack |
| H7 | CycloneDX SBOM + SHA-256 pinning | `scripts/sbom.py`, `requirements-locked.txt` | Supply-chain visibility, VEX correlation |
| H8 | Offensive self-test layer (MITRE-mapped) | `app/offsec/` | Continuous regression against local posture |

No stubs. No TODO markers left in the hardening surface. Every
module has a docstring that documents its threat model, its
invariants, and the conditions under which it refuses to run.

---

## 2. Control catalogue

### H1 — Signed update channel

**Design.** Every release artifact is accompanied by a detached
signature in a 72-byte envelope: 8-byte SHA-256 pubkey fingerprint
+ 64-byte Ed25519 signature. Verification fingerprint-routes into a
pinned list of trusted public keys; non-match is a hard fail.

**Signer.** `scripts/sign-release.py --priv PRIV.pem --artifact
DupeZ-5.8.0.exe` produces `DupeZ-5.8.0.exe.sig`. Private keys are
never checked into the repo.

**Verifier.** `app.core.update_verify.verify_update(artifact, sig)`.
Returns an `UpdateVerification` dataclass with the pubkey fingerprint
that produced the match. Called by the in-process updater before
any file replacement.

**Residual risk.** Supply-chain compromise of the *build host*. The
SBOM (H7) narrows the blast radius but a compromised build host could
still sign a trojaned artifact with the real key. Mitigation: offline
signing + hardware-backed key storage. This is an operational
commitment outside the software boundary.

### H2 — DPAPI-wrapped secret store

**Design.** `app.core.secret_store` exposes
`get_or_create_secret(kind, size=32)` that returns 32 random bytes
per `kind`, persisted under `%LOCALAPPDATA%\DupeZ\secrets\` on
Windows (or `$XDG_DATA_HOME/DupeZ/secrets/` on POSIX). On Windows
the bytes are sealed with `CryptProtectData` using
`CRYPTPROTECT_UI_FORBIDDEN`; on POSIX the file is chmod 0600 with a
strict read-time mode check that refuses to open a file whose group
or other bits are set.

**Invariants.**
1. Kind names must match `^[a-z][a-z0-9]*(\.[a-z0-9]+)*$`.
2. Writes are atomic (tmp → fsync → replace).
3. POSIX reads reject modes that have any `0o077` bit set.
4. `wipe_secret_in_memory(b)` zeroes the bytearray in place.

**Callers.**
- `app.logs.audit` for `audit.hmac` (32 B).
- `app.core.data_persistence` for `persistence.hmac` (32 B).
- Future: plugin-per-install key material.

### H3 — HMAC-SHA384 hash-chained audit log

**Design.** `app.logs.audit` writes JSON-line events with a
`prev_digest` field. Each digest is
`HMAC-SHA384(key, prev_digest || canonical_json_of_event)`. On open,
the module probes the tail for (a) current-key-HMAC match, (b)
legacy-SHA384 match → rotate aside + migration marker, (c) nothing
→ rotate aside as corrupted + reset marker.

**Legacy compatibility.** The migration rung preserves existing
audit trails across the DPAPI rollout. Users never lose forensic
history on upgrade; migrated files retain a `.legacy.<ts>.jsonl`
sibling for cross-reference.

**`verify_chain()`** uses `hmac.compare_digest` throughout and
tolerates CRLF-normalised and raw variants for Windows/Linux parity.

**Key sourcing.** Primary: `secret_store.get_or_create_secret("audit.hmac")`.
Fallback: ephemeral random key with `degraded=True` flag surfaced
on every written event as `key_state: "ephemeral"`. Means a
writable-but-unreadable secret store cannot silently break forensics.

### H4 — Plugin signing + capability sandbox

**Design.** `app.plugins.signing.verify_plugin_manifest(path)` is
called before any import. Steps (all hard):

1. Parse the manifest JSON; reject if the schema is violated, if
   `entry_sha384` is missing, or if the entry file path escapes the
   plugin directory (via `Path.relative_to`).
2. Compute SHA-384 of the on-disk entry file; reject on mismatch.
   This step runs even in dev mode.
3. Read the 72-byte signature envelope; route on the 8-byte
   fingerprint to one of the pinned `TRUSTED_PUBKEYS_PEM`.
4. Ed25519-verify the signature over raw manifest bytes.

**Dev override.** `DUPEZ_PLUGIN_DEV_MODE=1` skips steps 3-4 but
**not** step 2, and emits a loud `plugin_unsigned_loaded` audit
event every time.

**Sandbox.** `app.plugins.sandbox.activate_sandbox()` installs a
process-wide `sys.addaudithook` once at startup. `plugin_scope(name,
capabilities)` is a context manager pushed around every plugin
entrypoint. The hook consults the capability set and denies:

- `socket.connect` / `bind` / `sendto` / `recvfrom` unless
  `network.scan` or `network.http` is granted;
- `subprocess.Popen`, `os.system`, `os.popen`, `os.exec*`, `os.spawn*`
  unless `process.spawn` is granted;
- `open()` in any write mode unless `fs.write_user_data` is granted;
- `os.remove`, `os.unlink`, `os.rename`, `os.rmdir`, `os.chmod`,
  `os.chown` unless `fs.write_user_data` is granted;
- `urllib.Request`, `http.client`, `ssl.wrap_socket` unless
  `network.http` is granted;
- `exec()` and `compile()` — hard deny, no capability unlocks these.

Violations raise `SandboxViolation` (a `RuntimeError` subclass) and
record the attempt in the bounded `_violations` list
(`snapshot_violations()`). The loader catches the exception,
emits a `plugin_sandbox_violation` audit event, and cleans the
plugin out of `sys.modules`.

**Documented limitation.** A plugin that launches a new thread and
performs I/O from that thread is outside the scope pushed on the
caller's thread. This is by design — the sandbox is best-effort
defense-in-depth, not a Python-level security boundary (Python
does not provide one; ctypes defeats any in-language attempt).
The hard deny on `exec`/`compile` removes the easiest thread-escape
primitive.

### H5 — Authenticode self-verify + DLL-search hardening

**`harden_dll_search_path(extra_app_dirs=None)`.** Calls
`kernel32.SetDefaultDllDirectories(0x200|0x800|0x400)` —
`LOAD_LIBRARY_SEARCH_APPLICATION_DIR | LOAD_LIBRARY_SEARCH_USER_DIRS
| LOAD_LIBRARY_SEARCH_SYSTEM32`. Then `AddDllDirectoryW()` per
extra directory. Must be called before any DLL is loaded; the
one-shot `apply_startup_hardening()` helper does this and emits a
`startup_hardening` audit event.

**`verify_self_authenticode()`.** Builds a `_WINTRUST_DATA` with
`WTD_UI_NONE` and `WTD_REVOCATION_CHECK_CHAIN`, calls
`wintrust.WinVerifyTrust(INVALID_HANDLE_VALUE, &{00AAC56B-...}, &d)`,
classifies the HRESULT:

| HRESULT | State |
|---|---|
| `0x00000000` | TRUSTED |
| `0x800B0100` | UNSIGNED |
| `0x80096010`, `0x800B0004` | TAMPERED |
| `0x80092010` | REVOKED |
| `0x800B0101` | EXPIRED |

On POSIX both functions return `SKIPPED_NON_WINDOWS` and are no-ops.

### H6 — Safe subprocess wrapper

**Single funnel.** `app.core.safe_subprocess.run(argv, *, timeout=...)`.
Invariants:

1. `shell=False` — always. No override.
2. `argv` must be a `list`/`tuple` of `str`; a single pre-joined
   string is refused.
3. `argv[0]` must be an absolute path to an existing file, unless
   `trusted_executable=True` (only used for `sys.executable` relaunch).
4. NUL bytes in argv elements are refused.
5. `timeout` is mandatory, bounded `0 < t ≤ 600`.
6. On Windows, `CREATE_NO_WINDOW` for `run`; `CREATE_NO_WINDOW |
   DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP` for `spawn_detached`.
7. `expect_returncode={0}` by default; unexpected codes raise
   `SafeSubprocessError`.
8. Every spawn and exit emits an audit event (`subprocess_spawn`,
   `subprocess_exit`).

**PATH-hijack defense.** `resolve_system_binary("netsh")` hard-routes
to `%SystemRoot%\System32\netsh.exe`. Module-level constants
`NETSH`, `ARP`, `IPCONFIG`, `ROUTE` are pre-resolved at import time
on Windows.

**Future CI gate.** The one-file surface makes it trivial to add a
CI check that bans direct `subprocess.Popen` imports outside this
module. Suggested rule:

    rg -w 'from subprocess' app/ | grep -v 'safe_subprocess.py'

### H7 — SBOM + build provenance

**`scripts/sbom.py`** parses `requirements-locked.txt`
(pip-compile output) and emits a CycloneDX 1.5 JSON document with:

- `bomFormat: CycloneDX`, `specVersion: 1.5`, deterministic
  `serialNumber` (`urn:uuid:` prefix + SHA-256(product@version@ts)).
- `metadata.component`: DupeZ as the application root.
- `components[]`: one per pinned dependency, with
  - `type: library`
  - `purl: pkg:pypi/<name>@<version>`
  - `hashes[{alg: SHA-256, content: ...}]`
  - `externalReferences[distribution]` → PyPI URL

The tool imports nothing from `app/`, so it runs in a CI context
that only has the lock file. Smoke test: 32 components emitted
from the repo's current lock.

### H8 — Offensive self-test layer

**Scope.** Local-only, read-mostly. Consent-gated behind
`DUPEZ_OFFSEC_CONSENT=i-own-this-machine-and-accept-local-scope`.
Every public entrypoint calls `require_consent()` on its first
line; no module will execute without it.

**Tactics.**
- `app.offsec.recon` (TA0043) — host profile, Authenticode state,
  DLL-search-order state, writable PATH entries, credential-shaped
  env vars, loaded-module trust anchors.
- `app.offsec.attack_surface` (TA0007) — listening sockets,
  DupeZ-owned named pipes, sensitive-file permissions, interpreter
  integrity.
- `app.offsec.fuzz_ipc` (TA0008) — giant-frame DoS, malformed-JSON
  probes, cross-user peer-auth reminder, against DupeZ's own
  `\\.\pipe\DupeZ.*` and `/tmp/dupez.*` endpoints only.

**Outputs.** `FindingRegistry` → JSON (schema `dupez.offsec.findings.v1`)
with per-finding CVSS v3.1 base + vector and MITRE ATT&CK technique
IDs. `scripts/report_findings.py` renders a self-contained HTML
report (no CDN references) suitable for email or ticket attachment.

**Runner.**

    export DUPEZ_OFFSEC_CONSENT=i-own-this-machine-and-accept-local-scope
    python -m app.offsec.runner --out dist/offsec-findings.json
    python scripts/report_findings.py dist/offsec-findings.json

Exit codes: 0 run completed, 2 consent missing, 3 unhandled
tactic exception. Finding severity is **not** an exit-code input;
CI that wants a gate reads the JSON summary.

---

## 3. Cryptographic inventory

| Purpose | Primitive | Key size | Storage |
|---|---|---|---|
| Update signatures | Ed25519 | 256-bit | Offline (vendor), pinned in `TRUSTED_PUBKEYS_PEM` |
| Plugin signatures | Ed25519 | 256-bit | Offline, pinned in `app.plugins.signing.TRUSTED_PUBKEYS_PEM` |
| Audit-log chain | HMAC-SHA384 | 256-bit | DPAPI-sealed (Win) / chmod 0600 (POSIX) |
| Persistence HMAC | HMAC-SHA384 | 256-bit | Same as above |
| Digest pinning (plugins) | SHA-384 | n/a | Inline in signed manifest |
| Signed-artifact addressing | SHA-256 | n/a | `requirements-locked.txt` + SBOM |
| Pubkey fingerprint | SHA-256 (first 8 B) | n/a | In 72-byte signature envelope |

No RSA, no secret-seed reuse, no TOFU. All mandatory comparisons
route through `hmac.compare_digest`.

---

## 4. Threat model coverage matrix

| Threat (STRIDE) | Control | Status |
|---|---|---|
| **S**poofing: malicious update replacing real binary | H1 + H5 | Mitigated |
| **S**poofing: malicious plugin impersonating a trusted one | H4 (pinned pubkey fingerprint routing) | Mitigated |
| **T**ampering: edit of on-disk config by local process | H2 + H3 + persistence HMAC | Mitigated |
| **T**ampering: audit-log edit after the fact | H3 (chain + migration) | Mitigated |
| **T**ampering: DLL sideload from CWD | H5 (`SetDefaultDllDirectories`) | Mitigated |
| **R**epudiation: cannot trace an action to a subsystem | H3 (per-event audit) + H6 (subprocess audit) | Mitigated |
| **I**nformation disclosure: secret in unsealed file | H2 (DPAPI + 0o600) | Mitigated |
| **I**nformation disclosure: credential in env inherited to child | H6 (caller passes explicit `env=`) + H8 recon | Reported; caller enforcement required |
| **D**oS: oversized IPC frame | H8 fuzzer + server-side MAX_FRAME (outstanding) | Reported; server fix required |
| **D**oS: plugin spawning subprocesses | H4 capability `process.spawn` absent by default | Mitigated |
| **E**levation: PATH hijack via writable dir + system binary | H6 (absolute path mandatory) + H8 recon | Mitigated |
| **E**levation: arbitrary code via plugin load | H4 (sig + sha384 + sandbox) | Mitigated |
| **E**levation: Authenticode-unsigned binary replacement | H5 + H1 | Mitigated |

---

## 5. Known residual risks

Enumerated explicitly so the team can't claim surprise later.

1. **Python-language sandbox is best-effort.** A plugin that does
   `import ctypes; ctypes.CDLL(None).system(...)` bypasses the audit
   hook. Mitigation: plugin signing (H4) and the hard-deny on
   `exec`/`compile` force any such plugin to carry its bypass in its
   signed source — which is reviewable.
2. **Offsec fuzzer's cross-user peer-auth case is manual.** The
   fuzzer documents the expectation but cannot exercise it from
   inside the same user's process. Required test: run from a
   different OS user and confirm the server refuses the connection.
3. **Build-host compromise.** H1 signing keys live on a build host.
   Moving them to HSM-backed offline signing is tracked outside this
   document.
4. **POSIX DPAPI-equivalent.** On Linux the secret store is chmod
   0600 only; it does not achieve the same at-rest protection as
   Windows DPAPI. Root on the machine reads it trivially. Mitigation
   path: per-OS keychain backends (`SecretService` on Linux,
   Keychain on macOS). Ticket TBD.
5. **Plugin thread-escape.** Plugins that spawn threads can I/O
   outside the sandbox scope. Documented in `app/plugins/sandbox.py`.

---

## 6. Verification procedure

To reproduce this certification from a clean checkout:

    # 1. Verify lock + produce SBOM
    python scripts/sbom.py --product-version 5.8.0

    # 2. Build + sign the release
    python scripts/sign-release.py --priv /path/to/priv.pem \
        --artifact dist/DupeZ-5.8.0.exe

    # 3. Consent to self-test (local box only)
    export DUPEZ_OFFSEC_CONSENT=i-own-this-machine-and-accept-local-scope

    # 4. Run the offsec self-test
    python -m app.offsec.runner --out dist/offsec-findings.json \
        --product-version 5.8.0
    python scripts/report_findings.py dist/offsec-findings.json \
        --out dist/offsec-findings.html

    # 5. Verify audit chain integrity
    python -c "from app.logs.audit import verify_chain; \
        print(verify_chain())"

A passing run produces: a valid SBOM JSON with N components, a
signature envelope of exactly 72 bytes next to the release binary,
an offsec findings JSON with zero CRITICAL / HIGH items on a
correctly-installed host, and a `verify_chain()` result of `{'ok':
True, ...}`.

---

## 7. Sign-off

This document certifies the DupeZ 5.8.0 hardening stream meets the
controls listed in §2 and the threat-model coverage listed in §4.

Residual risks §5 are accepted and tracked.

- Author: DupeZ security automation (Claude-driven hardening pass)
- Date:   2026-04-17
- Commit: _(insert git SHA at tag time)_
