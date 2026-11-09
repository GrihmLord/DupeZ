# Qt Network exclusion and native provenance — 2026-11-09

The new explicit `frozen-raster-no-qtnetwork` engineering profile removes the
Qt Network payload affected by CVE-2026-116337. Both clean executables pass
archive and native-byte validation. GPU maintenance and dashboard validation
pass. **Compat runtime testing remains pending by owner instruction; no new
UAC or Compat launch was attempted.** This is not a public binary release.

This follows the earlier [raster adoption](QT_RASTER_ADOPTION_2026-11-09.md).
The older profiles and canonical production locks are unchanged; their Qt
Network issue is not fixed by this profile's component removal.

## What changed

Qt's [advisory](https://www.qt.io/blog/security-issue-cve-2026-116337) concerns
HTTP-response memory consumption. The pinned 6.11.3 source lacks both published
guards, as recorded in the [source review](QT_SOURCE_METADATA_REVIEW_2026-11-09.md).
The frozen manual-map application does not need Qt Network. This profile removes
`QtNetwork.pyd`, `Qt6Network.dll`, `qtuiotouchplugin.dll`,
`qnetworklistmanager.dll` and `qschannelbackend.dll`, along with their binding
definitions. Existing browser/QML and GL/helper exclusions remain in force.

Preparation uses a separate v4 manifest and receipt. Build selection is compiled
into the executable; inherited environment variables cannot change its runtime
contract. The source browser's TCP imports are lazy, and the excluded child mode
fails before creating a socket. Legacy Schannel checks remain required for the
profiles that retain Qt Network. The new profile verifies Python TLS defaults
and requires the Qt Network binding to be absent.

Build and final-archive checks inspect normal and delayed PE imports and the
exported DLL identity without loading native code. They reject retained files
that import or identify themselves as `Qt6Network.dll`, as well as forbidden
outer/PYZ names and a mismatched compiled profile. The canonical Python OpenSSL
pair remains required. This establishes removal of this affected component;
it does not establish freedom from every native vulnerability.

## Verified preparation and builds

The candidate wheel contains **28 native members and 33 QtBase catalogs**,
each compared with its pinned upstream origin. An independent repeat of the
preparation produced identical bytes:

`PyQt6-6.11.0-6.11.3dupezrasternonet-cp310-abi3-win_amd64.whl`

**18,720,658 bytes**, SHA-256
`27e8195852d1305cfad3ac88d47f19e32679229e3461fa6a4ac0e42fa09fef8a`.

The clean build checkpoint is **`22cddda2623250e08583eea14570af8ab9439d84`**.
A fresh local checkout prepared and installed its engineering profile from the
pinned offline inputs, passed `pip check`, verified installed wheel bytes and
376 notice documents, then built both variants. The source archive was compared
with that exact commit. These are engineering artifacts, not release assets.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| DupeZ-v5.8.0-source.zip | 25,160,893 | `7c684e5f24888b745805b5980702f2fd649ceb058a372e4a2d42999b24200b40` |
| DupeZ-GPU.exe | 56,753,386 | `ac4c4275929314b12134c0116c55a683228acc93564b5881c6b4e57ac6cd250d` |
| DupeZ-Compat.exe | 56,753,371 | `ea3b375529328ecfe75326d711a22d81588c7d473a93e61184152654d123edd3` |

Each executable contains **114 native entries**: 83 from the locked build
environment, 24 from the verified Python base, four managed binaries and three
Microsoft runtime DLLs. Both archives have the same native inventory digest.
Of the candidate wheel's 28 native members, 24 are collected into each frozen
application. The unused PrintSupport and SvgWidgets bindings and their two Qt
DLLs remain in the wheel but are absent from both executables. The evidence
collector now checks that exact partition; its initial assumption that all 28
would be collected failed before publication and is retained as a diagnostic.
The named GPU variant remains the standard-token process variant; these results
do not establish hardware-rendered maps or hardware smoke coverage.

The three Microsoft DLLs now match the exact signed 14.51.36247 redistributable
package through its Burn/CAB/MSI contents. The verifier reads those containers
as data, checks signatures, queries MSI read-only and rechecks consumed files
before issuing evidence. The new build profile enforces those three byte pins
and includes their package mapping in its engineering SBOM. See the
[Microsoft provenance review](../legal/MSVC_REDIST_PROVENANCE_REVIEW_2026-11-09.md).
This closes the upstream package identity gap, not the owner's redistribution
basis or the entire native SBOM.

## Tests and runtime observations

- Full production-dependency source suite: **3,825 passed, 10 expected skips**
  at the clean checkpoint. The exact build-lock-pinned PE parser was supplied
  on the isolated test subprocess path; canonical locks were not changed.
- Candidate environment: **440 passed, eight optional-browser skips**;
  **271 native guard tests passed**; final preparation/adoption checks:
  **147 passed**. These are scoped runs, not an additional full source suite.
- Ruff and AST checks passed for all **465 tracked Python files**.
- Python HTTPS loopback: trusted certificate succeeded with TLS 1.3; untrusted
  issuer and hostname mismatch were rejected before HTTP reached the server.
  No global trust store was changed. This is a Python TLS test, not a test of
  the removed Qt HTTP parser.
- Both frozen archive/native checks passed. GPU import/TLS maintenance passed.
- GPU normal and forced-low-resource dashboard lifecycles passed in production
  safety dry-run mode, including manual-map activation and clean process exit.
  No packet effect was activated and no browser helper was observed.
- The actual GPU v4 report passed the Windows PowerShell 5.1 consumer. Its log
  binds the validated JSON SHA-256. An initial launcher had an incompatible
  module path; a sandboxed retry also failed before execution. Both diagnostics
  are retained. The final check used the inbox module path outside the sandbox,
  with unchanged report/executable bytes and no execution-policy override.
- Compat build and offline inspection passed; maintenance and dashboard testing
  remain **pending per owner instruction**, with no fresh UAC attempt.

The [machine-readable evidence](../../packaging/license-evidence/qt-network-exclusion-2026-11-09.json)
contains exact input, report and log hashes, source recipe comparisons and the
scope of each observation. Local working artifacts are under
`build/qt-network-verified-20261109/`; raw machine logs are retained locally.

## Reproduce the explicit engineering profile

Use the reviewed Windows x64 Python 3.13.17 environment and fresh output paths.
The preparation commands use verified local caches; no native Qt compilation
is performed. The earlier raster audit documents the shared spec build pattern.

```powershell
$reviewPython = (Resolve-Path 'build/native-security-20261024/test-venv/Scripts/python.exe').Path
$qtProfile = 'frozen-raster-no-qtnetwork'
$wheelHash = '27e8195852d1305cfad3ac88d47f19e32679229e3461fa6a4ac0e42fa09fef8a'
& $reviewPython -I scripts/prepare_qt_candidate.py --profile $qtProfile `
  --cache build/qt-nonetwork-candidate-20261109/inputs `
  --output build/qt-network-recipient-new
if ($LASTEXITCODE -ne 0) { throw 'Qt preparation failed' }
& $reviewPython -I scripts/prepare_qt_adoption.py --profile $qtProfile `
  --candidate-root build/qt-network-recipient-new --expected-wheel-sha256 $wheelHash `
  --wheel-cache build/qt-adoption-wheel-cache-20261109 `
  --output build/qt-network-profile-new --install-build-env
if ($LASTEXITCODE -ne 0) { throw 'Engineering environment preparation failed' }
$buildPython = (Resolve-Path 'build/qt-network-profile-new/build-venv/Scripts/python.exe').Path
$env:DUPEZ_QT_BUILD_PROFILE = $qtProfile
& $buildPython -I -m PyInstaller packaging/dupez_gpu.spec --noconfirm `
  --distpath build/qt-network-profile-new/artifacts --workpath build/qt-network-profile-new/gpu
if ($LASTEXITCODE -ne 0) { throw 'GPU build failed' }
& $buildPython -I -m PyInstaller packaging/dupez_compat.spec --noconfirm `
  --distpath build/qt-network-profile-new/artifacts --workpath build/qt-network-profile-new/compat
if ($LASTEXITCODE -ne 0) { throw 'Compat build failed' }
& $buildPython -I scripts/release_preflight.py --qt-profile $qtProfile `
  --frozen-artifact build/qt-network-profile-new/artifacts/DupeZ-GPU.exe `
  --frozen-artifact build/qt-network-profile-new/artifacts/DupeZ-Compat.exe
if ($LASTEXITCODE -ne 0) { throw 'Frozen profile validation failed' }
```

Run build commands in a clean checkout with the environment sanitation described
in the earlier audit. `--qt-profile` is required for profile-aware native and
maintenance validators. The commands above build and inspect files; they do not
launch Compat or grant release approval.

## Remaining source, licensing and release work

The QtBase binary SPDX explicitly assigns `b21f6a785516e898388cda2fe5d3e7dacd6d4b7d`
to QtBase and Core, as well as the removed Network module. Official public
revision lookups still fail, while the public 6.11.3 tag resolves to
`138f955f0b5e50e4a6c2ee1e78a2279db52ae9e3`. Removing Network therefore does not
resolve the retained Core source-identity gap. These findings establish a
metadata discrepancy, not proof that source contents differ.

The current toolchain inventory lacks the required native C++ compiler/linker,
CMake and Ninja. Repeated wheel preparation and the clean PyInstaller builds
do not constitute a native Qt rebuild. Retained Qt/third-party compiler inputs,
IUP correspondence, complete native source/relink delivery and public recipient
delivery remain unfinished. Earlier evidence for 314 byte-identical catalog
rebuilds remains valid within its recorded scope.

The owner-selected GPL-3.0-only and unsigned/manual-install routes remain in
place. All six licensing-policy decisions remain unresolved pending their
specific evidence and owner determinations; no entitlement was inferred from
an installed compiler or a valid Microsoft signature. Source preflight reports
those six warnings. GitHub billing still prevents hosted checks, and local
results do not replace them. See the [release runbook](../release-notes/BLOCKED_RELEASE_GATES_RUNBOOK_5.8.0.md)
for owner actions and the [launch plan](../release-notes/LAUNCH_PLAN_5.8.0.md)
for the remaining release gates.
