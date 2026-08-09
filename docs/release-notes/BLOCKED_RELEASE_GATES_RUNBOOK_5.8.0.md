# Blocked Release Gates Runbook (v5.8.0)

This runbook completes the protected v5.8.0 artifact gates in strict order.
Source tests and a clean merge are prerequisites, not substitutes for testing
the exact frozen files that will be published.

## Preconditions

- Branch: `main` at the reviewed v5.8.0 commit.
- Working tree: clean (`git status --porcelain` is empty).
- Windows PowerShell 5.1 and Administrator access for protected phases.
- Inno Setup 6, current Microsoft Defender, and the expected build tools.
- Updater private key matching fingerprint `5555f0e8c31a40ed`.
- Authenticode inputs, unless the explicitly disclosed unsigned path is used.
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

### B. Standard desktop: GPU runtime validation

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/blocked_release_gates_sequence.ps1 -Phase gpu-validate -Version 5.8.0
```

### C. Administrator: Compat and manual validation

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

### E. Administrator: publish the verified draft

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/blocked_release_gates_sequence.ps1 -Phase admin-stage-publish -Version 5.8.0
```

## Required private evidence and public artifacts

- `dist/release-attestation.json`
- `dist/frozen-runtime-evidence-gpu.json`
- `dist/frozen-runtime-evidence-compat.json`
- `dist/manual-release-validation.json`
- `dist/release-validation-attestation.json`
- GPU and Compat executables, versioned and stable installers
- updater manifest/signature, SHA-256 list, SBOM, VEX, provenance, and Defender report

Publication is permitted only after the draft is downloaded and every staged
asset hash matches the locally validated artifact.
