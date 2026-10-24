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

## Candidate recipient rebuild route: unvalidated

These preparation instructions have not been validated by a recipient build or
covered-library replacement test. No binary build is authorized or executed as
part of this documentation update while the owner/native-runtime release gates
remain unresolved. Do not use this candidate recipe as evidence that
`source-and-relink-delivery` has passed.

The proposed route builds local GPU/Compat executables from a separate fresh
clone, without production keys, an installer, update metadata, or official
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

The following commands are candidate instructions, not completed validation:

```powershell
$ErrorActionPreference = 'Stop'
$recipientCommit = Read-Host 'Exact 40-hex commit from the source/release record'
$recipientRoot = Read-Host 'Absolute path for a NEW separate clone (must not exist)'
$recipientBootstrap = Read-Host 'Absolute path to verified 64-bit CPython 3.13.17 python.exe'
if ($recipientCommit -notmatch '^[0-9a-fA-F]{40}$') { throw 'An exact commit is required.' }
if (-not [IO.Path]::IsPathRooted($recipientRoot) -or (Test-Path -LiteralPath $recipientRoot)) {
    throw 'Choose a new absolute clone path; existing directories are not reused.'
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
Invoke-RecipientCommand 'git' @('clone', '--no-checkout', '--',
    'https://github.com/GrihmLord/DupeZ.git', $recipientRoot)
Set-Location -LiteralPath $recipientRoot
Invoke-RecipientCommand 'git' @('checkout', '--detach', $recipientCommit)
```

Review the checked-out commit against the source record before proceeding.
Keep this clone separate from the maintainer checkout and any existing install.

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
this disposable clone. The frozen inspection is a dependency/native-byte check,
not a release approval or a successful runtime/replacement demonstration.

Keep these outputs identified as recipient builds. Do not copy them into an
official release directory or attach official signed sidecars from another
build. Preserve startup hardening and updater verification; no production
private key is required or exposed by this route. Later validation must show
that both variants run appropriately (GPU as a standard user; Compat with its
normal elevation), using only authorized private test targets.

### 4. Demonstrate modification and replacement before claiming completion

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
