# Qt raster engineering adoption — 2026-11-09

This records the isolated `frozen-raster` engineering profile. Canonical
`requirements-locked.txt`, `packaging/requirements-build-locked.txt`, and the
production distribution inventory remain unchanged. The profile is not a public
release, and Qt Network CVE-2026-116337 remains unpatched.

## Verified preparation results

The independently checked candidate wheel is
`PyQt6-6.11.0-6.11.3dupezraster-cp310-abi3-win_amd64.whl`, **19,989,328 bytes**,
SHA-256 **`4f8d8948c6b4f1648bed5bd354c9243c0c040dcb0f604f10fdcc6e71738248cc`**.
It contains **33 native members and 33 QtBase translation catalogs**, each
compared directly with its pinned upstream archive or binding wheel. Those
counts describe the Qt wheel, not the entire frozen application's native set.
The repeated preparation after the requested-profile binding fix produced the
same wheel digest. A further preparation using the Git-portable LF manifest
produced identical bytes in `build/qt-raster-portable-20261109`.

The engineering dependency profile contains **24 runtime distributions** and
**31 unique hash-verified wheels** in its complete build wheelhouse. Installation
passed `pip check`, checked the real installed PyQt6 distribution metadata and
payload against the derived wheel, and validated **376 notice documents**.
Of these, **304 source notice inputs** came from the pinned QtBase, QtSvg,
QtImageFormats and QtTranslations archives. Notice collection is conservative;
it does not assert that every noticed source file is linked into the binaries.

Local preparation receipts are:

- `build/qt-raster-portable-20261109/preparation-receipt.json`
- `build/qt-raster-verified-final-20261109/runtime-checkout/build/qt-profile/engineering-profile.json`
- `build/qt-raster-verified-final-20261109/runtime-checkout/build/qt-profile/installation-receipt.json`
- `build/qt-raster-verified-final-20261109/runtime-checkout/build/qt-profile/notices/license-payload.json`

The candidate manifest has an explicit v3 `frozen-raster` identity. Preparation
rejects a valid manifest for the wrong requested profile before creating output
or fetching inputs. The previous v2 review profile remains available separately.
Both the native inventory and final wheel digest are checked independently of
the wheel's internal RECORD. Adoption captures consumed input identities and
rechecks them before publishing its profile; generated installation inputs are
also rechecked before an installation receipt is issued. Mutation regressions
cover source archives, locks, inventory, license, manifest, receipt and wheel.
A fresh-checkout failure also led to a fix: the validated output directory now
creates its missing build parent. The original failed preparation is retained
in the diagnostic record; the clean retry succeeds.

The candidate's loopback Schannel probe passed a TLS 1.3 handshake and rejected
both an untrusted CA and a wrong hostname. The receipt is
`build/qt-adoption-20261109/raster-tls.json`; it records no trust-store changes.
That result covers loopback TLS, not HTTP response parsing or the final frozen
application lifecycle.

## Reproduce the engineering preparation and build

Run from the repository root with the reviewed Windows x64 Python 3.13.17
environment. Use fresh output paths; the example uses recipient directories to
preserve the recorded observations. The caches below are existing verified
inputs, and the adoption installer resolves only from the local wheelhouse.

```powershell
$reviewPython = (Resolve-Path 'build/native-security-20261024/test-venv/Scripts/python.exe').Path
$wheelHash = '4f8d8948c6b4f1648bed5bd354c9243c0c040dcb0f604f10fdcc6e71738248cc'

& $reviewPython -I scripts/prepare_qt_candidate.py `
  --profile frozen-raster `
  --cache build/qt-raster-portable-20261109/inputs `
  --output build/qt-raster-recipient-20261109
if ($LASTEXITCODE -ne 0) { throw 'Qt candidate preparation failed' }

& $reviewPython -I scripts/prepare_qt_adoption.py `
  --candidate-root build/qt-raster-recipient-20261109 `
  --expected-wheel-sha256 $wheelHash `
  --wheel-cache build/qt-adoption-wheel-cache-20261109 `
  --output build/qt-adoption-recipient-20261109 `
  --product-version 5.8.0 `
  --install-build-env
if ($LASTEXITCODE -ne 0) { throw 'Engineering environment preparation failed' }

$profileRoot = (Resolve-Path 'build/qt-adoption-recipient-20261109').Path
$buildPython = Join-Path $profileRoot 'build-venv/Scripts/python.exe'
$env:DUPEZ_QT_BUILD_PROFILE = 'frozen-raster'
$env:PYTHONNOUSERSITE = '1'
$env:PYTHONHASHSEED = '0'
$env:SOURCE_DATE_EPOCH = '315532800'
Remove-Item Env:PYTHONHOME, Env:PYTHONPATH -ErrorAction SilentlyContinue
Remove-Item Env:DUPEZ_RELEASE_NATIVE_STAGE -ErrorAction SilentlyContinue

& $buildPython -I -m PyInstaller packaging/dupez_gpu.spec --noconfirm `
  --distpath "$profileRoot/artifacts" --workpath "$profileRoot/pyinstaller-gpu"
if ($LASTEXITCODE -ne 0) { throw 'GPU-named engineering build failed' }

& $buildPython -I -m PyInstaller packaging/dupez_compat.spec --noconfirm `
  --distpath "$profileRoot/artifacts" --workpath "$profileRoot/pyinstaller-compat"
if ($LASTEXITCODE -ne 0) { throw 'Compat engineering build failed' }

& $buildPython -I scripts/release_preflight.py --qt-profile frozen-raster `
  --frozen-artifact "$profileRoot/artifacts/DupeZ-GPU.exe" `
  --frozen-artifact "$profileRoot/artifacts/DupeZ-Compat.exe"
if ($LASTEXITCODE -ne 0) { throw 'Frozen raster inventory check failed' }
```

`DUPEZ_QT_BUILD_PROFILE=frozen-raster` is required during the actual PyInstaller
build. The preparation profile alone does not select the build-time policy.
The shared spec rejects forbidden GL/helper payloads before generic collection
cleanup. These direct spec invocations use source-provenance-checked managed
native inputs and create engineering executables; they do not invoke the public
release finalizer. The separately generated engineering notices and source
receipts are not automatically a complete distributable release bundle.

The existing executable names identify process/UAC variants. They do not mean
that the raster profile restores embedded Chromium or hardware-rendered maps.
These commands build and inspect files; they do not launch either executable.

## Native gaps removed from this profile and those retained

| Area | Disposition |
| --- | --- |
| Legacy Mesa/LLVM software OpenGL helper | `opengl32sw.dll` is absent from the candidate. Its old exact-source/compiler gap is removed from this profile's payload, not repaired in the upstream helper. |
| Direct3D compiler helper | `d3dcompiler_47.dll` is absent. This does not imply that Windows graphics libraries are absent from the running process. |
| Qt OpenGL bindings/libraries | Both `QtOpenGL` and `QtOpenGLWidgets` bindings/libraries, their definitions, and the associated designer plugin are excluded. |
| Embedded browser/QML | The existing exclusion remains: no Qt WebEngine/Chromium, Qt Quick/QML or embedded map runtime is admitted. |
| QtBase source identity | The `.tag` template discrepancy is explained, but the binary SPDX's `b21f6a…` revision still does not reconcile with the public tarball revision `138f955…`. |
| Qt Network | Retained. Both official CVE-2026-116337 HTTP-response guards are absent from the pinned source; no native patch or fixed-DLL claim is made. |
| Retained bundled dependencies | Source inventories and notices for QtBase/QtSvg/QtImageFormats improve correspondence. They do not prove the compiler/linker inputs or independent binary rebuild of libraries such as libpng, FreeType, HarfBuzz, PCRE2, libtiff and libwebp. |
| Translation catalogs | Existing evidence rebuilds all 314 catalogs byte-for-byte, including the 33 retained here. It does not rebuild Qt's native translation compiler. |

See the [November 9 source/security review](QT_SOURCE_METADATA_REVIEW_2026-11-09.md)
and [translation rebuild review](QT_TRANSLATION_SOURCE_REVIEW_2026-11-01-followup.md)
for exact pins and boundaries. First-party Qt Network uses found in the reviewed
Python are TCP IPC and a maintenance TLS probe. That observation does not prove
that the vulnerable native HTTP code is unreachable.

## Clean build and runtime evidence

The final clean checkpoint is **`6c255e59195017627728e498324f5bbac48755f3`**.
A new isolated checkout generated its engineering profile and build environment
offline from the committed recipe, then built both executables. Exact source
ZIP comparison, frozen raster policy and native-origin validation passed.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| DupeZ-v5.8.0-source.zip | 25,044,185 | `7f2b1debcc0b46bbc61a9c6f92578f266ab6d7370a9b137b729d65c6f4351727` |
| DupeZ-GPU.exe | 57,928,223 | `7f566e87e884797f56bb1e830fffa157495aeb344a0bc31e51d3244a2605d24a` |
| DupeZ-Compat.exe | 57,926,914 | `e7dada706d118ffb9771e4531553370cbb3c7f33030af7d6d71a65a04b69d564` |

Each executable has **119 native entries**: 88 from the hash-locked build
venv, 24 from the verified Python base, four managed binaries, and three from
Windows System32. The three System32 files are `MSVCP140.dll`, `MSVCP140_1.dll`
and `MSVCP140_2.dll`, all version 14.51.36247.0 with valid Microsoft signatures.
Their exact hashes match both archives. This establishes the observed local
origin; an independently pinned redistributable package, distribution basis
and complete native SBOM mapping remain open. These inputs must be addressed
before a public release or a claim of a fully pinned recipient-native rebuild.

**GPU runtime passed** import/TLS maintenance and both normal and forced-low-
resource dashboard lifecycles with a standard token. Manual-map activation,
clean shutdown, owned-process cleanup and absence of a WebEngine helper passed.
The actual v4 report passed the Windows PowerShell 5.1 consumer; its log records
the SHA-256 of the exact validated JSON. No packet effect was activated.

**Compat runtime testing is pending.** Windows canceled the normal UAC prompt
before its helper began. No Compat maintenance, lifecycle or helper-result
report was produced. The owner then instructed publication of the verified
work with Compat runtime testing pending. The prior November 1 Compat result
applies to a different executable and is not transferred to this build.

The stable source checkpoint passes **3,662 tests with ten expected skips**.
The isolated raster-compatible suite passes **3,588 tests with 18 expected
skips** and 57.51% application line coverage, excluding only
`tests/test_map_request_policy.py` and `tests/test_codeql_remediation.py` because
they import absent browser bindings. That raster suite preceded the final
preparation-only integrity/recipient fixes; **35 focused tests pass afterward**
in the same raster test environment. Source preflight passes with six unresolved
license-policy warnings. Commit hooks and Ruff pass.

Two failed attempts are retained as diagnostics: the first fresh checkout had
no build parent, leading to the now-fixed preparation error; an intermediate
full suite overlapped the commit hook's temporary Windows-path rewrite of the
secret baseline. The stable committed baseline and subsequent full suite pass.
Neither failed attempt is relabeled as successful evidence.

The [machine-readable evidence](../../packaging/license-evidence/qt-raster-adoption-2026-11-09.json)
binds the checkpoint, recipe identities, complete preparation/profile receipts,
source-notice pins, source/test/build/archive observations, GPU runtime proof,
System32 identities and canceled Compat attempt. The matching QtCore bytes in
both executables are checked against the derived wheel and its pinned origin;
the standalone TLS probe identifies that runtime as Qt 6.11.3. Local raw logs
remain hash references rather than exposing machine-specific paths.

## Public release gates remain open

A release still requires a fixed and validated retained native runtime; complete
corresponding-source and recipient rebuild evidence; reconciled effective
distribution identities, transitive SBOM and notices; and the existing licensing
evidence decisions. The authorized route remains GPL-3.0-only with corresponding
source and an explicitly disclosed unsigned/manual-install release. That route
does not bypass the repository's source, native provenance or distribution gates.

Protected release metadata/updater-signing requirements and GitHub hosted checks
also remain separate. GitHub billing is still blocked pending an owner-side
account change. A successful local engineering build does not turn blocked CI
or unsigned artifacts into an approved public release.
