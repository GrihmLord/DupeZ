# DupeZ v5.8.0 Source, Build, and Relink Information

This file is prepared to accompany DupeZ v5.8.0 release-candidate artifacts.
It is an engineering delivery record, not legal advice or proof that the
source/relink release gate has passed. The governing project license
is supplied separately as `LICENSE.txt`; third-party terms are reproduced in
`THIRD_PARTY_NOTICES.txt`.

## Exact DupeZ source

When release gates permit finalization, `DupeZ-v5.8.0-source.zip` is generated with
`git archive` from the exact clean commit named in `release-attestation.json`.
The archive hash is covered by both `SHA256SUMS.txt` and that attestation. It
contains the application source, the exact runtime/test/build locks, packaging
definitions, installer definition, release controls, and this delivery record.

The archive is the preferred corresponding-source input for the released
DupeZ binaries. A moving branch or an unbound repository checkout is not a
substitute for it.

## Official release rebuilding

The canonical release target is 64-bit CPython 3.13.17 on Windows. The following
is the maintainer's protected official-release path, not the recipient build
route. Use a clean maintainer checkout at the selected commit (the source ZIP
does not include Git metadata), and follow the release runbook's prerequisites:

1. create `.venv` with 64-bit CPython 3.13.17;
2. install the hash-pinned inputs from `requirements-locked.txt` and
   `packaging/requirements-build-locked.txt` using `--require-hashes` and
   binary wheels only;
3. review `packaging/release-tools.json` and install the exact pinned Inno
   Setup compiler when building an installer;
4. run `scripts/finalize_release.ps1 -Version 5.8.0 -AllowUnsigned` from an
   Administrator PowerShell for the no-purchase, explicitly unsigned route;
5. run the frozen GPU lifecycle as a standard desktop user and the Compat
   lifecycle from Administrator PowerShell.

The finalizer requires an external Ed25519 updater key matching a public key
already pinned in the application. That key authenticates update metadata; it
does not change or restrict the source-code license. An Authenticode
certificate is not required when the explicit unsigned route is selected, but
Windows will show an unknown-publisher warning.

No DupeZ license term is intended to prohibit debugging, reverse engineering,
replacement, or relinking that an applicable GPL or LGPL license permits.

## Recipient rebuild route: locally exercised, limited evidence

On October 24, both unsigned variants were built in isolated directories from
the source ZIP of commit `1db32d750ee1a1b23733ff38f6b53fdad8957d7f`, without
Git metadata or production keys. Both passed final native-byte/origin and
frozen-dependency inspection. GPU passed standard-user `--verify-runtime-imports`
and `--verify-native-tls` (Schannel only), each with exit 0. These checks do not
start a renderer, packet engine, GUI, or network connection. Compat's normal
administrator runtime has **not** been exercised by this evidence.

The exact source ZIP is 24,758,411 bytes, SHA-256
`875eb4c0f000c7a39f193b67fd7f3a10def528c5f004ff4f911d4ffb04df220f`.
This engineering checkpoint is not an official release source attestation.
Later documentation/evidence commits do not change the recorded build commit.
Do not treat these local observations as approval of `source-and-relink-delivery`.

The second, modified GPU build also passed: both application and actual
zeroconf Python-function markers were observed at runtime, followed by the
Schannel-only probe; both exited 0 as a standard user. The detailed
[engineering evidence](../../packaging/license-evidence/recipient-rebuild-2026-10-24.json)
records before/after source hashes, patch hashes, all three executable hashes,
native inventories and reports. This demonstrates a Python-layer library
modification, not rebuilt native Qt/Chromium, Cython extensions, or drivers.

The route builds local GPU/Compat executables from a separate fresh source
extraction, without production keys, an installer, update metadata, or official
release attestations. It never invokes `finalize_release.ps1`, `release.ps1`,
either build batch file, or a signing tool. Official publication continues to
require all existing release gates; this internal distinction does not limit
recipients' applicable GPL/LGPL rights.

### 1. Select verified inputs in a separate shell

Open a new standard-user `powershell.exe -NoProfile` session. Environment
changes below affect only that process and its children, not User/Machine
settings or another release shell. Do not print or copy secret values. Use the
exact 40-character commit from the reviewed source/release record, not a moving
branch. A source ZIP is not yet a validated release merely because it exists.

Use new paths for each experiment; do not reuse earlier outputs:

```powershell
$ErrorActionPreference = 'Stop'
$recipientCommit = Read-Host 'Exact 40-hex commit from the source/release record'
$recipientExtractRoot = Read-Host 'Absolute path for a NEW source extraction (must not exist)'
$recipientArchive = Read-Host 'Absolute path to the verified exact-commit source ZIP'
$recipientArchiveHash = Read-Host 'Expected SHA256 from the trusted source/evidence record'
$recipientBootstrap = Read-Host 'Absolute path to verified 64-bit CPython 3.13.17 python.exe'
if ($recipientCommit -notmatch '^[0-9a-fA-F]{40}$') { throw 'An exact commit is required.' }
if (-not [IO.Path]::IsPathRooted($recipientExtractRoot) -or (Test-Path -LiteralPath $recipientExtractRoot)) {
    throw 'Choose a new absolute extraction path; existing directories are not reused.'
}
if ($recipientArchiveHash -notmatch '^[0-9a-fA-F]{64}$' -or
    -not [IO.Path]::IsPathRooted($recipientArchive) -or
    (Get-FileHash -LiteralPath $recipientArchive -Algorithm SHA256).Hash -ne $recipientArchiveHash) {
    throw 'Source ZIP does not match the trusted input record.'
}
if (-not [IO.Path]::IsPathRooted($recipientBootstrap) -or
    -not (Test-Path -LiteralPath $recipientBootstrap -PathType Leaf)) {
    throw 'Choose the verified interpreter by its absolute path.'
}

Get-ChildItem Env: | Where-Object {
    $_.Name -match '^DUPEZ_(SIGN.*|RELEASE.*|INSTALLER_NATIVE_SNAPSHOT|EXPECTED_SIGNER_CERT_SHA256|ALLOW_UNSIGNED|PORTABLE_ONLY)$'
} | ForEach-Object { Remove-Item -LiteralPath ('Env:\' + $_.Name) }
Remove-Item -LiteralPath Env:PYTHONHOME,Env:PYTHONPATH -ErrorAction SilentlyContinue
$env:PYTHONNOUSERSITE = '1'
$env:PYTHONHASHSEED = '0'
$env:SOURCE_DATE_EPOCH = '315532800'
$env:PIP_REQUIRE_VIRTUALENV = 'true'

function Invoke-RecipientCommand {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Recipient command failed: $Program" }
}
Invoke-RecipientCommand $recipientBootstrap @('-I', '-S', '-c',
    "import struct, sys; raise SystemExit(0 if sys.version_info[:3] == (3, 13, 17) and struct.calcsize('P') == 8 else 1)")
Invoke-RecipientCommand $recipientBootstrap @('-I', '-S', '-c',
    "import sys, zipfile; z = zipfile.ZipFile(sys.argv[1]); raise SystemExit(0 if z.comment.decode('ascii') == sys.argv[2].lower() else 1)",
    $recipientArchive, $recipientCommit)
Expand-Archive -LiteralPath $recipientArchive -DestinationPath $recipientExtractRoot
$recipientRoot = Join-Path $recipientExtractRoot 'DupeZ-v5.8.0'
Set-Location -LiteralPath $recipientRoot
```

Obtain the expected hash from the trusted record, not from the downloaded ZIP
itself. Keep this extraction separate from the maintainer checkout and existing
install. The release archive checker also verifies required inputs and rejects
unsafe paths; a recorded hash is not a general-purpose archive-safety bypass.

### 2. Prepare an isolated environment and outputs

```powershell
$recipientVenv = Join-Path $recipientRoot '.recipient-venv'
$recipientPython = Join-Path $recipientVenv 'Scripts\python.exe'
$recipientOutput = Join-Path $recipientRoot 'recipient-output'
$recipientWork = Join-Path $recipientRoot 'recipient-work'
foreach ($recipientPath in @($recipientVenv, $recipientOutput, $recipientWork)) {
    if (Test-Path -LiteralPath $recipientPath) { throw "Refusing to reuse $recipientPath" }
}
New-Item -ItemType Directory -Path $recipientOutput,$recipientWork | Out-Null
Invoke-RecipientCommand $recipientBootstrap @('-I', '-S', '-m', 'venv', $recipientVenv)
Invoke-RecipientCommand $recipientPython @('-I', '-m', 'pip', 'install',
    '--disable-pip-version-check', '--only-binary=:all:', '--require-hashes',
    '-r', 'packaging/requirements-build-locked.txt', '-r', 'requirements-locked.txt')
```

Do not reuse `.release-venv`, `build/release-native`, canonical `dist`, or an
existing output/work directory. This baseline uses the exact locked inputs;
modified dependencies require separately documented inputs and notices.

### 3. Build and inspect local copies, without signing

```powershell
Invoke-RecipientCommand $recipientPython @('-I', '-m', 'PyInstaller',
    'packaging/dupez_gpu.spec', '--noconfirm',
    '--distpath', $recipientOutput, '--workpath', (Join-Path $recipientWork 'gpu'))
Invoke-RecipientCommand $recipientPython @('-I', '-m', 'PyInstaller',
    'packaging/dupez_compat.spec', '--noconfirm',
    '--distpath', $recipientOutput, '--workpath', (Join-Path $recipientWork 'compat'))
Invoke-RecipientCommand $recipientPython @('-I', 'scripts/release_preflight.py',
    '--frozen-artifact', (Join-Path $recipientOutput 'DupeZ-GPU.exe'),
    '--frozen-artifact', (Join-Path $recipientOutput 'DupeZ-Compat.exe'))
```

The specs use the shared `packaging/build_common.py` factory. Without
`DUPEZ_RELEASE_NATIVE_STAGE`, `packaging/release_data.py` verifies the tracked
native files against source provenance and supplies private hash-checked
snapshots; it does not require signing keys. The factory rewrites
`app/firewall_helper/_build_default.py`, so build the variants sequentially in
this disposable source tree. The frozen inspection is a dependency/native-byte check,
not a release approval or a successful runtime/replacement demonstration.

Keep these outputs identified as recipient builds. Do not copy them into an
official release directory or attach official signed sidecars from another
build. Preserve startup hardening and updater verification; no production
private key is required or exposed by this route. Full lifecycle/hardware
validation must still show both variants running appropriately (GPU as a
standard user; Compat with its normal elevation), using authorized private
test targets. Maintenance-only success does not satisfy that requirement.

### 4. Record modification and replacement, with precise limits

The reproducible demonstration patches are
`packaging/recipient-validation/application-marker.patch` and
`packaging/recipient-validation/zeroconf-marker.patch`. Use a **second** fresh
source extraction and venv, never the baseline or installed product. The first
adds an application marker without changing the version and makes the import
probe report it; the second adds a callable function to zeroconf's LGPL-covered
Python `__init__.py`, retaining its license header. The report calls that actual
function. No DNS service or packet operation is needed.

In a disposable extraction outside any other Git checkout, after the hash-pinned
install above, these commands apply the reviewed patches (Git is only a patch
utility here; no project `.git` directory or private key is required):

```powershell
Invoke-RecipientCommand 'git' @('apply', '--check',
    'packaging/recipient-validation/application-marker.patch')
Invoke-RecipientCommand 'git' @('apply',
    'packaging/recipient-validation/application-marker.patch')
Invoke-RecipientCommand 'git' @('apply', '--check',
    '--directory=.recipient-venv/Lib/site-packages',
    'packaging/recipient-validation/zeroconf-marker.patch')
Invoke-RecipientCommand 'git' @('apply',
    '--directory=.recipient-venv/Lib/site-packages',
    'packaging/recipient-validation/zeroconf-marker.patch')
```

Record original and modified file hashes and both patch hashes. The
record identifies which patch representation was measured: the local observation
used working-checkout LF patch bytes, while the exact source ZIP has equivalent
CRLF copies. Normalized content was independently compared and matched; byte
hashes must not be compared without accounting for that recorded distinction.
The resulting environment is a **hash-locked baseline plus recorded modifications**, not an
unchanged wheel install: the original wheel's `RECORD` no longer describes the
patched Python file. Build with a new work/output path and run the import probe
with a new `DUPEZ_VERIFY_REPORT`. Successful output must contain both
`application_marker` and `library_marker`, each exactly
`dupez-recipient-validation-20261024`, and an observed process exit 0.
`scripts/recipient_rebuild_evidence.py --modified` records the source/archive,
executable, report, and at least the three modified input hashes; it does not
run the executable or authenticate an operator-supplied exit status.

`scripts/native_build_evidence.py` separately checks final native bytes against
the generated build manifest and approved local roots. The unchanged native
inventory in a successful Python-layer demonstration does **not** demonstrate
recompiling zeroconf's Cython extensions or replacing native Qt/Chromium.

Record the actual source revision, environment, modified source/library inputs,
build commands, output hashes, notices, and observed runtime result. Demonstrate
an application change and replacement/rebuild of an applicable covered library,
not only an unchanged executable. Document how to supply a compatible modified
Qt/WebEngine library to the isolated build; onefile temporary extraction alone
is not a replacement/relink procedure.

For recipient-modified native files, record new hashes/provenance in the
recipient's own source copy instead of pretending they match the official
manifest. Modified dependency versions also need a truthful recipient input
inventory and applicable source/notices. Do not weaken official provenance
checks, reuse an official attestation for changed bytes, or mark the source
delivery decision complete before this evidence exists.

## Third-party source routes

The 33-component machine-readable source inventory, retained 32-archive bundle,
verification commands, and explicit unresolved mappings are documented in
[CORRESPONDING_SOURCE_INPUTS_V5.8.0.md](CORRESPONDING_SOURCE_INPUTS_V5.8.0.md).
Collection is complete for the selected pinned inputs, not complete
corresponding-source delivery. IUP and native wheel build/source matching remain
open, as do public delivery, retention, and owner decisions.

The exact binary/package versions and their notices are recorded in
`license-payload.json` and `packaging/third-party-components.json`. Relevant
upstream source routes include:

- PyQt6 6.11.0: https://pypi.org/project/PyQt6/6.11.0/#files
- PyQt6-WebEngine 6.11.0: https://pypi.org/project/PyQt6-WebEngine/6.11.0/#files
- Qt 6.11.2: https://download.qt.io/official_releases/qt/6.11/6.11.2/submodules/
- Qt WebEngine 6.11.2: https://download.qt.io/official_releases/qt/6.11/6.11.2/submodules/
- zeroconf 0.150.0: https://pypi.org/project/zeroconf/0.150.0/#files
- WinDivert 2.2: https://github.com/basil00/WinDivert/tree/v2.2.0
- Clumsy 0.3.4 fork source commit:
  https://github.com/kalirenegade-dev/clumsy/tree/bc87e73066168520d76122c9165e99ea703b166c
- CPython 3.13.17: https://www.python.org/downloads/release/python-31317/

Qt WebEngine also contains Chromium and other third-party components. Their
embedded notices are exposed by the deployed engine at `chrome://credits`
where supported, and Qt's licensing map is linked from the consolidated
notice. No proprietary media codecs are intentionally enabled by DupeZ.

These links are discovery routes, not proof that complete corresponding source
has been delivered. Before distribution, identify the exact sources matching
the shipped bindings, Qt/Chromium and other covered binaries, including required
patches, build configuration, and scripts. Pin source hashes, retain accessible
copies or another valid delivery mechanism, and provide clear directions next
to the binary downloads. Preserve applicable library replacement,
reverse-engineering, and installation-information rights. The DupeZ source ZIP
alone does not establish that upstream library obligations are fulfilled.

Before public distribution, the owner remains responsible for confirming that
the selected delivery route and retained source availability satisfy every
applicable license and jurisdiction-specific obligation.
