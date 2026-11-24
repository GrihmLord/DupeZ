# DupeZ v5.8.0 Merge and Release Runbook

This runbook separates source approval from public artifact approval. Merging
reviewed source does not authorize a tag or release; release approval belongs
to the exact rebuilt and validated bytes.

## 0. Repository trust controls (blocking)

DupeZ is currently a solo-maintainer repository. Its server-side policy must
not pretend that the pull-request author can provide independent review.
Before dispatching either release-artifact workflow, verify through the GitHub
API that:

- every change to `main` must use a pull request with all 14 up-to-date,
  exact-head checks passing;
- direct updates, force pushes, deletion, and bypass are disabled, and review
  conversations must be resolved;
- the path-unfiltered source-preflight check plus the supported Python, lock,
  secret, CodeQL, dependency-review, and frozen-boundary checks are required;
  and
- `production-release` permits deployments only from `main`. With only one
  write-capable account it has no reviewer rule; add independent approval and
  self-review prevention as soon as a second trusted maintainer exists.

After verifying those controls, set repository variable
`DUPEZ_RELEASE_GOVERNANCE_READY` to the exact value
`protected-main-solo-maintainer-environment`. Both artifact workflows fail
before checkout while the variable is absent or different.

The workflows also reject non-`refs/heads/main` dispatches and explicitly
checkout `github.sha`, but a direct pusher could remove those repository-local
guards. They become meaningful defense in depth only after the server-side
controls above are active. Mandatory automated checks are the compensating
control for the repository's disclosed lack of independent human review.

An authenticated read-only API audit on 2026-09-04 verified the active
no-bypass default-branch ruleset, all 14 strict check requirements, the
main-only `production-release` policy, the sole write-capable collaborator,
and the exact readiness variable. The minimized evidence is preserved in
`assessment/evidence/GITHUB_GOVERNANCE_AUDIT_2026-09-04.json`. That audit also
found all 14 checks on the observed PR 84 head unsuccessful with no assigned
runner or executed step, so configured governance does not authorize merge or
release. Re-query live policy and obtain passing exact-head checks before use.

## 1. Source candidate gates

Before merging the v5.8.0 pull request, require all checks on its exact head:

- Windows tests on supported Python versions.
- CodeQL, secret scanning, dependency/lock validation, and source preflight.
- Frozen import-boundary and archive-policy checks for GPU and Compat.
- Authorized hardware tests on the prepared Windows driver runner, with a
  machine-readable evidence artifact bound to the exact candidate commit.
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

Unsigned mode does not bypass updater signing, Defender, SBOM, the lock-bound
vulnerability review, provenance, hashes, frozen-import checks, or distribution
preflight. A clean review intentionally has no OpenVEX artifact; OpenVEX is
required only when the review contains actual vulnerability findings, which
still block release finalization.
Every distribution preflight also requires the review timestamp to be no more
than 24 hours old and no more than five minutes in the future. Complete
finalization, exact-byte validation, draft staging, and publication inside that
window. If it expires, restart finalization and regenerate all evidence bound
to the resulting release artifacts; do not edit or refresh the review in place.
The protected unsigned GitHub workflow is artifact-build-only: it cannot create
or publish a release and cannot generate human runtime or manual evidence.

The upstream `app/firewall/clumsy.exe` executes as a separate process and is
unsigned. Standard finalization therefore verifies the tracked source bytes,
copies the complete native inventory into `build/release-native`, and signs
only the staged Clumsy copy. The build proves that its PE image is
source-equivalent outside Authenticode, records its exact hash and signer in
distribution provenance, and makes both PyInstaller variants and the Inno
Setup installer consume a revalidated snapshot. Dist preflight independently extracts the nested child
and requires the signer authenticated by updater metadata. The explicit
unsigned route remains source-exact and retains its disclosure requirement.

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
GPU and Compat runtime evidence documents. Each document is valid for at most
24 hours, binds both profiles to one validator session, and is rejected if any
run, executable hash, source fingerprint, architecture, or WebEngine helper
proof differs. These local unsigned JSON files are operator evidence, not a
cryptographic attestation: keep `dist/` access restricted, never publish them,
and rely on the separately signed artifacts, hashes, and release attestation
for public provenance.

The automated lifecycle seeds the isolated profile with DupeZ's shipped
**Active Operation Safety > Dry Run** setting and requires every v3 evidence
record to report `production-safety-dry-run`. It therefore proves frozen GUI
startup, the split/in-process architecture boundary, both resource profiles,
real QtWebEngine Map navigation, force-quit, and process cleanup without
changing network traffic or waiting on an unattended secure-desktop UAC
prompt. It does not claim privileged packet-engine coverage. The exact-artifact
walkthrough in section 5 and the exact-commit hardware evidence in section 4
remain mandatory for helper elevation, WinDivert, bounded disruption, panic
stop, and network restoration.

## 4. Import exact-commit hardware evidence

Run the `Hardware Smoketest` workflow against the same commit. It creates
`hardware-smoketest-evidence.json` only after every selected hardware test and
the owned-process cleanup gate pass. Evidence creation is GitHub Actions-only
and requires the repository's exact seven-test/four-file canonical suite plus
the cleanup step's measured remaining-process count. Download that artifact
into `dist/` before manual validation. The evidence contains no target IP,
MAC, or CIDR.

The hardware workflow runs from source, so it cannot bind frozen executable
hashes. Before testing, it verifies and read-locks every source-native file;
the locks remain held through process cleanup and evidence creation. Evidence
binds the exact commit and all size/SHA-256 values from
`packaging/binary-provenance.json`; the GPU and Compat evidence above
separately binds the frozen executable hashes. Staging downloads the exact
GitHub Actions artifact ID, verifies GitHub's archive digest, and requires its
evidence bytes to match the local input. Missing, skipped-test, stale-commit,
or mismatched-native evidence blocks both manual recording and staging.

## 5. Record the exact-artifact walkthrough

Test install/upgrade/uninstall, startup and shutdown, diagnostic restore,
bounded disruption stop/panic paths, map retry, network scan, tray actions,
overlay lifecycle, account persistence, Smart Ops online/offline routing, and
support/backup output. Then record only observations actually performed:

```powershell
.\scripts\record_manual_release_validation.ps1 -Operator "<release operator>" -Version 5.8.0
```

For the explicitly disclosed unsigned route, append `-AllowUnsigned`. The
recorder binds that choice to the exact release attestation and verifies the
three manually tested artifacts are recorded as unsigned before prompting.

## 6. Stage, verify, and publish

```powershell
.\scripts\stage_release.ps1 -Mode Draft -Version 5.8.0 -Repository GrihmLord/DupeZ
```

For an unsigned release, staging must explicitly preserve the attested mode:

```powershell
.\scripts\stage_release.ps1 -Mode Draft -Version 5.8.0 -Repository GrihmLord/DupeZ -AllowUnsigned
```

Staging re-runs distribution preflight, verifies all private evidence against
the current commit and artifact hashes, rejects extra assets, downloads the
complete draft, and compares every SHA-256 digest. Inspect the draft and then:

```powershell
.\scripts\stage_release.ps1 -Mode Publish -Version 5.8.0 -Repository GrihmLord/DupeZ
```

For the same unsigned draft:

```powershell
.\scripts\stage_release.ps1 -Mode Publish -Version 5.8.0 -Repository GrihmLord/DupeZ -AllowUnsigned
```

Never replace assets on an already published tag or publish artifacts rebuilt
after the validation evidence was recorded.
