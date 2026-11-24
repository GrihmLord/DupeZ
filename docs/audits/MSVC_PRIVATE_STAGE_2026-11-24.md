# Private MSVC runtime stage and source follow-up — 2026-11-24

The explicit `frozen-raster-no-qtnetwork` engineering profile now takes its
three Microsoft C++ runtime DLLs from a private, hash-verified package stage.
Recipients no longer need those exact three DLL versions in System32 to
reproduce the build inputs. The code checkpoint is
**`a017ee201d2eff57aae3e3abbfc6284af89f3f36`**.

**Compat runtime testing remains pending per owner instruction.** This work
does not approve public binary distribution, change the canonical production
locks, or establish complete corresponding source and native reproduction.
The last inspected hosted checks were blocked by billing on November 9 at
`078067c`. Refresh checks after the new push; local results are separate evidence.

## What the stage verifies

The [existing package provenance review](../legal/MSVC_REDIST_PROVENANCE_REVIEW_2026-11-09.md)
identified the exact Microsoft 14.51.36247.0 package and its three required
DLLs. The new verifier route reads that package and its pinned license document
without requiring a prior System32 observation. The actual November 24 receipt
records `system_observation_compared: false` and
`previous_system_observation: null`. Package verification passed with the same
18,731,856-byte package SHA-256:
`843068991daaa1f73ad9f6239bce4d0f6a07a51f18c37ea2a867e9beca71295c`.
The installer is not executed and no global installation or elevation occurs.

`scripts/msvc_runtime_stage.py` creates `msvc-runtime/` next to the engineering
profile's `build-venv/`. Its closed inventory is exactly `MSVCP140.dll`,
`MSVCP140_1.dll`, `MSVCP140_2.dll`, `stage-receipt.json`, and
`upstream-receipt.json`. It checks the upstream receipt's package identity,
manifest identity, signature observations, consumed-file mapping and three
exact byte pins before copying the bounded file snapshots. The stage receipt
binds the exact manifest, package, DLLs and upstream receipt. Its distribution
and release approval fields remain false.

Validation rejects unexpected files, duplicate or substituted inputs, unsafe
path objects, hardlinks, reparse points, stale byte pins, malformed receipts,
and changes during inspection. The exact staged paths are returned only to
the local build integration; machine-specific source paths are not persisted
inside the stage receipt. Revalidating a receipt against committed package and
file pins does not turn a caller-written approval into authority.

The shared build factory supplies those three files to PyInstaller before
`Analysis`. After dependency collection, it requires the final native table
to name the same three exact source paths at their canonical destinations.
The provenance origin is `pinned-msvc-redist`; the surrounding directory is
not an approved root for arbitrary DLLs. This new profile rejects System32
native fallback rather than rewriting origins or replacing DLLs after
collection. It does not add the stage to the general search path.

The generated native manifest binds the redistributable manifest, package,
stage receipt and upstream receipt hashes. The final archive inspector checks
the frozen DLL bytes against the stage and revalidates it after inspection.
Historical archives without stage fields retain an explicit
`historical-system32` validation path. New builds require the private stage;
partial stage metadata and staged source paths cannot silently enter that
historical path.

This removes dependence on the host installation for these three selected
build inputs. It does not demonstrate byte-for-byte reproducibility of the
entire executable, native compiler reconstruction, arbitrary DLL ABI
compatibility, vulnerability freedom, or the owner's redistribution rights.

## Verified builds and runtime observations

The actual package was verified under
`build/msvc-private-stage-20261124/verified-package/`. A fresh checkout at the
checkpoint above was used for the engineering profile and sequential GPU
and Compat builds. The final record binds that checkout, exact source ZIP,
prepared profile, private stage, archive reports and runtime reports. Documentation commits made later do not change the recorded build
checkpoint.

| Check | Recorded result |
| --- | --- |
| Pinned package verification without a host observation | Passed; three DLLs; distribution approval false |
| Stage/native/archive guard tests | 259 passed, zero skipped; includes the real hardlink rejection test |
| Adoption and package-verifier tests | 97 passed |
| IUP selected-source tests | 23 passed, zero skipped |
| Ruff and AST over the checkpoint's tracked Python files | Passed for all 469 files; zero AST failures |
| Clean profile preparation | Passed: 376 notice documents, `pip check`, and installed wheel-byte validation |
| Full production-dependency source suite | 3,901 passed, 10 expected skips; exact JUnit/log hashes in evidence |
| Clean GPU build and native/archive inspection | Passed; 114 native entries, private-stage policy |
| Clean Compat build and native/archive inspection | Passed; 114 native entries, private-stage policy |
| GPU import/TLS maintenance | Passed; import/TLS report hashes bound in evidence |
| GPU dashboard lifecycle in production safety dry-run mode | Passed; normal and forced-low-resource profiles, clean exits, actual PS5.1 consumer |
| Compat maintenance and dashboard lifecycle | Pending per owner instruction; no new UAC attempt |
| GitHub-hosted checks | Last inspected prior head blocked by billing; refresh after push |

The initial full suite recorded 3,899 passes, two failures and ten skips because
launcher-injected Git transport configuration reached the provenance guard
before two mocked assertions. The original runner, log and JUnit are retained.
The corrected local runner removes only validated credential/HTTP config
overrides from its child process; the application guard and checkpoint are
unchanged. The complete rerun passes as recorded above.

The focused test groups overlap the later source suite and must not be added
to its count. Earlier pre-escalation testing had one skipped hardlink test
because the sandbox denied fixture creation. The final 259-test run exercised
that case successfully; retain the earlier diagnostic as a separate record.

| Engineering artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `DupeZ-v5.8.0-source.zip` | 25,230,960 | `50dfdbbc549a70ea00c115a5dd518d47f7ce50783a559a34314aedc0bdf0e989` |
| `DupeZ-GPU.exe` | 56,753,376 | `f1f7c0444dcc80325fcf6bfea2ad0670036d17b884e52f0c015675aa254f5973` |
| `DupeZ-Compat.exe` | 56,753,213 | `cc26fe33ebeaa257266e86156b8e905786576114e0f40b004b36a01df3d8f3b8` |

Both artifacts have **114 native entries**: 83 locked build environment, 24
verified Python base, four managed and three private-stage MSVC files. Neither
collects a System32-origin file. Their native inventory SHA-256 is
`8958fa7f8b6b2fc3748b7790f8dbed7f16903461049cdee49ba4090dfc3d621c`.
The stage receipt SHA-256 is `16b99fabc31042036b04deb3f3e9347e15dfd446417756a7e6f51a7f1ff22c42`;
its upstream receipt is `30217a7920995ff47e78edcc67972a15c07323892aba771874541de5717ec584`.
See the [machine-readable evidence](../../packaging/license-evidence/msvc-private-stage-2026-11-24.json)
(SHA-256 `4dcca1aa66dcdd524bb6d4d97ee7ed6c5d312357095239f8f43bc172282eadc1`).

Static build/archive checks do not launch the application or demonstrate a
working runtime. GPU maintenance checks establish only their specific import/TLS assertions.
The dashboard checks cover the two recorded dry-run modes and clean exits; they do not establish packet-effect,
hardware-rendering, or Compat coverage. The GPU name denotes the standard-token
variant and does not by itself prove hardware acceleration.

## Reproduce the explicit engineering profile

This recipe supersedes the reproduction commands in the
[November 9 Qt Network exclusion audit](QT_NETWORK_EXCLUSION_2026-11-09.md)
for new builds: `--msvc-redist-root` is now required. The November 9 build and
runtime observations remain historical evidence for their recorded checkpoint.

Use a clean, disposable checkout at the exact checkpoint and the reviewed
Windows x64 CPython 3.13.17 interpreter. Follow the process-local environment
sanitation in [Source, Build, and Relink Information](../legal/SOURCE_AND_RELINK_V5.8.0.md).
The local cache paths below are examples of verified retained inputs, not
public delivery locations. Obtain and verify the pinned inputs before running
the commands. Use new output/work directories; do not reuse prior build trees.
These commands prepare, build and inspect files. They do not install the
redistributable, launch Compat, request UAC, sign artifacts or publish a release.

```powershell
$ErrorActionPreference = 'Stop'
$reviewPython = (Resolve-Path 'build/native-security-20261024/test-venv/Scripts/python.exe').Path
$qtProfile = 'frozen-raster-no-qtnetwork'
$wheelHash = '27e8195852d1305cfad3ac88d47f19e32679229e3461fa6a4ac0e42fa09fef8a'
$verifiedMsvc = 'build/msvc-recipient-verified-new'
$candidateRoot = 'build/qt-network-recipient-new'
$profileRoot = 'build/qt-network-private-profile-new'

# Read the exact package as data; no System32 observation is required.
& $reviewPython -I scripts/verify_msvc_redist.py `
  --package build/msvc-redist-provenance-20261109/VC_redist.x64.exe `
  --license-document build/msvc-redist-provenance-20261109/Visual-C-V14-License-Redistributable_and_Runtime_ENU.docx `
  --output $verifiedMsvc
if ($LASTEXITCODE -ne 0) { throw 'Microsoft package verification failed' }

& $reviewPython -I scripts/prepare_qt_candidate.py --profile $qtProfile `
  --cache build/qt-nonetwork-candidate-20261109/inputs `
  --output $candidateRoot
if ($LASTEXITCODE -ne 0) { throw 'Qt candidate preparation failed' }

& $reviewPython -I scripts/prepare_qt_adoption.py --profile $qtProfile `
  --candidate-root $candidateRoot --expected-wheel-sha256 $wheelHash `
  --msvc-redist-root $verifiedMsvc `
  --wheel-cache build/qt-adoption-wheel-cache-20261109 `
  --output $profileRoot --install-build-env
if ($LASTEXITCODE -ne 0) { throw 'Engineering profile preparation failed' }

$buildVenv = (Resolve-Path (Join-Path $profileRoot 'build-venv')).Path
$buildPython = Join-Path $buildVenv 'Scripts/python.exe'
$pythonBase = & $buildPython -I -S -c 'import sys; print(sys.base_prefix)'
if ($LASTEXITCODE -ne 0) { throw 'Base interpreter identity failed' }
$env:DUPEZ_QT_BUILD_PROFILE = $qtProfile

& $buildPython -I -m PyInstaller packaging/dupez_gpu.spec --noconfirm `
  --distpath (Join-Path $profileRoot 'artifacts') `
  --workpath (Join-Path $profileRoot 'gpu')
if ($LASTEXITCODE -ne 0) { throw 'GPU build failed' }
& $buildPython -I -m PyInstaller packaging/dupez_compat.spec --noconfirm `
  --distpath (Join-Path $profileRoot 'artifacts') `
  --workpath (Join-Path $profileRoot 'compat')
if ($LASTEXITCODE -ne 0) { throw 'Compat build failed' }

& $buildPython -I scripts/native_build_evidence.py --qt-profile $qtProfile `
  --artifact (Join-Path $profileRoot 'artifacts/DupeZ-GPU.exe') `
  --manifest (Join-Path $profileRoot 'gpu/dupez_gpu/native-binaries.json') `
  --source-root (Get-Location).Path --build-venv $buildVenv `
  --python-base $pythonBase --output (Join-Path $profileRoot 'gpu-native.json')
if ($LASTEXITCODE -ne 0) { throw 'GPU native inspection failed' }
& $buildPython -I scripts/native_build_evidence.py --qt-profile $qtProfile `
  --artifact (Join-Path $profileRoot 'artifacts/DupeZ-Compat.exe') `
  --manifest (Join-Path $profileRoot 'compat/dupez_compat/native-binaries.json') `
  --source-root (Get-Location).Path --build-venv $buildVenv `
  --python-base $pythonBase --output (Join-Path $profileRoot 'compat-native.json')
if ($LASTEXITCODE -ne 0) { throw 'Compat native inspection failed' }
& $buildPython -I scripts/release_preflight.py --qt-profile $qtProfile `
  --frozen-artifact (Join-Path $profileRoot 'artifacts/DupeZ-GPU.exe') `
  --frozen-artifact (Join-Path $profileRoot 'artifacts/DupeZ-Compat.exe')
if ($LASTEXITCODE -ne 0) { throw 'Frozen profile validation failed' }
```

The `--msvc-redist-root` input is the verifier's fresh output directory, not a
directory of manually copied DLLs. Adoption validates its receipt and exact
bytes, builds the private stage, and rechecks that stage before issuing its
engineering receipt and after installation. Both build variants use the same
prepared stage. The existing older Qt profiles retain their separate behavior;
this option is required specifically for new preparations of the explicit
Network-free profile.

## IUP source correspondence: seven exact matches

The [IUP source review](../../packaging/license-evidence/iup-source-review-2026-11-24.json)
compares seven selected members of the retained `iup-3.30_Sources.zip` against
official SVN revision **5892**, using exact bytes with no normalization:

- `iup/include/iup.h`
- `iup/src/config.mak`
- `iup/src/iup.c`
- `iup/src/iup.def`
- `iup/src/win/iupwin_dialog.c`
- `iup/src/win/iupwin_loop.c`
- `iup/src/win/iupwin_text.c`

All seven match. The retained source archive is 14,226,631 bytes with SHA-256
`92e1b56a6c78eeaca7cce3897536d333787e27e3ec25f94487dd0ab1d8d053e6`.
Official dated-revision metadata selected revision 5892, dated
`2020-08-02T15:32:49.346111Z`, as the latest revision at the queried release
date. This is a historical revision selection, not a discovered IUP 3.30 tag
or an attestation of the shipped DLL's compiler inputs.

Only those seven files were compared. The repository-wide depth request was
denied and no complete historical snapshot was acquired. The source archive's
later upload date does not invalidate the selected exact matches, but complete
archive identity, patches, compiler/SDK inputs and native DLL reconstruction
remain unresolved. The new validator and its tests establish selected-file
correspondence only; they do not close full native source/relink delivery.

## Next Qt candidate and remaining release work

The [November 24 Qt research](../../packaging/license-evidence/qt-security-refresh-2026-11-24.json)
records newly available official Qt **6.12.1** Windows and source routes.
It is the next coordinated candidate to investigate. The research did not
acquire or adopt that runtime, verify its binary/source checksums and archive
contents, or test compatibility.

The recorded PyPI metadata makes the version distinction material: PyQt6
6.12.1 alone still selected native Qt 6.12.0 at review time. Its binding also
requires Qt `>=6.12,<6.13` and SIP `>=13.13,<14`, so it cannot simply replace
the current PyQt6 6.11.0 binding while preserving Qt 6.11.3 and SIP 13.11.1.
A new candidate must pin the coordinated binding, SIP, Qt binary/source and
plugin inputs; preserve the restricted profile's exclusions; resolve exact
SPDX/source correspondence; and pass build, import, TLS and lifecycle checks
before any promotion. The current QtBase/Core `b21f6a...` versus public
`138f955...` source-identity discrepancy remains unresolved.

The reviewed November advisories and absent-module dispositions are targeted
triage, not comprehensive clearance of transitive image, font or compression
libraries. Private MSVC staging changes input provenance and portability; it
does not itself patch Qt or settle the retained Qt native-source gap.

The owner-selected GPL-3.0-only source release and unsigned/manual-install
route remain the intended release routes. Microsoft package identity and valid
signatures do not establish a qualifying owner license or redistribution basis.
Complete corresponding-source/relink delivery, owner licensing decisions,
public recipient delivery and retention, hosted checks, and Compat runtime
validation remain independent gates. No approval field should be changed from
false on the strength of this engineering evidence alone.
