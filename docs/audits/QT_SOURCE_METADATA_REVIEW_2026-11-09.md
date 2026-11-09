# Qt source metadata and security follow-up — 2026-11-09

The previously unexplained `.tag` checksum differences in QtBase, QtSvg and
QtTools are now explained and reproducibly verified. The Git source contains an
export template; the release tarball contains its expanded commit ID. The
separate QtBase binary/source revision discrepancy remains unresolved.

A new advisory published today also affects retained Qt Network. The pinned
6.11.3 source lacks both published fixes for CVE-2026-116337. This review adds
source evidence, not a patched native runtime or release approval.

## Verified Git export behavior

At the exact public source revisions, each module's Git `.tag` contains the
12-byte string `$Format:%H$` followed by LF. Their `.gitattributes` declares
`.tag export-subst`, plus `export-ignore` for `.gitattributes` and `.gitignore`.
Git documents that this template expands to a commit hash when creating an
archive. [Git export documentation](https://git-scm.com/docs/gitattributes#_creating_an_archive)

Normalizing the template to Windows CRLF gives SHA1
`8eb01c346a92a2321c358ae8327d3b48c163b1b0`, exactly the `.tag` checksum in all
three pinned source SPDX inventories. The downloaded `.gitattributes` files also
match their source SPDX checksums after the same explicit normalization.

| Module | Expanded tarball `.tag` | Result |
| --- | --- | --- |
| QtBase | `138f955f0b5e50e4a6c2ee1e78a2279db52ae9e3` | Template and export declarations match source SPDX |
| QtSvg | `f5d99721911e4a1989965a087813cf1277519bc6` | Template and export declarations match source SPDX |
| QtTools | `b0b5b911411ffb0da4f29643ab295b90c52dc26d` | Template and export declarations match source SPDX |

The official metadata was read at immutable revision URLs:
[QtBase attributes](https://code.qt.io/cgit/qt/qtbase.git/plain/.gitattributes?id=138f955f0b5e50e4a6c2ee1e78a2279db52ae9e3),
[QtSvg attributes](https://code.qt.io/cgit/qt/qtsvg.git/plain/.gitattributes?id=f5d99721911e4a1989965a087813cf1277519bc6), and
[QtTools attributes](https://code.qt.io/cgit/qt/qttools.git/plain/.gitattributes?id=b0b5b911411ffb0da4f29643ab295b90c52dc26d).
Their exact bytes, SHA-256 pins and source-SPDX pins are retained in the
[dated evidence](../../packaging/license-evidence/qt-source-metadata-review-2026-11-09.json).
SHA1 is used only for matching upstream inventory records; input trust pins use
SHA-256.

This explains `.tag` substitution and the declared Git metadata exclusions. It
does not assert that every omitted nested Git metadata file was retrieved or
that the native binaries were independently rebuilt. QtBase's binary SPDX still
names `b21f6a785516e898388cda2fe5d3e7dacd6d4b7d`. The official cgit commit and
`.tag` endpoints for that revision returned HTTP 404 on November 9; the tarball's
`138f955…` commit is public. A 404 does not explain the revision discrepancy, so
the verifier keeps that finding unresolved.

## New retained Qt Network issue

[Qt's November 9 advisory](https://www.qt.io/blog/security-issue-cve-2026-116337)
describes excessive memory consumption while reading malicious HTTP responses.
It provides two patches for 6.11 and lists 6.8.10 and 6.12.1 as fixed release
routes. Qt's [6.11.3 announcement](https://www.qt.io/blog/qt-6.11.3-released)
calls it the final 6.11 release; the current
[6.11 download directory](https://download.qt.io/official_releases/qt/6.11/)
still lists 6.11.3 as its newest version.

The exact pinned 6.11.3 source does not contain either new guard:

| Published patch | SHA-256 | Read-only applicability result |
| --- | --- | --- |
| `CVE-2026-116337-qtbase-6.11-0001.diff` | `2a5cc5a016bd41b8487555d68ccbbd808a9a418bc457486e9c779d217cb7e31a` | Full forward check passes; reverse check fails |
| `CVE-2026-116337-qtbase-6.11-0002.diff` | `ea58081d0999d6e3ea0e40277631fec26589c3e436922bfcfef7f771c626a4f3` | Production-source forward check passes; reverse check fails |

Patch 1 limits header accumulation. Patch 2 limits the status line. The second
patch's full test changes depend on patch 1; checking it alone against untouched
source fails that test context. The production hunk was checked separately.
No patch was applied, and no native DLL was changed. The evidence records all
commands, exit codes, patch pins and inspected source-member hashes.

First-party Python references to Qt Network are map-host TCP IPC in
`app/gui/map_host/launcher.py` and `host.py`, plus the maintenance TLS probe in
`scripts/probe_qt_tls.py`. Searching `app/**/*.py` and `scripts/**/*.py` found
no direct `QNetworkAccessManager` or `QNetworkRequest` references. This limited
source search is not proof that affected native code is unreachable. Qt Network
remains in the candidate, and the new advisory remains an explicit native
security gap.

The newer [Qt WebSockets authentication advisory](https://www.qt.io/blog/security-issue-cve-2026-114366)
and [Qt5Compat conversion advisory](https://www.qt.io/blog/security-advisory-cve-2026-107479-integer-truncation-vulnerability-in-qtextcodec-conversion-functions-impacts-qt-framework)
both identify 6.11.3 as a fixed version. Those modules are excluded from this
restricted candidate. This is targeted advisory triage, not a complete native
dependency security clearance.

## Rebuild recipe evidence and remaining work

The pinned QtBase binary metadata records MSVC **19.44.35227.0**, CMake **4.3.2**,
shared debug/release libraries, and the exact configure arguments. Qt's
[6.11.3 tools table](https://wiki.qt.io/Qt_6.11_Tools_and_Versions)
also lists CMake 4.3.2, x64 Ninja 1.10.2, sccache v0.15.0, and OpenSSL x64 3.5.4
for Windows 11 24H2. The version table helps locate build inputs; it is not an
artifact-hash manifest. The configure receipt references a Python 3.10 location,
so the table's generic Python entry must not be substituted for that build input.

A native rebuild still needs exact compiler/linker, SDK/runtime, CMake, Ninja,
sccache and external-input provenance and hashes; a reconciled source revision;
and tests of newly built libraries. A patched 6.11.3 route must include both
new HTTP-response fixes. A newer Qt route needs separate binding, plugin,
source-delivery and compatibility validation. No toolchain was installed or
native compilation started in this review.

## Reproduce the metadata verification

The new verifier consumes the existing pinned local archives/SPDX files and the
downloaded Git metadata. It performs no network or native execution:

```powershell
python -I scripts/verify_qt_export_metadata.py `
  --candidate-root build/qt-candidate-parity-final-20261101 `
  --qttools-root build/qt-translation-review-20261101-followup `
  --metadata-root build/qt-source-tag-review-20261109
```

The evidence includes each metadata filename, immutable URL, exact content and
SHA-256 digest, so another recipient can prepare the same inputs. The verifier parses the exact verified archive byte snapshot, avoiding a
path-substitution gap between hashing and parsing. It checks archive/SPDX/metadata hashes, a unique bounded ordinary `.tag` member,
explicit export declarations, both normalized source-SPDX checksums, and the
exported revision. It reports successful export mapping for all three modules
while preserving `qtbase_binary_revision_discrepancy_resolved: false` and
`native_rebuild_proven: false`.

Validation: all three real archive comparisons passed; **13 focused tests
passed**; Ruff passed. Existing 314-catalog rebuild evidence was not rerun.
