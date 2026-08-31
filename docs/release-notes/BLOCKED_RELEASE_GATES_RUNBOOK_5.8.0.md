# Blocked Release Gates Runbook (v5.8.0)

This runbook completes the protected v5.8.0 artifact gates in strict order.
Source tests and a clean merge are prerequisites, not substitutes for testing
the exact frozen files that will be published.

## Preconditions

- GitHub `main` is protected by reviewed pull requests and required exact-head
  checks; force push, deletion, direct push, and bypass are disabled.
- The `production-release` environment requires an independent reviewer,
  prevents self-review, and permits deployments only from `main`. The
  2026-08-28 read-only audit found these repository controls and the
  governance-ready variable absent, so this
  runbook remains blocked until the repository owner enables them.
- After API-verifying those controls, repository variable
  `DUPEZ_RELEASE_GOVERNANCE_READY` has the exact value
  `protected-main-reviewed-environment`; leave it unset while either control
  is absent.
- Branch: `main` at the reviewed v5.8.0 commit.
- Working tree: clean (`git status --porcelain` is empty).
- `packaging/license-policy.json` records owner evidence for every decision,
  and the root `LICENSE.txt` is compatible with the exact PyQt binding terms.
- Windows PowerShell 5.1 and Administrator access for protected phases.
- Inno Setup 6, current Microsoft Defender, and the expected build tools.
- Updater private key matching fingerprint `5555f0e8c31a40ed`.
- Authenticode inputs, unless the explicitly disclosed unsigned path is used.
- Passing GitHub Actions `Hardware Smoketest` evidence for this exact commit,
  exact canonical hardware suite, and measured post-cleanup process count, downloaded from
  the prepared private-target runner without target identifiers.
- GitHub authentication through `GITHUB_TOKEN` or `GH_TOKEN`.

## Recommended launcher

Run this command again after each elevated or non-elevated phase finishes:

```cmd
scripts\release_gate_launcher.cmd
```

Progress is version-bound in `dist/blocked-release-gates-progress.json`. The
launcher discards stale progress from another release, elevates protected
phases, and refuses to perform GPU validation from an Administrator shell.

Useful commands:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/release_gate_launcher.ps1 -Phase status -Version 5.8.0
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/release_gate_launcher.ps1 -Phase reset -Version 5.8.0
```

## Exact sequence

### A. Administrator: finalize exact artifacts

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/blocked_release_gates_sequence.ps1 -Phase admin-finalize -Version 5.8.0
```

For the explicitly disclosed unsigned public route, append `-AllowUnsigned`.
The updater manifest still requires the protected Ed25519 key.
Keep that switch on the Compat/manual, draft, and publish phases below. Each
phase validates its own evidence mode and fails closed if the switch is omitted.

### B. Standard desktop: GPU runtime validation

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/blocked_release_gates_sequence.ps1 -Phase gpu-validate -Version 5.8.0
```

### C. Administrator: Compat and manual validation

Before this phase, place the matching workflow artifact at
`dist/hardware-smoketest-evidence.json`. The recorder revalidates its commit,
passing/non-skipped test count, zero owned-process remainder, and every source
native size/SHA-256 against `packaging/binary-provenance.json`. Hardware runs
exercise source at the exact commit; frozen GPU/Compat hashes remain bound by
their separate runtime evidence. Draft staging then authenticates that local
copy against the successful exact-commit GitHub Actions run, exact artifact ID,
GitHub archive digest, and downloaded evidence bytes.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/blocked_release_gates_sequence.ps1 -Phase admin-compat -Version 5.8.0 -Operator <YOUR_NAME>
```

For the explicitly disclosed unsigned public route, append `-AllowUnsigned`
so the manual evidence is bound to the attested unsigned distribution mode.

The manual recorder requires explicit observation of every listed behavior on
the exact GPU, Compat, and installer bytes. Do not record an unobserved pass.

### D. Administrator: create and verify the draft

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/blocked_release_gates_sequence.ps1 -Phase admin-stage-draft -Version 5.8.0
```

Unsigned route:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/blocked_release_gates_sequence.ps1 -Phase admin-stage-draft -Version 5.8.0 -AllowUnsigned
```

### E. Administrator: publish the verified draft

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/blocked_release_gates_sequence.ps1 -Phase admin-stage-publish -Version 5.8.0
```

Unsigned route:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/blocked_release_gates_sequence.ps1 -Phase admin-stage-publish -Version 5.8.0 -AllowUnsigned
```

## Required private evidence and public artifacts

- `dist/release-attestation.json`
- `dist/frozen-runtime-evidence-gpu.json`
- `dist/frozen-runtime-evidence-compat.json`
- `dist/hardware-smoketest-evidence.json` (private input; summarized in the
  public validation attestation)
- `dist/manual-release-validation.json`
- `dist/release-validation-attestation.json`
- GPU and Compat executables, versioned and stable installers
- updater manifest/signature, SHA-256 list, SBOM, lock-bound vulnerability
  review generated within the preceding 24 hours, provenance, and Defender
  report
- project `LICENSE.txt`, `SOURCE_AND_RELINK.txt`,
  `THIRD_PARTY_NOTICES.txt`, `license-payload.json`, and the exact-commit
  `DupeZ-v5.8.0-source.zip`

Frozen-runtime JSON is private, unsigned operator evidence with a 24-hour
freshness limit and per-invocation session binding. It is not cryptographic
provenance and must never be substituted for the signed release attestation.

Publication is permitted only after the draft is downloaded and every staged
asset hash matches the locally validated artifact.
