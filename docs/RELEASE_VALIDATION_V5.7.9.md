# DupeZ v5.7.9 Merge and Release Runbook

This runbook separates **source merge approval** from **release publication**.
The signed binaries are rebuilt from the resulting `main` commit, so merging the
validated source candidate does not itself authorize a tag or release.

## 1. Source candidate gates before merging PR #42

All checks must apply to the exact PR head:

- Windows pytest on Python 3.11 and 3.12.
- AST, CodeQL, secret scan, dependency review, and requirements-lock checks.
- Canonical unsigned GPU and Compat PyInstaller build.
- `--verify-runtime-imports` in both unsigned variants.
- Frozen archive-policy preflight.
- Authorized PS5 full Clumsy control matrix.
- Authorized PS5 hidden-window matrix proving normal operation is invisible and
  authenticated diagnostics are the only restoration path.
- No orphaned `clumsy.exe`; generated files and Git working tree restored.

The current branch must remain draft while any exact-head gate is pending or
failed. Merge with an expected head SHA so a late push cannot bypass review.
Do not create `v5.7.9` at this stage.

## 2. Rebuild signed artifacts from merged `main`

The protected Windows signing host must provide, outside the repository:

- an Authenticode PFX through `DUPEZ_SIGN_CERT`;
- its password through `DUPEZ_SIGN_PASS` when required;
- the existing Ed25519 private key matching updater fingerprint
  `4e9c3c6731efbaa8` through `DUPEZ_SIGN_PRIVKEY`;
- Windows SDK SignTool;
- Inno Setup 6 `ISCC.exe`;
- current Microsoft Defender with real-time protection enabled.

From Administrator PowerShell on `main`:

```powershell
Set-Location X:\path\to\DupeZ
git switch main
git pull --ff-only

.\scripts\finalize_release.ps1 -Version 5.7.9
```

The finalizer fails unless it can build and verify:

- `DupeZ-GPU.exe`;
- `DupeZ-Compat.exe`;
- versioned and stable Inno Setup installers;
- valid SHA-256 Authenticode signatures with RFC3161 timestamps;
- an Ed25519 updater manifest/signature matching the stable installer;
- SBOM, VEX, and binary provenance;
- a current Microsoft Defender custom scan of every release artifact;
- final source, frozen archive, and distribution preflight;
- `SHA256SUMS.txt`, `release-attestation.json`, and `DefenderScan.txt`.

The protected GitHub workflow `.github/workflows/release.yml` may perform this
same build/sign/scan/attest stage. It has read-only repository permission and
cannot create or publish a release.

## 3. Architecture-correct frozen lifecycle validation

Run against the exact signed files produced above.

### GPU — standard non-Administrator desktop PowerShell

```powershell
Set-Location X:\path\to\DupeZ
.\scripts\validate_frozen_runtime.ps1 -Variant GPU
```

The script refuses an elevated GPU session. It verifies the split GUI as a
standard user, normal and forced-low-resource profiles, real dashboard creation,
Map opening through `Ctrl+2`, clean force-quit through `Ctrl+Q`, and helper/child
cleanup. It writes `dist\frozen-runtime-evidence-gpu.json`.

### Compat — Administrator PowerShell

```powershell
Set-Location X:\path\to\DupeZ
.\scripts\validate_frozen_runtime.ps1 -Variant Compat
```

It verifies the in-process High Integrity architecture and writes
`dist\frozen-runtime-evidence-compat.json`.

Neither evidence file is uploaded publicly because it contains local runtime
metadata.

## 4. Exact-artifact manual walkthrough

Using the same signed GPU, Compat, and installer files, verify:

- no native Clumsy flash during normal disruption;
- diagnostic restore and re-hide in both frozen architectures;
- map failure UI and successful Retry without restarting;
- network scan;
- manual disruption and stop;
- event-queue stop semantics;
- hotkeys and panic restoration;
- tray status, Stop All, and Quit;
- OBS overlay start/serve/stop;
- account tracker load/switch/persist/clear;
- Smart Ops provider/offline routing;
- diagnostics, network health, and support/backup bundle;
- fresh install, upgrade, and uninstall behavior.

Record the observation interactively:

```powershell
.\scripts\record_manual_release_validation.ps1 `
    -Operator "<release operator>" `
    -Version 5.7.9
```

Every gate requires an explicit `YES`. The result is private
`dist\manual-release-validation.json`, bound to the current commit and exact
GPU, Compat, and installer hashes.

## 5. Create a draft release

Only after Sections 2–4 pass:

```powershell
$env:GH_TOKEN = "<release-scoped token>"
.\scripts\stage_release.ps1 `
    -Mode Draft `
    -Version 5.7.9 `
    -Repository GrihmLord/DupeZ
```

Staging re-runs distribution preflight, validates both frozen evidence files and
the manual attestation, and emits a sanitized public
`release-validation-attestation.json`. Raw machine/operator evidence remains
private. If `v5.7.9` is already published, asset replacement is refused.

Inspect the draft assets, notes, signatures, hashes, installer size/version, and
updater sidecars before publication.

## 6. Publish the already-verified draft

```powershell
.\scripts\stage_release.ps1 `
    -Mode Publish `
    -Version 5.7.9 `
    -Repository GrihmLord/DupeZ
```

Publication is the final explicit action. Do not publish from an unsigned build,
a source-only result, a different commit, or regenerated artifacts that have not
repeated the exact-artifact validation sequence.
