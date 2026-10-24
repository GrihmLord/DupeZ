# Blocked Release Gates Runbook (v5.8.0)

This runbook completes the protected v5.8.0 artifact gates in strict order.
Source tests and a clean merge are prerequisites, not substitutes for testing
the exact frozen files that will be published.

## Preconditions

- GitHub `main` requires a pull request, resolution of review conversations,
  and all 14 up-to-date exact-head checks; force push, deletion, direct update,
  and bypass are disabled.
- The `production-release` environment permits deployments only from `main`.
  DupeZ currently has one write-capable maintainer, so no independent-review
  claim is made; mandatory automated checks compensate until a second trusted
  maintainer can be required for review.
- After API-verifying those controls, repository variable
  `DUPEZ_RELEASE_GOVERNANCE_READY` has the exact value
  `protected-main-solo-maintainer-environment`; leave it unset while either
  control is absent.
- The 2026-09-04 read-only audit verified those settings and is preserved at
  `assessment/evidence/GITHUB_GOVERNANCE_AUDIT_2026-09-04.json`. Re-verify
  live settings before release because repository policy can change.
- Branch: `main` at the exact-head-validated v5.8.0 commit.
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

## Canonical launcher

Start with the read-only status view:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/release.ps1 -Version 5.8.0
```

Progress is version-bound in `dist/blocked-release-gates-progress.json`. The
launcher also binds progress to the exact commit, release mode, and validation
policy. It ignores stale progress in read-only status, waits for protected
elevated phases, and refuses to perform GPU validation from an Administrator
shell. Use the explicit named phases below for the auditable release sequence.
`-Phase auto` may select the next non-publication phase, but it always stops
before publish; publication requires explicit `-Phase admin-stage-publish`.

Progress saves now flush a private sibling file before replacing the checkpoint.
An unsuccessful replacement leaves the previous checkpoint intact. Phase work
and reset take exclusive OS-handle ownership of
`dist/blocked-release-gates-progress.json.lock`; competing launchers fail without
starting a phase. The lock file stays on disk after normal completion: its
existence is not evidence that a release is still running. Do not delete it to
try to bypass a running launcher. Status remains read-only and unlocked.

If a launcher crashes after starting a phase, inspect its child processes and
external effects before retrying. Checkpoint persistence is not a transaction
covering builds, hardware tests, uploads, or publication. Automatic selection
is repeated after elevation, and selection is checked again under the lock.

Useful commands:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/release.ps1 -Phase status -Version 5.8.0
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/release.ps1 -Phase reset -Version 5.8.0
```

## Exact sequence

### A. Administrator: finalize exact artifacts

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/release.ps1 -Phase admin-finalize -Version 5.8.0
```

For the explicitly disclosed unsigned public route, append `-AllowUnsigned`.
The updater manifest still requires the protected Ed25519 key.
Keep that switch on every subsequent phase, including GPU validation,
Compat/manual, draft, and publish. Launcher progress is release-mode-bound, and
each phase fails closed if the switch is omitted.

### B. Standard desktop: GPU runtime validation

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/release.ps1 -Phase gpu-validate -Version 5.8.0
```

For the unsigned route, append `-AllowUnsigned` here and on every later phase.

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
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/release.ps1 -Phase admin-compat -Version 5.8.0 -Operator "YOUR_NAME"
```

For the explicitly disclosed unsigned public route, append `-AllowUnsigned`
so the manual evidence is bound to the attested unsigned distribution mode.

The manual recorder requires explicit observation of every listed behavior on
the exact GPU, Compat, and installer bytes. Do not record an unobserved pass.

### D. Administrator: create and verify the draft

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/release.ps1 -Phase admin-stage-draft -Version 5.8.0
```

Unsigned route:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/release.ps1 -Phase admin-stage-draft -Version 5.8.0 -AllowUnsigned
```

### E. Administrator: publish the verified draft

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/release.ps1 -Phase admin-stage-publish -Version 5.8.0
```

Unsigned route:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/release.ps1 -Phase admin-stage-publish -Version 5.8.0 -AllowUnsigned
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
