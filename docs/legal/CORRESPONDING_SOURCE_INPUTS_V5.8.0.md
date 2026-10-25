# DupeZ 5.8.0 third-party source-input evidence

Reviewed October 24, 2026. This engineering record is **not** an approval of
distribution terms, complete corresponding source, or an official release.
The project recipient-build record is separate in `SOURCE_AND_RELINK_V5.8.0.md`.

**Historical checkpoint:** the 32-archive counts, hashes and commands below
describe the October 24 manifest at commit
`6fa81f48b1c96c949abe27b4822805914d128e78`. The October 25 follow-up in
[`NATIVE_SOURCE_MAPPING_2026-10-25.md`](NATIVE_SOURCE_MAPPING_2026-10-25.md)
pins the previously missing IUP source and verifies the official release
correspondence of all four managed native files. All 33 upstream version-source
inputs are now pinned; exact native rebuild and delivery gaps remain.

The earlier bundle and receipt remain unchanged. Because `verify-bundle`
deliberately checks its embedded manifest against the supplied manifest, verify
that historical bundle with the October 24 manifest via `--manifest`, not the
updated manifest. The commands below are a historical recipe for that checkout;
use the follow-up's current offline verification recipe for the expanded cache.

## Completed local collection

All 32 pinned source archives were retained and reinspected with the final
security guards. The deterministic bundle was then independently rehashed by
`verify-bundle`; both generated receipts are byte-identical. The tracked
technical record is
`packaging/license-evidence/source-input-collection-2026-10-24.json`.

- Local bundle: `build/source-delivery-20261024/third-party-source-inputs.zip`
- Bundle size: **1,733,430,647 bytes**
- Bundle SHA-256: `1876b6d2db883886fa3411718a61d8f81bb299de2645d635f4371566eccf7321`
- Receipt SHA-256: `efc6fde17a0710919aacd59402b1fc28064f22a3020f5a39c080afcfc367545d`
- Verification: **86 tests passed**, Ruff passed, collection recipe parsed.

IUP is the sole uncollected inventory component, but collection of the other
32 does **not** resolve their recorded native-build mappings or source-delivery
obligations. No license-policy decision was approved by this work.

## What is pinned

`packaging/source-inputs.json` accounts for all 33 components in
`packaging/third-party-components.json`. It records exact versions, source
archive names, HTTPS origins, sizes, SHA-256 digests, and primary evidence URLs.
Thirty-two components have upstream source archives pinned. IUP 3.30 remains
explicitly unresolved: the Clumsy source archive includes dependency binaries,
which are not a substitute for the source/build mapping of the shipped IUP DLL.

Twenty-three runtime packages publish exact-version PyPI sdists. PyQtGraph
0.14.0 and pywin32 312 instead use release tags resolved to immutable commits.
The additional inputs include CPython 3.13.17, PyInstaller 6.22.2, WinDivert's
2.2.0 source commit, the provenance-pinned Clumsy commit, and Inno Setup 6.7.1.
The two native Qt entries use official Qt 6.11.2 source archives. Source hashes
from PyPI/Qt/Python are upstream-published metadata; GitHub archive hashes were
measured from HTTPS downloads of immutable commits. These are integrity pins,
not independent publisher signatures or attestations of binary equivalence.

The official Qt mirror list redirects binary downloads. The collector does
not follow that redirect: its manifest pins the direct HTTPS mirror advertised
by the official list, with Qt's independently published size and SHA-256.

| Native source archive | Compressed bytes | SHA-256 |
| --- | ---: | --- |
| Qt 6.11.2 full source | 1,019,661,552 | `6dcfbca271d76a6502741a2c0dc6fc98ef7dd0b7b4cfd0abcebb285a86a26f33` |
| Qt WebEngine 6.11.2 source | 580,351,104 | `6101c1aa00ff933d1b65ee5d167f76e8d71b9ac5b378b0111277723ebda7c163` |
| CPython 3.13.17 source | 23,233,336 | `6020bd10aff3bf4821be16f088ebb1591beb7b811dcd8fab1da8f7c22a7b27e7` |

## Safe collection and offline verification

Run from the reviewed DupeZ checkout with a verified Python interpreter. This
example uses the isolated interpreter already prepared for local evidence;
recipients may substitute their verified interpreter path. No administrator
rights or production signing keys are required.

```powershell
$sourcePython = 'build/native-security-20261024/test-venv/Scripts/python.exe'
& $sourcePython scripts/corresponding_source.py plan
if ($LASTEXITCODE -ne 0) { throw 'Source plan failed' }

$sourceManifest = Get-Content packaging/source-inputs.json -Raw | ConvertFrom-Json
$sourceSelection = @()
foreach ($sourceComponent in $sourceManifest.components) {
    if ($sourceComponent.source_status -eq 'upstream-source-pinned') {
        $sourceSelection += @('--component', $sourceComponent.id)
    }
}
$sourceCache = 'build/source-delivery-20261024/archives'
$sourceBundle = 'build/source-delivery-20261024/third-party-source-inputs.zip'
$sourceReceipt = 'build/source-delivery-20261024/source-input-receipt.json'
$sourceArguments = @(
    'scripts/corresponding_source.py', 'collect',
    '--cache', $sourceCache,
    '--max-artifact-bytes', '1100000000',
    '--bundle', $sourceBundle,
    '--receipt', $sourceReceipt
) + $sourceSelection
& $sourcePython @sourceArguments
if ($LASTEXITCODE -ne 0) { throw 'Source collection failed; no completeness claim is valid' }

& $sourcePython scripts/corresponding_source.py verify-bundle --bundle $sourceBundle
if ($LASTEXITCODE -ne 0) { throw 'Source bundle verification failed' }
Get-FileHash -LiteralPath $sourceBundle -Algorithm SHA256
```

The explicit budget permits the approximately 1.02 GB full-Qt archive. The
default per-archive budget is 128 MiB, so large downloads require a deliberate
choice. The combined 32 archives are 1,733,386,826 bytes; preserving both Qt
archives intentionally duplicates some WebEngine source for the separate
wheel mapping. To collect only small inputs, exclude the two native Qt entries
from `$sourceSelection` and omit the budget override.

The tool reuses only already verified ordinary cache files. Receipts and bundle
outputs never overwrite existing paths: choose new names for a repeat run.
Use `verify` with the same component selection and cache to rehash and reinspect
cached archives without network access. `verify-bundle` checks the embedded
manifest against the current reviewed manifest, rehashes every archive,
rejects unexpected members, and checks that the receipt preserves every gap
and uncollected component. It never extracts the archives.

Network downloads are limited to reviewed HTTPS source routes; credentials,
ports, query strings, redirects, ambient proxies, content encodings and
unreviewed origins are refused. Hash/size validation precedes bounded archive
inspection. Paths, special entries, link escapes, cycles, duplicate entries
and expansion/count limits are checked. Safe internal source links are
preserved in the original archive. No dependency setup script, package build
backend, downloaded program, or archive extraction is invoked. Bundle and
receipt publication is atomic and no-overwrite; failed writes leave no final
output path. The dedicated regression suite includes adversarial archive,
network, receipt, and publication tests.

Do not rename a partial input bundle as a complete source release. The
receipt's claim explicitly says that it contains verified upstream source
inputs only. `--require-delivery-ready` fails while known gaps remain; there is
no `--allow-unresolved` approval bypass. Ignored `build/` artifacts are local
evidence, not publicly delivered source or a retention commitment.

## What is still unresolved

- Exact Qt/Qt WebEngine Windows wheel provenance: patches, configuration,
  compiler inputs, security-backport correspondence and bundled third-party
  source/notices. Both wheel releases publish binaries but no sdist; their
  installed metadata identifies version/license, not a reproducible build.
- Exact IUP source/build mapping and independent validation that Clumsy and
  WinDivert source/build inputs correspond to the distributed native bytes.
- The final dependency graph of the corrected frozen build, including any
  additional bundled native/transitive libraries and their source obligations.
- The exact DupeZ commit archive and successful recipient application-change
  and covered-library replacement evidence, recorded separately.
- Public source delivery, retention arrangements, rights confirmation and
  owner/legal-policy decisions. This tooling does not update license approvals.

Riverbank's public PyQt-builder documentation is useful for rebuild research,
but it is not evidence of the parameters used for these particular wheels.
It says `pyqt-bundle` takes an existing Qt installation and ordinarily assumes
one from the Qt Company's binary installer; source-built Qt is not a supported
assumption of that bundling command. Obtain exact upstream wheel build inputs
or produce independently recorded compatible replacement builds before
claiming that the native-source mapping is complete.

## Primary sources

- [Riverbank source distributions and wheels](https://www.riverbankcomputing.com/software/pyqt/download)
- [PyQt6-Qt6 6.11.2 metadata](https://pypi.org/pypi/pyqt6-qt6/6.11.2/json)
- [PyQt6-WebEngine-Qt6 6.11.2 metadata](https://pypi.org/pypi/pyqt6-webengine-qt6/6.11.2/json)
- [Full Qt archive size and hash](https://download.qt.io/official_releases/qt/6.11/6.11.2/single/qt-everywhere-src-6.11.2.tar.xz.mirrorlist)
- [Qt WebEngine archive size and hash](https://download.qt.io/official_releases/qt/6.11/6.11.2/submodules/qtwebengine-everywhere-src-6.11.2.tar.xz.mirrorlist)
- [Qt WebEngine licensing map](https://doc.qt.io/qt-6.11/qtwebengine-licensing.html)
- [PyQt-builder bundling documentation](https://pyqt-builder.readthedocs.io/en/latest/pyqtbundle.html)
- [PyQt-builder source](https://github.com/Python-PyQt/PyQt-builder)
- [CPython 3.13.17 source release](https://www.python.org/downloads/release/python-31317/)

Additional exact release/tag/source URLs are recorded per component in the
machine-readable manifest, not replaced with moving branch links.
