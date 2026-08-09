# DupeZ v5.8.0 Merge and Release Runbook

This runbook separates source approval from public artifact approval. Merging
reviewed source does not authorize a tag or release; release approval belongs
to the exact rebuilt and validated bytes.

## 1. Source candidate gates

Before merging the v5.8.0 pull request, require all checks on its exact head:

- Windows tests on supported Python versions.
- CodeQL, secret scanning, dependency/lock validation, and source preflight.
- Frozen import-boundary and archive-policy checks for GPU and Compat.
- Authorized hardware tests where the required Windows driver is available.
- A clean tree with no orphaned DupeZ-owned packet-process state.

Merge only with the expected head SHA. Do not create `v5.8.0` yet.

## 2. Rebuild from merged main

Use the protected Windows release host. The disposable packaging environment
is `.release-venv`; it is recreated from `requirements-locked.txt` with hashes.

From Administrator PowerShell on clean `main`:

```powershell
git switch main
git pull --ff-only
.\scripts\finalize_release.ps1 -Version 5.8.0
```

If and only if the public release is intentionally unsigned and its notes
disclose Windows publisher warnings, use:

```powershell
.\scripts\finalize_release.ps1 -Version 5.8.0 -AllowUnsigned
```

Unsigned mode does not bypass updater signing, Defender, SBOM/VEX, provenance,
hashes, frozen-import checks, or distribution preflight.

## 3. Validate both frozen architectures

In a standard non-Administrator desktop PowerShell:

```powershell
.\scripts\validate_frozen_runtime.ps1 -Variant GPU
```

In Administrator PowerShell:

```powershell
.\scripts\validate_frozen_runtime.ps1 -Variant Compat
```

These commands must operate on the exact final files and produce the private
GPU and Compat runtime evidence documents.

## 4. Record the exact-artifact walkthrough

Test install/upgrade/uninstall, startup and shutdown, diagnostic restore,
bounded disruption stop/panic paths, map retry, network scan, tray actions,
overlay lifecycle, account persistence, Smart Ops online/offline routing, and
support/backup output. Then record only observations actually performed:

```powershell
.\scripts\record_manual_release_validation.ps1 -Operator "<release operator>" -Version 5.8.0
```

## 5. Stage, verify, and publish

```powershell
.\scripts\stage_release.ps1 -Mode Draft -Version 5.8.0 -Repository GrihmLord/DupeZ
```

Staging re-runs distribution preflight, verifies all private evidence against
the current commit and artifact hashes, rejects extra assets, downloads the
complete draft, and compares every SHA-256 digest. Inspect the draft and then:

```powershell
.\scripts\stage_release.ps1 -Mode Publish -Version 5.8.0 -Repository GrihmLord/DupeZ
```

Never replace assets on an already published tag or publish artifacts rebuilt
after the validation evidence was recorded.
