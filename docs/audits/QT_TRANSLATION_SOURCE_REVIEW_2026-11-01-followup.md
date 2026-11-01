# Qt translation source mapping and artifact rebuild, 2026-11-01 follow-up

All **314 Qt 6.11.3 compiled translation catalogs rebuilt byte-for-byte**, including
the **33 qtbase catalogs retained by the isolated DupeZ candidate**. The rebuild
used the matching official Qt `lrelease` binary and pinned translation source
archive. It resolves the earlier uncertainty about 13 English catalogs that had
no same-name `.ts` file in the archive.

This is translation artifact rebuild evidence. It does not independently rebuild
the native compiler or Qt, complete corresponding-source delivery, approve
distribution, or change the production Qt 6.11.2 locks.

## What the source actually generates

The pinned `qttranslations-everywhere-src-6.11.3.tar.xz` archive contains 301
same-name source TS inputs for the shipped catalogs. Its
`translations/CMakeLists.txt` defines `generate_empty_ts_file`, which writes
`<TS language="en_US"></TS>`. The recipe generates these additional 13 inputs:

`assistant_en`, `designer_en`, `linguist_en`, `qt_en`, `qt_help_en`, `qtbase_en`,
`qtconnectivity_en`, `qtdeclarative_en`, `qtlocation_en`, `qtmultimedia_en`,
`qtserialport_en`, `qtwebengine_en`, and `qtwebsockets_en`.

The same CMake file passes all source and generated inputs to `qt_add_lrelease`
with `OPTIONS "-silent"`. The verifier pins the exact CMake recipe SHA-256
`1c464f57b5b8878b81972fdd4f6e56f3d9f4f8f074ef9396e7afbc9a6c35a2e4` before
using this recipe. The rebuilt `qtbase_en.qm` is 33 bytes and exactly matches the
official binary archive. Its lack of a checked-in English TS file is therefore
explained by a reproducible generated source input.

## Reviewed compiler and inputs

The existing candidate manifest pins the QtBase binary, QtTranslations binary,
and QtTranslations source archives. The verifier adds two local review inputs;
their sizes and SHA-256 digests were checked against the official Qt mirror
metadata before downloading:

| Input | Bytes | SHA-256 |
| --- | ---: | --- |
| QtTools 6.11.3 Windows/MSVC2022 binary archive | 27,042,501 | `b519f552424d8c748ed37c6b3a7615d29a1e3920383ee8ccf9b2066998341c2c` |
| QtTools 6.11.3 source archive | 10,273,528 | `0a2da018a67ae081ab93d686fefce47e95eb8d82389151c476202ee8c4b375e4` |

The source/binary URLs, archive listing pin, all 314 input/output digest pairs,
and signature observations are in
[`qt-translation-source-review-2026-11-01-followup.json`](../../packaging/license-evidence/qt-translation-source-review-2026-11-01-followup.json).
Official metadata: [QtTools binary mirror details](https://download.qt.io/online/qtsdkrepository/windows_x86/desktop/qt6_6113/qt6_6113_msvc2022_64/qt.qt6.6113.win64_msvc2022_64/6.11.3-0-202610220312qttools-Windows-Windows_11_24H2-MSVC2022-Windows-Windows_11_24H2-X86_64.7z.mirrorlist)
and [QtTools source mirror details](https://download.qt.io/online/qtsdkrepository/all_os/qt/qt6_6113_unix_line_endings_src/qt.qt6.6113.src/6.11.3-0-202610220312qttools-everywhere-src-6.11.3.tar.xz.mirrorlist).

Only two native files were staged for execution:

| File | SHA-256 |
| --- | --- |
| `lrelease.exe` | `896e5134448612c8bc2fd4a9384d17929d0dca16b59f01f699ad931e96ff676e` |
| `Qt6Core.dll` | `3b088187284c91250fbb696b1779459ca1ab1ad14295e71ee9b12d71767c9501` |

Both had valid Authenticode signatures from The QT Company Oy with signer
thumbprint `3D89F77A33C5AD89F45F681848958E755B727C5A`. Import inspection showed
that `lrelease.exe` needs Qt6Core and Windows/Microsoft CRT libraries; Qt6Core
also imports the Windows ICU library. The run used a standard user token, a new
tool directory, and a minimal private environment with only trusted Windows
directories on PATH. No UAC prompt, packet operation, or helper activation was
invoked. The verifier performs no network operations. Windows and CRT binaries remain
host dependencies; this is not an independently rebuilt native toolchain.

QtTools source SPDX correlation found 659 raw matches and 3,748 matches after
explicit LF-to-CRLF normalization. All 324 files under `src/linguist/` matched.
Fourteen Git metadata files are omitted from the source tarball and `.tag` has
a different digest from the binary archive's source SPDX. Those wider archive
differences remain disclosed; translation output equality does not erase them.

## Reproduce locally

Prepare the existing isolated candidate with `scripts/prepare_qt_candidate.py`.
Place the two exact QtTools archives above in a separate input directory. The
verifier performs no downloads or installation. From a standard-user Windows
shell, with a reviewed Python interpreter:

```powershell
python -I scripts/verify_qt_translation_sources.py `
  --candidate-root build/qt-candidate-parity-final-20261101 `
  --tools-inputs build/qt-translation-review-20261101-followup `
  --output build/qt-translation-rebuild-20261101-followup-final `
  --run-compiler
```

Use a new output directory on each run. Omitting `--run-compiler` performs source
mapping without executing `lrelease`. The verifier rejects altered input hashes,
unreviewed archive listings, unsafe or special archive members, changed generation
recipes, elevated compiler runs, existing output directories, and unmatched
compiler source files. It freshly extracts the pinned binary translation archive
and compares every rebuilt QM directly with that reference. It returns failure
if any rebuilt output differs.

The final run returned `catalogs: 314`, `compiler_run: true`, and
`all_byte_identical: true`. Its complete receipt SHA-256 is
`f56e39ff8abbbbbb99351effab197291f088408ee165a7a2e0cd0767be928cd1`.
Fourteen focused verifier tests passed; Ruff reported no findings.

## Remaining boundaries

QtTranslations still does not supply a standalone source SPDX document. The
source-to-QM mapping now has concrete reproducible artifact evidence despite that
missing upstream document. `catalogs.json` is generated by the same CMake source
but is outside this 314-QM compilation count. Native compiler/Qt rebuild evidence,
other Qt source mapping issues, complete source-bundle integration, and existing
release/license gates remain separate unfinished work.
