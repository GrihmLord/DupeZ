# Engineering source bundle and recipient rebuilds

This recipe applies only to `frozen-raster-no-qtnetwork`: Qt/PyQt 6.12.1,
PyQt6-sip 13.13.1 and CPython 3.13.17 on Windows x64. It prepares verifiable
source inputs and records unresolved work. It does not approve distribution,
complete corresponding source, native reproducibility or public retention.
Compat runtime testing remains pending; none of these commands launches Compat.

## Plan the exact inputs

[`packaging/engineering-source-inputs.json`](../../packaging/engineering-source-inputs.json)
is separate from the canonical and historical manifests. Its 46 entries comprise
the profile's 24 runtime distributions and 10 additional components, ten pinned
freezer/bundler tools, QtTools source for the catalog compiler, and an unresolved
Microsoft runtime entry. The 45 retained source archives total 227,653,716 bytes.
Inno Setup is inventoried tooling; these two frozen executables contain no
installer. Inspect the full versions, upstream URLs, hashes and gaps as data:

```powershell
$sourcePlan = Get-Content -LiteralPath packaging/engineering-source-inputs.json -Raw | ConvertFrom-Json
$sourcePlan.components | Select-Object id, version, source_status
$sourcePlan.delivery_gaps
$sourcePlan.components | Where-Object { $_.gaps.Count } | Select-Object id, gaps
```

The wrapper has `create` and `verify` commands; it has no `plan` subcommand.
It collects all pinned inputs, retaining unresolved entries in the receipt.
Microsoft runtime source is not supplied. No WebEngine, full-Qt or software
OpenGL helper source archive is included. Individual Qt module archives retain
their original complete contents, including unused source files.

Prepare a clean Git checkout at the exact application checkpoint and the
matching local build/adoption record. Every collected recipe and the engineering
manifest must byte-match that checkpoint's Git blobs. An older application
build cannot be combined with newer recipes. The exact application ZIP is
checked against `git archive`; its source checkpoint, effective profile lock,
component inventory and both observed native payloads are recorded together.
Separately dated source/licensing observations are hash-bound supporting evidence.

The current frozen builds contain 114 native files each. Their mapping accounts
for every observed entry, while distinguishing candidate-wheel modules from the
five Qt bindings/DLLs actually frozen. Candidate PrintSupport and SvgWidgets are
absent from those executables. Mapping a native file to a source component is
not proof that its binary was rebuilt from that source.

## Create, repeat and verify

Use the matching profile's pinned build interpreter, which supplies the local
PyInstaller archive reader. The commands below name the selected build layout;
run them only after its matching adoption record has been produced. For another
checkpoint, supply its matching directory and record. `--python-base` must name
the verified CPython base used by that build. Cache paths can be relocated;
archive filenames, sizes and hashes must match the manifest. Acquisition of
missing inputs is separate: `create` has no network-download mode.

```powershell
$sourceBuild = 'build/native-source-release-20261124'
$sourceEvidence = 'packaging/license-evidence/native-source-builds-2026-11-24.json'
$sourcePython = Join-Path $sourceBuild 'runtime-checkout/build/qt-profile/build-venv/Scripts/python.exe'
$sourceBase = 'build/native-security-20261024/python-3.13.17/runtime/tools'
$sourceCaches = @(
    'build/source-delivery-20261024/archives',
    'build/native-source-mapping-20261025/archives',
    'build/qt6121-inputs-20261124/public-source',
    'build/qt6121-inputs-20261124/cache',
    'build/engineering-source-20261124/archives'
)
$sourceArgs = @(
    '-I', 'scripts/engineering_source_bundle.py', 'create',
    '--build-root', $sourceBuild, '--adoption-evidence', $sourceEvidence,
    '--python-base', $sourceBase
)
foreach ($sourceCache in $sourceCaches) { $sourceArgs += @('--cache', $sourceCache) }
$sourceA = 'build/engineering-source-recipient-a'
$sourceB = 'build/engineering-source-recipient-b'
foreach ($sourceOutput in @($sourceA, $sourceB)) {
    & $sourcePython @sourceArgs --output $sourceOutput
    if ($LASTEXITCODE -ne 0) { throw 'Source bundle creation failed' }
    & $sourcePython -I scripts/engineering_source_bundle.py verify `
        --bundle "$sourceOutput/engineering-source-inputs.zip" `
        --receipt "$sourceOutput/bundle-receipt.json"
    if ($LASTEXITCODE -ne 0) { throw 'Source bundle verification failed' }
}
$sourceHashA = Get-FileHash -Algorithm SHA256 -LiteralPath "$sourceA/engineering-source-inputs.zip"
$sourceHashB = Get-FileHash -Algorithm SHA256 -LiteralPath "$sourceB/engineering-source-inputs.zip"
if ($sourceHashA.Hash -cne $sourceHashB.Hash) { throw 'Repeat bundle bytes differ' }
$sourceHashA
```

Both output directories must be new. Failed attempts remain available for
diagnosis; retry into a different directory. Collection holds Windows read locks
over pinned inputs, rechecks source archive structure and hashes, and performs
offline frozen-native inspection. It extracts no source archives and invokes no
package build backend, application payload, installer or UAC prompt. Git and the
reviewed Python tooling run locally. ZIP entries have fixed timestamps and modes;
unsafe names, case-insensitive collisions, unexpected members and changed bytes
are rejected. Canonical locks and historical bundles remain unchanged.

The ZIP includes the exact application source archive, original third-party
source archives, effective notices, recipes, component/native mappings and
receipts. For an independently received bundle, first obtain the expected
receipt digest through the published evidence channel and compare it locally.
Then run `verify` with that receipt. A receipt supplied only inside an untrusted
ZIP is not an independent trust anchor. Verification reads and hashes every
embedded file without extraction. All completeness and approval flags remain
false even when byte verification succeeds.

## Native rebuild work remains separate

The [Qt translation record](../../packaging/license-evidence/qt-6121-translations-2026-11-24.json)
reconstructs all 314 catalogs, including the 33 retained QtBase catalogs,
byte-for-byte using the pinned publisher compiler. It does not rebuild lrelease,
QtCore or the other native libraries. The
[Qt source comparison](../../packaging/license-evidence/qt-6121-source-correspondence-2026-11-24.json)
preserves absent/mismatching source metadata instead of treating version equality
as binary-source proof.

The independent IUP/Clumsy recipes under `scripts/native_rebuild/` are separate
compile-only experiments. Use their reviewed versions from the same checkpoint
as a standard Windows user. Acquisition downloads the exact portable LLVM-MinGW
archive into `build/native-compilation-20261124/inputs` and extracts it privately;
an existing cache is verified. It neither installs nor executes the compiler.
The source inputs must already be at the paths pinned in each recipe. Clumsy
also needs the official IUP 3.30 and WinDivert 2.2.0 binary/import-library archives
identified in the [native mapping record](../../packaging/license-evidence/native-source-mapping-2026-10-25.json).
The source bundle does not supply every compiler/import-library binary input.

```powershell
& $sourcePython -I scripts/native_rebuild/acquire_toolchain.py
if ($LASTEXITCODE -ne 0) { throw 'Portable toolchain verification failed' }

# Prepare a source/patch/command plan without executing compiler tools.
& $sourcePython -I scripts/native_rebuild/build_iup.py `
    --output build/native-compilation-20261124/iup-recipient-plan
if ($LASTEXITCODE -ne 0) { throw 'IUP source preparation failed' }

# Explicit compilation: use a different fresh output directory.
& $sourcePython -I scripts/native_rebuild/build_iup.py `
    --output build/native-compilation-20261124/iup-recipient-build --execute
if ($LASTEXITCODE -ne 0) { throw 'IUP compilation failed; retain its logs' }

# This command compiles immediately and requires a fresh run name.
& $sourcePython -I scripts/native_rebuild/build_clumsy.py --run recipient-build
if ($LASTEXITCODE -ne 0) { throw 'Clumsy compilation failed; retain its logs' }
```

IUP uses a separate patched source tree with an exact preimage/postimage pin for
the reviewed CreateDIBSection pointer conversion. Clumsy compiles the pinned
upstream commit with its documented legacy-C configuration. The resulting
library and executable are not launched or substituted into the shipped app.
Source-bundle collection never invokes these compilation commands. Keep separate
source/toolchain/output pins, build logs, patch descriptions and limits; compare
fresh repeat outputs before claiming repeatability. Linking alone does not
establish stock-binary equality, ABI compatibility or a safe runtime replacement.
Driver signing and WinDivert replacement remain separate. Actual attempt counts,
hashes and results belong in the dated native evidence, not this recipe.

Other unresolved mappings include Python's native externals, CFFI/libffi,
cryptography's OpenSSL/Rust dependencies, NumPy/OpenBLAS and its runtime,
Pillow's codecs, PortAudio, libyaml, generated extension toolchains and Microsoft
runtime distribution entitlement. See each component's `gaps` and the separate
[distribution basis](DISTRIBUTION_BASIS_V5.8.0.md). A private source ZIP does not
establish public delivery or retention. Final source-bundle creation and native
rebuild evidence must be recorded against the selected clean checkpoint before
any release claim is updated.
